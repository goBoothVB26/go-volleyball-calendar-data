"""Adapter for YMCA Central Florida Adult Volleyball
(https://ymcacf.org/programs/adultsports/volleyball/).

The page is a JS-driven widget (`#ymca-events`), so this uses
`fetch_rendered`. The location filter defaults to "Any Location" (the
select's empty `value=""` option), which already covers every branch, so
no filter interaction is needed.

Each card gives a start/end date range and a set of weekday abbreviations
("DAYS OF WEEK") but no time, so events are expanded to one per matching
weekday in the range via `leagueapps.weekly_dates`, with no start/end time
set.
"""

from datetime import datetime

from dateutil import parser as dateparser

from .. import leagueapps
from ..fetch import fetch_rendered
from ..models import Event
from .base import ClubAdapter


class YMCACentralFloridaAdapter(ClubAdapter):
    club_name = "YMCA Central Florida"
    category = "adult"
    schedule_url = "https://ymcacf.org/programs/adultsports/volleyball/"

    def scrape(self) -> list[Event]:
        soup = fetch_rendered(self.schedule_url, wait_selector=".ymca-event-card")
        events: list[Event] = []

        for card in soup.select(".ymca-event-card"):
            title_el = card.select_one(".ymca-event-card-title")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)

            location_el = card.select_one(".ymca-event-location")
            location = location_el.get_text(strip=True) if location_el else None

            start_date, end_date = self._parse_date_range(card)
            if start_date is None or end_date is None:
                continue

            weekdays = self._parse_weekdays(card)
            if not weekdays:
                continue

            for day in leagueapps.weekly_dates(start_date, end_date, weekdays):
                events.append(
                    Event(
                        club=self.club_name,
                        title=title,
                        start=datetime.combine(day, datetime.min.time()),
                        end=None,
                        location=location,
                        url=self.schedule_url,
                    )
                )

        return events

    @staticmethod
    def _parse_date_range(card):
        highlights = card.select(".ymca-event-info-high-light")
        date_highlights = [h for h in highlights if "-" in h.get_text(strip=True) and any(c.isdigit() for c in h.get_text())]
        if len(date_highlights) < 2:
            return None, None
        try:
            start = dateparser.parse(date_highlights[0].get_text(strip=True)).date()
            end = dateparser.parse(date_highlights[1].get_text(strip=True)).date()
        except (ValueError, OverflowError):
            return None, None
        return start, end

    @staticmethod
    def _parse_weekdays(card) -> set[int]:
        weekdays = set()
        for span in card.select(".ymca-day"):
            abbr = span.get_text(strip=True).lower()[:3]
            if abbr in leagueapps.WEEKDAY_ABBRS:
                weekdays.add(leagueapps.WEEKDAY_ABBRS.index(abbr))
        return weekdays
