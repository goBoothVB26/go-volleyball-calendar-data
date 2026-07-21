"""Persistent event cache, backed by a separate historical archive.

Each scraper run merges freshly-scraped events with a JSON cache so that:
  - New events are added.
  - Updated events (same UID, different fields) are overwritten with the
    fresh data.
  - Past events that disappear from the source site are retained from the
    cache, so history is never lost.
  - FUTURE events that disappear from a successfully-scraped source are
    dropped — an upcoming event the site no longer lists was almost
    certainly cancelled or rescheduled, and keeping it would show a
    phantom event on the calendar. As a safety net, if a scrape returns
    zero events (site down, selector broke) the whole cache for that club
    is kept untouched rather than treated as "everything was cancelled".

ARCHIVE: a second JSON file (events_archive.json) that mirrors every
PAST event ever seen, independent of the live cache. Every run backs up
that run's past events into the archive, and restores any past events
missing from the live cache (e.g. after `del events_cache.json` to force
a full re-scrape/re-tag) back in before merging. This means the live
cache file can be safely wiped at any time to force fresh data and
re-tagging on every club, without losing history that's no longer
reachable on the source sites — the archive is the permanent backstop.
`--purge-club` clears both the live cache AND the archive for that one
club, since it's meant as a full reset, not a routine refresh.

Both files are a JSON object keyed by club slug; each value is a list of
serialised Event dicts. Paths are anchored to the project folder (not
the current working directory) so running the script from anywhere
always finds the same cache/archive.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import Event

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = PROJECT_ROOT / ".cache" / "events_cache.json"
ARCHIVE_PATH = PROJECT_ROOT / ".cache" / "events_archive.json"
DATETIME_FMT = "%Y-%m-%dT%H:%M:%S"


def _event_to_dict(event: Event) -> dict[str, Any]:
    return {
        "club": event.club,
        "title": event.title,
        "start": event.start.strftime(DATETIME_FMT),
        "end": event.end.strftime(DATETIME_FMT) if event.end else None,
        "location": event.location,
        "description": event.description,
        "url": event.url,
        "category": event.category,
        "all_day": event.all_day,
        "stable_id": event.stable_id,
        "skill_level": event.skill_level,
        "gym_type": event.gym_type,
        "net_height": event.net_height,
        "price": event.price,
        "image": event.image,
        "uid": event.uid(),
    }


def _dict_to_event(d: dict[str, Any]) -> Event:
    return Event(
        club=d["club"],
        title=d["title"],
        start=datetime.strptime(d["start"], DATETIME_FMT),
        end=datetime.strptime(d["end"], DATETIME_FMT) if d.get("end") else None,
        location=d.get("location"),
        description=d.get("description"),
        url=d.get("url"),
        category=d.get("category"),
        all_day=d.get("all_day", False),
        stable_id=d.get("stable_id"),
        skill_level=d.get("skill_level"),
        gym_type=d.get("gym_type"),
        net_height=d.get("net_height"),
        price=d.get("price"),
        image=d.get("image"),
    )


def load_cache(path: Path = CACHE_PATH) -> dict[str, dict[str, dict]]:
    """Return {club_slug: {uid: event_dict}} from the cache file."""
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return {
        slug: {e["uid"]: e for e in events}
        for slug, events in raw.items()
    }


def save_cache(cache: dict[str, dict[str, dict]], path: Path = CACHE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {slug: list(events.values()) for slug, events in cache.items()},
            f,
            indent=2,
        )


def load_archive(path: Path = ARCHIVE_PATH) -> dict[str, dict[str, dict]]:
    """Same shape as load_cache(); a standalone historical backup that
    survives the live cache being deleted."""
    return load_cache(path)


def save_archive(archive: dict[str, dict[str, dict]], path: Path = ARCHIVE_PATH) -> None:
    save_cache(archive, path)


def restore_from_archive(
    cache: dict[str, dict[str, dict]],
    archive: dict[str, dict[str, dict]],
    now: datetime | None = None,
) -> int:
    """Backfill past events missing from the live cache (e.g. after it
    was wiped to force a full re-scrape) from the archive, in place.
    Only PAST events are restored — a future event absent from both a
    fresh scrape and the live cache is presumed cancelled, and the
    archive must never resurrect that. Returns the number restored."""
    now = now or datetime.now()
    restored = 0
    for slug, archived_events in archive.items():
        live = cache.setdefault(slug, {})
        for uid, event_dict in archived_events.items():
            if uid in live:
                continue
            started = datetime.strptime(event_dict["start"], DATETIME_FMT)
            if started <= now:
                live[uid] = event_dict
                restored += 1
    return restored


def backup_past_events(
    archive: dict[str, dict[str, dict]],
    club_slug: str,
    events: dict[str, dict],
    now: datetime | None = None,
) -> None:
    """Copy every already-past event from this run's merged cache into
    the archive, in place. Called after every merge() so the archive is
    always at least as fresh as the live cache for events that have
    already happened."""
    now = now or datetime.now()
    archived = archive.setdefault(club_slug, {})
    for uid, event_dict in events.items():
        started = datetime.strptime(event_dict["start"], DATETIME_FMT)
        if started <= now:
            archived[uid] = event_dict


def prune_before(cache: dict[str, dict[str, dict]], cutoff: datetime) -> int:
    """Drop cached events that started before `cutoff`, across all clubs.
    Returns the number of events removed. Used by the --prune-before flag
    to keep the cache and .ics files from growing forever."""
    removed = 0
    for slug, events in cache.items():
        keep = {
            uid: d
            for uid, d in events.items()
            if datetime.strptime(d["start"], DATETIME_FMT) >= cutoff
        }
        removed += len(events) - len(keep)
        cache[slug] = keep
    return removed


def merge(club_slug: str, fresh: list[Event], cache: dict[str, dict[str, dict]]) -> list[Event]:
    """Merge fresh events into the cache for one club and return the full
    merged event list. See the module docstring for the retention policy.
    """
    cached_by_uid: dict[str, dict] = cache.get(club_slug, {})

    if not fresh:
        # Scrape came back empty — could be a broken selector or a site
        # outage, so don't interpret it as "every event was cancelled".
        cache[club_slug] = cached_by_uid
        return [_dict_to_event(d) for d in cached_by_uid.values()]

    now = datetime.now()
    fresh_uids = {event.uid() for event in fresh}

    merged: dict[str, dict] = {}
    for uid, event_dict in cached_by_uid.items():
        started = datetime.strptime(event_dict["start"], DATETIME_FMT)
        if uid in fresh_uids or started <= now:
            merged[uid] = event_dict
        # else: future event no longer on the source site → cancelled; drop.

    for event in fresh:
        merged[event.uid()] = _event_to_dict(event)

    cache[club_slug] = merged
    return [_dict_to_event(d) for d in merged.values()]
