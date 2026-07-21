import argparse
import os
import sys

from datetime import datetime

from . import fetch
from .adapters import ALL_ADAPTERS
from .cache import (
    backup_past_events,
    load_archive,
    load_cache,
    merge,
    prune_before,
    restore_from_archive,
    save_archive,
    save_cache,
)
from .ical import write_ics
from .jsonexport import write_events_json
from .tagging import normalize_skill, tag_event


def slugify(club_name: str) -> str:
    return club_name.lower().replace(" ", "_")


def run(
    output_dir: str = ".",
    prune_cutoff: datetime | None = None,
    purge_clubs: list[str] | None = None,
) -> None:
    cache = load_cache()
    archive = load_archive()

    for slug in purge_clubs or []:
        # --purge-club is a full reset for one club: wipe it from BOTH
        # the live cache and the historical archive, so nothing about
        # it (including bad/phantom data) survives to be restored.
        dropped = cache.pop(slug, None)
        archive.pop(slug, None)
        if dropped is None:
            print(f"--purge-club: no cache entry named {slug!r}", file=sys.stderr)
        else:
            print(f"Purged {len(dropped)} cached events for {slug} (will be re-scraped fresh)")

    # Restore any past events missing from the live cache (e.g. it was
    # deleted on purpose to force a full re-scrape/re-tag) from the
    # archive backup. Only past events are ever restored -- see
    # scraper/cache.py for why future events are never resurrected.
    restored = restore_from_archive(cache, archive)
    if restored:
        print(f"Restored {restored} past event(s) from the archive backup")

    if prune_cutoff:
        removed = prune_before(cache, prune_cutoff)
        print(f"Pruned {removed} cached events starting before {prune_cutoff.date()}")

    failed: list[str] = []
    suspect: list[str] = []
    all_events = []

    try:
        for adapter_cls in ALL_ADAPTERS:
            adapter = adapter_cls()
            slug = slugify(adapter.club_name)
            try:
                fresh = adapter.scrape()
            except Exception as exc:  # one club failing shouldn't kill the run
                print(f"[{adapter.club_name}] failed: {exc}", file=sys.stderr)
                failed.append(adapter.club_name)
                continue

            # Health check: a successful scrape with 0 events, while the
            # cache has events for this club, usually means the site
            # changed its layout and the selectors silently stopped
            # matching -- flag it instead of letting the calendar go stale.
            if not fresh and cache.get(slug):
                print(
                    f"[{adapter.club_name}] WARNING: 0 fresh events but "
                    f"{len(cache[slug])} in cache -- site layout may have changed",
                    file=sys.stderr,
                )
                suspect.append(adapter.club_name)

            print(f"[{adapter.club_name}] found {len(fresh)} fresh events")
            for event in fresh:
                tag_event(event)  # fill filter tags before caching
            events = merge(slug, fresh, cache)
            for event in events:
                # Cached events may carry pre-consolidation skill labels
                event.skill_level = normalize_skill(event.skill_level)
            all_events.extend(events)
            # Back up this run's past events into the archive so they
            # survive even if the live cache is later wiped entirely.
            backup_past_events(archive, slug, cache[slug])
            output_path = os.path.join(output_dir, f"{slug}_schedule.ics")
            write_ics(events, output_path, name=adapter.club_name)
            print(f"Wrote {len(events)} events to {output_path} ({len(events) - len(fresh)} retained from cache)")
    finally:
        fetch.shutdown()
        save_cache(cache)
        save_archive(archive)

    json_path = os.path.join(output_dir, "events.json")
    write_events_json(all_events, json_path)
    print(f"Wrote {len(all_events)} combined events to {json_path}")

    print()
    if failed:
        print(f"{len(failed)} adapter(s) failed this run: {', '.join(failed)}", file=sys.stderr)
    if suspect:
        print(f"{len(suspect)} adapter(s) returned 0 events and may need updating: {', '.join(suspect)}", file=sys.stderr)
    if not failed and not suspect:
        print("All adapters succeeded.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape volleyball club schedules into one .ics file per club")
    parser.add_argument("--output-dir", default=".", help="Directory to write the per-club .ics files into")
    parser.add_argument(
        "--prune-before",
        metavar="YYYY-MM-DD",
        help="Drop cached events that started before this date (e.g. 2025-01-01)",
    )
    parser.add_argument(
        "--purge-club",
        metavar="CLUB_SLUG",
        action="append",
        help="Drop ALL cached events for this club slug before scraping (e.g. greater_orlando_volleyball_club); repeatable",
    )
    args = parser.parse_args()
    cutoff = datetime.strptime(args.prune_before, "%Y-%m-%d") if args.prune_before else None
    run(args.output_dir, prune_cutoff=cutoff, purge_clubs=args.purge_club)


if __name__ == "__main__":
    main()
