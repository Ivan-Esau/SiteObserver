from __future__ import annotations

import threading
import time

import streamlit as st

from state import SharedState, Condition, COLORS
from scraper import run_scraper
import notifier
import auth

# ── Page config ──────────────────────────────────────────────────────────────

st.set_page_config(page_title="SiteObserver", page_icon="🎰", layout="wide")

COLOR_OPTIONS = {"Black (CT)": "ct", "Orange (T)": "t", "Green (Bonus)": "bonus"}
CONDITION_TYPES = {
    "Count below threshold": "count_below",
    "Absent for N rolls": "absent_streak",
    "Consecutive streak": "consecutive",
}
COLOR_HEX = {"ct": "#2c3e50", "t": "#e67e22", "bonus": "#27ae60"}


# ── Singleton scraper start ──────────────────────────────────────────────────

@st.cache_resource
def get_shared_state() -> SharedState:
    return SharedState()


@st.cache_resource
def start_scraper(_state: SharedState) -> threading.Thread:
    t = threading.Thread(target=run_scraper, args=(_state,), daemon=True)
    t.start()
    return t


state = get_shared_state()
start_scraper(state)


# ── Auth helpers ─────────────────────────────────────────────────────────────

def _show_auth_form() -> None:
    """Render login/signup forms in the sidebar."""
    tab_login, tab_signup = st.tabs(["Login", "Sign Up"])

    with tab_login:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login")
            if submitted:
                ok, msg = auth.login(email, password)
                if ok:
                    st.session_state["user_email"] = email.strip().lower()
                    st.rerun()
                else:
                    st.error(msg)

    with tab_signup:
        with st.form("signup_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            password2 = st.text_input("Confirm password", type="password")
            submitted = st.form_submit_button("Sign Up")
            if submitted:
                if password != password2:
                    st.error("Passwords do not match")
                else:
                    ok, msg = auth.signup(email, password)
                    if ok:
                        st.session_state["user_email"] = email.strip().lower()
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)


# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("SiteObserver")

    # Scraper status
    scraper_status, scraper_error = state.get_scraper_status()
    status_icons = {
        "running": "🟢", "starting": "🟡",
        "stopped": "🔴", "error": "🔴",
    }
    st.markdown(f"**Scraper:** {status_icons.get(scraper_status, '⚪')} {scraper_status}")
    if scraper_error:
        st.caption(f"Error: {scraper_error[:100]}")

    st.divider()

    # Auth section
    user_email = st.session_state.get("user_email")

    if user_email:
        st.markdown(f"**Logged in as:** {user_email}")

        # Discord ID management
        current_discord_id = auth.get_discord_id(user_email) or ""
        discord_input = st.text_input(
            "Discord User ID",
            value=current_discord_id,
            help="Right-click your profile in Discord > Copy User ID",
        )
        if discord_input != current_discord_id:
            if st.button("Save Discord ID"):
                auth.set_discord_id(user_email, discord_input)
                st.success("Discord ID saved")
                st.rerun()

        if st.button("Logout"):
            del st.session_state["user_email"]
            st.rerun()
    else:
        _show_auth_form()

    st.divider()

    # Auto-refresh
    refresh = st.toggle("Auto-refresh (10s)", value=True)


# ── Main area ────────────────────────────────────────────────────────────────

tab_rolls, tab_conditions, tab_alerts = st.tabs(
    ["Live Rolls", "Alert Conditions", "Alert Log"]
)

# ── Tab 1: Live rolls (visible to everyone) ──────────────────────────────────

with tab_rolls:
    rolls = state.get_rolls(100)

    if not rolls:
        st.info("Waiting for scraper to connect and receive rolls...")
    else:
        ct = sum(1 for r in rolls if r.coin == "ct")
        t = sum(1 for r in rolls if r.coin == "t")
        bonus = sum(1 for r in rolls if r.coin == "bonus")
        total = len(rolls)

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total rolls", total)
        col2.metric("Black (CT)", ct)
        col3.metric("Orange (T)", t)
        col4.metric("Green (Bonus)", bonus)

        # All 100 rolls, most recent first
        st.subheader("Last 100 rolls")
        display_rolls = list(reversed(rolls[-100:]))
        dots = ""
        for r in display_rolls:
            color = COLOR_HEX.get(r.coin, "#888")
            label = COLORS.get(r.coin, "?")[0]
            dots += (
                f'<span style="display:inline-block;width:28px;height:28px;'
                f"line-height:28px;text-align:center;border-radius:50%;"
                f'background:{color};color:white;font-size:12px;'
                f'font-weight:bold;margin:2px;">{label}</span>'
            )
        st.markdown(dots, unsafe_allow_html=True)

        st.caption(
            f"Latest roll index: {rolls[-1].index} | "
            f"Last updated: {rolls[-1].timestamp[:19]}"
        )

