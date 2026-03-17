"""Compute explainable fire risk scores from event + weather data."""

from app.models import FireEvent, WeatherContext, RiskAssessment


def compute_risk(event: FireEvent, weather: WeatherContext) -> RiskAssessment:
    """Score fire risk 0-100 with explainable factors.

    Weighting:
      - Fire intensity (brightness + FRP): 40%
      - Detection confidence: 20%
      - Weather conditions (temp, wind, humidity): 40%
    """
    factors: list[str] = []

    intensity = _score_intensity(event, factors)
    confidence = _score_confidence(event, factors)
    weather_score = _score_weather(weather, factors)

    score = round(
        (intensity * 0.4) + (confidence * 0.2) + (weather_score * 0.4), 1
    )
    score = min(max(score, 0), 100)

    level = "high" if score >= 70 else "medium" if score >= 40 else "low"

    return RiskAssessment(score=score, level=level, factors=factors)


def _score_intensity(event: FireEvent, factors: list[str]) -> float:
    """Score 0-100 based on brightness and fire radiative power."""
    # VIIRS bright_ti4 typically 300-500K for fires
    bright_score = 0.0
    if event.brightness > 300:
        bright_score = min((event.brightness - 300) / 200 * 100, 100)
        if bright_score > 60:
            factors.append(f"High brightness ({event.brightness:.0f}K)")

    # FRP typically 0-500+ MW, cap at 200 MW
    frp_score = min(event.frp / 200 * 100, 100) if event.frp > 0 else 0.0
    if frp_score > 50:
        factors.append(f"Strong fire radiative power ({event.frp:.1f} MW)")

    return (bright_score * 0.5) + (frp_score * 0.5)


def _score_confidence(event: FireEvent, factors: list[str]) -> float:
    """Score 0-100 based on detection confidence."""
    conf = event.confidence
    mapping = {"low": 20, "nominal": 50, "high": 90}

    try:
        score = mapping.get(conf.lower(), float(conf))
    except (ValueError, AttributeError):
        score = 30.0

    score = min(score, 100)
    if score >= 80:
        factors.append(f"High detection confidence ({conf})")

    return score


def _score_weather(weather: WeatherContext, factors: list[str]) -> float:
    """Score 0-100: high temp + high wind + low humidity = high risk."""
    if weather.error:
        factors.append("Weather data unavailable")
        return 50.0

    temp = weather.temperature_c or 0
    wind = weather.windspeed_kmh or 0
    humidity = weather.humidity_pct or 50

    # Temp: scale 20-45C
    temp_score = min(max((temp - 20) / 25 * 100, 0), 100)
    if temp > 35:
        factors.append(f"High temperature ({temp:.1f}C)")

    # Wind: scale 0-50 km/h
    wind_score = min(max(wind / 50 * 100, 0), 100)
    if wind > 25:
        factors.append(f"Strong winds ({wind:.1f} km/h)")

    # Humidity: lower = worse
    humidity_score = max(100 - humidity, 0)
    if humidity < 25:
        factors.append(f"Very low humidity ({humidity:.0f}%)")

    return (temp_score * 0.35) + (wind_score * 0.35) + (humidity_score * 0.3)
