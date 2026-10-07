"""Combined events.json export for the website's filterable calendar.

One JSON file with every club's events plus the filter tags, sorted by
start time. The website widget fetches this file and filters client-side
on skill_level / gym_type / net_height / price, and plots lat/lng (from
scraper/geocode.py) on the map view.
"""

import json
from datetime import datetime
from typing import Any

from .models import Event

DATETIME_FMT = "%Y-%m-%dT%H:%M:%S"


def _event_to_json(event: Event, geocoded: dict) -> dict[str, Any]:
    coords = geocoded.get(event.location) if event.location else None
    return {
        "uid": event.uid(),
        "club": event.club,
        "title": event.title,
        "start": event.start.strftime(DATETIME_FMT),
        "end": event.end.strftime(DATETIME_FMT) if event.end else None,
        "all_day": event.all_day,
        "location": event.location,
        "lat": coords["lat"] if coords else None,
        "lng": coords["lng"] if coords else None,
        "description": event.description,
        "url": event.url,
        "skill_level": event.skill_level,
        "gym_type": event.gym_type,
        "net_height": event.net_height,
        "price": event.price,
        "image": event.image,
    }


def write_events_json(events: list[Event], path: str, geocoded: dict | None = None) -> None:
    geocoded = geocoded or {}
    payload = {
        "generated": datetime.now().strftime(DATETIME_FMT),
        "events": [_event_to_json(e, geocoded) for e in sorted(events, key=lambda e: e.start)],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
