"""Shared parsing helpers for LeagueApps-hosted program listings.

Several club sites (Out Sports League, Greater Orlando Volleyball Club)
are hosted on LeagueApps and share the same `<li id="baseevent-...">`
markup: a `dl.basic` of label/value pairs (Season, Starts, Ends,
Location, ...) plus a `.base-schedule` widget with bolded/struck-through
weekday abbreviations (in fixed Mon..Sun order) and a time range.

The weekday widget isn't fully consistent across deployments -- on one
site it bolded every weekday the *venue* runs leagues on (not just this
program's actual day), while on another it bolds only the program's own
day(s). To handle both: if the title names a specific weekday (e.g.
"Wednesdays - ...") and that weekday is among the bolded ones, trust the
title; otherwise trust the full bolded set.

Dates are written like "Jul 8 ’26" (curly apostrophe + 2-digit year,
joined by &nbsp;), which dateutil can't parse until the apostrophe is
stripped.
"""

import re
from datetime import date, datetime, time, timedelta
from typing import Optional

from dateutil import parser as dateparser

WEEKDAY_ABBRS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

# Cleanup passes for flattened rich-text descriptions (see
# flatten_rich_text): collapse runs of blank lines/spaces left by empty
# <p></p> tags, and drop the stray space that appears before punctuation
# when a bold/italic tag ends right at a period.
_BLANK_LINES_RE = re.compile(r"\n{3,}")
_EXTRA_SPACE_RE = re.compile(r"[ \t]+")
_SPACE_BEFORE_NEWLINE_RE = re.compile(r" *\n *")
_SPACE_BEFORE_PUNCT_RE = re.compile(r" +([.,;:!?])")

# Program-metadata lines to scrub out of extracted descriptions (see
# strip_program_metadata): the details sidebar repeats the Season /
# Starts / Ends / Registration Dates / Location fields, the weekday
# strip, and the time slot -- all of which the calendar card already
# shows as structured event fields.
_METADATA_LABEL_RE = re.compile(
    r"^(season|starts|ends|registration dates|location)\s*:\s*(\S.*)?$",
    re.IGNORECASE,
)
_MEMBERSHIP_LINE_RE = re.compile(r"^requires\b.*\bmembership\b.{0,20}$", re.IGNORECASE)
_WEEKDAY_ROW_RE = re.compile(
    r"^(mon|tue|wed|thu|fri|sat|sun)((\s|/|,)+(mon|tue|wed|thu|fri|sat|sun))+$",
    re.IGNORECASE,
)
_TIME_RANGE_LINE_RE = re.compile(
    r"^\d{1,2}(:\d{2})?\s*(am|pm)\s+to\s+\d{1,2}(:\d{2})?\s*(am|pm)$",
    re.IGNORECASE,
)


def strip_program_metadata(text: Optional[str]) -> Optional[str]:
    """Remove program-details sidebar noise from a flattened description.

    When a program has no real prose write-up, the largest text block on
    its detail page is the details sidebar itself, so the extracted
    "description" is a raw dump of Season:/Starts:/Ends:/Registration
    Dates:/Location: label-value pairs, the Mon..Sun weekday strip, the
    time slot, and a "Requires ... Membership" note. All of that already
    appears on the calendar card as structured fields (start, end,
    location, ...), so those lines are dropped here. Anything else --
    genuine prose, and the fees section ("Individual Fees" / "Free") --
    is kept. A label line's value may sit on the same line after the
    colon or on the following (possibly blank-separated) line; both
    forms are consumed.
    """
    if not text:
        return None
    kept: list[str] = []
    skip_value = False  # a bare label line was seen; its value line is next
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            if not skip_value:
                kept.append(line)
            continue
        if skip_value:
            skip_value = False
            continue
        label_match = _METADATA_LABEL_RE.match(stripped)
        if label_match:
            skip_value = label_match.group(2) is None  # bare label: value follows
            continue
        if (
            _MEMBERSHIP_LINE_RE.match(stripped)
            or _WEEKDAY_ROW_RE.match(stripped)
            or _TIME_RANGE_LINE_RE.match(stripped)
        ):
            continue
        kept.append(line)
    result = _BLANK_LINES_RE.sub("\n\n", "\n".join(kept)).strip()
    return result or None


