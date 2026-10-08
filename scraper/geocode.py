"""Geocoding for event locations, used to power the calendar's map view.

Turns a location's free-text venue name/address (e.g. "Dommerich Park")
into latitude/longitude via OpenStreetMap's Nominatim search API
(https://nominatim.org/release-docs/latest/api/Search/) -- free, no API
key or signup required.

Each location becomes one or more search queries, tried in order until
one resolves:

1. LOCATION_OVERRIDES below, for venues the automatic rules get wrong
   (a same-named place in another state, a typo, a name OSM doesn't
   know). Add an entry here whenever a map pin lands in the wrong spot.
2. Locations with a street address (NAGVA's "Venue | 123 Main St, City,
   ST ..." or USAV's "Venue, Hall A, 9400 Universal Blvd., Orlando, FL")
   are searched by that address, then by just its city/state. These and
   the overrides are only nudged toward Florida, not Orlando: an Orlando
   nudge turned "Newberry, FL" and "Wellington, FL" into local streets.
3. Bare venue names ("Cady Way Park") are searched inside the Orlando
   metro only, then anywhere in Florida -- never worldwide, which is how
   "Westside Community Center" used to land in Miami and "The Net" in
   Seattle.

Results are cached in .cache/geocode_cache.json, keyed by query, so a
run only geocodes queries it hasn't seen before (most runs geocode zero
new ones, since the same handful of venues repeat every week). This
keeps calls to Nominatim's public server rare and respects their usage
policy (https://operations.osmfoundation.org/policies/nominatim/): max 1
request/second and a descriptive User-Agent, both handled below. A query
Nominatim can't resolve is cached as a dated failure and retried after
FAILED_RETRY_DAYS; a network error isn't cached at all, so the next run
simply tries again.
"""

import json
import re
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = PROJECT_ROOT / ".cache" / "geocode_cache.json"
CACHE_VERSION = 2  # bump to discard every cached result and re-geocode

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "go-volleyball-calendar-data/1.0 (https://github.com/goBoothVB26/go-volleyball-calendar-data)"
REQUEST_DELAY_SECONDS = 1.1  # Nominatim usage policy: max 1 request/sec
FAILED_RETRY_DAYS = 30
# Nominatim down or blocking us: stop asking for the rest of this run
# (cached results still apply) instead of timing out on every query.
MAX_CONSECUTIVE_ERRORS = 3

# lon/lat pairs: the Orlando metro (Tavares/Sanford down to Kissimmee),
# and all of Florida.
ORLANDO_VIEWBOX = "-81.9,29.0,-80.8,28.0"
FLORIDA_VIEWBOX = "-87.7,31.1,-79.8,24.4"

