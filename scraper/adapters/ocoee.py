"""Adapters for City of Ocoee Parks & Recreation volleyball programs
(https://www.ocoee.org/171/Adult-Programs).

The page is a plain server-rendered CivicPlus page -- no JS rendering
needed, so this uses `fetch_static`. Each program is its own `<h3
class="subhead2">` heading followed by a `<p>` description; we match the
heading by its exact text to tell the programs apart.
"""

import re
from datetime import datetime, time, timedelta

from ..fetch import fetch_rendered, fetch_static
from ..models import Event
from .base import ClubAdapter

SCHEDULE_URL = "https://www.ocoee.org/171/Adult-Programs"
VENUE = "Jim Beech Recreation Center"


def _find_paragraph(soup, heading_text: str):
    for tag in soup.select("h3.subhead2"):
        if tag.get_text(strip=True).lower() == heading_text.lower():
            return tag.find_next("p")
    return None


class OcoeeCoedLeagueAdapter(ClubAdapter):
    """As of writing, this program explicitly says "Upcoming league season
    dates to be announced" -- there's no real season start/end date to
    build actual calendar entries from yet. Rather than skip this adapter
    entirely, we emit one placeholder event (dated today) carrying all the
    known recurring details plus the waiver link, contact email, and phone
    number in its description, so it's visible on the calendar as a
    reminder until the site posts real dates.
    """

    club_name = "Ocoee Coed League"
    category = "adult"
    schedule_url = SCHEDULE_URL

    WAIVER_URL = "https://ocoee-recreation-parks-and-rec.app.transform.civicplus.com/forms/35724"
    CONTACT_EMAIL = "agonzalez@ocoee.org"
    CONTACT_PHONE = "407-905-3180"

    def scrape(self) -> list[Event]:
        soup = fetch_static(self.schedule_url)
        paragraph = _find_paragraph(soup, "Co-Ed Volleyball League")
        if paragraph is None:
            return []

        details = paragraph.get_text(" ", strip=True)
        description_parts = [
            details,
            f"Volleyball Participation Waiver: {self.WAIVER_URL}",
            f"Email contact: {self.CONTACT_EMAIL}",
            f"Call Parks and Recreation Leisure Services: {self.CONTACT_PHONE}",
        ]

        placeholder_start = datetime.combine(datetime.now().date(), time(18, 30))

        return [
            Event(
                club=self.club_name,
                title="Co-Ed Volleyball League (season dates TBD)",
                start=placeholder_start,
                end=None,
                location=VENUE,
                description="\n\n".join(part for part in description_parts if part),
                url=self.schedule_url,
                # The start date shifts to "today" on every run; without a
                # stable UID the cache would accumulate one copy per day.
                stable_id="ocoee_coed_league-season-tbd-placeholder",
            )
        ]


class OcoeeOpenGymAdapter(ClubAdapter):
    """Open Gym Volleyball runs every Tuesday night on an ongoing basis (no
    season start/end, unlike the league), so this generates one event per
    upcoming Tuesday over a rolling lookahead window instead of a single
    placeholder.
    """

    club_name = "Ocoee Open Gym Volleyball"
    category = "adult"
    schedule_url = SCHEDULE_URL

    REGISTRATION_URL = (
        "https://secure.rec1.com/FL/ocoee-parks-recreation-fl/catalog/index/"
        "0679b20b7684e99b55b7c87a01b6acfc?filter=c2VhcmNoPSZjYXRlZ29yeSU1QjMyNDg3JTVEPTE="
    )
    LOOKAHEAD_DAYS = 90
    TUESDAY = 1
    START_TIME = time(20, 15)
    END_TIME = time(22, 30)

    def scrape(self) -> list[Event]:
        soup = fetch_static(self.schedule_url)
        paragraph = _find_paragraph(soup, "Open Gym Volleyball")
        if paragraph is None:
            return []

        details = paragraph.get_text(" ", strip=True)
        single_price, annual_price = self._fetch_pass_prices()

        description_parts = [details]
        if annual_price is not None:
            description_parts.append(
                f"Annual court pass available for ${annual_price:g}."
            )
        description_parts.append(f"Register: {self.REGISTRATION_URL}")
        description = "\n\n".join(description_parts)

        events: list[Event] = []
        today = datetime.now().date()
        for offset in range(self.LOOKAHEAD_DAYS):
            day = today + timedelta(days=offset)
            if day.weekday() != self.TUESDAY:
                continue
            events.append(
                Event(
                    club=self.club_name,
                    title="Open Gym Volleyball",
                    start=datetime.combine(day, self.START_TIME),
                    end=datetime.combine(day, self.END_TIME),
                    location=VENUE,
                    description=description,
                    url=self.schedule_url,
                    price=single_price,
                )
            )

        return events

    def _fetch_pass_prices(self):
        """(single_day_price, annual_price) from the rec1 registration
        catalog's item rows. The single-day pass is the per-event price;
        the annual court pass is mentioned in the description. Any
        failure returns (None, None) rather than breaking the adapter."""
        try:
            catalog = fetch_rendered(self.REGISTRATION_URL, wait_selector=".rec1-catalog-item")
        except Exception:
            return None, None

        single = annual = None
        for item in catalog.select(".rec1-catalog-item"):
            name_el = item.select_one(".rec1-catalog-item-name a")
            price_el = item.select_one(".rec1-catalog-item-price .item-price")
            if not name_el or not price_el:
                continue
            name = name_el.get_text(strip=True).lower()
            match = re.search(r"\$\s*([\d,]+(?:\.\d{2})?)", price_el.get_text())
            if not match:
                continue
            amount = float(match.group(1).replace(",", ""))
            if "single day" in name:
                single = amount
            elif "annual" in name:
                annual = amount
        return single, annual
