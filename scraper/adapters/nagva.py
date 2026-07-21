"""Adapter for NAGVA Tournaments (https://www.nagva.org/tournaments).

Like Game Point Volleyball, this is a Wix site with events as repeater
items (`div[role="listitem"]`). Each card links to a detail page that
contains structured sections (Contacts, Divisions, Facilities, Registration,
Seeding Party, etc.) rendered as Wix rich-text elements.

For each event we follow the detail page link to extract:
  - Location: the facility name + address from the "Facilities" section
  - Description: all labelled sections combined into readable text

NAGVA tournaments are all-day events, so events are written with DATE-only
dtstart/dtend (no time component) in the .ics file.

Wix renders client-side, so `fetch_rendered` is required for the listing
page. Detail pages are also Wix SPA pages so they also need `fetch_rendered`.
"""

import re

from ..dateparse import parse_event_date_range
from ..fetch import fetch_rendered
from ..models import Event
from .base import ClubAdapter

SECTION_HEADINGS = [
    "Contacts", "Divisions", "Facilities", "Registration",
    "Seeding Party", "Banquet/Awards Party", "Payment Deadlines",
    "Payment Details",
]


def _extract_sections(soup) -> dict[str, str]:
    """Walk every h1 on the detail page; if its text matches a known section
    heading, collect the rich-text elements that follow it in document
    order, stopping at the next h1 (the next section).

    An earlier version climbed to an ancestor container and collected all
    rich text inside it -- but on some events every section shares one
    page-level container, which made each section's text the entire page,
    repeated once per heading. Slicing heading-to-heading in document
    order keeps each section to just its own content.
    """
    sections: dict[str, str] = {}
    for h1 in soup.select('h1[class*="wixui-rich-text"]'):
        heading = h1.get_text(strip=True)
        if heading not in SECTION_HEADINGS:
            continue
        texts: list[str] = []
        for el in h1.next_elements:
            if getattr(el, "name", None) is None:
                continue  # skip plain text nodes
            if el.name == "h1":
                break  # reached the next section heading
            if el.get("data-testid") != "richTextElement":
                continue
            # Leaf rich-text elements only, so nested wrappers don't
            # duplicate their children's text.
            if el.find(attrs={"data-testid": "richTextElement"}) is not None:
                continue
            text = el.get_text(" ", strip=True)
            if text and text != "​":
                texts.append(text)
        if texts:
            sections[heading] = " | ".join(texts)
    return sections


def _build_location(sections: dict[str, str]) -> str | None:
    return sections.get("Facilities") or None


# Matches date strings like "June 15, 2026" so they can be stripped
# before hunting for the fee amount (their day/year digits would
# otherwise be mistaken for a price).
_DATE_TEXT_RE = re.compile(r"[A-Z][a-z]+\.?\s+\d{1,2},?\s+\d{4}")


def _parse_price(sections: dict[str, str]) -> float | None:
    """Entry fee for the earliest payment deadline: the Payment Deadlines
    section lists deadline dates followed by the fee amounts in the same
    order, so after stripping the dates the first number is the
    earliest-deadline fee."""
    text = sections.get("Payment Deadlines", "")
    if not text:
        return None
    cleaned = _DATE_TEXT_RE.sub("", text)
    match = re.search(r"\$?\s*(\d{2,4}(?:\.\d{2})?)\b", cleaned)
    return float(match.group(1)) if match else None


def _build_description(sections: dict[str, str], url: str) -> str:
    parts = []
    for heading in SECTION_HEADINGS:
        if heading in sections and heading != "Facilities":
            parts.append(f"{heading}: {sections[heading]}")
    if url:
        parts.append(f"More info: {url}")
    return "\n\n".join(parts) if parts else ""


class NAGVAAdapter(ClubAdapter):
    club_name = "NAGVA"
    category = "adult"
    schedule_url = "https://www.nagva.org/tournaments"

    def scrape(self) -> list[Event]:
        soup = fetch_rendered(self.schedule_url, wait_selector='div[role="listitem"]')
        events: list[Event] = []

        for card in soup.select('div[role="listitem"]'):
            headings = [
                h.get_text(strip=True)
                for h in card.select('h1[class*="wixui-rich-text"]')
                if h.get_text(strip=True)
            ]
            if not headings:
                continue
            date_text = headings[0]

            start, end = parse_event_date_range(date_text)
            if start is None:
                continue

            title_el = card.select_one('p[class*="wixui-rich-text"] a')
            title = title_el.get_text(strip=True) if title_el else date_text

            link_el = card.select_one('a[data-testid="linkElement"]')
            url = link_el["href"] if link_el and link_el.has_attr("href") else self.schedule_url

            # Follow detail page for location, price, and rich description
            location = None
            description = ""
            price = None
            try:
                detail_soup = fetch_rendered(url, wait_selector='h1[class*="wixui-rich-text"]')
                sections = _extract_sections(detail_soup)
                location = _build_location(sections)
                description = _build_description(sections, url)
                price = _parse_price(sections)
            except Exception:
                description = f"More info: {url}"

            events.append(
                Event(
                    club=self.club_name,
                    title=title,
                    start=start,
                    end=end,
                    location=location,
                    description=description or None,
                    url=url,
                    all_day=True,
                    price=price,
                )
            )

        return events
