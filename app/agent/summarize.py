"""Call local Nemotron model to generate incident summaries."""

import json
import logging
import requests

from app.config import MODEL_BASE_URL, MODEL_NAME, MODEL_API_KEY, REQUEST_TIMEOUT_SECONDS
from app.models import (
    FireEvent, WeatherContext, RiskAssessment, IncidentSummary,
)
from app.agent.prompts import SUMMARIZE_INCIDENT_PROMPT

log = logging.getLogger("firewatch")


def summarize_incident(
    event: FireEvent,
    weather: WeatherContext,
    risk: RiskAssessment,
) -> IncidentSummary:
    """Generate an LLM summary for a fire incident via local Nemotron endpoint.

    Falls back to a template-based summary if the model is unreachable or
    returns malformed output.
    """
    prompt = SUMMARIZE_INCIDENT_PROMPT.format(
        latitude=event.latitude,
        longitude=event.longitude,
        brightness=event.brightness,
        frp=event.frp,
        confidence=event.confidence,
        acq_date=event.acq_date,
        acq_time=event.acq_time,
        temperature_c=weather.temperature_c or "N/A",
        windspeed_kmh=weather.windspeed_kmh or "N/A",
        wind_direction_deg=weather.wind_direction_deg or "N/A",
        humidity_pct=weather.humidity_pct or "N/A",
        risk_score=risk.score,
        risk_level=risk.level,
        risk_factors=", ".join(risk.factors) or "none",
    )

    try:
        return _call_model(prompt)
    except Exception as e:
        log.warning("LLM summarization failed, using fallback: %s", e)
        return _fallback_summary(event, weather, risk)


def _call_model(prompt: str) -> IncidentSummary:
    """POST to the OpenAI-compatible /v1/chat/completions endpoint."""
    url = f"{MODEL_BASE_URL}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {MODEL_API_KEY}",
    }
    payload = {
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 512,
    }

    resp = requests.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
    resp.raise_for_status()

    content = resp.json()["choices"][0]["message"]["content"].strip()
    # Strip markdown code fences if the model wraps its output
    if content.startswith("```"):
        content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    data = json.loads(content)
    return IncidentSummary(**data)


def _fallback_summary(
    event: FireEvent,
    weather: WeatherContext,
    risk: RiskAssessment,
) -> IncidentSummary:
    """Template-based summary when the LLM is unavailable."""
    wind_info = (
        f" with winds at {weather.windspeed_kmh} km/h"
        if weather.windspeed_kmh else ""
    )

    return IncidentSummary(
        headline=f"{risk.level.upper()} risk fire near ({event.latitude:.2f}, {event.longitude:.2f})",
        summary=(
            f"Wildfire hotspot detected at ({event.latitude:.4f}, {event.longitude:.4f}) "
            f"on {event.acq_date} with brightness {event.brightness:.0f}K and "
            f"FRP {event.frp:.1f} MW. "
            f"Temperature {weather.temperature_c or 'unknown'}C{wind_info}."
        ),
        recommended_action=(
            "Monitor closely" if risk.level == "high"
            else "Track for changes" if risk.level == "medium"
            else "Low priority — routine monitoring"
        ),
        reasoning=", ".join(risk.factors) if risk.factors else "Standard risk assessment",
    )
