"""Adapter for Out Sports League (LeagueApps-hosted).

Aggregates two league-listing pages -- indoor volleyball and sand
volleyball -- auto-discovering every program on each rather than
pointing at one hardcoded program ID, so new leagues LeagueApps adds
later are picked up automatically without code changes.

This is server-rendered LeagueApps HTML (no JS rendering, no
`?ngmp_2023_iframe_transition=1` param needed -- unlike GOVC, this
site's plain URLs already return full content).

Two shapes of `<li id="baseevent-...">` program appear on a list page:
  - A directly-dated program (e.g. sand volleyball's single league):
    has real Starts/Ends dates right there in its `dl.basic`, so it's
    parsed immediately into one calendar event per matching week (see
    `scraper/leagueapps.py` for the shared parsing helpers and the
    weekday-resolution heuristic).
  - A GROUPING program (e.g. "Orlando INDOOR VOLLEYBALL"): only shows a
    vague "Season" label, no Starts/Ends, plus a "View Sub-Programs"
    link. Its own detail page (the same URL its title links to) lists
    the real dated sub-programs -- e.g. "Tuedays - Recreational (C/D)",
    "Thursdays - Competitive (A/B)" -- as standard baseevent li markup,
    each directly parseable the same way. _parse_program_li() recurses
    into that detail page when it finds no usable dates, capped at a
    couple of levels deep as a safety net against an unexpected cycle.

Each directly-dated program's own detail page (the same page its
title links to) separately carries the real prose description --
skill-level breakdown, league info, fees, location, FAQ, etc. -- via
the shared `leagueapps.extract_rich_description` helper. That page is
fetched once per program (not once per weekly event) and its text
becomes the event description, replacing the terse "season" label
from the list page. If the detail page can't be fetched or has no
`div.mod`, the adapter falls back to that short season label so a
site hiccup never breaks the whole scrape.
"""

from datetime import datetime
from typing import Optional

from .. import leagueapps
from ..fetch import fetch_static
from ..models import Event
from .base import ClubAdapter

BASE_URL = "https://outsportsleague.leagueapps.com"

LEAGUE_LIST_URLS = [
    f"{BASE_URL}/leagues/volleyball-(indoor)",
    f"{BASE_URL}/leagues/volleyball-(sand)",
]

# How many levels of "grouping program -> its own detail page" to
# follow before giving up. Two real levels are known to exist (top
# list -> grouping program -> dated sub-programs); this allows one
# extra level of headroom without risking an unbounded recursion if a
# future page shape doesn't resolve to real dates.
_MAX_RECURSION_DEPTH = 3


class OutSportsLeagueAdapter(ClubAdapter):
    club_name = "Out Sports League"
    category = "adult"
    schedule_url = LEAGUE_LIST_URLS[0]

    def scrape(self) -> list[Event]:
        events: list[Event] = []
        for list_url in LEAGUE_LIST_URLS:
            soup = fetch_static(list_url)
            for li in soup.select('li[id^="baseevent-"]'):
                events.extend(self._parse_program_li(li))
        return events

    def _parse_program_li(self, li, depth: int = 0) -> list[Event]:
        title_el = li.select_one("h2 a")
        if not title_el:
            return []
        title = title_el.get_text(strip=True)

        href = title_el["href"]
        url = (BASE_URL + href) if href.startswith("/") else href

        details = leagueapps.parse_details(li)
        start_date = leagueapps.parse_date(details.get("starts"))
        end_date = leagueapps.parse_date(details.get("ends"))

        if start_date is None or end_date is None:
            # No real dates here -- a grouping program whose actual
            # dated sub-programs live on its own detail page.
            if depth >= _MAX_RECURSION_DEPTH:
                return []
            try:
                detail_soup = fetch_static(url)
            except Exception:
                return []
            events: list[Event] = []
            for sub_li in detail_soup.select('li[id^="baseevent-"]'):
                events.extend(self._parse_program_li(sub_li, depth=depth + 1))
            return events

        weekdays = leagueapps.resolve_weekdays(li, title)
        if not weekdays:
            return []

        start_time, end_time = leagueapps.parse_time_range(li)
        price = leagueapps.parse_fee(li)

        location_el = li.select_one("dd.program-list-location a")
        location = location_el.get_text(strip=True) if location_el else None

        description = self._scrape_program_description(url) or details.get("season")

        return [
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
            for day in leagueapps.weekly_dates(start_date.date(), end_date.date(), weekdays)
        ]

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
