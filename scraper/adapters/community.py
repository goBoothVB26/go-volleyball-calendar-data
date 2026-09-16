"""Adapter for community-submitted events (Google Form -> Google Sheet).

People/groups submit non-website events through a Google Form whose
responses land in a private Google Sheet. A tiny Apps Script web app
bound to that sheet (see website/community_feed_apps_script.js) serves
the rows as JSON; this adapter fetches that feed. No Google Cloud
project, service account, or API key is needed -- the sheet stays
private and the feed URL is an unguessable token.

SETUP:
 1. Follow the steps at the top of website/community_feed_apps_script.js
    (paste it into the responses sheet's Apps Script, deploy as web app).
 2. Put the web app URL in COMMUNITY_FEED_URL below, or set the
    COMMUNITY_FEED_URL environment variable.

Calendar treatment: each submission's "Organization / club / league
name" IS the event's club, so every org gets its own entry in the
calendar's Club filter (and its own color, if pinned in the widget's
CLUB_COLORS map). Rows without one fall back to "Community Submitted".

Column handling: headers are matched by keyword, so the form's question
wording doesn't need to match exactly ("Event Name", "Name of event",
and "Title" all map to the title). Rows missing a title or an
unparseable date are skipped with a warning. If the sheet gains an
"Approved" column, only rows marked yes/true/approved are ingested.
The submitter-email column is never read.

Recurring events: the form's "Is this a one-time or recurring event?"
question, combined with "If recurring, which day(s)?" and "End date",
expands into one Event per matching weekday between Start date and End
date -- e.g. Start 8/30, End 11/1, weekday Sun produces a Sunday event
every week in that range, not just the single Start date row. A row
marked recurring but missing a usable end date or weekday falls back to
a single one-time event on the Start date (with a warning), same as
before this was supported.
"""

import os
import re
import sys
from datetime import date, datetime, timedelta
from typing import Optional

import requests
from dateutil import parser as dateparser

from ..models import Event
from ..tagging import infer_net_heights
from .base import ClubAdapter

# The Apps Script web app URL (ends in /exec). See module docstring.
COMMUNITY_FEED_URL = os.environ.get(
    "COMMUNITY_FEED_URL",
    "https://script.google.com/macros/s/AKfycbzCPF0KsZeIzJM-7Llg_w_sm0N2rMaetprVUodkUtLzFqHk9MH31Nz6M_bOsktVUpfM/exec",
)

# Header keywords -> event field. First header containing any keyword
# (case-insensitive) wins for that field. More specific keywords are
# listed first within each field so e.g. "end_date"'s "end date" and
# "date"'s "start date" each land on their own column rather than one
# of them accidentally swallowing the other's.
_HEADER_KEYWORDS = {
    "title": ["event name", "name of event", "event title", "title"],
    "date": ["event date", "start date", "date"],
    "end_date": ["end date"],
    "recurring": ["one-time or recurring"],
    "weekdays": ["which day"],
    "start_time": ["start time", "begins", "from"],
    "end_time": ["end time", "ends", "until", "to"],
    "location": ["location", "venue", "address", "where"],
    "description": ["description", "details", "about", "additional info", "notes"],
    "price": ["price", "cost", "fee"],
    "url": ["registration", "sign up link", "link", "url", "website"],
    "organization": ["organization", "club", "group", "host", "team name"],
    "division": ["division"],
    "approved": ["approved", "approval", "reviewed"],
}

_APPROVED_RE = re.compile(r"^\s*(yes|y|true|approved|ok|1)\s*$", re.I)
_PRICE_RE = re.compile(r"(\d+(?:\.\d{1,2})?)")
_RECURRING_RE = re.compile(r"\brecurring\b", re.I)

_WEEKDAY_ABBR_TO_INDEX = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _find_columns(headers: list[str]) -> dict[str, int]:
    """Map event fields to column indexes by keyword-matching headers."""
    lowered = [h.strip().lower() for h in headers]
    columns: dict[str, int] = {}
    for field, keywords in _HEADER_KEYWORDS.items():
        for keyword in keywords:
            hit = next((i for i, h in enumerate(lowered) if keyword in h), None)
            if hit is not None and hit not in columns.values():
                columns[field] = hit
                break
    return columns


def _parse_price(text: str) -> Optional[float]:
    if not text:
        return None
    if re.search(r"\bfree\b", text, re.I):
        return 0.0
    match = _PRICE_RE.search(text)
    return float(match.group(1)) if match else None


def _normalize_url(text: str) -> Optional[str]:
    """Submitters sometimes type a link without a scheme (e.g.
    "www.example.com/path"), which browsers treat as a relative path
    rather than an external link. Add https:// when one's missing."""
    if not text:
        return None
    if re.match(r"^https?://", text, re.I):
        return text
    return "https://" + text


