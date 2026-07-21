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
