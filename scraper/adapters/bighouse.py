"""Adapter for Big House Open Gym and League Play (Tavares, FL).

Two Weebly pages, both scraped on every run:

1. Open Gym -- a "pick your date" storefront product, where each
   available night is a checkbox option (e.g. "June 2", value/data-price
   attributes for the add-on fee). The page gives no year or time; the
   year is assumed to be the current year, and the 8:15-10:15 PM EST time
   slot is fixed per the club (Tuesdays/Thursdays), since it's only
   published in prose on a different page.

2. League Play (https://www.bighouseusa.com/bighouseadultvolleyball.html)
   -- a plain HTML table, NOT one row per event. Column 0 (the "League
   Play" column) packs three different kinds of information into its
   three data rows instead:
     row 1: every play date, grouped by month ("October 20, 27",
            "November 10, 17, 24", ...), each on its own line (<br>).
     row 2: dates with no play (e.g. "No Play on November 3").
     row 3: "Scheduled Times: 6:30p and 7:45" -- the two match start
            times run that night.
   Columns 1-3 (Important Dates / Registration Fees / Free Agents &
   Roster Size) hold registration/fee prose for each row and are folded
   into the description so nothing on the page is lost, even though
   only column 0 determines the actual event dates/times.
"""

import re
from datetime import date, datetime, time, timedelta

from dateutil import parser as dateparser

from ..dateparse import coerce_upcoming_year
from ..fetch import fetch_static
from ..models import Event
from .base import ClubAdapter

START_TIME = time(20, 15)
END_TIME = time(22, 15)
LOCATION = "The Big House, Tavares, FL"

LEAGUE_SCHEDULE_URL = "https://www.bighouseusa.com/bighouseadultvolleyball.html"
LEAGUE_TITLE = "Big House League Play"
# Scheduled Times only ever gives start times ("6:30p and 7:45"), not an
# end time for the last match -- assumed same length as the gap between
# the two starts (an hour fifteen here), same inference style as the
# Open Gym time slot above.
LEAGUE_MATCH_DURATION_MIN = 75

_DATE_LINE_RE = re.compile(r"^([A-Za-z]+)\s+(.+)$")
_NO_PLAY_RE = re.compile(r"No Play on\s+([A-Za-z]+\s+\d{1,2})", re.IGNORECASE)
_TIME_TOKEN_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*([ap])?\.?m?\.?\b", re.IGNORECASE)
# The description ends up with several unrelated dollar amounts (a sponsor
# fee, a per-add-on free-agent fee, a $3 add/drop admin fee...) -- left to
# tag_event()'s generic "lowest dollar amount in the text" fallback, the
# $3 admin fee would get picked as "the price". Pulling the team fee out
# explicitly (same reasoning as NAGVA's _parse_price) avoids that. A
# closed/expired tier's row omits the dollar amount entirely ("Team Fee -
# (Includes ...)"), so only the still-open tier ever matches.
_TEAM_FEE_RE = re.compile(r"Team Fee\s*-\s*\$\s*(\d+(?:\.\d{2})?)", re.IGNORECASE)


def _cell_lines(cell) -> list[str]:
    """A table cell's text, one entry per line, blanks dropped. Formatting
    tags (<strong>, <font>, ...) collapse to plain text, which is all the
    date/time parsing below needs.

    Lines are separated by <br> tags on the pasted snapshot of this page,
    but the live page's raw text also carries literal \\r\\n / bare \\r
    line breaks inside the same cell (CRLF/CR, not <br> elements) --
    those have to be normalized to \\n too, or everything after the first
    one gets glued onto one unparseable line.
    """
    for br in cell.find_all("br"):
        br.replace_with("\n")
    text = cell.get_text().replace("\r\n", "\n").replace("\r", "\n")
    return [line.strip() for line in text.split("\n") if line.strip()]


def _parse_date_list(cell) -> list[date]:
    year = datetime.now().year
    days: list[date] = []
    for line in _cell_lines(cell):
        m = _DATE_LINE_RE.match(line)
        if not m:
            continue
        month_name, rest = m.groups()
        for day_token in rest.split(","):
            digits = re.sub(r"\D", "", day_token)
            if not digits:
                continue
            try:
                parsed = dateparser.parse(f"{month_name} {digits} {year}")
            except (ValueError, OverflowError):
                continue
            days.append(coerce_upcoming_year(parsed).date())
    return days


def _parse_excluded_dates(cell) -> set[date]:
    year = datetime.now().year
    text = " ".join(_cell_lines(cell))
    excluded: set[date] = set()
    for month_day in _NO_PLAY_RE.findall(text):
        try:
            parsed = dateparser.parse(f"{month_day} {year}")
        except (ValueError, OverflowError):
            continue
        excluded.add(coerce_upcoming_year(parsed).date())
    return excluded


