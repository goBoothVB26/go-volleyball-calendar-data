"""Daily weather forecast for the calendar widget's weather badges.

Fetches an 8-day forecast (today plus the next 7 days) for the Orlando
area from Open-Meteo's free forecast API (https://open-meteo.com/) --
no API key, no signup, generous free-tier limits. One shared forecast
covers every event and every day cell: the clubs this calendar tracks
are all Central-Florida based, and per-venue forecasts would differ by
only a few miles -- not worth a second geocoded fetch per event.
"""

import json
import urllib.request
from datetime import datetime
from typing import Any, Optional

FORECAST_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude=28.5383&longitude=-81.3792"
    "&daily=weathercode,temperature_2m_max,temperature_2m_min"
    "&temperature_unit=fahrenheit"
    "&timezone=America%2FNew_York"
    "&forecast_days=8"
)

USER_AGENT = "go-volleyball-calendar-data/1.0 (https://github.com/goBoothVB26/go-volleyball-calendar-data)"

# WMO weather interpretation codes (https://open-meteo.com/en/docs) collapsed
# into a handful of simple categories; the frontend maps each to one emoji.
_CODE_CATEGORY = {
    0: "clear",
    1: "mostly_clear", 2: "partly_cloudy", 3: "overcast",
    45: "fog", 48: "fog",
    51: "drizzle", 53: "drizzle", 55: "drizzle", 56: "drizzle", 57: "drizzle",
    61: "rain", 63: "rain", 65: "rain", 66: "rain", 67: "rain",
    71: "snow", 73: "snow", 75: "snow", 77: "snow",
    80: "rain", 81: "rain", 82: "rain",
    85: "snow", 86: "snow",
    95: "storm", 96: "storm", 99: "storm",
}


def _category(code: int) -> str:
    return _CODE_CATEGORY.get(code, "unknown")


def fetch_forecast() -> Optional[dict[str, Any]]:
    """Returns {"generated": ..., "days": [{"date","high","low","code","category"}, ...]}
    or None if the forecast couldn't be fetched (network hiccup, API down,
    unexpected response shape) -- callers should treat that as "no weather
    data available this run" rather than a fatal error, same as a failed
    geocode leaves an event with no map pin instead of crashing the scrape.
    """
    req = urllib.request.Request(FORECAST_URL, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

    daily = data.get("daily")
    if not daily:
        return None
    try:
        dates = daily["time"]
        codes = daily["weathercode"]
        highs = daily["temperature_2m_max"]
        lows = daily["temperature_2m_min"]
    except KeyError:
        return None
    if not (len(dates) == len(codes) == len(highs) == len(lows)):
        return None

    days = []
    for date, code, high, low in zip(dates, codes, highs, lows):
        days.append({
            "date": date,
            "high": round(high),
            "low": round(low),
            "code": code,
            "category": _category(code),
        })
    return {
        "generated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "days": days,
    }


def write_weather_json(path: str) -> bool:
    """Fetches the forecast and writes it to `path`. Returns True on
    success. On failure, leaves any existing file at `path` untouched --
    a forecast from a few hours ago is still more useful than none."""
    forecast = fetch_forecast()
    if forecast is None:
        return False
    with open(path, "w", encoding="utf-8") as f:
        json.dump(forecast, f, indent=2)
    return True
