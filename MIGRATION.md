# Migrating from local .bat runs to automatic GitHub runs

End state: the public data repo (`go-volleyball-calendar-data`) contains
the scraper AND its outputs, and a GitHub Action re-scrapes every
6 hours and commits the results. Nothing runs on your PC anymore.

The website widget keeps reading the exact same URL
(`https://raw.githubusercontent.com/goBoothVB26/go-volleyball-calendar-data/main/events.json`),
so no Squarespace change is needed.

## One-time migration steps

Work in your local clone of `go-volleyball-calendar-data` (the folder
`publish_events.bat` pushes from). Copy these from THIS project into it:

1. `scraper/`  (the whole folder -- delete any `__pycache__` inside)
2. `requirements.txt`
3. `.github/workflows/update-calendar.yml`
4. `.cache/`  (your local cache + archive, so event history, tags, and
   past events carry over; without it the first cloud run starts fresh
   and past events disappear)
5. Also copy your latest local `events.json` and `*_schedule.ics`
   files in, so there's no gap before the first scheduled run.

Then:

6. Push it all:
   ```
   git add -A
   git commit -m "Move scraper into data repo for scheduled runs"
   git push
   ```
7. On github.com, open the data repo -> **Settings -> Actions ->
   General -> Workflow permissions** -> select **Read and write
   permissions** -> Save. (This lets the workflow commit its results.)
8. Open the **Actions** tab -> "Update calendar data" -> **Run
   workflow** to do a first manual run and confirm it goes green and
   commits an updated `events.json`.

That's it. It now runs at ~2am/8am/2pm/8pm Orlando time daily.

## Calendar subscriptions (replacing the Google Drive links)

Every per-club `.ics` now has a stable public URL, e.g.:

```
https://raw.githubusercontent.com/goBoothVB26/go-volleyball-calendar-data/main/greater_orlando_volleyball_club_schedule.ics
```

Use these in Google Calendar's "From URL" box instead of the Drive
direct-download links -- they update automatically every run. (Existing
Drive-based subscriptions keep working only as long as you keep copying
files to Drive, which you can now stop doing; re-add each calendar From
URL once and delete the Drive copies.)

## What you can retire locally

- `generate_calendar_links.bat`, `publish_events.bat`, `drive_links.py`
  (Drive links are replaced by the raw GitHub .ics URLs above) -- these
  now live in `archive/` in this repo
- The `G:\My Drive\Calendar` output folder
- This repo remains the development home for the widget + Apps Script
  files; when the scraper changes here, copy `scraper/` into the data
  repo again (or make the data repo the only home for scraper code).

## Notes

- The community feed + notification Apps Scripts are untouched -- they
  already run in Google's cloud on their own triggers.
- Manual re-tags still work, just in the cloud: run the workflow by
  hand after editing tagging rules, or locally run
  `python -m scraper.main --purge-club <slug>` inside the data repo and
  push.
- If a scheduled run fails, GitHub emails the repo owner; the run log
  shows the same per-club output your .bat printed.
