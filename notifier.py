from __future__ import annotations

import logging
import os
from datetime import datetime

import requests
from dotenv import load_dotenv

from state import Condition, Roll, COLORS

logger = logging.getLogger(__name__)

load_dotenv()

DISCORD_API = "https://discord.com/api/v10"


def _get_bot_token() -> str:
    """Read bot token from env var (.env) or Streamlit secrets (cloud)."""
    token = os.getenv("DISCORD_BOT_TOKEN", "")
    if not token:
        try:
            import streamlit as st
            token = st.secrets.get("DISCORD_BOT_TOKEN", "")
        except Exception:
            pass
    return token


_bot_token: str = _get_bot_token()


def is_configured() -> bool:
    return bool(_bot_token) and _bot_token != "your_bot_token_here"


def _build_message(condition: Condition, rolls: list[Roll]) -> str:
    last_100 = rolls[-100:]
    ct = sum(1 for r in last_100 if r.coin == "ct")
    t = sum(1 for r in last_100 if r.coin == "t")
    bonus = sum(1 for r in last_100 if r.coin == "bonus")
    now = datetime.now().isoformat(timespec="seconds")

    return (
        f"**SiteObserver Alert**\n\n"
        f"Condition triggered: **{condition.description}**\n\n"
        f"Last {len(last_100)} rolls:\n"
        f"  Black (CT): **{ct}**\n"
        f"  Orange (T): **{t}**\n"
        f"  Green (Bonus): **{bonus}**\n\n"
        f"Time: {now}\n"
        f"Cooldown: {condition.cooldown_minutes} min"
    )


def send_alert(
    discord_user_id: str,
    condition: Condition,
    rolls: list[Roll],
) -> tuple[bool, str]:
    """Send a Discord DM alert. Returns (success, error_message)."""
    if not is_configured():
        return False, "DISCORD_BOT_TOKEN not configured"

    if not discord_user_id:
        return False, "No Discord user ID set"

    headers = {
        "Authorization": f"Bot {_bot_token}",
        "Content-Type": "application/json",
    }

    # Step 1: Open DM channel
    try:
        resp = requests.post(
            f"{DISCORD_API}/users/@me/channels",
            json={"recipient_id": discord_user_id},
            headers=headers,
            timeout=10,
        )
        resp.raise_for_status()
        channel_id = resp.json()["id"]
    except requests.RequestException as exc:
        error = f"Failed to open DM channel: {exc}"
        logger.error(error)
        return False, error

    # Step 2: Send message
    message = _build_message(condition, rolls)
    try:
        resp = requests.post(
            f"{DISCORD_API}/channels/{channel_id}/messages",
            json={"content": message},
            headers=headers,
            timeout=10,
        )
        resp.raise_for_status()
        logger.info(
            "Discord DM sent to %s: %s", discord_user_id, condition.description
        )
        return True, ""
    except requests.RequestException as exc:
        error = f"Failed to send DM: {exc}"
        logger.error(error)
        return False, error
