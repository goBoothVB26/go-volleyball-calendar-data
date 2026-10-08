"""Geocoding for event locations, used to power the calendar's map view.

Turns a location's free-text venue name/address (e.g. "Dommerich Park")
into latitude/longitude via OpenStreetMap's Nominatim search API
(https://nominatim.org/release-docs/latest/api/Search/) -- free, no API
key or signup required.

Results are cached forever in .cache/geocode_cache.json, keyed by the
exact location string, so a run only geocodes location strings it
hasn't seen before (most runs geocode zero new locations, since the
same handful of venues repeat every week). This keeps calls to
Nominatim's public server rare and respects their usage policy
(https://operations.osmfoundation.org/policies/nominatim/): max 1
request/second and a descriptive User-Agent, both handled below. A
location Nominatim can't resolve is cached as None so it isn't
retried every run either.
"""

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = PROJECT_ROOT / ".cache" / "geocode_cache.json"

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "go-volleyball-calendar-data/1.0 (https://github.com/goBoothVB26/go-volleyball-calendar-data)"
REQUEST_DELAY_SECONDS = 1.1  # Nominatim usage policy: max 1 request/sec

# Biases results toward Central Florida -- every location here is a bare
# venue name or partial address with no city/state, so without this,
# "Dommerich Park" could resolve anywhere in the world that shares the name.
VIEWBOX = "-81.9,29.0,-80.8,28.0"  # lon/lat pairs roughly bounding Orlando metro


def load_cache() -> dict:
    if not CACHE_PATH.exists():
        return {}
    with open(CACHE_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, sort_keys=True)


def _geocode_one(location: str) -> dict | None:
    params = {
        "q": location,
        "format": "jsonv2",
        "limit": 1,
        "viewbox": VIEWBOX,
        "bounded": 0,  # bias toward the viewbox, don't hard-exclude outside it
    }
    url = NOMINATIM_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            results = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    if not results:
        return None
    return {"lat": float(results[0]["lat"]), "lng": float(results[0]["lon"])}


def geocode_locations(locations: set) -> dict:
    """Geocode every location not already cached, persist the cache, and
    return {location: {"lat":.., "lng":..} or None} for every location
    passed in (cached hits and newly geocoded ones alike)."""
    cache = load_cache()
    to_fetch = sorted(loc for loc in locations if loc and loc not in cache)
    for i, location in enumerate(to_fetch):
        if i > 0:
            time.sleep(REQUEST_DELAY_SECONDS)
        cache[location] = _geocode_one(location)
    if to_fetch:
        save_cache(cache)
        failed = sum(1 for loc in to_fetch if cache[loc] is None)
        print(f"Geocoded {len(to_fetch)} new location(s), {failed} failed")
    return {loc: cache.get(loc) for loc in locations if loc}
