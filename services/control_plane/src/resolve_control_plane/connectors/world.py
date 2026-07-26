"""Weather and travel time — the two facts RESOLVE was guessing at.

Both are deliberately KEYLESS. Open-Meteo (forecast + geocoding) and OSRM
(routing) are free, need no API key, no OAuth, and no billing account, so
there's one less secret in Render and no per-call cost. Google Maps and the
paid weather APIs are better only in ways that don't matter here: Trav needs
"is it going to rain on Thursday" and "when do I leave to make a 3pm", not
turn-by-turn navigation or hyperlocal radar.

Where this bites: `run_travel_watch` in routines.py fires at 06:00 on travel
days to tell him when to leave, and until now it had no routing data at all —
it was inferring departure time from the calendar entry alone.
"""

from __future__ import annotations

import requests

GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"
# OSRM's public demo router. Driving profile only, which is the one that matters.
OSRM = "https://router.project-osrm.org/route/v1/driving/{coords}"

# Open-Meteo returns WMO weather codes, not text.
WMO = {
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "freezing fog", 51: "light drizzle", 53: "drizzle",
    55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    66: "freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "light showers", 81: "showers", 82: "violent showers",
    85: "snow showers", 86: "heavy snow showers",
    95: "thunderstorms", 96: "thunderstorms with hail", 99: "thunderstorms with hail",
}


def describe_code(code: object) -> str:
    try:
        return WMO.get(int(code), "unsettled")
    except (TypeError, ValueError):
        return "unknown"


def geocode(place: str) -> dict:
    """Place name -> coordinates. Also the input validator for everything below:
    a typo'd city fails here with a clear message instead of silently returning
    the weather for somewhere else."""
    r = requests.get(GEOCODE, params={"name": place, "count": 1}, timeout=15)
    r.raise_for_status()
    hits = (r.json() or {}).get("results") or []
    if not hits:
        raise ValueError(f"I couldn't find a place called “{place}”.")
    top = hits[0]
    label = ", ".join(x for x in (top.get("name"), top.get("admin1"),
                                  top.get("country_code")) if x)
    return {"lat": top["latitude"], "lon": top["longitude"], "label": label}


def weather(place: str = "Baltimore", days: int = 3) -> dict:
    """Current conditions plus a short daily forecast."""
    spot = geocode(place)
    days = max(1, min(int(days or 3), 7))
    r = requests.get(FORECAST, params={
        "latitude": spot["lat"], "longitude": spot["lon"],
        "current": "temperature_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                 "precipitation_probability_max,sunrise,sunset",
        "temperature_unit": "fahrenheit", "wind_speed_unit": "mph",
        "precipitation_unit": "inch", "timezone": "America/New_York",
        "forecast_days": days,
    }, timeout=20)
    r.raise_for_status()
    data = r.json() or {}
    cur, daily = data.get("current") or {}, data.get("daily") or {}

    out_days = []
    for i, day in enumerate(daily.get("time") or []):
        out_days.append({
            "date": day,
            "conditions": describe_code((daily.get("weather_code") or [None])[i]),
            "high": (daily.get("temperature_2m_max") or [None])[i],
            "low": (daily.get("temperature_2m_min") or [None])[i],
            "rainChance": (daily.get("precipitation_probability_max") or [None])[i],
            "sunrise": (daily.get("sunrise") or [None])[i],
            "sunset": (daily.get("sunset") or [None])[i],
        })

    return {
        "place": spot["label"],
        "now": {
            "temp": cur.get("temperature_2m"),
            "feelsLike": cur.get("apparent_temperature"),
            "conditions": describe_code(cur.get("weather_code")),
            "windMph": cur.get("wind_speed_10m"),
            "precipInches": cur.get("precipitation"),
        },
        "forecast": out_days,
    }


def travel_time(origin: str, destination: str) -> dict:
    """Driving distance and duration between two places.

    OSRM gives free-flow time with no live traffic, so it under-reads at rush
    hour — the padding advice belongs in the answer, not silently in the number.
    """
    a, b = geocode(origin), geocode(destination)
    coords = f"{a['lon']},{a['lat']};{b['lon']},{b['lat']}"
    r = requests.get(OSRM.format(coords=coords),
                     params={"overview": "false"}, timeout=25)
    r.raise_for_status()
    data = r.json() or {}
    routes = data.get("routes") or []
    if not routes:
        raise ValueError(f"I couldn't find a driving route from {a['label']} to {b['label']}.")
    route = routes[0]
    minutes = round(route["duration"] / 60)
    return {
        "from": a["label"], "to": b["label"],
        "minutes": minutes,
        "miles": round(route["distance"] / 1609.34, 1),
        "note": "Free-flow driving time — no live traffic, so add padding at rush hour.",
    }
