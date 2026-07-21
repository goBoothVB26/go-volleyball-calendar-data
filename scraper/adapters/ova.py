"""Adapter for OVA / LVA Orlando (https://www.lvaorlando.com/).

TODO: real page structure not yet inspected (no network access in this
environment). Replace selectors below once you've viewed the actual
schedule page source.
"""

from datetime import datetime

from dateutil import parser as dateparser

from ..fetch import fetch_static
from ..models import Event
from .base import ClubAdapter


class OVAAdapter(ClubAdapter):
    club_name = "OVA"
    category = "youth"
    schedule_url = "https://www.lvaorlando.com/"  # TODO: point at the actual schedule page

    def scrape(self) -> list[Event]:
        soup = fetch_static(self.schedule_url)
        events: list[Event] = []

        # TODO: replace with the real container/row selectors for this site.
        for row in soup.select(".schedule-row"):
            title_el = row.select_one(".event-title")
            date_el = row.select_one(".event-date")
            location_el = row.select_one(".event-location")
            if not title_el or not date_el:
                continue

            start = self._parse_date(date_el.get_text(strip=True))
            if start is None:
                continue

            events.append(
                Event(
                    club=self.club_name,
                    title=title_el.get_text(strip=True),
                    start=start,
                    location=location_el.get_text(strip=True) if location_el else None,
                    url=self.schedule_url,
                )
            )

        return events

    @staticmethod
    def _parse_date(text: str) -> datetime | None:
        try:
            return dateparser.parse(text)
        except (ValueError, OverflowError):
            return None
