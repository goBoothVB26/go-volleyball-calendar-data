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
from datetime import datetime, timedelta
from typing import Optional

from dateutil import parser as dateparser

from .. import fetch
from ..models import Event
from .base import ClubAdapter

AFFILIATION_USAV = "number:250004"

# "Adult Volleyball" optgroup labels from the Event Type dropdown,
# matched by their VISIBLE TEXT rather than the <option value="number:N">
# the dropdown renders. Those values come from an internal Angular index
# that isn't stable -- confirmed live: several of this list's original
# hardcoded values (e.g. "Two Day Format") had quietly stopped existing
# on the page at all, which made select_option retry until timeout
# instead of failing fast, while OTHER options had picked up a second,
# differently-valued duplicate under the same label. Labels are what the
# site actually guarantees stays put; same reasoning as the region
# dropdown below, which was already selected by label for exactly this
# kind of instability. "... - Girls"/"... - Boys" suffixed entries
# (National Championships/Qualifier/Region Bid) are youth-only and
# deliberately excluded.
ADULT_VOLLEYBALL_EVENT_TYPE_LABELS = [
    "Festival",
    "Half Day Format",
    "Full Day Format",
    "Two Day Format",
    "Three Day Format",
    "Four Day Format",
    "National Championships",
    "Other - Full Day",
    "Other - Multi-Day",
]

# The site's region filter doesn't reliably exclude everything, so events
# are also filtered after scraping:
#   - location must be in Florida (", FL")
#   - youth events (boys/girls/juniors, an explicit age bracket like
#     "(12-18...)" or "(13-17 OPEN)", or hosted at JJVA) are skipped
#   - organizer "test" events are skipped
# The age-bracket and JJVA checks exist because confirmed live: half of
# AES's "Adult Volleyball" format results were actually junior/club
# tournaments whose titles never use the words "boys/girls/juniors" at
# all -- age shows up only as a numeric range in the title ("Tropical
# Ice Challenge (12-18USA, 12O & 18O)"), or the event is simply hosted
# at JJVA (Jacksonville, FL), which every other one of those age-bracket
# events was also hosted at -- strongly suggesting it's a juniors
# academy venue, even for its own listings that don't state an age
# range in the title.
_FLORIDA_RE = re.compile(r",\s*FL\b", re.I)
_YOUTH_RE = re.compile(r"\b(boys?|girls?|juniors?)\b", re.I)
_YOUTH_AGE_BRACKET_RE = re.compile(r"\(\s*\d{1,2}\s*-\s*\d{1,2}|\(\s*\d{1,2}[UO]\b", re.I)
_JJVA_RE = re.compile(r"\bJJVA\b", re.I)
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

            for event_type_label in ADULT_VOLLEYBALL_EVENT_TYPE_LABELS:
                try:
                    # Short timeout: a label the site has renamed/removed
                    # should just be skipped, not stall the whole adapter
                    # until the full default timeout elapses.
                    page.select_option(
                        '[data-test-id="filter-dropdown-event-type"]',
                        label=event_type_label, force=True, timeout=5000,
                    )
                except Exception:
                    continue
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
                    if _YOUTH_RE.search(title) or _YOUTH_AGE_BRACKET_RE.search(title):
                        continue  # boys/girls/juniors event, or an explicit age bracket
                    if _JJVA_RE.search(title) or (location and _JJVA_RE.search(location)):
                        continue  # hosted at (or run by) JJVA, a juniors academy
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
                        # all-day dtend is exclusive (one day past the
                        # real last day) -- without all_day=True and this
                        # +1, a tournament rendered as a zero-duration
                        # event at midnight instead of spanning its day(s).
                        end=end + timedelta(days=1) if end else None,
                        all_day=True,
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
