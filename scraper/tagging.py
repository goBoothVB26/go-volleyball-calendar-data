"""Filter-tag inference for events.

Fills in skill_level, gym_type, net_height, and price on scraped events
so the website calendar can offer attribute filters. Adapters may set any
of these explicitly; tag_event() only fills fields that are still None,
using keyword rules on the title/description first and falling back to
per-club defaults.

Values are deliberately small fixed vocabularies so the filter UI stays
clean:
  gym_type:    Open Gym | League | Clinics/Training | Tournament
  net_height:  Men's | Women's | Co-ed
  skill_level: AA | A | BB | B | Open | Beginner | Intermediate |
               Advanced | All Levels
Anything that can't be determined stays None ("not stated"), which the
filter UI can treat as matching every selection.

MANUAL_OVERRIDES lets you pin tags for specific events by title keyword
per club without touching adapter code -- first matching rule wins.
"""

import re
from typing import Optional

from .models import Event

# ---------------------------------------------------------------------------
# Per-club defaults (applied when keyword rules find nothing)
# ---------------------------------------------------------------------------

GYM_TYPE_BY_CLUB = {
    "Game Point Volleyball": "Tournament",
    "WPVC": "Open Gym",
    "Out Sports League": "League",
    "AES Adult Volleyball (USAV, Florida)": "Tournament",
    "Greater Orlando Volleyball Club": "League",
    "NAGVA": "Tournament",
    "Big House Open Gym": "Open Gym",
    "City of Sanford Adult Volleyball": "League",
    "Volley Vortex": "Tournament",
    "Goldenrod Community Park": "Open Gym",
    "Meadow Woods Recreation Center": "Open Gym",
    "YMCA Central Florida": "League",
    "Volleyball Life": "Tournament",
    "Ocoee Coed League": "League",
    "Ocoee Open Gym Volleyball": "Open Gym",
    "USAV Florida Region": "Tournament",
}

NET_HEIGHT_BY_CLUB = {
    "NAGVA": "Men's",  # gay men's volleyball association
    "Ocoee Coed League": "Co-ed",
    "Ocoee Open Gym Volleyball": "Co-ed",
}

PRICE_BY_CLUB: dict[str, float] = {
    # Sources that never state a fee in scraped text but have a known
    # fixed price can be pinned here, e.g. "Ocoee Open Gym Volleyball": 5.0
}

# ---------------------------------------------------------------------------
# Manual per-event overrides: (club, title keyword, field, value).
# First matching rule wins; matching is case-insensitive substring.
# ---------------------------------------------------------------------------

MANUAL_OVERRIDES: list[tuple[str, str, str, object]] = [
    # ("Greater Orlando Volleyball Club", "open gym", "skill_level", "All Levels"),
]

# ---------------------------------------------------------------------------
# Keyword rules
# ---------------------------------------------------------------------------

_GYM_TYPE_RULES = [
    ("Open Gym", re.compile(r"\bopen\s+(gym|play)\b|\bpick[\s-]?up\b", re.I)),
    ("Clinics/Training", re.compile(r"\b(clinic|class|classes|training|skills?|lesson|camp|workout)\b", re.I)),
    ("Tournament", re.compile(r"\b(tournament|championship|qualifier|challenge|series|invitational|classic|fest)\b", re.I)),
    ("League", re.compile(r"\bleagues?\b", re.I)),
]

_NET_HEIGHT_RULES = [
    ("Men's", re.compile(r"\b(men'?s?|boys?)\b", re.I)),
    ("Women's", re.compile(r"\b(women'?s?|ladies|girls?)\b", re.I)),
    ("Co-ed", re.compile(r"\b(co-?ed|coed|mixed|reverse)\b", re.I)),
]

_NET_HEIGHT_ORDER = ["Men's", "Women's", "Co-ed"]

# Events that state nothing about gender/net height get tagged as BOTH
# Men's and Co-ed (men can play, and it's assumed mixed-gender friendly
# absent any statement otherwise) -- not Women's, since that's never
# assumed without it being explicitly stated.
NET_HEIGHT_DEFAULT = "Men's, Co-ed"


