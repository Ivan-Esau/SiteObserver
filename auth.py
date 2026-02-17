from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

USERS_FILE = Path(__file__).parent / "users.json"
_lock = threading.Lock()


def _hash_password(password: str, salt: str) -> str:
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def _load_users() -> dict:
    if not USERS_FILE.exists():
        return {}
    try:
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to load users")
        return {}


def _save_users(users: dict) -> None:
    try:
        USERS_FILE.write_text(json.dumps(users, indent=2), encoding="utf-8")
    except Exception:
        logger.exception("Failed to save users")


def signup(email: str, password: str) -> tuple[bool, str]:
    """Register a new user. Returns (success, message)."""
    email = email.strip().lower()
    if not email or "@" not in email:
        return False, "Invalid email address"
    if len(password) < 6:
        return False, "Password must be at least 6 characters"

    with _lock:
        users = _load_users()
        if email in users:
            return False, "Email already registered"

        salt = os.urandom(16).hex()
        users[email] = {
            "password_hash": _hash_password(password, salt),
            "salt": salt,
        }
        _save_users(users)

    return True, "Account created successfully"


def login(email: str, password: str) -> tuple[bool, str]:
    """Authenticate a user. Returns (success, message)."""
    email = email.strip().lower()

    with _lock:
        users = _load_users()

    user = users.get(email)
    if not user:
        return False, "Email not found"

    expected = _hash_password(password, user["salt"])
    if expected != user["password_hash"]:
        return False, "Incorrect password"

    return True, "Login successful"


def get_discord_id(email: str) -> str | None:
    """Return the stored Discord user ID for the given email, or None."""
    email = email.strip().lower()
    with _lock:
        users = _load_users()
    user = users.get(email)
    if not user:
        return None
    return user.get("discord_id") or None


def set_discord_id(email: str, discord_id: str) -> tuple[bool, str]:
    """Save Discord user ID for the given email. Returns (success, message)."""
    email = email.strip().lower()
    discord_id = discord_id.strip()

    with _lock:
        users = _load_users()
        if email not in users:
            return False, "User not found"
        users[email]["discord_id"] = discord_id
        _save_users(users)

    return True, "Discord ID saved"