def flatten_rich_text(el) -> Optional[str]:
    """Flatten a rich-text HTML element into readable plain text: <br>
    and <p>/<li> boundaries become real line breaks, while inline
    bold/italic tag boundaries do NOT fragment sentences. Mutates `el`
    (replaces its <br> tags), so pass a throwaway parse tree."""
    for br in el.find_all("br"):
        br.replace_with("\n")
    for p in el.find_all("p"):
        p.insert_after("\n\n")
    for li in el.find_all("li"):
        li.insert_before("- ")
        li.insert_after("\n")

    text = el.get_text(" ", strip=False)
    text = _EXTRA_SPACE_RE.sub(" ", text)
    text = _SPACE_BEFORE_NEWLINE_RE.sub("\n", text)
    text = _BLANK_LINES_RE.sub("\n\n", text)
    text = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)
    text = text.strip()
    return text or None


def extract_rich_description(soup) -> Optional[str]:
    """Full program description from a LeagueApps program detail page.

    Two markups exist across LeagueApps deployments/pages:
      - the server-rendered "monolith" pages put it in a `div.mod`
        (a generic module class also used by fee/date sidebar widgets,
        so the LARGEST .mod by text wins -- the real write-up is always
        far longer than the sidebar widgets), and
      - the React pages put it in a styled-components container whose
        class starts with "StyledHTML__StylesContainer" (the prefix is
        stable across builds; the hash suffix is not).
    Returns None if nothing substantial is found, so callers can fall
    back to the terse season label.
    """
    candidates = soup.select("div.mod") + soup.select('div[class*="StyledHTML__StylesContainer"]')
    # The registration-options widget ("Select an Option ... Free Agent
    # $0.00 +$0.00 processing fee ...") is also a div.mod, and on pages
    # with a short real write-up it can be the LARGEST one -- so anything
    # that reads like the registration widget is excluded outright
    # rather than competing on size.
    _REG_MARKERS = ("processing fee", "select an option", "registration option")
    candidates = [
        el for el in candidates
        if not any(m in el.get_text(" ", strip=True).lower() for m in _REG_MARKERS)
    ]
    if not candidates:
        return None
    best = max(candidates, key=lambda el: len(el.get_text(strip=True)))
    if len(best.get_text(strip=True)) < 200:
        return None
    return strip_program_metadata(flatten_rich_text(best))


def parse_details(li) -> dict[str, str]:
    details = {}
    for dt in li.select("dl.basic dt"):
        label = dt.get_text(strip=True).rstrip(":").lower()
        dd = dt.find_next_sibling("dd")
        if dd:
            details[label.replace(" ", "_")] = dd.get_text(" ", strip=True)
    return details


def parse_date(text: Optional[str]) -> Optional[datetime]:
    if not text:
        return None
    cleaned = text.replace("’", "").replace("'", "")
    try:
        return dateparser.parse(cleaned)
    except (ValueError, OverflowError):
        return None


def parse_time_range(li) -> tuple[Optional[time], Optional[time]]:
    em = li.select_one(".base-schedule em")
    if not em:
        return None, None
    text = em.get_text(strip=True)
    parts = [p.strip() for p in text.split(" to ")]
    try:
        start_time = dateparser.parse(parts[0]).time()
        end_time = dateparser.parse(parts[1]).time() if len(parts) > 1 else None
    except (ValueError, OverflowError):
        return None, None
    return start_time, end_time


def parse_fee(li) -> Optional[float]:
    """Individual fee from the .base-fees block, e.g.
    '<span class="individual-price">$70.00</span>' → 70.0.
    Free programs render the literal text "Free" → 0.0."""
    price_el = li.select_one(".base-fees .individual-price")
    if not price_el:
        return None
    text = price_el.get_text(strip=True)
    if text.lower() == "free":
        return 0.0
    text = text.replace("$", "").replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def weekday_from_title(title: str) -> Optional[int]:
    first_word = title.split(" - ")[0].strip().lower()
    for index, abbr in enumerate(WEEKDAY_ABBRS):
        if first_word.startswith(abbr):
            return index
    return None


def bolded_weekdays(li) -> set[int]:
    gamedays = li.select_one(".base-gamedays")
    if not gamedays:
        return set()
    tags = gamedays.find_all(["del", "strong"])
    return {index for index, tag in enumerate(tags) if tag.name == "strong"}


def resolve_weekdays(li, title: str) -> set[int]:
    bolded = bolded_weekdays(li)
    title_weekday = weekday_from_title(title)
    if title_weekday is not None and title_weekday in bolded:
        return {title_weekday}
    if bolded:
        return bolded
    if title_weekday is not None:
        return {title_weekday}
    return set()


def weekly_dates(start: date, end: date, weekdays: set[int]) -> list[date]:
    if not weekdays:
        return []
    dates = []
    current = start
    while current <= end:
        if current.weekday() in weekdays:
            dates.append(current)
        current += timedelta(days=1)
    return dates
