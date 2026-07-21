"""Adapter for Greater Orlando Volleyball Club (LeagueApps-hosted).

Aggregates three separate program-listing pages on the same site --
tournaments (single/multi-day events), leagues (weekly recurring
series), and classes (long-running weekly recurring sessions) -- into
one combined set of events. The site's outer pages are a React shell
that embeds the actual program listing in an iframe pointing at
LeagueApps' older server-rendered "monolith" markup (same `<li
id="baseevent-...">` structure as Out Sports League); appending
`?ngmp_2023_iframe_transition=1` fetches that monolith page directly
without needing a browser. See `scraper/leagueapps.py` for the shared
parsing helpers.

Subprogram pages (e.g. Open Gym class detail) use a different
`div.program-row` layout where each row is a single dated session.
The date comes from the `.program-name` text (e.g. "July 5th @
College Park"), the time and location come from the 2nd and 3rd
`<em>` tags inside `.col-4` of that row.
"""

import re
from datetime import datetime
from typing import Optional

from dateutil import parser as dateparser

from .. import leagueapps
from ..dateparse import coerce_upcoming_year
from ..tagging import infer_gym_type
from ..fetch import fetch_static
from ..models import Event
from .base import ClubAdapter

BASE_URL = "https://goadultsportsleague.leagueapps.com"

LIST_PAGE_URLS = [
    f"{BASE_URL}/tournaments?ngmp_2023_iframe_transition=1",
    f"{BASE_URL}/leagues?ngmp_2023_iframe_transition=1",
    f"{BASE_URL}/events?ngmp_2023_iframe_transition=1",
    # Classes are handled separately by _scrape_classes() which auto-discovers
    # each class and picks the right parser per entry -- do not add classes here.
]

# Classes list page -- scraped to auto-discover all active class links.
# Any new class added to the site is picked up automatically without
# code changes.
CLASSES_PAGE_URL = f"{BASE_URL}/classes?ngmp_2023_iframe_transition=1"

# A clock-time range like "2:00PM to 5:00PM" (the session's time slot).
_TIME_RANGE_RE = re.compile(r"\d{1,2}(:\d{2})?\s*(am|pm)\s+to\s+\d", re.IGNORECASE)

# A season date range like "Jul 1 - Sep 30": month name + day + dash.
_DATE_RANGE_HINT_RE = re.compile(
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\.?\s+\d{1,2}\s*[-–]",
    re.IGNORECASE,
)

# A venue name in prose, e.g. "Come play grass with us at Cady Way Park"
# -> "Cady Way Park". Used when a program has no structured location.
_VENUE_RE = re.compile(
    r"\b([A-Z][\w'.-]*(?:\s+[A-Z][\w'.-]*){0,4}\s+"
    r"(?:Park|Center|Complex|Gymnasium|Gym|Courts?|Field[s]?))\b"
)

# A dollar amount described as a registration/entry fee in prose, e.g.
# "$250 registration per team". Requires a fee keyword within the same
# sentence so prize money ("$500 cash prize") isn't mistaken for the fee.
_PROSE_FEE_RE = re.compile(
    r"\$\s*([\d,]+(?:\.\d{2})?)(?=[^.\n$]*\b(registration|entry|per\s+team|per\s+player|per\s+person)\b)",
    re.IGNORECASE,
)


def _parse_time_range(text: str) -> tuple[Optional[datetime], Optional[datetime]]:
    """Parse '2:00PM to 5:00PM' into a (start_time, end_time) pair."""
    parts = [p.strip() for p in text.lower().split(" to ")]
    try:
        start = dateparser.parse(parts[0]).time()
        end = dateparser.parse(parts[1]).time() if len(parts) > 1 else None
    except (ValueError, AttributeError):
        return None, None
    return start, end