def _parse_scheduled_times(cell) -> list[time]:
    text = " ".join(_cell_lines(cell))
    label = re.search(r"Scheduled Times:?\s*(.+)", text, re.IGNORECASE)
    if not label:
        return []
    times: list[time] = []
    last_meridiem = "p"  # evening league; "7:45" with no suffix inherits the prior one
    for tok in _TIME_TOKEN_RE.finditer(label.group(1)):
        hour = int(tok.group(1))
        if hour > 12:
            continue
        minute = int(tok.group(2) or 0)
        meridiem = (tok.group(3) or last_meridiem).lower()
        last_meridiem = meridiem
        hour24 = (hour % 12) + (12 if meridiem == "p" else 0)
        times.append(time(hour24, minute))
    return times


def _build_description(headers: list[str], rows) -> str:
    """Every row's Important Dates / Registration Fees / Free Agents cell
    (everything but column 0, which is parsed separately for dates/times),
    labelled with that column's own header text -- so registration and fee
    details survive even though they don't drive the event dates."""
    blocks = []
    for tr in rows:
        cells = tr.select("td")
        if len(cells) < 2:
            continue
        parts = []
        for i in range(1, len(cells)):
            label = headers[i] if i < len(headers) else f"Column {i + 1}"
            text = " ".join(_cell_lines(cells[i]))
            if text:
                parts.append(f"{label}: {text}")
        if parts:
            blocks.append("\n".join(parts))
    return "\n\n".join(blocks)


def _parse_team_fee(headers: list[str], rows) -> float | None:
    fee_col = next(
        (i for i, h in enumerate(headers) if "registration fee" in h.lower()), None
    )
    if fee_col is None:
        return None
    fee = None
    for tr in rows:
        cells = tr.select("td")
        if fee_col >= len(cells):
            continue
        m = _TEAM_FEE_RE.search(" ".join(_cell_lines(cells[fee_col])))
        if m:
            fee = float(m.group(1))  # last (most current) match wins
    return fee


class BigHouseOpenGymAdapter(ClubAdapter):
    club_name = "Big House Open Gym"
    category = "adult"
    schedule_url = "https://www.bighouseusa.com/store/p228/Big_House_Volleyball_Open_Gym_-_Pick_Your_Date.html"

    def scrape(self) -> list[Event]:
        events = self._scrape_open_gym()
        try:
            events.extend(self._scrape_league())
        except Exception:
            # The league page is a second, unrelated scrape -- a layout
            # change or outage there shouldn't cost us the Open Gym dates.
            pass
        return events

    def _scrape_open_gym(self) -> list[Event]:
        soup = fetch_static(self.schedule_url)
        events: list[Event] = []

        date_group = soup.select_one('div[data-modifier-name="Date"]')
        if not date_group:
            return events

        year = datetime.now().year
        for checkbox in date_group.select('input[type="checkbox"]'):
            date_text = checkbox.get("name")
            if not date_text:
                continue
            try:
                day = coerce_upcoming_year(dateparser.parse(f"{date_text} {year}")).date()
            except (ValueError, OverflowError):
                continue

            # Each date option carries its fee as a data-price attribute
            price = None
            if checkbox.get("data-price"):
                try:
                    price = float(checkbox["data-price"])
                except ValueError:
                    pass

            events.append(
                Event(
                    club=self.club_name,
                    title="Big House Open Gym",
                    start=datetime.combine(day, START_TIME),
                    end=datetime.combine(day, END_TIME),
                    location=LOCATION,
                    url=self.schedule_url,
                    price=price,
                )
            )

        return events

    def _scrape_league(self) -> list[Event]:
        soup = fetch_static(LEAGUE_SCHEDULE_URL)
        events: list[Event] = []

        table = soup.select_one("table.simple-table")
        if not table:
            return events
        rows = table.select("tr")
        if len(rows) < 4:  # 1 header row + the 3 data rows column 0 is split across
            return events

        headers = [c.get_text(" ", strip=True) for c in rows[0].select("td")]
        data_rows = rows[1:]
        col0_cells = [tr.select_one("td") for tr in data_rows]
        if any(c is None for c in col0_cells):
            return events

        play_dates = _parse_date_list(col0_cells[0])
        excluded = _parse_excluded_dates(col0_cells[1])
        match_times = _parse_scheduled_times(col0_cells[2])
        if not play_dates or not match_times:
            return events

        description = _build_description(headers, data_rows)
        team_fee = _parse_team_fee(headers, data_rows)
        first_start = min(match_times)
        last_start = max(match_times)

        for day in sorted(set(play_dates)):
            if day in excluded:
                continue
            start_dt = datetime.combine(day, first_start)
            end_dt = datetime.combine(day, last_start) + timedelta(minutes=LEAGUE_MATCH_DURATION_MIN)
            events.append(
                Event(
                    club=self.club_name,
                    title=LEAGUE_TITLE,
                    start=start_dt,
                    end=end_dt,
                    location=LOCATION,
                    url=LEAGUE_SCHEDULE_URL,
                    gym_type="League",
                    description=description or None,
                    price=team_fee,
                )
            )

        return events
