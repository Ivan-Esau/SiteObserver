from __future__ import annotations

import threading
import time

import streamlit as st

from state import SharedState, Condition, COLORS
from scraper import run_scraper
import notifier

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


# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("SiteObserver")

    # Scraper status
    scraper_status, scraper_error = state.get_scraper_status()
    status_colors = {
        "running": "🟢", "starting": "🟡",
        "stopped": "🔴", "error": "🔴",
    }
    st.markdown(f"**Scraper:** {status_colors.get(scraper_status, '⚪')} {scraper_status}")
    if scraper_error:
        st.caption(f"Error: {scraper_error[:100]}")

    st.divider()

    # Email config
    st.subheader("Email notifications")
    if notifier.is_configured():
        st.caption("Resend API key: configured")
    else:
        st.warning("Set RESEND_API_KEY in .env or Streamlit secrets")

    current_email = state.get_email()
    new_email = st.text_input("Notification email", value=current_email)
    if new_email != current_email:
        state.set_email(new_email)
        st.success("Email saved")

    st.divider()

    # Auto-refresh
    refresh = st.toggle("Auto-refresh (10s)", value=True)


# ── Main area ────────────────────────────────────────────────────────────────

tab_rolls, tab_conditions, tab_alerts = st.tabs(["Live Rolls", "Alert Conditions", "Alert Log"])

# ── Tab 1: Live rolls ───────────────────────────────────────────────────────

with tab_rolls:
    rolls = state.get_rolls(100)

    if not rolls:
        st.info("Waiting for scraper to connect and receive rolls...")
    else:
        # Distribution bar
        ct = sum(1 for r in rolls if r.coin == "ct")
        t = sum(1 for r in rolls if r.coin == "t")
        bonus = sum(1 for r in rolls if r.coin == "bonus")
        total = len(rolls)

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total rolls", total)
        col2.metric("Black (CT)", ct)
        col3.metric("Orange (T)", t)
        col4.metric("Green (Bonus)", bonus)

        # Color-coded roll display (most recent first)
        st.subheader("Recent rolls")
        display_rolls = list(reversed(rolls[-50:]))
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

# ── Tab 2: Alert conditions ─────────────────────────────────────────────────

with tab_conditions:
    st.subheader("Add new condition")

    with st.form("add_condition", clear_on_submit=True):
        col_a, col_b = st.columns(2)
        with col_a:
            color_label = st.selectbox("Color", list(COLOR_OPTIONS.keys()))
            cond_type_label = st.selectbox("Condition type", list(CONDITION_TYPES.keys()))
        with col_b:
            cond_type = CONDITION_TYPES[cond_type_label]
            if cond_type == "count_below":
                param_n = st.number_input("In last N rolls", min_value=10, max_value=100, value=100)
                param_threshold = st.number_input("Below count", min_value=1, max_value=100, value=5)
            elif cond_type == "absent_streak":
                param_n = st.number_input("Absent for N rolls", min_value=5, max_value=100, value=20)
                param_threshold = 0
            else:
                param_n = st.number_input("Consecutive count", min_value=2, max_value=50, value=5)
                param_threshold = 0
            cooldown = st.number_input("Cooldown (minutes)", min_value=1, max_value=120, value=10)

        submitted = st.form_submit_button("Add condition")
        if submitted:
            condition = Condition(
                color=COLOR_OPTIONS[color_label],
                type=cond_type,
                param_n=param_n,
                param_threshold=param_threshold,
                cooldown_minutes=cooldown,
            )
            state.add_condition(condition)
            st.success(f"Added: {condition.description}")
            st.rerun()

    # List active conditions
    st.subheader("Active conditions")
    active_conditions = state.get_conditions()
    if not active_conditions:
        st.info("No conditions configured yet.")
    else:
        for c in active_conditions:
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
                state.remove_condition(c.id)
                st.rerun()

# ── Tab 3: Alert log ────────────────────────────────────────────────────────

with tab_alerts:
    alerts = state.get_alerts(50)
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
