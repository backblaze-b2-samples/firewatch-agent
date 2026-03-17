"""Enrich fire events with weather data from Open-Meteo (free, no key)."""

import logging
import requests

from app.config import WEATHER_SOURCE_BASE_URL, REQUEST_TIMEOUT_SECONDS
from app.models import FireEvent, WeatherContext

log = logging.getLogger("firewatch")


def fetch_weather(event: FireEvent) -> WeatherContext:
    """Fetch current weather conditions at a fire event's location.

    Uses Open-Meteo free API — no key required.
    Returns WeatherContext with error field set on failure.
    """
    params = {
        "latitude": event.latitude,
        "longitude": event.longitude,
        "current_weather": "true",
        "hourly": "relative_humidity_2m",
        "forecast_days": 1,
    }

    try:
        resp = requests.get(
            WEATHER_SOURCE_BASE_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS
        )
        resp.raise_for_status()
        data = resp.json()

        current = data.get("current_weather", {})
        humidity_vals = data.get("hourly", {}).get("relative_humidity_2m", [])

        return WeatherContext(
            temperature_c=current.get("temperature"),
            windspeed_kmh=current.get("windspeed"),
            wind_direction_deg=current.get("winddirection"),
            humidity_pct=humidity_vals[0] if humidity_vals else None,
        )
    except requests.RequestException as e:
        log.warning("Weather fetch failed for (%.2f, %.2f): %s",
                    event.latitude, event.longitude, e)
        return WeatherContext(error=str(e))
