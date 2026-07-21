"""Adapter for WPVC (https://www.wpvc.org/programs/adults).

The page is a client-rendered SPA (raw source has no content), so this
uses `fetch_rendered`. The page lists each actual session as its own
card (date + time), e.g. "Friday, June 19" / "8:00 PM - 10:30 PM" --
no year is given, so the current year is assumed. There's also a
"Session Details" card with title (`h2`), category label, description,
and location, used to fill in the rest of each event.
"""

import re
from datetime import datetime

from dateutil import parser as dateparser

from ..dateparse import coerce_upcoming_year
from ..fetch import fetch_rendered
from ..models import Event
from .base import ClubAdapter


class WPVCAdapter(ClubAdapter):
    club_name = "WPVC"
    category = "adult"
    schedule_url = "https://www.wpvc.org/programs/adults"

    def scrape(self) -> list[Event]:
        soup = fetch_rendered(self.schedule_url, wait_selector="h2")
        events: list[Event] = []

        title_el = soup.select_one("h2")
        category_el = soup.select_one("p.mb-3")
        if not title_el:
            return events
        title = title_el.get_text(strip=True)
        description = category_el.get_text(strip=True) if category_el else None

        # Cost tile in the stats grid: label "Cost", value like "$8 / person".
        # Walk up from the dollar icon to the smallest ancestor that has a
        # value <p>; matching the tile div by class alone is unreliable and
        # a :has() selector on the grid matches the whole grid first.
        price = None
        dollar_svg = soup.select_one("svg.lucide-dollar-sign")
        if dollar_svg:
            for parent in dollar_svg.parents:
                value_el = parent.select_one("p.mt-1") if hasattr(parent, "select_one") else None
                if value_el:
                    match = re.search(r"\$\s*(\d+(?:\.\d{2})?)", value_el.get_text())
                    if match:
                        price = float(match.group(1))
                    break

        location_el = soup.select_one('div:has(svg.lucide-map-pin) p.font-semibold')
        location_sub_el = soup.select_one('div:has(svg.lucide-map-pin) p.text-muted-foreground')
        location = " ".join(
            text for text in (
                location_el.get_text(strip=True) if location_el else None,
                location_sub_el.get_text(strip=True) if location_sub_el else None,
            ) if text
        ) or None

        for card in soup.select('div.rounded-lg.border.bg-card.p-4:has(svg.lucide-calendar-days)'):
            date_el = card.select_one("p.font-semibold, p.text-sm.font-semibold")
            time_el = card.select_one("p.text-xs, p.text-muted-foreground")
            if not date_el or not time_el:
                continue

            start, end = self._parse_session(date_el.get_text(strip=True), time_el.get_text(strip=True))
            if start is None:
                continue

            events.append(
                Event(
                    club=self.club_name,
                    title=title,
                    start=start,
                    end=end,
                    location=location,
                    description=description,
                    url=self.schedule_url,
                    price=price,
                )
            )

        return events

    @staticmethod
    def _parse_session(date_text: str, time_text: str) -> tuple[datetime | None, datetime | None]:
        year = datetime.now().year
        try:
            day = coerce_upcoming_year(dateparser.parse(f"{date_text} {year}")).date()
        except (ValueError, OverflowError):
            return None, None

        parts = [p.strip() for p in time_text.split(" - ")]
        try:
            start_time = dateparser.parse(parts[0]).time()
            end_time = dateparser.parse(parts[1]).time() if len(parts) > 1 else None
        except (ValueError, OverflowError):
            return datetime.combine(day, datetime.min.time()), None

        start = datetime.combine(day, start_time)
        end = datetime.combine(day, end_time) if end_time else None
        return start, end
