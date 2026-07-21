# Volleyball Schedule Scraper

Scrapes schedule data from multiple volleyball club websites and merges it
into a single `.ics` calendar file you can import into Google/Apple/Outlook
calendars.

## Status

This environment has no outbound network access, so the real HTML structure
of these sites hasn't been inspected yet:

- Game Point Volleyball — https://gamepointvolleyball.com/
- WPVC — https://www.wpvc.org/
- OVA / LVA Orlando — https://www.lvaorlando.com/
- Out Sports League — https://www.outsportsleague.com/

The plumbing (fetching, parsing pipeline, iCal export, CLI) is fully built
and tested. Each adapter in `scraper/adapters/` has placeholder CSS
selectors marked `TODO` — they need to be replaced with the real ones from
each site before scraping will return actual events.

## Finishing the adapters

For each site in `scraper/adapters/`:

1. Open the site's schedule page in a browser, view source / inspect
   element, and find the HTML structure around each schedule entry
   (tournament, match, practice, etc).
2. Update the `schedule_url` to point at the actual schedule page if it's
   not the homepage.
3. Replace the `soup.select(...)` calls with the real selectors for the
   row, title, date, and location.
4. If the schedule is rendered client-side via JavaScript (check by viewing
   page source vs. the rendered DOM — if the raw HTML has no schedule data,
   it's JS-rendered), swap `fetch_static` for `fetch_rendered` from
   `scraper/fetch.py`, which uses headless Chromium via Playwright. You'll
   also need to run `playwright install chromium` once.

## Usage

```bash
pip install -r requirements.txt
playwright install chromium  # only needed if any adapter uses fetch_rendered
python -m scraper.main
```

This prints a per-club event count and writes one calendar per club, named
`<club>_schedule.ics` (e.g. `wpvc_schedule.ics`, `out_sports_league_schedule.ics`).
Pass `--output-dir` to write them somewhere other than the current directory.
Any club whose scrape fails is skipped (logging the error) rather than
aborting the whole run.
