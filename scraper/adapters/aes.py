"""Adapter for Advanced Event Systems (https://www.advancedeventsystems.com/events).

AES filters are applied entirely client-side via Angular: choosing an
"Event Type" or "Event Affiliation" dropdown option doesn't change the
URL, it re-filters an already-loaded event list. The "Event Type"
dropdown is also single-select, and "Adult Volleyball" formats
(Festival, Full Day Format, Two Day Format, ...) are separate options
within that one dropdown rather than a selectable group — so we select
the USAV affiliation once, then iterate every Adult Volleyball
event-type option in turn, scraping the result list after each
selection, and dedupe by event URL.
"""

import re
from datetime import datetime
from typing import Optional

from dateutil import parser as dateparser

from .. import fetch
from ..models import Event
from .base import ClubAdapter

AFFILIATION_USAV = "number:250004"

# "Adult Volleyball" optgroup option values from the Event Type dropdown.
ADULT_VOLLEYBALL_EVENT_TYPES = [
    "number:13",  # Festival
    "number:15",  # Full Day Format
    "number:16",  # Two Day Format
    "number:17",  # Three Day Format
    "number:20",  # National Championships
    "number:21",  # Other - Full Day
    "number:26",  # Other - Multi-Day
]

# The site's region filter doesn't reliably exclude everything, so events
# are also filtered after scraping:
#   - location must be in Florida (", FL")
#   - youth events (boys/girls/juniors) are skipped
#   - organizer "test" events are skipped
_FLORIDA_RE = re.compile(r",\s*FL\b", re.I)
_YOUTH_RE = re.compile(r"\b(boys?|girls?|juniors?)\b", re.I)
_TEST_RE = re.compile(r"\btest(ing)?\b", re.I)
_OFFICIALS_RE = re.compile(r"officials?\s+only", re.I)


class AESAdapter(ClubAdapter):
    club_name = "AES Adult Volleyball (USAV, Florida)"
    category = "adult"
    schedule_url = "https://www.advancedeventsystems.com/events"

    def scrape(self) -> list[Event]:
        events_by_url: dict[str, Event] = {}

        page = fetch.new_page()
        try:
            page.goto(self.schedule_url, timeout=30000)
            # The real <select> elements are visually hidden behind a custom
            # dropdown widget, so wait for "attached" rather than "visible"
            # and force selection past Playwright's actionability checks.
            page.wait_for_selector(
                '[data-test-id="filter-dropdown-affiliation"]', state="attached", timeout=30000
            )
            page.select_option('[data-test-id="filter-dropdown-affiliation"]', AFFILIATION_USAV, force=True)

            # The region dropdown's options are objects, so Angular's
            # ng-options assigns them opaque "object:N" hash-key values that
            # aren't stable across page loads — select by visible label
            # ("Florida (FL)") instead. It's also disabled until the
            # affiliation list has loaded, so wait for that first.
            page.wait_for_selector('[data-test-id="filter-dropdown-region"]', state="attached", timeout=30000)
            page.wait_for_function(
                "document.querySelector('[data-test-id=\"filter-dropdown-region\"]')"
                " && !document.querySelector('[data-test-id=\"filter-dropdown-region\"]').disabled",
                timeout=30000,
            )
            page.select_option(
                '[data-test-id="filter-dropdown-region"]', label="Florida (FL)", force=True
            )

            for event_type_value in ADULT_VOLLEYBALL_EVENT_TYPES:
                page.select_option('[data-test-id="filter-dropdown-event-type"]', event_type_value, force=True)
                page.wait_for_timeout(1500)

                for card in page.query_selector_all("a.aes-card"):
                    href = card.get_attribute("href")
                    if not href or href in events_by_url:
                        continue

                    title_el = card.query_selector(".public-event-card-title")
                    date_el = card.query_selector(".public-event-date span")
                    location_el = card.query_selector(".public-event-location span")
                    if not title_el or not date_el:
                        continue

                    title = title_el.inner_text().strip()
                    location = location_el.inner_text().strip() if location_el else None

                    if not location or not _FLORIDA_RE.search(location):
                        continue  # outside Florida (or no stated location)
                    if _YOUTH_RE.search(title):
                        continue  # boys/girls/juniors event
                    if _TEST_RE.search(title):
                        continue  # organizer test listing
                    if _OFFICIALS_RE.search(title):
                        continue  # officials-only event

                    start, end = self._parse_date_range(date_el.inner_text().strip())
                    if start is None:
                        continue

                    events_by_url[href] = Event(
                        club=self.club_name,
                        title=title,
                        start=start,
                        end=end,
                        location=location,
                        url=f"https://www.advancedeventsystems.com{href}",
                    )

            # Division entry fees live on each event's detail page in an
            # Angular divisions table (tr[ng-repeat over modal.divisions],
            # 2nd cell is the fee). Visit each kept event and take the
            # lowest division fee as the starting price.
            for href, event in events_by_url.items():
                try:
                    event.price = self._scrape_min_division_fee(page, href)
                except Exception:
                    pass  # price stays None; never fail the whole adapter
        finally:
            page.close()

        return list(events_by_url.values())

    @staticmethod
    def _scrape_min_division_fee(page, href: str) -> Optional[float]:
        row_selector = 'tr[ng-repeat*="modal.divisions"]'
        page.goto(f"https://www.advancedeventsystems.com{href}", timeout=30000)
        try:
            page.wait_for_selector(row_selector, state="attached", timeout=8000)
        except Exception:
            # The table may sit behind a "Divisions" link/button
            for el in page.query_selector_all("a, button"):
                if (el.inner_text() or "").strip().lower() == "divisions":
                    el.click()
                    break
            page.wait_for_selector(row_selector, state="attached", timeout=8000)

        prices = []
        for td in page.query_selector_all(row_selector + " td:nth-child(2)"):
            match = re.search(r"\$\s*([\d,]+(?:\.\d{2})?)", td.inner_text())
            if match:
                prices.append(float(match.group(1).replace(",", "")))
        return min(prices) if prices else None

    @staticmethod
    def _parse_date_range(text: str) -> tuple[Optional[datetime], Optional[datetime]]:
        # AES always renders a full range like "Feb 7, 2027 - Feb 7, 2027",
        # even for single-day events, so each side parses unambiguously.
        parts = [p.strip() for p in text.split(" - ")]
        try:
            start = dateparser.parse(parts[0])
            end = dateparser.parse(parts[1]) if len(parts) > 1 else start
        except (ValueError, OverflowError):
            return None, None
        return start, end