def _parse_weekdays(text: str) -> set[int]:
    """Parse a free-text weekday list like "Sun" or "Mon, Wed" (the
    form's "which day(s)?" answer) into weekday indices (Mon=0..Sun=6,
    matching date.weekday()). Matches on the first 3 letters so full
    names ("Sunday") work too; unrecognized tokens are skipped."""
    days: set[int] = set()
    for token in re.split(r"[,/&]|\band\b", text, flags=re.I):
        token = token.strip().lower()[:3]
        if token in _WEEKDAY_ABBR_TO_INDEX:
            days.add(_WEEKDAY_ABBR_TO_INDEX[token])
    return days


def _weekly_dates(start: date, end: date, weekdays: set[int]) -> list[date]:
    """Every date from start to end (inclusive) that falls on one of the
    given weekdays."""
    if not weekdays or end < start:
        return []
    dates = []
    current = start
    while current <= end:
        if current.weekday() in weekdays:
            dates.append(current)
        current += timedelta(days=1)
    return dates


class CommunityEventsAdapter(ClubAdapter):
    club_name = "Community Submitted"
    category = "adult"
    schedule_url = COMMUNITY_FEED_URL

    def scrape(self) -> list[Event]:
        if not COMMUNITY_FEED_URL:
            print("[Community Submitted] COMMUNITY_FEED_URL not set -- skipping", file=sys.stderr)
            return []

        # Apps Script web apps can have slow cold starts (observed a
        # 30s read timeout in production), so this gets more headroom
        # than a typical request.
        response = requests.get(COMMUNITY_FEED_URL, timeout=60)
        response.raise_for_status()
        rows = response.json().get("values", [])
        if len(rows) < 2:
            return []  # header only (or empty sheet)

        headers, data_rows = rows[0], rows[1:]
        columns = _find_columns(headers)
        if "title" not in columns or "date" not in columns:
            raise RuntimeError(
                f"could not locate title/date columns in sheet headers: {headers}"
            )

        def cell(row: list[str], field: str) -> str:
            index = columns.get(field)
            if index is None or index >= len(row):
                return ""
            return str(row[index]).strip()

        events: list[Event] = []
        for row_number, row in enumerate(data_rows, start=2):
            title = cell(row, "title")
            date_text = cell(row, "date")
            if not title or not date_text:
                continue

            # Moderation: if the sheet has an Approved column, only rows
            # explicitly marked approved are published.
            if "approved" in columns and not _APPROVED_RE.match(cell(row, "approved")):
                continue

            try:
                start_date = dateparser.parse(date_text, fuzzy=True).date()
            except (ValueError, OverflowError):
                print(
                    f"[{self.club_name}] row {row_number}: unparseable date {date_text!r} -- skipped",
                    file=sys.stderr,
                )
                continue

            # Recurring submissions expand into one Event per matching
            # weekday between Start date and End date; anything else
            # (one-time, or recurring with missing/unusable end
            # date/weekday data) stays a single event on Start date.
            days = [start_date]
            if _RECURRING_RE.search(cell(row, "recurring")):
                end_date_text = cell(row, "end_date")
                weekdays = _parse_weekdays(cell(row, "weekdays"))
                end_date = None
                if end_date_text:
                    try:
                        end_date = dateparser.parse(end_date_text, fuzzy=True).date()
                    except (ValueError, OverflowError):
                        pass
                if end_date and weekdays:
                    expanded = _weekly_dates(start_date, end_date, weekdays)
                    if expanded:
                        days = expanded
                    else:
                        print(
                            f"[{self.club_name}] row {row_number}: recurring range produced no "
                            f"matching dates (start {start_date}, end {end_date}, weekdays "
                            f"{sorted(weekdays)}) -- using start date only",
                            file=sys.stderr,
                        )
                else:
                    print(
                        f"[{self.club_name}] row {row_number}: marked recurring but missing a "
                        f"usable end date and/or weekday(s) -- using start date only",
                        file=sys.stderr,
                    )

            start_text = cell(row, "start_time")
            end_text = cell(row, "end_time")
            organization = cell(row, "organization")
            location = cell(row, "location") or None
            description = cell(row, "description") or None
            url = _normalize_url(cell(row, "url"))
            price = _parse_price(cell(row, "price"))

            # The form's "Division(s)" answer states the men's/women's/
            # coed allocation directly, so it drives net_height. Setting
            # it here means tag_event() won't overwrite it with the
            # "Men's, Co-ed" default -- that default only applies when
            # the submitter left the field blank or unrecognizable.
            net_height = infer_net_heights(cell(row, "division")) or None

            for day in days:
                start = datetime.combine(day, datetime.min.time())
                end = None
                all_day = True
                if start_text:
                    try:
                        start = datetime.combine(day, dateparser.parse(start_text).time())
                        all_day = False
                    except (ValueError, OverflowError):
                        pass
                if end_text and not all_day:
                    try:
                        end = datetime.combine(day, dateparser.parse(end_text).time())
                        if end <= start:  # e.g. 10pm-1am spills into the next day
                            end += timedelta(days=1)
                    except (ValueError, OverflowError):
                        end = None

                events.append(
                    Event(
                        club=organization or self.club_name,
                        title=title,
                        start=start,
                        end=end,
                        all_day=all_day,
                        location=location,
                        description=description,
                        url=url,
                        price=price,
                        net_height=net_height,
                    )
                )

        return events
