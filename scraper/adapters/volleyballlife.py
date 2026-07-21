"""Adapter for Volleyball Life (https://volleyballlife.com/events).

Same Vuetify SPA card markup as Volley Vortex (it's the same underlying
platform), so this uses `fetch_rendered` with the same `.v-card` selectors.
The schedule URL already filters to Adults / Orlando, FL / 200mi via query
params, so unlike Volley Vortex there's no need for a per-event category
split here -- everything returned is adult.
"""

import re
from datetime import datetime, timedelta

from dateutil import parser as dateparser

from ..dateparse import coerce_upcoming_year
from ..fetch import fetch_rendered
from ..models import Event
from .base import ClubAdapter


class VolleyballLifeAdapter(ClubAdapter):
    club_name = "Volleyball Life"
    category = "adult"
    schedule_url = (
        "https://volleyballlife.com/events"
        "?ageCat=adult&addr=Orlando,+FL,+USA&ll=28.5383832,-81.3789269&dist=200"
    )

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

            # Prefer a per-event link when the card carries one; fall back
            # to the listing page otherwise.
            url = self.schedule_url
            link_el = card.select_one("a[href]")
            if link_el:
                href = link_el["href"]
                if href.startswith("/"):
                    href = "https://volleyballlife.com" + href
                if href.startswith("http"):
                    url = href

            start, end = self._parse_date_range(date_el.get_text(strip=True))
            if start is None:
                continue

            image = self._card_image(card)

            # iCal all-day DTEND is exclusive, so add 1 day to include
            # the final day fully (e.g. Jul 11-12 → DTEND Jul 13).
            all_day_end = (end or start) + timedelta(days=1)

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
                )
            )

        return events

    @staticmethod
    def _card_image(card) -> str | None:
        """Host-org logo for this event's row.

        The logo lives in a `.event-logo-rotator` block (a plain
        `img.v-img__img` with an Azure-blob src) which sits in a SIBLING
        column of the row, not inside the `.v-card` itself -- so after
        checking the card, walk up a few ancestors and look for the
        rotator there. The ancestor walk is capped so a too-high parent
        (which would contain OTHER rows' logos) is never used: the
        nearest ancestor that has exactly one rotator wins.
        """
        def _src_from(root) -> str | None:
            img = root.select_one(".event-logo-rotator img[src]") if root else None
            if img is None and root is not None:
                img = root.select_one("img.v-img__img[src]")
            if img is None:
                return None
            src = img["src"]
            if src.startswith("//"):
                src = "https:" + src
            return src if src.startswith("http") else None

        found = _src_from(card)
        if found:
            return found

        ancestor = card
        for _ in range(4):
            ancestor = ancestor.parent
            if ancestor is None:
                break
            rotators = ancestor.select(".event-logo-rotator")
            if len(rotators) == 1:
                found = _src_from(ancestor)
                if found:
                    return found
            if len(rotators) > 1:
                break  # too high: this ancestor spans multiple rows

        # Last resort: an inline background-image inside the card
        bg = card.select_one('[style*="background-image"]')
        if bg:
            m = re.search(r'url\(["\']?(https?://[^"\')]+)', bg.get("style", ""))
            if m:
                return m.group(1)
        return None

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
