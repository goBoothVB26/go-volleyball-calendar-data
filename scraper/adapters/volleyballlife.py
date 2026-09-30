"""Adapter for Volleyball Life (https://volleyballlife.com/events).

Same Vuetify SPA card markup as Volley Vortex (it's the same underlying
platform), so this uses a rendered fetch with the same `.v-card`
selectors. The schedule URL already filters to Adults / Orlando, FL /
200mi via query params, so unlike Volley Vortex there's no need for a
per-event category split here -- everything returned is adult.

Per-event URLs: confirmed by inspecting the live DOM that cards have NO
`<a href>` anywhere -- clicking one drives client-side routing with no
URL change, not a real link. The only place a per-event identifier
exists is the page's own backend call to
`https://api-v8.volleyballlife.com/tournament/summaries?...` (confirmed
via the browser's Network tab), whose JSON includes each event's `id`,
and `https://volleyballlife.com/event/{id}` was confirmed (by loading
it directly) to be the real per-event detail page.
Rather than reconstruct that API call ourselves -- which would risk
silently dropping the geo-filter query params `schedule_url` relies on
-- this drives the page directly and listens for the SAME response the
page itself triggers when loading `schedule_url`, so whatever
filtering the frontend actually applies is exactly what we see.

This is also the catch-all for events posted here by clubs that have
their OWN dedicated adapter elsewhere in this repo: rather than leave
every such event mislabeled "Volleyball Life", each card's title (then
its full text, if the title doesn't say it) is checked against every
other adapter's club_name, and a match re-attributes the event to that
club instead -- so, say, a GOVC-organized tournament posted here shows
up under the GOVC filter, not buried in a generic "Volleyball Life"
umbrella. The one exception: a club running its OWN white-label
volleyballlife.com subdomain (same platform, e.g. SSOVA, Volley Vortex)
already has its dedicated adapter scraping this exact event
independently -- relabeling would just create a literal duplicate
entry, so those are skipped here entirely instead. See
_club_registry()/_find_club() below.

Recurring weekly leagues: a card like "Sand Coed 4's Social League -
Wednesdays, Fall 2026" shows a date range that's actually the SEASON's
bounding dates (e.g. Sep 30 - Nov 19), not one continuous multi-day
event -- treating it as a single all_day block over that whole range
renders as the event covering every day in it, not just Wednesdays.
When the title names a weekday and the type line says "League" (a
tournament's multi-day span is a real single event and should stay
one), this expands into one all-day occurrence per matching weekday
instead, via the same weekly_dates() helper community.py uses for its
own recurring-event expansion. See _weekday_from_title() below.
"""

import re
from datetime import date, datetime, timedelta
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from dateutil import parser as dateparser

from .. import fetch
from ..dateparse import coerce_upcoming_year, weekly_dates
from ..models import Event
from .base import ClubAdapter

SUMMARIES_API_MARKER = "api-v8.volleyballlife.com/tournament/summaries"

_WEEKDAY_NAME_TO_INDEX = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}
_WEEKDAY_NAME_RE = re.compile(
    r"\b(" + "|".join(_WEEKDAY_NAME_TO_INDEX) + r")s?\b", re.IGNORECASE
)