# Exact location string (as scraped) -> address queries to try in order.
# An empty list means "never map this one" -- better no pin than a wrong
# one. Addresses come from each venue's own site or the city's park
# directory.
_WPVC = ["2603 Ace Rd, Orlando, FL 32792", "Ace Road, Orlando, FL"]
LOCATION_OVERRIDES = {
    # City of Sanford: OSM's only "Westside Community Center" is in Miami.
    "Westside Community Center": ["919 S Persimmon Ave, Sanford, FL 32771", "Sanford, FL"],
    # Out Sports League
    "Dr. James R. Smith Center": ["1723 Bruton Blvd, Orlando, FL 32805"],
    "Festival Park Volleyball Courts": ["2911 E Robinson St, Orlando, FL 32803"],
    "Englewood Neighborhood Center": ["6123 La Costa Dr, Orlando, FL 32807"],
    # Greater Orlando Volleyball Club
    "College Park Neighborhood Center": [
        "College Park Neighborhood Center, Orlando, FL",
        "2393 Elizabeth Ave, Orlando, FL 32804",
    ],
    # Winter Park Volleyball Club, under every name the sources use
    "Winter Park Volleyball Club": _WPVC,
    "Winter Park Volleyball Club Summer Adult Open Gym": _WPVC,
    "Winter Park Volleyball Center": _WPVC,
    "The Annex @ Winter Park Volleyball Club": _WPVC,
    "Winter Park Volleyball Club, 2603 Ace Rd. Orlando, FL 32792": _WPVC,
    # Trotters Park (Orlando); "Trotter Park" alone matched one in Texas.
    "Trotters Park": ["2701 Lee Rd, Orlando, FL 32789"],
    "Trotter Park": ["2701 Lee Rd, Orlando, FL 32789"],
    "Trotwood Park": ["Trotwood Park, Winter Springs, FL"],
    # Game Point: typos and the convention center
    "OCCC Orlando, Fl": ["9800 International Dr, Orlando, FL 32819"],
    "Daytonan Beach, Florida": ["Daytona Beach, FL"],
    "Wellinton, Florida": ["Wellington, FL"],
    # Beach / out-of-town tournaments (Volleyball Life, SSOVA)
    "Newberry Sand Courts at Jimmy Durden Park": ["Jimmy Durden Park, Newberry, FL", "Newberry, FL"],
    "Gulfport Beach Courts": ["Gulfport Beach, Gulfport, FL", "Gulfport, FL"],
    "Gulfport Volleyball Courts": ["Gulfport Beach, Gulfport, FL", "Gulfport, FL"],
    "Upham Beach Park- St. Pete Beach": ["Upham Beach Park, St. Pete Beach, FL", "St. Pete Beach, FL"],
    "Upham Beach Park- St.Pete Beach": ["Upham Beach Park, St. Pete Beach, FL", "St. Pete Beach, FL"],
    "High Springs Sports Complex": ["High Springs Sports Complex, High Springs, FL", "High Springs, FL"],
    "Hickory Point Recreational Facility": ["Hickory Point Beach Sand Volleyball Complex, Tavares, FL", "Tavares, FL"],
    "Tavares Sand Volleyball Courts": ["Hickory Point Beach Sand Volleyball Complex, Tavares, FL", "Tavares, FL"],
    "The Pit: Frost Park, Dania Beach, Fl": ["Frost Park, Dania Beach, FL", "Dania Beach, FL"],
    "South of Jacksonville Beach Fishing Pier": ["Jacksonville Beach Pier, Jacksonville Beach, FL"],
    "City Courts at Pinellas Park": ["Pinellas Park, FL"],
    # A city name, which the Orlando-area name search matched to a street
    "Pompano Beach": ["Pompano Beach, FL"],
    # Unknown venues the name search sent out of state; no pin until
    # someone pins down the real address.
    "Elevate": [],
    "The Net": [],
    # Not a venue: NAGVA's old scrape leaked the next section's heading.
    "Registration": [],
}

# "9400 Universal Blvd", "91-384 Komohana St" -- not a "9W6W+3GV" plus code
_STREET_ADDRESS = re.compile(r"^\d+(-\d+)?[A-Za-z]?\s+\S")


def _queries(location: str) -> list[tuple[str, str, bool]]:
    """(query, viewbox, bounded) searches to try for a location, in order."""
    normalized = " ".join(location.split())  # scraped text has stray double/nbsp spaces
    if normalized in LOCATION_OVERRIDES:
        return [(q, FLORIDA_VIEWBOX, False) for q in LOCATION_OVERRIDES[normalized]]
    location = normalized

    # NAGVA joins venue/address/next-heading with " | "; USAV joins venue,
    # hall and address with ", ". Search by the first street address found.
    segments = [s.strip() for s in location.split("|") if s.strip() and s.strip() != "Registration"]
    for segment in segments:
        parts = [p.strip() for p in segment.split(",")]
        # The street must be followed by a city ("808 Athletic Club" alone
        # is a venue name, not an address).
        for i, part in enumerate(parts[:-1]):
            if _STREET_ADDRESS.match(part):
                address = ", ".join(parts[i:])
                city = ", ".join(parts[i + 1:])
                queries = [(address, FLORIDA_VIEWBOX, False)]
                if city:
                    queries.append((city, FLORIDA_VIEWBOX, False))
                return queries

    if not segments or location.endswith("| Registration"):
        # Nothing, or a NAGVA venue name with no address (its scrape
        # leaked the next "Registration" heading): an out-of-state gym we
        # can't place, and a Florida search would match the wrong one.
        return []
    name = segments[0]
    if "," in name:
        # Already says where ("Wesley Chapel, Fl", "The Big House, Tavares, FL")
        return [(name, FLORIDA_VIEWBOX, False)]
    # Bare venue name: Orlando metro first, then the rest of Florida.
    return [(name, ORLANDO_VIEWBOX, True), (name, FLORIDA_VIEWBOX, True)]


