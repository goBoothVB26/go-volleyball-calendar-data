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
"""

import os
import re
import sys
from datetime import datetime, timedelta
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
# (case-insensitive) wins for that field.
_HEADER_KEYWORDS = {
    "title": ["event name", "name of event", "event title", "title"],
    "date": ["event date", "start date", "date"],
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


class CommunityEventsAdapter(ClubAdapter):
    club_name = "Community Submitted"
    category = "adult"
    schedule_url = COMMUNITY_FEED_URL

    def scrape(self) -> list[Event]:
        if not COMMUNITY_FEED_URL:
            print("[Community Submitted] COMMUNITY_FEED_URL not set -- skipping", file=sys.stderr)
            return []

        response = requests.get(COMMUNITY_FEED_URL, timeout=30)
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
                day = dateparser.parse(date_text, fuzzy=True)
            except (ValueError, OverflowError):
                print(
                    f"[{self.club_name}] row {row_number}: unparseable date {date_text!r} -- skipped",
                    file=sys.stderr,
                )
                continue

            start = day
            end = None
            all_day = True
            start_text = cell(row, "start_time")
            if start_text:
                try:
                    start = datetime.combine(day.date(), dateparser.parse(start_text).time())
                    all_day = False
                except (ValueError, OverflowError):
                    pass
            end_text = cell(row, "end_time")
            if end_text and not all_day:
                try:
                    end = datetime.combine(day.date(), dateparser.parse(end_text).time())
                    if end <= start:  # e.g. 10pm-1am spills into the next day
                        end += timedelta(days=1)
                except (ValueError, OverflowError):
                    end = None

            organization = cell(row, "organization")

            # The form's "Division(s)" answer states the men's/women's/
            # coed allocation directly, so it drives net_height. Setting
            # it here means tag_event() won't overwrite it with the
            # "Men's, Co-ed" default -- that default only applies when
            # the submitter left the field blank or unrecognizable.
            net_height = infer_net_heights(cell(row, "division")) or None

            events.append(
                Event(
                    club=organization or self.club_name,
                    title=title,
                    start=start,
                    end=end,
                    all_day=all_day,
                    location=cell(row, "location") or None,
                    description=cell(row, "description") or None,
                    url=cell(row, "url") or None,
                    price=_parse_price(cell(row, "price")),
                    net_height=net_height,
                )
            )

        return events
