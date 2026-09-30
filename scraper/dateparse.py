"""Custom date-range parsing for messy club schedule text.

dateutil's fuzzy mode silently produces wrong results for ranges like
"Jan. 3-4, 2026" (misreads the second number as part of the year) and
fails outright on cross-month ranges ("Feb. 28- Mar.1, 2026") or
placeholders like "TBD". This module extracts month/day/year fields with
a regex first, then hands each individual (unambiguous) date to dateutil.
"""

import re
from datetime import date, datetime, timedelta
from typing import Optional

from dateutil import parser as dateparser

def coerce_upcoming_year(dt: datetime, today: Optional[date] = None, grace_days: int = 60) -> datetime:
    """Fix year-rollover for dates parsed with an assumed current year.

    Sites that publish dates without a year ("Jan 10") get parsed with
    `datetime.now().year`, which is wrong when scraping a January event in
    December. If the parsed date is more than `grace_days` in the past,
    assume it actually refers to next year. The grace window keeps
    recently-finished events (which the cache retains) on their true date.
    """
    today = today or datetime.now().date()
    if dt.date() < today - timedelta(days=grace_days):
        try:
            return dt.replace(year=dt.year + 1)
        except ValueError:  # Feb 29 → non-leap year
            return dt.replace(year=dt.year + 1, day=28)
    return dt


_DATE_RANGE_RE = re.compile(
    r"(?P<month1>[A-Za-z]{3,9})\.?\s*"
    r"(?P<day1>\d{1,2})\s*"
    r"(?:-\s*(?:(?P<month2>[A-Za-z]{3,9})\.?\s*)?(?P<day2>\d{1,2}))?"
    r"\s*,*\s*"
    r"(?P<year>\d{4})?",
    re.IGNORECASE,
)


def parse_event_date_range(
    text: str, fallback_year: Optional[int] = None
) -> tuple[Optional[datetime], Optional[datetime]]:
    """Parse strings like "Jan. 3-4, 2026" or "SEPT. 18 - 19, 2026".

    Returns (start, end) where end is None for single-day events. Returns
    (None, None) for unparseable or placeholder text (e.g. "TBD").
    """
    text = text.strip()
    if not text or text.upper() == "TBD":
        return None, None

    match = _DATE_RANGE_RE.search(text)
    if not match:
        return None, None

    year = match.group("year") or fallback_year
    if year is None:
        return None, None

    month1 = match.group("month1")
    day1 = match.group("day1")
    try:
        start = dateparser.parse(f"{month1} {day1} {year}")
    except (ValueError, OverflowError):
        return None, None

    day2 = match.group("day2")
    end = None
    if day2:
        month2 = match.group("month2") or month1
        try:
            end = dateparser.parse(f"{month2} {day2} {year}")
        except (ValueError, OverflowError):
            end = None

    return start, end


def weekly_dates(start: date, end: date, weekdays: set[int]) -> list[date]:
    """Every date from start to end (inclusive) that falls on one of the
    given weekdays (Mon=0..Sun=6, matching date.weekday()).

    Shared by any adapter that needs to expand a "season start - season
    end" range into its actual weekly occurrences, e.g. a recurring
    league whose site only states the series' bounding dates (not each
    individual date) -- treating that range as one continuous all-day
    event would otherwise render as covering every day in it, not just
    the day(s) it actually runs.
    """
    if not weekdays or end < start:
        return []
    dates = []
    current = start
    while current <= end:
        if current.weekday() in weekdays:
            dates.append(current)
        current += timedelta(days=1)
    return dates
