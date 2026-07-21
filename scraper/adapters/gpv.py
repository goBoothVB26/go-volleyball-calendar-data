"""Adapter for Game Point Volleyball (https://www.gamepointevents.com/).

The schedule page is a Wix site, with events grouped into month tabs.
Each event is a repeater item (`div[role="listitem"]`) containing:

- an `h2` (Wix "rich text") whose first line is the date (often colored
  green) and second line, after a `<br>`, is the event title.
- a following rich-text block with two `<p>` lines: age group and
  location.
- a "LEARN MORE" link (`a[data-testid="linkElement"]`) when the event
  has a real page; some upcoming events only have a disabled
  `div[role="button"]` placeholder with no link.

Wix renders this client-side, so `fetch_static` may return an empty
shell with no `listitem` elements — if so, switch to `fetch_rendered`.
"""

from datetime import datetime

from ..dateparse import parse_event_date_range
from ..fetch import fetch_rendered
from ..models import Event
from .base import ClubAdapter


class GamePointVolleyballAdapter(ClubAdapter):
    club_name = "Game Point Volleyball"
    category = "youth"
    schedule_url = "https://www.gamepointevents.com/copy-of-tournament-calendar-2026"

    def scrape(self) -> list[Event]:
        soup = fetch_rendered(self.schedule_url, wait_selector='div[role="listitem"]')
        events: list[Event] = []

        fallback_year = self._find_fallback_year(soup)

        for card in soup.select('div[role="listitem"]'):
            date_title_el = card.select_one('h2[class*="wixui-rich-text"]')
            if not date_title_el:
                continue

            lines = [line.strip() for line in date_title_el.get_text("\n").split("\n") if line.strip()]
            if not lines:
                continue
            date_text, title = lines[0], " ".join(lines[1:]) or lines[0]

            start, end = parse_event_date_range(date_text, fallback_year=fallback_year)
            if start is None:
                continue

            detail_paragraphs = [
                p.get_text(strip=True)
                for p in card.select('div[class*="wixui-rich-text"] p')
                if p.get_text(strip=True)
            ]
            age_group = detail_paragraphs[0] if detail_paragraphs else None
            location = detail_paragraphs[1] if len(detail_paragraphs) > 1 else None

            link_el = card.select_one('a[data-testid="linkElement"]')
            url = link_el["href"] if link_el and link_el.has_attr("href") else self.schedule_url

            events.append(
                Event(
                    club=self.club_name,
                    title=title,
                    start=start,
                    end=end,
                    location=location,
                    description=age_group,
                    url=url,
                )
            )

        return events

    @staticmethod
    def _find_fallback_year(soup) -> int | None:
        """Look for a 4-digit year in tab labels, used when an event's own
        date text omits the year (e.g. "OCT. 25- 26")."""
        for tab in soup.select('[role="tab"], [class*="tab"]'):
            text = tab.get_text(strip=True)
            for token in text.split():
                if token.isdigit() and len(token) == 4:
                    return int(token)
        return datetime.now().year