def _cache_key(query: str, viewbox: str, bounded: bool) -> str:
    return f"{query} @ {viewbox}" if bounded else f"{query} ~ {viewbox}"


def load_cache() -> dict:
    if not CACHE_PATH.exists():
        return {}
    with open(CACHE_PATH, encoding="utf-8") as f:
        data = json.load(f)
    if data.get("version") != CACHE_VERSION:
        return {}  # older format: start over
    return data["entries"]


def save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump({"version": CACHE_VERSION, "entries": cache}, f, indent=2, sort_keys=True)


def _geocode_one(query: str, viewbox: str, bounded: bool) -> dict:
    """{"lat", "lng"} on success, {"failed": date} if Nominatim found
    nothing. Raises on network errors so they aren't cached."""
    params = {
        "q": query,
        "format": "jsonv2",
        "limit": 1,
        "viewbox": viewbox,
        "bounded": 1 if bounded else 0,
    }
    url = NOMINATIM_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=10) as resp:
        results = json.loads(resp.read().decode("utf-8"))
    if not results:
        return {"failed": date.today().isoformat()}
    return {"lat": float(results[0]["lat"]), "lng": float(results[0]["lon"])}


def _is_fresh(entry: dict | None) -> bool:
    if entry is None:
        return False
    if "failed" not in entry:
        return True
    return date.fromisoformat(entry["failed"]) > date.today() - timedelta(days=FAILED_RETRY_DAYS)


def geocode_locations(locations: set) -> dict:
    """Geocode every location, persist the cache, and return
    {location: {"lat":.., "lng":..} or None} for every location passed in."""
    cache = load_cache()
    used = {}
    fetched = failed = errors = 0
    consecutive_errors = 0
    last_request = 0.0
    result = {}
    for location in sorted(loc for loc in locations if loc):
        coords = None
        for query, viewbox, bounded in _queries(location):
            key = _cache_key(query, viewbox, bounded)
            entry = cache.get(key)
            if not _is_fresh(entry) and consecutive_errors < MAX_CONSECUTIVE_ERRORS:
                wait = REQUEST_DELAY_SECONDS - (time.monotonic() - last_request)
                if wait > 0:
                    time.sleep(wait)
                last_request = time.monotonic()
                try:
                    entry = _geocode_one(query, viewbox, bounded)
                except Exception:
                    errors += 1
                    consecutive_errors += 1
                    entry = None
                else:
                    consecutive_errors = 0
                    fetched += 1
                    failed += "failed" in entry
            if entry is not None:
                used[key] = entry
            if entry and "failed" not in entry:
                coords = entry
                break
        result[location] = coords
    # Only queries still in use are kept, so the cache doesn't fill up
    # with venues that left the calendar long ago.
    if used != cache:
        save_cache(used)
    if fetched or errors:
        print(f"Geocoded {fetched} new query(ies): {failed} not found, {errors} network error(s)")
    mapped = sum(1 for c in result.values() if c)
    print(f"Map: {mapped} of {len(result)} locations have coordinates")
    return result
