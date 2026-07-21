"""Adapter for Out Sports League (LeagueApps-hosted, indoor volleyball).

https://outsportsleague.leagueapps.com/leagues/volleyball-(indoor)/5048667-orlando-indoor-volleyball

This is server-rendered LeagueApps HTML (no JS rendering needed). Each
program/session is an `<li id="baseevent-...">` listing a season (Starts/
Ends dates) rather than individual game dates, so we expand each one into
one calendar event per matching week. See `scraper/leagueapps.py` for the
shared parsing helpers and the weekday-resolution heuristic.

Each program's own detail page (the same page the "title" link points
to) carries the real description (extracted by the shared
leagueapps.extract_rich_description helper) -- skill-level
breakdown, league info, fees, location, FAQ, etc. That page is fetched
once per program (not once per weekly event) and its text becomes the
event description, replacing the terse "season" label from the list
page. If the detail page can't be fetched or has no `div.mod`, the
adapter falls back to that short season label so a site hiccup never
breaks the whole scrape.
"""

from datetime import datetime
from typing import Optional

from .. import leagueapps
from ..fetch import fetch_static
from ..models import Event
from .base import ClubAdapter

class OutSportsLeagueAdapter(ClubAdapter):
    club_name = "Out Sports League"
    category = "adult"
    schedule_url = "https://outsportsleague.leagueapps.com/leagues/volleyball-(indoor)/5048667-orlando-indoor-volleyball"

    def scrape(self) -> list[Event]:
        soup = fetch_static(self.schedule_url)
        events: list[Event] = []

        for li in soup.select('li[id^="baseevent-"]'):
            title_el = li.select_one("h2 a")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)

            weekdays = leagueapps.resolve_weekdays(li, title)
            if not weekdays:
                continue

            details = leagueapps.parse_details(li)
            start_date = leagueapps.parse_date(details.get("starts"))
            end_date = leagueapps.parse_date(details.get("ends"))
            if start_date is None or end_date is None:
                continue

            start_time, end_time = leagueapps.parse_time_range(li)
            price = leagueapps.parse_fee(li)

            location_el = li.select_one("dd.program-list-location a")
            location = location_el.get_text(strip=True) if location_el else None

            url = title_el["href"]
            if url.startswith("/"):
                url = "https://outsportsleague.leagueapps.com" + url

            description = self._scrape_program_description(url) or details.get("season")

            for day in leagueapps.weekly_dates(start_date.date(), end_date.date(), weekdays):
                events.append(
                    Event(
                        club=self.club_name,
                        title=title,
                        start=datetime.combine(day, start_time) if start_time else datetime.combine(day, datetime.min.time()),
                        end=datetime.combine(day, end_time) if end_time else None,
                        location=location,
                        description=description,
                        url=url,
                        price=price,
                    )
                )

        return events

    @staticmethod
    def _scrape_program_description(url: str) -> Optional[str]:
        """Full league description from the program's own detail page
        (skill-level breakdown, fees, location, FAQ, ...) via the shared
        LeagueApps rich-description extractor. Returns None on any
        failure so a fetch hiccup just falls back to the terse season
        label instead of breaking the whole scrape."""
        try:
            return leagueapps.extract_rich_description(fetch_static(url))
        except Exception:
            return None
