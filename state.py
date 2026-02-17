from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

PERSIST_FILE = Path(__file__).parent / "state.json"

COLORS = {"ct": "Black", "t": "Orange", "bonus": "Green"}


@dataclass
class Roll:
    index: int
    coin: str  # "ct", "t", "bonus"
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    @property
    def color_name(self) -> str:
        return COLORS.get(self.coin, self.coin)


@dataclass
class Condition:
    id: str = ""
    color: str = ""          # "ct", "t", "bonus"
    type: str = ""           # "count_below", "absent_streak", "consecutive"
    param_n: int = 100       # window size or streak length
    param_threshold: int = 0  # for count_below
    cooldown_minutes: int = 10
    last_fired_at: str = ""
    enabled: bool = True
    user_email: str = ""     # owner of this condition

    def __post_init__(self) -> None:
        if not self.id:
            self.id = uuid.uuid4().hex[:8]

    @property
    def description(self) -> str:
        color = COLORS.get(self.color, self.color)
        if self.type == "count_below":
            return f"{color} count < {self.param_threshold} in last {self.param_n} rolls"
        if self.type == "absent_streak":
            return f"{color} absent for {self.param_n} consecutive rolls"
        if self.type == "consecutive":
            return f"{color} appears {self.param_n}x in a row"
        return f"Unknown condition type: {self.type}"


@dataclass
class Alert:
    id: str = ""
    condition_id: str = ""
    condition_desc: str = ""
    user_email: str = ""
    fired_at: str = ""
    email_sent: bool = False
    error: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = uuid.uuid4().hex[:8]
        if not self.fired_at:
            self.fired_at = datetime.now().isoformat()


class SharedState:
    _instance: SharedState | None = None
    _lock = threading.Lock()

    def __new__(cls) -> SharedState:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._data_lock = threading.Lock()
        self.rolls: list[Roll] = []
        self.last_index: int = 0
        self.conditions: list[Condition] = []
        self.alerts: list[Alert] = []
        self.scraper_status: str = "stopped"
        self.scraper_error: str = ""
        self._load()

    def _load(self) -> None:
        if not PERSIST_FILE.exists():
            return
        try:
            data = json.loads(PERSIST_FILE.read_text(encoding="utf-8"))
            self.conditions = [
                Condition(**c) for c in data.get("conditions", [])
            ]
            logger.info("Loaded %d conditions from %s", len(self.conditions), PERSIST_FILE)
        except Exception:
            logger.exception("Failed to load persisted state")

    def _save(self) -> None:
        try:
            data = {
                "conditions": [asdict(c) for c in self.conditions],
            }
            PERSIST_FILE.write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )
        except Exception:
            logger.exception("Failed to save state")

    # ── Rolls (global, shared across all users) ──────────────────────────

    def add_rolls(self, new_rolls: list[Roll]) -> list[Roll]:
        with self._data_lock:
            added = []
            for roll in new_rolls:
                if roll.index > self.last_index:
                    self.rolls.append(roll)
                    self.last_index = roll.index
                    added.append(roll)
            if len(self.rolls) > 200:
                self.rolls = self.rolls[-200:]
            return added

    def get_rolls(self, n: int = 100) -> list[Roll]:
        with self._data_lock:
            return list(self.rolls[-n:])

    # ── Conditions (per-user) ────────────────────────────────────────────

    def add_condition(self, condition: Condition) -> None:
        with self._data_lock:
            self.conditions.append(condition)
            self._save()

    def remove_condition(self, condition_id: str, user_email: str) -> None:
        with self._data_lock:
            self.conditions = [
                c for c in self.conditions
                if not (c.id == condition_id and c.user_email == user_email)
            ]
            self._save()

    def get_conditions(self, user_email: str | None = None) -> list[Condition]:
        with self._data_lock:
            if user_email is None:
                return list(self.conditions)
            return [c for c in self.conditions if c.user_email == user_email]

    def get_all_conditions(self) -> list[Condition]:
        with self._data_lock:
            return list(self.conditions)

    def update_condition_fired(self, condition_id: str) -> None:
        with self._data_lock:
            for c in self.conditions:
                if c.id == condition_id:
                    c.last_fired_at = datetime.now().isoformat()
                    break
            self._save()

    # ── Alerts (per-user) ────────────────────────────────────────────────

    def add_alert(self, alert: Alert) -> None:
        with self._data_lock:
            self.alerts.append(alert)
            if len(self.alerts) > 500:
                self.alerts = self.alerts[-500:]

    def get_alerts(self, user_email: str | None = None, n: int = 50) -> list[Alert]:
        with self._data_lock:
            if user_email is None:
                return list(self.alerts[-n:])
            user_alerts = [a for a in self.alerts if a.user_email == user_email]
            return user_alerts[-n:]

    # ── Scraper status ───────────────────────────────────────────────────

    def set_scraper_status(self, status: str, error: str = "") -> None:
        with self._data_lock:
            self.scraper_status = status
            self.scraper_error = error

    def get_scraper_status(self) -> tuple[str, str]:
        with self._data_lock:
            return self.scraper_status, self.scraper_error
