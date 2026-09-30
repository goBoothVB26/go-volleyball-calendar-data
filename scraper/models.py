from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Event:
    """A single schedule entry (match, tournament, practice, etc)."""

    club: str
    title: str
    start: datetime
    end: Optional[datetime] = None
    location: Optional[str] = None
    description: Optional[str] = None
    url: Optional[str] = None
    category: Optional[str] = None
    """Overrides the adapter's category for this one event, for sources
    that mix categories (e.g. both adult and youth divisions)."""
    all_day: bool = False
    """If True, the event is written as a DATE-only (all-day) iCal event
    instead of a DATETIME event. start/end are still datetime objects but
    only their date portion is used."""
    stable_id: Optional[str] = None
    """Explicit UID override. Set this on synthetic/placeholder events whose
    start date shifts between runs (e.g. "dated today" placeholders) so the
    cache and calendar treat every run's copy as the same single event
    instead of accumulating one copy per distinct date."""
    recurring_occurrence: bool = False
    """True for one occurrence of a weekly-expanded recurring series (see
    scraper/dateparse.py's weekly_dates()) -- one Event per matching
    weekday, synthesized from a single source listing (one card, one form
    row) that doesn't independently confirm each individual date.

    This exempts the event from cache.py's "future event missing from a
    healthy scrape -> treat as cancelled, drop" rule: that rule assumes a
    missing event means the SOURCE stopped listing it, but here a future
    occurrence can easily be absent from one run's fresh results (e.g. a
    rendered page only showing its next ~10 upcoming cards, so a
    recurring league's card simply isn't among them that particular run)
    without the series actually being cancelled. Without this flag,
    scrape flakiness silently deletes legitimate future occurrences one
    run at a time."""

    # Filter tags (see scraper/tagging.py). Adapters may set these
    # explicitly; anything left None is inferred from keywords / per-club
    # defaults by tag_event() before the event is cached.
    skill_level: Optional[str] = None
    """e.g. "B", "BB", "A", "AA", "Open", "Beginner", "All Levels"."""
    gym_type: Optional[str] = None
    """One of "Open Gym", "League", "Clinics/Training", "Tournament"."""
    net_height: Optional[str] = None
    """One of "Men's", "Women's", "Co-ed"."""
    price: Optional[float] = None
    """Entry/session fee in dollars, when the source states one."""
    image: Optional[str] = None
    """Per-event image/logo URL scraped from the source's event card
    (e.g. Volleyball Life host-org avatars). The website popup shows
    this in place of the club-level CLUB_LOGOS fallback when present."""

    def uid(self) -> str:
        if self.stable_id:
            return self.stable_id
        key = f"{self.club}-{self.title}-{self.start.isoformat()}"
        return key.replace(" ", "_")
