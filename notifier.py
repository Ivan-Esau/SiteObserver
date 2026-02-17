from __future__ import annotations

import logging
import os

import resend
from dotenv import load_dotenv

from state import Condition, Roll, COLORS

logger = logging.getLogger(__name__)

load_dotenv()


def _get_api_key() -> str:
    """Read API key from env var (.env) or Streamlit secrets (cloud)."""
    key = os.getenv("RESEND_API_KEY", "")
    if not key:
        try:
            import streamlit as st
            key = st.secrets.get("RESEND_API_KEY", "")
        except Exception:
            pass
    return key


_api_key: str = _get_api_key()


def is_configured() -> bool:
    return bool(_api_key) and _api_key != "your_key_here"


def send_alert(
    to_email: str,
    condition: Condition,
    rolls: list[Roll],
) -> tuple[bool, str]:
    """Send an alert email. Returns (success, error_message)."""
    if not is_configured():
        return False, "RESEND_API_KEY not configured"

    if not to_email:
        return False, "No recipient email set"

    resend.api_key = _api_key

    last_100 = rolls[-100:]
    ct_count = sum(1 for r in last_100 if r.coin == "ct")
    t_count = sum(1 for r in last_100 if r.coin == "t")
    bonus_count = sum(1 for r in last_100 if r.coin == "bonus")

    subject = f"SiteObserver Alert: {condition.description}"

    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 500px; margin: 0 auto;">
        <h2 style="color: #e74c3c;">Alert Triggered</h2>
        <p style="font-size: 16px;"><strong>{condition.description}</strong></p>

        <h3>Current Distribution (last {len(last_100)} rolls)</h3>
        <table style="border-collapse: collapse; width: 100%;">
            <tr>
                <td style="padding: 8px; background: #2c3e50; color: white;">
                    Black (CT): <strong>{ct_count}</strong>
                </td>
            </tr>
            <tr>
                <td style="padding: 8px; background: #27ae60; color: white;">
                    Green (Bonus): <strong>{bonus_count}</strong>
                </td>
            </tr>
            <tr>
                <td style="padding: 8px; background: #e67e22; color: white;">
                    Orange (T): <strong>{t_count}</strong>
                </td>
            </tr>
        </table>

        <p style="color: #888; font-size: 12px; margin-top: 20px;">
            Cooldown: {condition.cooldown_minutes} min before next alert for this condition.
        </p>
    </div>
    """

    try:
        resend.Emails.send({
            "from": "SiteObserver <onboarding@resend.dev>",
            "to": [to_email],
            "subject": subject,
            "html": html_body,
        })
        logger.info("Alert email sent to %s: %s", to_email, condition.description)
        return True, ""
    except Exception as exc:
        error = str(exc)
        logger.exception("Failed to send alert email")
        return False, error