def infer_gym_type(text: str) -> Optional[str]:
    """Gym type from keywords in text, or None. Used by adapters that
    know a better text source than the event title (e.g. GOVC class
    sessions titled "July 5th @ College Park" inherit their program's
    title "Open Gym - Summer Series")."""
    return _first_match(_GYM_TYPE_RULES, text)


def infer_net_heights(text: str) -> Optional[str]:
    """ALL net heights mentioned, comma-joined in canonical order --
    e.g. "Men's/Women's/Coed Tournament" → "Men's, Women's, Co-ed"."""
    found = {value for value, pattern in _NET_HEIGHT_RULES if pattern.search(text)}
    ordered = [v for v in _NET_HEIGHT_ORDER if v in found]
    return ", ".join(ordered) if ordered else None

# Consolidated skill buckets. An event keeps EVERY bucket it mentions
# (comma-joined, e.g. "Open, A/AA, B/BB" for a multi-division
# tournament); anything unstated is "Any Level".
#
# "All Levels" is reserved for genuine catch-all signals -- explicit
# phrases like "all skill levels", "new players", "novices", or a
# structured C/D division letter -- rather than a generic fallback that
# gets glued onto other detected buckets. When a catch-all phrase is
# found and NO specific division/letter signal is present, the event is
# tagged "All Levels" exclusively (see infer_skill_levels).
_SKILL_SPECIFIC_RULES = [
    ("Open", re.compile(r"\bopen\s+(division|level|a/aa)\b|\bopen\s*a/aa\b", re.I)),
    ("A/AA", re.compile(
        r"\b(advanced|competitive|elite|gold)\b|\bAA\b"
        r"|(division|div\.?|level)\s*[:\-]?\s*A\b|\bA\s+(division|league)\b|\b(men'?s|women'?s|coed|co-ed)\s+A\b", re.I)),
    ("B/BB", re.compile(
        r"\b(intermediate|silver)\b|\bBB\b"
        r"|(division|div\.?|level)\s*[:\-]?\s*B\b|\bB\s+(division|league)\b|\b(men'?s|women'?s|coed|co-ed)\s+B\b", re.I)),
    # Bronze is a real named division like Gold/Silver, so it's treated
    # as a specific combinable signal (not the exclusive catch-all rule
    # below) -- "Gold & Bronze Divisions" tags A/AA + All Levels together.
    ("All Levels", re.compile(r"\bbronze\b", re.I)),
]

# A structured division letter (C or D) is a real explicit signal, not
# marketing copy, so it's detected separately from the catch-all phrases
# below and still combines with other specific buckets found.
_DIVISION_CD_RE = re.compile(r"(division|div\.?|level)\s*[:\-]?\s*[CD]\b|\b[CD]\s+(division|league)\b", re.I)

# Catch-all phrasing: "all skill levels", "new players", "novices", etc.
# When one of these is found and no specific division/letter signal is
# present elsewhere in the text, the event is tagged "All Levels" ONLY --
# it does not get combined with any other bucket.
_SKILL_CATCHALL_RE = re.compile(
    r"\b(recreational?|casual)\b|\brec\s+league\b"
    r"|\ball\s+(skill\s+)?levels?\b|\ball\s+skills\b"
    r"|\bany\s+(skill\s+)?levels?\b|\bany\s+skills?\b"
    r"|\bnew\s+players?\b|\bnovices?\b|\bbeginners?\b|\bintro(ductory)?\b"
    r"|\bno\s+experience\s+(necessary|required|needed)\b"
    r"|\bopen\s+to\s+all\b",
    re.I,
)

# "All Levels" doubles as the default for events that state nothing
# about skill.
SKILL_DEFAULT = "All Levels"
_SKILL_ORDER = ["Open", "A/AA", "B/BB", "New Players", "All Levels"]

