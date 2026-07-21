"""Adapter for City of Sanford Adult Volleyball (rec1 registration catalog).

The "Adult Volleyball" program group lists each season as a catalog
item with day-of-week, a date range, and a time range right in the
summary row (e.g. "Sun" / "08/23-11/22" / "2pm-9pm") -- no need to open
the expanded per-item details table.

The catalog page lists ~100 unfiltered activities and only renders a
handful of groups up front; the "Adult Volleyball" group isn't in that
initial render. Driving the catalog's own search box (typing
"volleyball" and pressing Enter) narrows the list down to just the
matching groups, same as a user would do manually.
"""

import base64
import re
from datetime import datetime
from urllib.parse import quote

from dateutil import parser as dateparser

from .. import fetch, leagueapps
from ..models import Event
from .base import ClubAdapter

WEEKDAY_ABBRS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


class SanfordAdultVolleyballAdapter(ClubAdapter):
    club_name = "City of Sanford Adult Volleyball"
    category = "adult"
    schedule_url = "https://secure.rec1.com/FL/sanford-fl/catalog/index/01268e61f70f8acae7d1913bf1ae0e3b"

    def scrape(self) -> list[Event]:
        from bs4 import BeautifulSoup

        page = fetch.new_page()
        try:
            page.goto(self.schedule_url, timeout=30000)
            page.wait_for_selector("#filter_search", timeout=30000)
            page.fill("#filter_search", "volleyball")
            page.keyboard.press("Enter")
            page.wait_for_selector(".rec1-catalog-group", timeout=30000)
            page.wait_for_timeout(2000)
            html = page.content()
        finally:
            page.close()

        soup = BeautifulSoup(html, "lxml")
        events: list[Event] = []

        for group in soup.select(".rec1-catalog-group"):
            heading = group.select_one(".rec1-catalog-group-name")
            if not heading or "volleyball" not in heading.get_text(strip=True).lower():
                continue

            for item in group.select(".rec1-catalog-item"):
                title_el = item.select_one(".rec1-catalog-item-name a")
                location_el = item.select_one(".rec1-catalog-item-feature.location span")
                days_el = item.select_one(".rec1-catalog-item-feature.days span")
                dates_el = item.select_one(".rec1-catalog-item-feature.dates span")
                times_el = item.select_one(".rec1-catalog-item-feature.times span")
                if not title_el or not days_el or not dates_el:
                    continue

                title = title_el.get_text(strip=True)
                weekdays = {
                    WEEKDAY_ABBRS[abbr.strip().lower()[:3]]
                    for abbr in days_el.get_text(strip=True).split(",")
                    if abbr.strip().lower()[:3] in WEEKDAY_ABBRS
                }
                if not weekdays:
                    continue

                start_date, end_date = self._parse_date_range(dates_el.get_text(strip=True), title)
                if start_date is None or end_date is None:
                    continue

                start_time, end_time = self._parse_time_range(times_el.get_text(strip=True) if times_el else None)

                location = location_el.get_text(strip=True) if location_el else None

                # Row-level fee badge, e.g. <span class="item-price">$100</span>
                price = None
                price_el = item.select_one(".rec1-catalog-item-price .item-price")
                if price_el:
                    match = re.search(r"\$\s*([\d,]+(?:\.\d{2})?)", price_el.get_text())
                    if match:
                        price = float(match.group(1).replace(",", ""))

                # rec1 has no per-event pages (item links are
                # javascript:void(0)), but the catalog accepts a base64
                # `filter` param -- link to the catalog pre-searched to
                # this exact session name so it's the only item shown.
                event_url = self._deep_link(title)

                for day in leagueapps.weekly_dates(start_date, end_date, weekdays):
                    events.append(
                        Event(
                            club=self.club_name,
                            title=title,
                            start=datetime.combine(day, start_time) if start_time else datetime.combine(day, datetime.min.time()),
                            end=datetime.combine(day, end_time) if end_time else None,
                            location=location,
                            url=event_url,
                            price=price,
                        )
                    )

        return events

    def _deep_link(self, title: str) -> str:
        """Catalog URL pre-filtered to this session via the base64
        `filter` query param (same scheme rec1 itself uses)."""
        filter_b64 = base64.b64encode(f"search={title}".encode()).decode()
        return f"{self.schedule_url}?filter={quote(filter_b64)}"

    @staticmethod
    def _parse_date_range(text: str, title: str):
        match = re.search(r"(\d{1,2})/(\d{1,2})\s*-\s*(\d{1,2})/(\d{1,2})", text)
        if not match:
            return None, None
        month1, day1, month2, day2 = (int(part) for part in match.groups())

        year_match = re.search(r"\b(20\d{2})\b", title)
        year = int(year_match.group(1)) if year_match else datetime.now().year

        try:
            start = dateparser.parse(f"{month1}/{day1}/{year}").date()
            end_year = year + 1 if month2 < month1 else year
            end = dateparser.parse(f"{month2}/{day2}/{end_year}").date()
        except (ValueError, OverflowError):
            return None, None
        return start, end

    @staticmethod
    def _parse_time_range(text: str | None):
        if not text:
            return None, None
        parts = [p.strip() for p in text.split("-")]
        try:
            start_time = dateparser.parse(parts[0]).time()
            end_time = dateparser.parse(parts[1]).time() if len(parts) > 1 else None
        except (ValueError, OverflowError):
            return None, None
        return start_time, end_time
