"""Adapter for Goldenrod Community Park (CalendarWiz widget).

The mobile widget (https://www.calendarwiz.com/mobile.html?crd=goldenrodcommunitypark)
only server-renders the current day's events; switching days in the browser
calls a JSON API (`cwapi.php?view=s&...`) behind the scenes. That API takes
an explicit begin/end date range and returns every event in it directly as
JSON, so we hit it ourselves instead of driving a browser.

Event titles for volleyball aren't consistent ("Adult Member Time:
Volleyball" vs. "Adult Volleyball Court B"), so events are matched loosely:
title contains "adult" and "volleyball" (case-insensitive).
"""

from datetime import datetime, timedelta

import requests

from ..models import Event
from .base import ClubAdapter

API_URL = "https://www.calendarwiz.com/cwapi.php"
LOOKAHEAD_DAYS = 90


class GoldenrodCommunityParkAdapter(ClubAdapter):
    club_name = "Goldenrod Community Park"
    category = "adult"
    schedule_url = "https://www.calendarwiz.com/mobile.html?crd=goldenrodcommunitypark"

    def scrape(self) -> list[Event]:
        start = datetime.now().date()
        end = start + timedelta(days=LOOKAHEAD_DAYS)

        params = {
            "fmt": "json",
            "view": "s",
            "crd": "goldenrodcommunitypark",
            "bd": start.day,
            "bm": start.month,
            "by": start.year,
            "ed": end.day,
            "em": end.month,
            "ey": end.year,
        }
        response = requests.get(API_URL, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        events: list[Event] = []
        for summary in data.get("eventsummaries", []):
            title = summary.get("title", "")
            lowered = title.lower()
            if "adult" not in lowered or "volleyball" not in lowered:
                continue

            event_start = self._parse_datetime(summary.get("event_startdatetime"))
            event_end = self._parse_datetime(summary.get("event_enddatetime"))
            if event_start is None:
                continue

            location = summary.get("location_name") or "Goldenrod Community Park"

            events.append(
                Event(
                    club=self.club_name,
                    title=title,
                    start=event_start,
                    end=event_end,
                    location=location,
                    url=self.schedule_url,
                )
            )

        return events

    @staticmethod
    def _parse_datetime(text: str | None) -> datetime | None:
        if not text:
            return None
        try:
            return datetime.strptime(text, "%m/%d/%Y %I:%M%p")
        except ValueError:
            return None
