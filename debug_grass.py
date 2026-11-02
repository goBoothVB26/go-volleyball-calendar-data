"""TEMP one-off debug script: will be reverted. Narrowing down exactly
where GOVC's "Grass Pick Up" program (weekdays resolve fine to Mon/Wed)
gets dropped before it reaches _parse_baseevent_li's output.
"""

from scraper.fetch import fetch_static
from scraper import leagueapps
from scraper.adapters.govc import GreaterOrlandoVolleyballClubAdapter

BASE = "https://goadultsportsleague.leagueapps.com"

soup = fetch_static(f"{BASE}/events?ngmp_2023_iframe_transition=1")
for li in soup.select('li[id^="baseevent-"]'):
    title_el = li.select_one("h2 a")
    title = title_el.get_text(strip=True) if title_el else "(no title)"
    if "grass" not in title.lower():
        continue

    print(f"=== {title!r} ===")
    details = leagueapps.parse_details(li)
    print("  raw parse_details():", details)

    start_date = leagueapps.parse_date(details.get("starts"))
    end_date = leagueapps.parse_date(details.get("ends"))
    print(f"  start_date={start_date!r} end_date={end_date!r}")

    weekdays = leagueapps.resolve_weekdays(li, title)
    print(f"  weekdays={sorted(weekdays)}")

    start_time, end_time = leagueapps.parse_time_range(li)
    print(f"  start_time={start_time!r} end_time={end_time!r}")

    location_el = li.select_one("dd.program-list-location a")
    print(f"  location_el={location_el!r}")

    url = title_el["href"] if title_el else None
    print(f"  url={url!r}")

    adapter = GreaterOrlandoVolleyballClubAdapter()
    result = adapter._parse_baseevent_li(li, fetch_prose=True)
    print(f"  _parse_baseevent_li() returned {len(result)} event(s)")
    for ev in result[:3]:
        print("    ", ev.start, ev.end, ev.title)

    print()
    print("  --- raw li HTML (first 3000 chars) ---")
    print(li.prettify()[:3000])
