from __future__ import annotations

import asyncio
import logging
import subprocess

from playwright.async_api import async_playwright, Page, Browser

import auth
import conditions as cond_engine
import notifier
from state import SharedState, Roll, Alert

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 15
TARGET_URL = "https://csgoempire.com/roulette"

JS_POLL = """
() => {
    const app = document.querySelector('#app');
    if (!app || !app.__vue_app__) return null;
    const store = app.__vue_app__.config.globalProperties.$store;
    if (!store) return null;
    const r = store.state.roulette;
    return {
        rolls: r.previousRolls.map(x => ({ index: x.index, coin: x.coin })),
        index: r.previousRollsIndex,
        round: r.round,
        state: r.roundState
    };
}
"""


async def _accept_cookies(page: Page) -> None:
    try:
        accept_btn = page.locator('a:has-text("Accept")').first
        if await accept_btn.is_visible(timeout=3000):
            await accept_btn.click()
            logger.info("Accepted cookies")
    except Exception:
        pass


async def _poll_once(page: Page, state: SharedState) -> None:
    data = await page.evaluate(JS_POLL)
    if data is None:
        logger.warning("Vuex store not accessible yet")
        return

    raw_rolls = data.get("rolls", [])
    server_index = data.get("index", 0)

    if server_index <= state.last_index and state.last_index > 0:
        return

    new_rolls = [
        Roll(index=r["index"], coin=r["coin"])
        for r in raw_rolls
        if r["index"] > state.last_index
    ]

    if not new_rolls:
        if state.last_index == 0 and raw_rolls:
            seed = [Roll(index=r["index"], coin=r["coin"]) for r in raw_rolls]
            state.add_rolls(seed)
            logger.info("Seeded %d historical rolls", len(seed))
        return

    added = state.add_rolls(new_rolls)
    if added:
        logger.info(
            "Added %d new rolls (latest index: %d)",
            len(added), state.last_index,
        )

    _evaluate_conditions(state)


def _evaluate_conditions(state: SharedState) -> None:
    rolls = state.get_rolls(100)

    for condition in state.get_all_conditions():
        if not condition.enabled:
            continue
        if cond_engine.is_in_cooldown(condition):
            continue
        if not cond_engine.evaluate(condition, rolls):
            continue

        logger.info("Condition triggered: %s (user: %s)", condition.description, condition.user_email)

        success, error = False, "No Discord ID configured"
        discord_id = auth.get_discord_id(condition.user_email) if condition.user_email else None
        if discord_id and notifier.is_configured():
            success, error = notifier.send_alert(discord_id, condition, rolls)
        elif not discord_id:
            logger.warning("No Discord ID for user %s, skipping notification", condition.user_email)

        state.update_condition_fired(condition.id)
        state.add_alert(Alert(
            condition_id=condition.id,
            condition_desc=condition.description,
            user_email=condition.user_email,
            email_sent=success,
            error=error,
        ))


async def _run_scraper_loop(page: Page, state: SharedState) -> None:
    state.set_scraper_status("running")
    while True:
        try:
            await _poll_once(page, state)
        except Exception:
            logger.exception("Error during poll")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


def _ensure_browser_installed() -> None:
    """Install Chromium if not already present (needed on Streamlit Cloud)."""
    try:
        subprocess.run(
            ["playwright", "install", "chromium"],
            check=True, capture_output=True, text=True,
        )
        logger.info("Playwright Chromium installed/verified")
    except Exception:
        logger.exception("Failed to install Chromium — it may already be present")


async def _run_async(state: SharedState) -> None:
    """Async entry point — connects Playwright and polls forever."""
    _ensure_browser_installed()

    while True:
        browser: Browser | None = None
        try:
            logger.info("Starting Playwright browser")
            state.set_scraper_status("starting")

            pw = await async_playwright().start()
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page()

            logger.info("Navigating to %s", TARGET_URL)
            await page.goto(TARGET_URL, wait_until="networkidle", timeout=60000)
            await _accept_cookies(page)

            await page.wait_for_function(
                "() => document.querySelector('#app')?.__vue_app__?.config?.globalProperties?.$store?.state?.roulette?.previousRolls?.length > 0",
                timeout=30000,
            )
            logger.info("Vuex store ready, starting poll loop")

            await _run_scraper_loop(page, state)

        except Exception as exc:
            error_msg = str(exc)
            logger.exception("Scraper crashed, restarting in 30s")
            state.set_scraper_status("error", error_msg)

            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

            await asyncio.sleep(30)


def run_scraper(state: SharedState) -> None:
    """Sync wrapper — creates its own event loop. Safe to call from a thread.

    On Windows, Streamlit/Tornado sets a SelectorEventLoop policy which does
    not support subprocess creation. Playwright needs ProactorEventLoop to
    spawn its Node.js driver process.
    """
    import sys

    if sys.platform == "win32":
        loop = asyncio.ProactorEventLoop()  # type: ignore[attr-defined]
    else:
        loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(_run_async(state))
