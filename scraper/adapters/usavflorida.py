"""Adapter for USAV Florida Region (https://floridavolleyball.org/events/).

A server-rendered WordPress/Elementor site, so `fetch_static` works for
both the listing and detail pages. The listing renders each event as a
`div.uc_post_list_box` card containing:

  - title + detail link in `.uc_post_list_title a`
  - `.ue-grid-item-meta-data` rows: the first with a date/range like
    "July 23-26, 2026" (explicit year), the second with a city ("Orlando, FL")

Each detail page has an `ul.elementor-post-info` whose `.elementor-icon-
list-text` items are (date, venue name, street address) -- the venue +
address replace the listing's city as the event location. The rest of the
page body is Elementor heading/text/icon-list widgets, which are collected
in document order into a readable description (Registration, Team Entry
Fees, Refund Policy, ...).

Events are date-ranges with no time of day, so they're written as all-day
events spanning the full duration (iCal exclusive DTEND = last day + 1).
"""

from datetime import timedelta

from ..dateparse import parse_event_date_range
from ..fetch import fetch_static
from ..models import Event
from .base import ClubAdapter

MAX_DESCRIPTION_CHARS = 3000


class USAVFloridaRegionAdapter(ClubAdapter):
    club_name = "USAV Florida Region"
    category = "adult"
    schedule_url = "https://floridavolleyball.org/events/"

    def scrape(self) -> list[Event]:
        soup = fetch_static(self.schedule_url)
        events: list[Event] = []

        for card in soup.select("div.uc_post_list_box"):
            title_el = card.select_one(".uc_post_list_title a")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            url = title_el.get("href") or self.schedule_url

            meta_texts = [
                m.get_text(strip=True) for m in card.select(".ue-grid-item-meta-data")
            ]
            if not meta_texts:
                continue
            date_text = meta_texts[0]
            city = meta_texts[1] if len(meta_texts) > 1 else None

            start, end = parse_event_date_range(date_text)
            if start is None:
                continue

            # Follow the detail page for venue + address and description;
            # fall back to the listing's city if it fails.
            location = city
            description = None
            try:
                detail = fetch_static(url)
                location = self._parse_location(detail) or city
                description = self._parse_description(detail)
            except Exception:
                pass

            # iCal all-day DTEND is exclusive: add 1 day past the last day.
            all_day_end = (end or start) + timedelta(days=1)

            events.append(
                Event(
                    club=self.club_name,
                    title=title,
                    start=start,
                    end=all_day_end,
                    location=location,
                    description=description,
                    url=url,
                    all_day=True,
                )
            )

        return events

    @staticmethod
    def _parse_location(detail) -> str | None:
        """The post-info list items are (date, venue name, street address);
        skip the first and join the rest."""
        items = [
            li.get_text(strip=True)
            for li in detail.select("ul.elementor-post-info .elementor-icon-list-text")
        ]
        if len(items) < 2:
            return None
        return ", ".join(items[1:])

    @staticmethod
    def _parse_description(detail) -> str | None:
        """Collect the page's section headings, text blocks, and bullet
        lists in document order into readable text."""
        parts: list[str] = []
        seen: set[str] = set()
        selector = (
            "h2.elementor-heading-title, "
            ".elementor-widget-text-editor .elementor-widget-container, "
            ".elementor-widget-icon-list .elementor-icon-list-text"
        )
        for el in detail.select(selector):
            text = el.get_text(" ", strip=True)
            if not text or text in seen:
                continue
            seen.add(text)
            if el.name == "h2":
                parts.append(f"\n{text.upper()}:")
            elif "elementor-icon-list-text" in (el.get("class") or []):
                parts.append(f"- {text}")
            else:
                parts.append(text)

        if not parts:
            return None
        description = "\n".join(parts).strip()
        if len(description) > MAX_DESCRIPTION_CHARS:
            description = description[:MAX_DESCRIPTION_CHARS] + "…"
        return description
