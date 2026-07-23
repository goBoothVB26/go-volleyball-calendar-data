# GO Volleyball Calendar — data repo

Public home of the Orlando-area volleyball calendar: the scraper, its
outputs, and the GitHub Action that keeps them fresh. Every 6 hours the
[Update calendar data](.github/workflows/update-calendar.yml) workflow
re-scrapes every source and commits the results straight back into this
repo:

- `events.json` — every club's events combined, with filter tags
  (skill level, gym type, net height, price). The website widget reads
  this from
  `https://raw.githubusercontent.com/goBoothVB26/go-volleyball-calendar-data/main/events.json`
  and filters client-side.
- `<club>_schedule.ics` — one subscribable calendar per club, importable
  into Google/Apple/Outlook.
- `.cache/` — the persistent event cache plus a historical archive, so
  past events survive even after they disappear from the source sites.

## Sources

One adapter per source in `scraper/adapters/`:

AES Adult Volleyball (USAV, Florida) · Big House Open Gym · City of
Sanford Adult Volleyball · Community Submitted (Google Form feed) ·
Game Point Volleyball · Goldenrod Community Park · Greater Orlando
Volleyball Club · Meadow Woods Recreation Center · NAGVA · Ocoee Coed
League · Ocoee Open Gym Volleyball · Out Sports League · OVA ·
USAV Florida Region · Volleyball Life · Volley Vortex · WPVC ·
YMCA Central Florida

All adapters are live except **OVA** (`scraper/adapters/ova.py`), which
still has placeholder selectors — its schedule page hasn't been mapped
yet.

"Community Submitted" isn't a website scrape: people submit events
through a Google Form, and a small Apps Script web app
(`website/community_feed_apps_script.js`) serves the responses sheet as
JSON for the adapter to ingest. Each submission's organization name
becomes its own club in the calendar filter.

## How a run works

1. Each adapter scrapes its site (static fetch, or headless Chromium via
   Playwright for JS-rendered pages — see `scraper/fetch.py`).
2. `scraper/tagging.py` fills in filter tags (skill level, gym type,
   net height, price) from keyword rules and per-club defaults.
3. Results merge into the cache (`scraper/cache.py`): past events are
   kept forever, future events that vanish from a healthy scrape are
   treated as cancelled and dropped, and a zero-event scrape leaves the
   club's cache untouched rather than wiping it. A separate archive file
   backs up every past event ever seen, so the live cache can be deleted
   at any time to force a full re-scrape without losing history.
4. Per-club `.ics` files and the combined `events.json` are written, and
   the workflow commits whatever changed.

One club failing (or suspiciously returning 0 events when its cache has
some) is logged and flagged in the run output; it never aborts the rest.

## Running locally

```bash
pip install -r requirements.txt
python -m playwright install chromium   # for the JS-rendered sites
python -m scraper.main --output-dir .
```

Useful flags:

- `--prune-before YYYY-MM-DD` — drop cached events that started before
  a date.
- `--purge-club <slug>` (repeatable) — full reset for one club: wipes it
  from both the cache and the archive so it re-scrapes completely fresh
  (e.g. `--purge-club greater_orlando_volleyball_club`).

`debug_dump.py` fetches and dumps a single page's HTML/DOM, handy when a
site changes layout and an adapter's selectors need updating.

## Repo layout

| Path | What it is |
| --- | --- |
| `scraper/` | The scraper package: adapters, cache, tagging, iCal/JSON export |
| `.github/workflows/update-calendar.yml` | The 6-hourly scrape-and-commit workflow (also runnable manually from the Actions tab) |
| `website/` | Squarespace embed snippets: calendar widget, carousel, theme toggle, submit-event + volunteer + blog pages, Apps Scripts |
| `logos/` | Club logos referenced by the website (`logos_local_backup/` holds the originals) |
| `scripts/` | Logo prep tools (transparency, white variants) |
| `archive/` | Retired local-run tooling from before the scraper moved into this repo (see `MIGRATION.md`) |

## Adding a new source

1. Copy an existing adapter in `scraper/adapters/` and point it at the
   site's schedule page. If the schedule only appears in the rendered
   DOM (not the raw page source), use `fetch_rendered` instead of
   `fetch_static`.
2. Register it in `scraper/adapters/__init__.py` (`ALL_ADAPTERS`).
3. Optionally add per-club tag defaults or manual overrides in
   `scraper/tagging.py`.
4. Run `python -m scraper.main` and check the new
   `<club>_schedule.ics` and its entries in `events.json`.