class GreaterOrlandoVolleyballClubAdapter(ClubAdapter):
    club_name = "Greater Orlando Volleyball Club"
    category = "adult"
    schedule_url = BASE_URL

    def __init__(self) -> None:
        # Per-run memo of program detail pages: several extractors
        # (full description, prose fee, prose venue) all read the same
        # detail page, so it's fetched exactly once per program.
        self._detail_soups: dict = {}
        self._full_descriptions: dict = {}

    def scrape(self) -> list[Event]:
        events: list[Event] = []
        events.extend(self._scrape_list_pages())
        events.extend(self._scrape_classes())
        return events

    def _detail_soup(self, url: str):
        """Fetch (once) and memoize a program's detail page, with the
        iframe-transition param that yields server-rendered content.
        Returns None if the fetch fails."""
        if url not in self._detail_soups:
            detail_url = url + ("&" if "?" in url else "?") + "ngmp_2023_iframe_transition=1"
            try:
                self._detail_soups[url] = fetch_static(detail_url)
            except Exception:
                self._detail_soups[url] = None
        return self._detail_soups[url]

    def _scrape_full_description(self, url: str) -> Optional[str]:
        """Full rich description from the program's detail page via the
        shared LeagueApps extractor. Memoized separately from the soup
        because the extractor mutates the parse tree it flattens."""
        if url not in self._full_descriptions:
            soup = self._detail_soup(url)
            try:
                self._full_descriptions[url] = leagueapps.extract_rich_description(soup) if soup else None
            except Exception:
                self._full_descriptions[url] = None
        return self._full_descriptions[url]

    # ------------------------------------------------------------------
    # Tournaments + leagues: standard baseevent li markup
    # ------------------------------------------------------------------

    def _scrape_list_pages(self) -> list[Event]:
        """Scrape tournaments, leagues, and events pages using standard
        LeagueApps baseevent li markup. Events-page programs (pick-up
        style) also pull their prose description from the detail page."""
        events: list[Event] = []
        for page_url in LIST_PAGE_URLS:
            soup = fetch_static(page_url)
            fetch_prose = "/events?" in page_url
            for li in soup.select('li[id^="baseevent-"]'):
                events.extend(self._parse_baseevent_li(li, fetch_prose=fetch_prose))
        return events

    def _parse_baseevent_li(self, li, fetch_prose: bool = False) -> list[Event]:
        title_el = li.select_one("h2 a")
        if not title_el:
            return []
        title = title_el.get_text(strip=True)

        weekdays = leagueapps.resolve_weekdays(li, title)
        if not weekdays:
            return []

        details = leagueapps.parse_details(li)
        start_date = leagueapps.parse_date(details.get("starts"))
        end_date = leagueapps.parse_date(details.get("ends"))
        if start_date is None or end_date is None:
            return []

        start_time, end_time = leagueapps.parse_time_range(li)
        price = leagueapps.parse_fee(li)

        location_el = li.select_one("dd.program-list-location a")
        location = location_el.get_text(strip=True) if location_el else None

        url = title_el["href"]
        if url.startswith("/"):
            url = BASE_URL + url

        if price is None:
            # Some programs (e.g. Summer Bash tournament) state their fee
            # only in the detail page's prose ("$250 registration per team").
            price = self._scrape_prose_fee(url)

        # Every list-page program (tournaments/leagues/events) gets its
        # FULL rich description from its detail page -- tournament
        # details, formats, entry/prizes, how-to-register, etc. -- via
        # the shared LeagueApps extractor. The terse season label is
        # appended below it (or used alone if the fetch fails).
        season = details.get("season")
        full_description = self._scrape_full_description(url)
        if full_description:
            description = full_description + (f"\n\n{season}" if season else "")
        else:
            description = season

        if fetch_prose or location is None:
            # Events-page programs name their venue in prose ("...at
            # Cady Way Park...") -- used as the location fallback when
            # the structured Location field is missing. (Their prose
            # description is covered by the full description above; the
            # single-paragraph fallback only fills in when that failed.)
            prose_location, prose_description = self._scrape_detail_venue(url)
            if location is None:
                location = prose_location
            if prose_description and not full_description:
                description = prose_description + (f"\n\n{season}" if season else "")

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

    # ------------------------------------------------------------------
    # Classes: auto-discover from list page, then pick parser per class
    # ------------------------------------------------------------------

    def _scrape_classes(self) -> list[Event]:
        """Auto-discover all active classes from the classes list page.

        For each class: if the list-page li already has time + location
        AND an end date, the standard baseevent parser can expand it into
        weekly events on its own. If any of those are missing (e.g. Open
        Gym has no time/location; the Skills Training classes have no
        "Ends:" date), the real sessions are individual dated sub-rows on
        the detail page, so fetch that and use the subprogram parser.
        """
        events: list[Event] = []
        soup = fetch_static(CLASSES_PAGE_URL)

        for li in soup.select('li[id^="baseevent-"]'):
            title_el = li.select_one("h2 a")
            if not title_el:
                continue

            has_time = bool(li.select_one(".base-schedule em"))
            has_location = bool(li.select_one("dd.program-list-location a"))
            has_end_date = leagueapps.parse_date(leagueapps.parse_details(li).get("ends")) is not None

            if has_time and has_location and has_end_date:
                events.extend(self._parse_baseevent_li(li))
            else:
                href = title_el["href"]
                detail_url = (BASE_URL + href) if href.startswith("/") else href
                # Append the iframe-transition param so fetch_static gets the
                # server-rendered content instead of the empty React shell.
                detail_url += "?ngmp_2023_iframe_transition=1"
                program_title = title_el.get_text(strip=True)
                events.extend(self._scrape_subprogram_detail(detail_url, program_title))

        return events

    def _scrape_detail_venue(self, url: str) -> tuple[Optional[str], Optional[str]]:
        """(venue, description) from a detail page whose description
        paragraph names the venue in prose. Returns (None, None) on any
        failure. Uses the memoized detail-page fetch."""
        try:
            soup = self._detail_soup(url)
            if soup is None:
                return None, None
            for p in soup.find_all("p"):
                text = p.get_text(" ", strip=True)
                match = _VENUE_RE.search(text)
                if match:
                    return match.group(1), text
        except Exception:
            pass
        return None, None

    def _scrape_prose_fee(self, url: str) -> Optional[float]:
        """Fee from a detail page's free-text description, keyed to
        registration/entry wording. Returns None on any failure. Uses
        the memoized detail-page fetch."""
        try:
            soup = self._detail_soup(url)
            if soup is None:
                return None
            match = _PROSE_FEE_RE.search(soup.get_text(" ", strip=True))
            if match:
                return float(match.group(1).replace(",", ""))
        except Exception:
            pass
        return None

    def _scrape_subprogram_detail(self, url: str, program_title: str = "") -> list[Event]:
        """Parse a class detail page that lists individual dated sessions
        as div.program-row rows.

        Date → .program-name text before '@' (e.g. 'July 5th @ College Park').

        The .col-4 <em> elements are identified by content, not position:
        the time is the em matching a clock-time range ('2:00PM to 5:00PM'),
        the location is the last em that isn't the time and isn't the
        season date-range ('Jul 1 - Sep 30'). Some rows carry extra ems
        (e.g. a notes line), so fixed indexes mis-assign fields.
        """
        events: list[Event] = []
        year = datetime.now().year
        soup = fetch_static(url)

        # Session rows are titled by date ("July 5th @ College Park"), so
        # the gym type comes from the parent program's title instead
        # ("Open Gym - Summer Series" -> Open Gym; "Skills Training
        # Workout" -> Clinics/Training).
        gym_type = infer_gym_type(program_title) if program_title else None

        for row in soup.select("div.program-row"):
            name_el = row.select_one(".program-name")
            if not name_el:
                continue

            raw_name = name_el.get_text(strip=True)
            date_text = raw_name.split("@")[0].strip()
            # Bundle/summary rows like "All July Sessions @ College Park"
            # have no day number; fuzzy parsing would fill in TODAY's day
            # and invent a phantom event dated whenever the scraper ran.
            if not re.search(r"\d", date_text):
                continue
            try:
                event_date = dateparser.parse(f"{date_text} {year}", fuzzy=True)
            except (ValueError, OverflowError):
                continue
            if event_date is None:
                continue
            event_date = coerce_upcoming_year(event_date)

            em_texts = [em.get_text(strip=True) for em in row.select(".col-4 em")]
            time_text = next((t for t in em_texts if _TIME_RANGE_RE.search(t)), "")
            location_candidates = [
                t for t in em_texts
                if t and t != time_text and not _DATE_RANGE_HINT_RE.search(t)
            ]
            location = location_candidates[-1] if location_candidates else None

            price = None
            fee_el = row.select_one(".col-price .program-fee-amount")
            if fee_el:
                try:
                    price = float(fee_el.get_text(strip=True).replace(",", ""))
                except ValueError:
                    pass

            # Instructor column: the non-price .col-2 in the details grid
            instructor = None
            instructor_el = row.select_one(".program-details .col-2:not(.col-price) em")
            if instructor_el:
                name = instructor_el.get_text(strip=True)
                if name and name.upper() != "TBD":
                    instructor = f"Instructor: {name}"

            start_time, end_time = _parse_time_range(time_text) if time_text else (None, None)

            events.append(
                Event(
                    club=self.club_name,
                    title=raw_name,
                    start=datetime.combine(event_date.date(), start_time) if start_time else event_date,
                    end=datetime.combine(event_date.date(), end_time) if end_time else None,
                    location=location,
                    description=instructor,
                    url=url,
                    price=price,
                    gym_type=gym_type,
                )
            )

        return events