class VolleyballLifeAdapter(ClubAdapter):
    club_name = "Volleyball Life"
    category = "adult"
    schedule_url = (
        "https://volleyballlife.com/events"
        "?ageCat=adult&addr=Orlando,+FL,+USA&ll=28.5383832,-81.3789269&dist=200"
    )

    def scrape(self) -> list[Event]:
        soup, event_id_by_title = self._fetch_page_and_ids()
        skip_names, relabel_names = self._club_registry()
        events: list[Event] = []

        for card in soup.select(".v-card"):
            title_el = card.select_one(".text-subtitle-2 span")
            date_el = card.select_one(".text-body-2")
            caption_els = card.select(".event-card-content .text-caption.text-medium-emphasis")
            if not title_el or not date_el or not caption_els:
                continue

            title = title_el.get_text(strip=True)
            card_text = card.get_text(" ", strip=True)

            # This event's own platform-sibling adapter (same
            # {org}.volleyballlife.com white-label site) already scrapes
            # it independently -- skip here rather than relabel, since
            # relabeling would just produce a literal duplicate entry.
            if self._find_club(title, skip_names) or self._find_club(card_text, skip_names):
                continue

            location = caption_els[0].get_text(strip=True)
            type_line = caption_els[1].get_text(strip=True) if len(caption_els) > 1 else ""

            # Title checked first, then the rest of the card's text, for
            # any OTHER known club's name -- a match means this club
            # posted its own event here, so attribute it to them instead
            # of the generic "Volleyball Life" umbrella. No match keeps
            # the default.
            club = (
                self._find_club(title, relabel_names)
                or self._find_club(card_text, relabel_names)
                or self.club_name
            )

            event_id = event_id_by_title.get(title)
            url = f"https://volleyballlife.com/event/{event_id}" if event_id else self.schedule_url

            start, end = self._parse_date_range(date_el.get_text(strip=True))
            if start is None:
                continue

            image = self._card_image(card)

            # A recurring weekly league's card shows its SEASON's
            # bounding dates, not one continuous event -- expand into
            # one all-day occurrence per matching weekday instead of a
            # single block spanning the whole range (see module
            # docstring). Gated on both a weekday actually being named
            # in the title AND the type line saying "League", so a
            # genuine multi-day tournament (no weekday in its title) is
            # never mistakenly split up.
            weekday = self._weekday_from_title(title) if end else None
            if weekday is not None and (end - start).days > 7 and "league" in type_line.lower():
                events.extend(
                    self._expand_weekly_league(
                        club, title, start.date(), end.date(), weekday,
                        location, type_line, url, image,
                    )
                )
                continue

            # iCal all-day DTEND is exclusive, so add 1 day to include
            # the final day fully (e.g. Jul 11-12 → DTEND Jul 13).
            all_day_end = (end or start) + timedelta(days=1)

            events.append(
                Event(
                    club=club,
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
    def _weekday_from_title(title: str) -> int | None:
        """The weekday named in a recurring league's title (e.g.
        "...Wednesdays, Fall 2026" -> 2), or None if it doesn't name
        one. Matches singular or plural (Mon=0..Sun=6, date.weekday())."""
        m = _WEEKDAY_NAME_RE.search(title)
        return _WEEKDAY_NAME_TO_INDEX[m.group(1).lower()] if m else None

    @staticmethod
    def _expand_weekly_league(
        club: str, title: str, start: date, end: date, weekday: int,
        location: str, type_line: str, url: str, image: str | None,
    ) -> list[Event]:
        """One all-day Event per date in [start, end] that falls on
        weekday -- see the "recurring weekly leagues" module docstring
        note for why this exists instead of one event spanning the
        whole range."""
        return [
            Event(
                club=club,
                title=title,
                start=datetime.combine(day, datetime.min.time()),
                end=datetime.combine(day, datetime.min.time()) + timedelta(days=1),
                location=location,
                description=type_line or None,
                url=url,
                all_day=True,
                image=image,
                recurring_occurrence=True,
            )
            for day in weekly_dates(start, end, {weekday})
        ]

    @staticmethod
    def _club_registry() -> tuple[list[str], list[str]]:
        """Every OTHER adapter's club_name, split into (skip_names,
        relabel_names) by whether that club runs its own white-label
        volleyballlife.com subdomain (same platform as this adapter) --
        see the module docstring for why that split matters. Built from
        ALL_ADAPTERS so a newly added club is picked up automatically,
        with no list to hand-maintain here.

        Lazy import: scraper/adapters/__init__.py imports THIS module to
        build ALL_ADAPTERS, so importing it back at this module's top
        level would be circular. Safe here since scrape() only runs
        after the whole adapters package has finished importing.
        """
        from . import ALL_ADAPTERS

        skip_names: list[str] = []
        relabel_names: list[str] = []
        for adapter_cls in ALL_ADAPTERS:
            name = adapter_cls.club_name
            if name in ("Volleyball Life", "Community Submitted"):
                continue
            host = urlparse(adapter_cls.schedule_url).hostname or ""
            if host.endswith(".volleyballlife.com"):
                skip_names.append(name)
            else:
                relabel_names.append(name)
        return skip_names, relabel_names

    @staticmethod
    def _find_club(text: str, club_names: list[str]) -> str | None:
        """First name in club_names that appears as a whole phrase in
        text (case-insensitive), or None. Boundaried so a short name
        (e.g. "AES") can't match inside an unrelated word -- using
        lookarounds rather than \\b on both ends, since \\b requires an
        actual word/non-word transition and several club names end in
        punctuation (e.g. the closing paren in "AES Adult Volleyball
        (USAV, Florida)"), where a following space is non-word on both
        sides and \\b would never match."""
        for name in club_names:
            pattern = r"(?<!\w)" + re.escape(name) + r"(?!\w)"
            if re.search(pattern, text, re.IGNORECASE):
                return name
        return None

    def _fetch_page_and_ids(self) -> tuple[BeautifulSoup, dict[str, int]]:
        """Render schedule_url, capturing the page's own call to the
        summaries API along the way so real per-event URLs can be built.

        The listener is attached before navigation so it can't miss the
        request. Matching JSON events back to rendered cards is done by
        exact title text -- the UI renders each event's `name` field
        directly as the card title, so they should always agree. If two
        upcoming events ever share an identical title, the later one in
        the API response wins; that's a rare, low-stakes edge case (the
        card would just fall back to the listing-page URL if it lost the
        title match entirely, same as before this fix)."""
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
