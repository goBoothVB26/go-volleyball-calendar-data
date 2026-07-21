# Archive

Retired files kept for reference. Nothing in this folder is part of the
live setup anymore.

| File | What it was | Why it's retired |
| --- | --- | --- |
| `generate_calendar_links.bat` | Local run: scrape to `G:\My Drive\Calendar`, then walk through creating Google Drive share links for each `.ics` | Replaced by the scheduled GitHub Action in the data repo (see `MIGRATION.md`); calendar subscriptions now use raw GitHub `.ics` URLs |
| `publish_events.bat` | Local run: copy `events.json` into the data repo clone and push | Same — the Action commits `events.json` directly |
| `drive_links.py` | Converted Drive share links into direct-download URLs for Google Calendar's "From URL" box | Drive links replaced by raw GitHub `.ics` URLs |
| `site_theme_sync.js` | Site-wide dark/light theme sync via Squarespace Code Injection | The organization's Squarespace plan doesn't include Code Injection; per-page snippets (`theme_sync_snippet.html`, `theme_toggle_widget.html`) are used instead |
