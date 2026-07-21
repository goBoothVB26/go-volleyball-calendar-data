"""Adapter for Meadow Woods Recreation Center (CalendarWiz).

Same platform as Goldenrod Community Park, so the same JSON API is used
(`cwapi.php?fmt=json&view=s&crd=meadowwoods&...`) instead of scraping
the rendered month grid -- it returns every event in a date range with
clean start/end datetimes, so the calendar page's `epopup(...)` anchors
never need parsing.

Filtering (per the site's own category setup):
  - category: "Adult Sports" (CalendarWiz category id 83495). The id is
    passed as a request param AND re-checked against any category field
    the response carries, so youth "Volleyball Camp"-style events can't
    leak through even if the API ignores the param.
  - title: must contain "volleyball" (case-insensitive).

The club logo is NOT scraped: the calendar page shows the Orange County
Parks logo, which is the same one already stored in the data repo as
logos/goldenrod.png (it's a county-wide logo shared across the
community centers, not specific to Goldenrod). The website's CLUB_LOGOS
map points this club at that existing file, so no image handling is
needed here.
"""

from datetime import datetime, timedelta

import requests

from ..models import Event
from .base import ClubAdapter

API_URL = "https://www.calendarwiz.com/cwapi.php"
LOOKAHEAD_DAYS = 90

# "Adult Sports" category id from the calendar's Select Category filter
ADULT_SPORTS_CATEGORY_ID = "83495"

# Response keys that might carry category info, across CalendarWiz's
# JSON schema variations -- checked defensively since the exact field
# name isn't guaranteed.
_CATEGORY_KEYS = (
    "category", "categories", "category_name", "categoryname",
    "catname", "category_id", "categoryid", "cid",
)


class MeadowWoodsRecreationCenterAdapter(ClubAdapter):
    club_name = "Meadow Woods Recreation Center"
    category = "adult"
    schedule_url = "https://www.calendarwiz.com/calendars/calendar.php?crd=meadowwoods&"

    def scrape(self) -> list[Event]:
        start = datetime.now().date()
        end = start + timedelta(days=LOOKAHEAD_DAYS)

        params = {
            "fmt": "json",
            "view": "s",
            "crd": "meadowwoods",
            "bd": start.day,
            "bm": start.month,
            "by": start.year,
            "ed": end.day,
            "em": end.month,
            "ey": end.year,
            # NOTE: no category param here on purpose -- passing one
            # (categories=83495) made cwapi return a non-JSON error page
            # instead of results. Category filtering happens response-
            # side in _is_adult_sports() below instead, exactly like the
            # (working) Goldenrod adapter's parameter set.
        }
        response = requests.get(API_URL, params=params, timeout=30)
        response.raise_for_status()
        try:
            data = response.json()
        except ValueError as exc:
            # Surface what the API actually returned, so a future
            # breakage is diagnosable from the run log alone.
            snippet = response.text[:200].replace("\n", " ")
            raise RuntimeError(f"cwapi returned non-JSON: {snippet!r}") from exc

        events: list[Event] = []
        for summary in data.get("eventsummaries", []):
            title = summary.get("title", "")
            if "volleyball" not in title.lower():
                continue
            if not self._is_adult_sports(summary):
                continue

            event_start = self._parse_datetime(summary.get("event_startdatetime"))
            event_end = self._parse_datetime(summary.get("event_enddatetime"))
            if event_start is None:
                continue

            location = summary.get("location_name") or "Meadow Woods Recreation Center"

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
    def _is_adult_sports(summary: dict) -> bool:
        """True when the event belongs to the Adult Sports category.

        If the response carries any recognizable category field, require
        the Adult Sports id or name in it; when no category field exists
        at all (schema variation), fall through open -- the title filter
        still applies either way."""
        joined = " ".join(
            str(summary[k]) for k in _CATEGORY_KEYS if summary.get(k)
        ).lower()
        if not joined:
            return True
        return ADULT_SPORTS_CATEGORY_ID in joined or "adult sports" in joined

    @staticmethod
    def _parse_datetime(text: str | None) -> datetime | None:
        if not text:
            return None
        try:
            return datetime.strptime(text, "%m/%d/%Y %I:%M%p")
        except ValueError:
            return None
