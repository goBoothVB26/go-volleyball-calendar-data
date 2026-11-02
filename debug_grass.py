"""TEMP one-off debug script: will be reverted. User reports a Monday/
Wednesday grass league from GOVC that isn't coming through. Dumps every
baseevent program title across tournaments/leagues/events/classes plus
its weekday-resolution result, so a program silently dropped by
resolve_weekdays() (empty weekday set -> _parse_baseevent_li returns
[]) is visible instead of just missing with no trace.
"""

from scraper.fetch import fetch_static
from scraper import leagueapps

BASE = "https://goadultsportsleague.leagueapps.com"

for page in ["tournaments", "leagues", "events", "classes"]:
    url = f"{BASE}/{page}?ngmp_2023_iframe_transition=1"
    print(f"=== {page} ===")
    try:
        soup = fetch_static(url)
    except Exception as exc:
        print("  FETCH FAILED:", exc)
        continue
    lis = soup.select('li[id^="baseevent-"]')
    print(f"  {len(lis)} baseevent li(s) found")
    for li in lis:
        title_el = li.select_one("h2 a")
        title = title_el.get_text(strip=True) if title_el else "(no title)"
        weekdays = leagueapps.resolve_weekdays(li, title)
        bolded = leagueapps.bolded_weekdays(li)
        gamedays_el = li.select_one(".base-gamedays")
        gamedays_text = gamedays_el.get_text(" ", strip=True) if gamedays_el else "(no .base-gamedays element)"
        flag = " <<< DROPPED (no weekday resolved)" if not weekdays else ""
        print(f"  - {title!r} | resolved_weekdays={sorted(weekdays)} | bolded={sorted(bolded)} | gamedays={gamedays_text!r}{flag}")
