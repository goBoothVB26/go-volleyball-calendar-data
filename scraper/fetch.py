"""Shared page-fetching helpers.

Tries a plain HTTP GET first since it's fast and cheap. Falls back to a
headless browser (Playwright) for sites that render the schedule with
JavaScript and return little/no usable HTML on first load.

The headless browser is launched lazily on first use and then shared by
every rendered fetch in the run (one Chromium launch instead of one per
page — NAGVA alone fetches ~10 detail pages). Call `shutdown()` when the
run is finished; `main.run()` does this in a finally block.

Both fetchers retry transient failures with a short backoff so a single
network blip doesn't wipe out an adapter for the whole run.
"""

import time

from bs4 import BeautifulSoup
import requests

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

RETRIES = 2  # attempts = RETRIES + 1
RETRY_BACKOFF_S = 2

_playwright = None
_browser = None


def _get_browser():
    global _playwright, _browser
    if _browser is None:
        from playwright.sync_api import sync_playwright

        _playwright = sync_playwright().start()
        _browser = _playwright.chromium.launch()
    return _browser


def new_page(**kwargs):
    """Open a tab in the shared headless browser (launched on first use).

    For adapters that need to drive the page themselves (fill filters,
    select dropdowns) rather than just grab rendered HTML. Callers must
    close() the page when done.
    """
    return _get_browser().new_page(**kwargs)


def shutdown() -> None:
    """Close the shared browser, if one was launched."""
    global _playwright, _browser
    if _browser is not None:
        _browser.close()
        _browser = None
    if _playwright is not None:
        _playwright.stop()
        _playwright = None


def _retry(fn):
    for attempt in range(RETRIES + 1):
        try:
            return fn()
        except Exception:
            if attempt == RETRIES:
                raise
            time.sleep(RETRY_BACKOFF_S * (attempt + 1))


def fetch_static(url: str, timeout: int = 20) -> BeautifulSoup:
    def attempt() -> BeautifulSoup:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")

    return _retry(attempt)


def fetch_rendered(
    url: str, wait_selector: str | None = None, timeout: int = 30000, settle_ms: int = 3000
) -> BeautifulSoup:
    """Render the page with a headless browser, for JS-driven schedule widgets.

    `wait_selector` only guarantees the selector exists -- some SPAs (e.g.
    Volleyball Life) render a loading-skeleton card matching the selector
    before the real data populates it, so `wait_for_selector` can resolve
    too early. `settle_ms` gives the page a bit more time after that to
    finish populating before we grab the HTML.
    """

    def attempt() -> BeautifulSoup:
        page = new_page(user_agent=USER_AGENT)
        try:
            page.goto(url, timeout=timeout)
            if wait_selector:
                page.wait_for_selector(wait_selector, timeout=timeout)
            if settle_ms:
                page.wait_for_timeout(settle_ms)
            html = page.content()
        finally:
            page.close()
        return BeautifulSoup(html, "lxml")

    return _retry(attempt)
