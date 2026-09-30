"""Adapter for SSOVA / Sunshine State Outdoor Volleyball Association
(https://ssova.volleyballlife.com/events).

A white-label instance of the same Volleyball Life Vuetify SPA platform
as volleyballlife.py and volleyvortex.py (`{org}.volleyballlife.com`),
so this reuses the identical `.v-card` markup and per-event-ID technique
from volleyballlife.py: rather than hardcode the summaries API's query
params (which differ per organization/site), this drives the page
directly and listens for whatever request IT fires when loading
schedule_url, then matches JSON events back to rendered cards by exact
title text. See volleyballlife.py's module docstring for the full
rationale.

No ageCat/addr filter on the schedule URL (this org doesn't split by
age the way the main volleyballlife.com listing does). Confirmed from a
real scrape that this listing does mix Adult and Juniors events (e.g.
"Tournament · Juniors · Beach · 2s"), same situation as Volley Vortex,
so category is set per-card from its own type line rather than the
adapter-wide "adult" default.

Recurring weekly leagues: same platform as volleyballlife.py, same
issue -- a card's date range can be a season's bounding dates rather
than one continuous event. Reuses that module's weekday-name detection
and the shared weekly_dates() expansion helper rather than duplicating
them; see its module docstring for the full rationale.
"""

from datetime import datetime, timedelta

from bs4 import BeautifulSoup
from dateutil import parser as dateparser

from .. import fetch
from ..dateparse import coerce_upcoming_year, weekly_dates
from ..models import Event
from .base import ClubAdapter
from .volleyballlife import VolleyballLifeAdapter

SUMMARIES_API_MARKER = "api-v8.volleyballlife.com/tournament/summaries"


class SSOVAAdapter(ClubAdapter):
    club_name = "SSOVA"
    category = "adult"
    schedule_url = "https://ssova.volleyballlife.com/events"

    def scrape(self) -> list[Event]:
        soup, event_id_by_title = self._fetch_page_and_ids()
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

            event_id = event_id_by_title.get(title)
            url = f"https://ssova.volleyballlife.com/event/{event_id}" if event_id else self.schedule_url

            start, end = self._parse_date_range(date_el.get_text(strip=True))
            if start is None:
                continue

            # Same Vuetify card markup as volleyballlife.py -- reuse its
            # image-scraping logic rather than duplicate it.
            image = VolleyballLifeAdapter._card_image(card)

            all_day_end = (end or start) + timedelta(days=1)

            # Confirmed from real scraped data: this listing mixes Adult
            # and Juniors events on one page (e.g. "Tournament · Juniors
            # · Beach · 2s"), same situation as Volley Vortex -- so set
            # category per-card from its own type line rather than the
            # adapter-wide default.
            category = "youth" if "juniors" in type_line.lower() else self.category

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
                            url=url,
                            all_day=True,
                            image=image,
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
                    end=all_day_end,
                    location=location,
                    description=type_line or None,
                    url=url,
                    all_day=True,
                    image=image,
                    category=category,
                )
            )

        return events

    def _fetch_page_and_ids(self) -> tuple[BeautifulSoup, dict[str, int]]:
        """See VolleyballLifeAdapter._fetch_page_and_ids -- identical
        approach, just pointed at this org's schedule_url."""
        event_id_by_title: dict[str, int] = {}

        def on_response(response) -> None:
            if SUMMARIES_API_MARKER not in response.url:
                return
            try:
                for item in response.json():
                    name, event_id = item.get("name"), item.get("id")
                    if name and event_id:
                        event_id_by_title[name] = event_id
            except Exception:
                pass  # malformed/unexpected response shape -- fall back to listing-page URLs

        page = fetch.new_page(user_agent=fetch.USER_AGENT)
        page.on("response", on_response)
        try:
            page.goto(self.schedule_url, timeout=30000)
            # See fetch.fetch_rendered's docstring: a loading-skeleton
            # card can match this selector before real data populates it.
            page.wait_for_selector(".text-subtitle-2", timeout=30000)
            page.wait_for_timeout(3000)
            html = page.content()
        finally:
            page.close()

        return BeautifulSoup(html, "lxml"), event_id_by_title

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