# Slash-joined division letter groups like "(A/B)" or "A/B/C/D" tag every
# letter's bucket. ("A/AA" is not matched by this -- AA has its own rule.)
_LETTER_GROUP_RE = re.compile(r"\b([A-D](?:\s*/\s*[A-D])+)\b")
_LETTER_BUCKET = {"A": "A/AA", "B": "B/BB", "C": "All Levels", "D": "All Levels"}

# Legacy labels from earlier runs (still present in cached events) mapped
# into the consolidated buckets.
_SKILL_CONSOLIDATION = {
    "Open": "Open",
    "AA": "A/AA", "A": "A/AA", "Advanced": "A/AA",
    "BB": "B/BB", "B": "B/BB", "Intermediate": "B/BB",
    "C": "All Levels", "D": "All Levels",
    "Recreational": "All Levels", "Recreation": "All Levels",
    "Beginner": "All Levels", "New Players": "All Levels", "Novice": "All Levels",
    "Any Level": "All Levels",
}


def infer_skill_levels(text: str) -> Optional[str]:
    """ALL skill buckets mentioned, comma-joined in canonical order.

    Specific/structured signals (Open, A/AA, B/BB, explicit division
    letters) take priority and combine as before. Catch-all phrasing
    ("all skill levels", "new players", "novices", ...) is ONLY applied
    when no specific signal is present, and produces "All Levels"
    exclusively -- it never mixes with other buckets.
    """
    found = {value for value, pattern in _SKILL_SPECIFIC_RULES if pattern.search(text)}
    for group in _LETTER_GROUP_RE.findall(text):
        for letter in re.split(r"\s*/\s*", group):
            found.add(_LETTER_BUCKET[letter.upper()])
    if _DIVISION_CD_RE.search(text):
        found.add("All Levels")

    if found:
        ordered = [v for v in _SKILL_ORDER if v in found]
        return ", ".join(ordered)

    if _SKILL_CATCHALL_RE.search(text):
        return "All Levels"

    return None


def normalize_skill(value: Optional[str]) -> str:
    """Map legacy single labels (and lists) into the consolidated
    buckets, deduped in canonical order."""
    if not value:
        return SKILL_DEFAULT
    mapped = [_SKILL_CONSOLIDATION.get(v.strip(), v.strip()) for v in value.split(",") if v.strip()]
    ordered = [v for v in _SKILL_ORDER if v in mapped]
    ordered += [v for v in mapped if v not in ordered]
    return ", ".join(dict.fromkeys(ordered)) if ordered else SKILL_DEFAULT

_PRICE_RE = re.compile(r"\$\s*(\d{1,4}(?:\.\d{2})?)")


def _event_text(event: Event) -> str:
    return " ".join(part for part in (event.title, event.description) if part)


def _first_match(rules, text: str) -> Optional[str]:
    for value, pattern in rules:
        if pattern.search(text):
            return value
    return None


def infer_price(text: str) -> Optional[float]:
    """Lowest dollar amount mentioned, as the 'starting at' price."""
    amounts = [float(m) for m in _PRICE_RE.findall(text)]
    return min(amounts) if amounts else None


def tag_event(event: Event) -> Event:
    """Fill any missing filter tags in place; returns the same event."""
    text = _event_text(event)

    for club, keyword, field, value in MANUAL_OVERRIDES:
        if event.club == club and keyword.lower() in event.title.lower():
            if getattr(event, field) is None:
                setattr(event, field, value)

    if event.gym_type is None:
        event.gym_type = _first_match(_GYM_TYPE_RULES, text) or GYM_TYPE_BY_CLUB.get(event.club)
    if event.net_height is None:
        event.net_height = (
            infer_net_heights(text)
            or NET_HEIGHT_BY_CLUB.get(event.club)
            or NET_HEIGHT_DEFAULT
        )
    if event.skill_level is None:
        event.skill_level = infer_skill_levels(text) or SKILL_DEFAULT
    else:
        event.skill_level = normalize_skill(event.skill_level)
    if event.price is None:
        event.price = infer_price(text)
        if event.price is None:
            event.price = PRICE_BY_CLUB.get(event.club)

    return event
