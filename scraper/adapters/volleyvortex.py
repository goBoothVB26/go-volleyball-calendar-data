"""Adapter for Volley Vortex (https://volleyvortex.volleyballlife.com/events).

A Vuetify SPA event-listing page (so this uses `fetch_rendered`). Each
event is a card whose title, date range, location name, and a
"Tournament/League · Adults/Youth · Beach/Indoor · 2s/..." type line are
all plain text -- no stable IDs, just Vuetify's generated classes. Cards
don't carry their own detail-page link (clicking opens an in-page
panel rather than navigating), so `url` just points at the events page.

Adults vs Youth varies per card, so each event's `category` is set
directly from its type line rather than relying on a fixed adapter-wide
category.

Recurring weekly leagues: same platform as volleyballlife.py, same
issue -- a card's date range can be a season's bounding dates rather
than one continuous event (e.g. "...Wednesdays, Fall 2026" showing a
~7-week span). Reuses that module's weekday-name detection and the
shared weekly_dates() expansion helper rather than duplicating them;
see its module docstring for the full rationale.
"""

from datetime import datetime, timedelta

from dateutil import parser as dateparser

from ..dateparse import coerce_upcoming_year, weekly_dates
from ..fetch import fetch_rendered
from ..models import Event
from .base import ClubAdapter
from .volleyballlife import VolleyballLifeAdapter


class VolleyVortexAdapter(ClubAdapter):
    club_name = "Volley Vortex"
    category = "adult"  # fallback; most cards set their own via type line
    schedule_url = "https://volleyvortex.volleyballlife.com/events"

    def scrape(self) -> list[Event]:
        soup = fetch_rendered(self.schedule_url, wait_selector=".text-subtitle-2")
        events: list[Event] = []

        for card in soup.select(".v-card"):
            title_el = card.select_one(".text-subtitle-2 span")
            date_el = card.select_one(".text-body-2")
            caption_els = card.select(".event-card-content .text-caption.text-medium-emphasis")
            if not title_el or not date_el or not caption_els:
                continue

            title = title_el.get_text(strip=True)
            location = caption_els[0].get_text(strip=True)
            type_line = caption_els[1].get_text(strip=True) if len(caption_els) > 1 else ""

            start, end = self._parse_date_range(date_el.get_text(strip=True))
            if start is None:
                continue

            category = "youth" if "youth" in type_line.lower() else "adult"

            # See module docstring: a recurring weekly league's card
            # shows its season's bounding dates, not one continuous
            # event, so expand into one occurrence per matching weekday
            # instead of a single event spanning the whole range.
            weekday = VolleyballLifeAdapter._weekday_from_title(title) if end else None
            if weekday is not None and (end - start).days > 7 and "league" in type_line.lower():
                for day in weekly_dates(start.date(), end.date(), {weekday}):
                    occurrence_start = datetime.combine(day, datetime.min.time())
                    events.append(
                        Event(
                            club=self.club_name,
                            title=title,
                            start=occurrence_start,
                            end=occurrence_start + timedelta(days=1),
                            location=location,
                            description=type_line or None,
                            url=self.schedule_url,
                            category=category,
                            recurring_occurrence=True,
                        )
                    )
                continue

            events.append(
                Event(
                    club=self.club_name,
                    title=title,
                    start=start,
                    end=end,
                    location=location,
                    description=type_line or None,
                    url=self.schedule_url,
                    category=category,
                )
            )

        return events

    @staticmethod
    def _parse_date_range(text: str) -> tuple[datetime | None, datetime | None]:
        parts = [p.strip() for p in text.split(" - ")]
        year = datetime.now().year
        try:
            start = coerce_upcoming_year(dateparser.parse(f"{parts[0]} {year}", fuzzy=True))
            end = coerce_upcoming_year(dateparser.parse(f"{parts[1]} {year}", fuzzy=True)) if len(parts) > 1 else start
        except (ValueError, OverflowError):
            return None, None
        return start, end
