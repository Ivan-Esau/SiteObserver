from __future__ import annotations

from datetime import datetime, timedelta

from state import Condition, Roll


def evaluate(condition: Condition, rolls: list[Roll]) -> bool:
    """Evaluate a condition against a list of rolls. Pure function."""
    if not rolls or not condition.enabled:
        return False

    if condition.type == "count_below":
        return _check_count_below(condition, rolls)
    if condition.type == "absent_streak":
        return _check_absent_streak(condition, rolls)
    if condition.type == "consecutive":
        return _check_consecutive(condition, rolls)
    return False


def is_in_cooldown(condition: Condition) -> bool:
    """Check if a condition is still in its cooldown window."""
    if not condition.last_fired_at:
        return False
    try:
        last = datetime.fromisoformat(condition.last_fired_at)
        return datetime.now() - last < timedelta(minutes=condition.cooldown_minutes)
    except ValueError:
        return False


def _check_count_below(condition: Condition, rolls: list[Roll]) -> bool:
    """True when color count in last N rolls is below threshold."""
    window = rolls[-condition.param_n:]
    count = sum(1 for r in window if r.coin == condition.color)
    return count < condition.param_threshold


def _check_absent_streak(condition: Condition, rolls: list[Roll]) -> bool:
    """True when color hasn't appeared in the last N rolls."""
    window = rolls[-condition.param_n:]
    if len(window) < condition.param_n:
        return False
    return all(r.coin != condition.color for r in window)


def _check_consecutive(condition: Condition, rolls: list[Roll]) -> bool:
    """True when the last N rolls are all the same color."""
    if len(rolls) < condition.param_n:
        return False
    tail = rolls[-condition.param_n:]
    return all(r.coin == condition.color for r in tail)