# ── Tab 2: Alert conditions (requires login) ────────────────────────────────

with tab_conditions:
    user_email = st.session_state.get("user_email")

    if not user_email:
        st.warning("Please log in to configure alert conditions.")
    else:
        st.subheader("Add new condition")

        discord_id = auth.get_discord_id(user_email)
        if discord_id:
            st.caption(f"Alerts will be sent via Discord DM to user `{discord_id}`")
        else:
            st.warning("Set your Discord User ID in the sidebar to receive alerts.")

        if not notifier.is_configured():
            st.warning("DISCORD_BOT_TOKEN not set — DMs won't be sent.")

        with st.form("add_condition", clear_on_submit=True):
            col_a, col_b = st.columns(2)
            with col_a:
                color_label = st.selectbox("Color", list(COLOR_OPTIONS.keys()))
                cond_type_label = st.selectbox(
                    "Condition type", list(CONDITION_TYPES.keys())
                )
            with col_b:
                cond_type = CONDITION_TYPES[cond_type_label]
                if cond_type == "count_below":
                    param_n = st.number_input(
                        "In last N rolls", min_value=10, max_value=100, value=100
                    )
                    param_threshold = st.number_input(
                        "Below count", min_value=1, max_value=100, value=5
                    )
                elif cond_type == "absent_streak":
                    param_n = st.number_input(
                        "Absent for N rolls", min_value=5, max_value=100, value=20
                    )
                    param_threshold = 0
                else:
                    param_n = st.number_input(
                        "Consecutive count", min_value=2, max_value=50, value=5
                    )
                    param_threshold = 0
                cooldown = st.number_input(
                    "Cooldown (minutes)", min_value=1, max_value=120, value=10
                )

            submitted = st.form_submit_button("Add condition")
            if submitted:
                condition = Condition(
                    color=COLOR_OPTIONS[color_label],
                    type=cond_type,
                    param_n=param_n,
                    param_threshold=param_threshold,
                    cooldown_minutes=cooldown,
                    user_email=user_email,
                )
                state.add_condition(condition)
                st.success(f"Added: {condition.description}")
                st.rerun()

        # List user's active conditions
        st.subheader("Your active conditions")
        user_conditions = state.get_conditions(user_email)
        if not user_conditions:
            st.info("No conditions configured yet.")
        else:
            for c in user_conditions:
                col_desc, col_status, col_del = st.columns([4, 2, 1])
                color_hex = COLOR_HEX.get(c.color, "#888")
                col_desc.markdown(
                    f'<span style="color:{color_hex};font-weight:bold;">'
                    f"{c.description}</span>",
                    unsafe_allow_html=True,
                )
                if c.last_fired_at:
                    col_status.caption(f"Last fired: {c.last_fired_at[:19]}")
                else:
                    col_status.caption("Never fired")
                if col_del.button("Delete", key=f"del_{c.id}"):
                    state.remove_condition(c.id, user_email)
                    st.rerun()

# ── Tab 3: Alert log (per-user) ─────────────────────────────────────────────

with tab_alerts:
    user_email = st.session_state.get("user_email")

    if not user_email:
        st.warning("Please log in to view your alert history.")
    else:
        alerts = state.get_alerts(user_email, n=50)
        if not alerts:
            st.info("No alerts fired yet.")
        else:
            for alert in reversed(alerts):
                icon = "✅" if alert.email_sent else "⚠️"
                st.markdown(
                    f"**{icon} {alert.fired_at[:19]}** — {alert.condition_desc}"
                )
                if alert.error:
                    st.caption(f"Error: {alert.error}")

# ── Auto-refresh ─────────────────────────────────────────────────────────────

if refresh:
    time.sleep(10)
    st.rerun()
