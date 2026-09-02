"""Persist fire event packages as structured local folders.

Output format designed for OpenClaw agent inspection:
  data/events/{event_id}/
    fire_event.json
    weather.json
    evidence.json
    risk.json
    summary.json
    summary.md
"""

import json
import logging
from pathlib import Path

from app.config import EVENTS_DIR
from app.models import (
    FireEvent, WeatherContext, EvidenceAsset,
    RiskAssessment, IncidentSummary,
)
from app.privacy import coarse_location, redact_coordinate_pairs

log = logging.getLogger("firewatch")


def make_event_id(event: FireEvent) -> str:
    """Deterministic event ID from location + acquisition timestamp."""
    date = event.acq_date or "unknown-date"
    time = event.acq_time or "0000"
    return f"evt_{event.latitude:.2f}_{event.longitude:.2f}_{date}_{time}"


def save_event_package(
    event_id: str,
    fire_event: FireEvent,
    weather: WeatherContext,
    evidence: EvidenceAsset,
    risk: RiskAssessment,
    summary: IncidentSummary | None = None,
) -> Path:
    """Write all event artifacts to a local folder.

    Returns the event directory path.
    """
    event_dir = EVENTS_DIR / event_id
    event_dir.mkdir(parents=True, exist_ok=True)

    _write_json(event_dir / "fire_event.json", fire_event.model_dump())
    _write_json(event_dir / "weather.json", weather.model_dump())
    _write_json(event_dir / "evidence.json", evidence.model_dump())
    _write_json(event_dir / "risk.json", risk.model_dump())

    if summary:
        _write_json(event_dir / "summary.json", _redact_summary(summary).model_dump())
        _write_markdown(event_dir / "summary.md", event_id, fire_event, risk, summary)

    log.info("Saved event package: event_id=%s path=%s", event_id, event_dir)
    return event_dir


def _write_json(path: Path, data: dict) -> None:
    """Write human-readable JSON."""
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def _write_markdown(
    path: Path,
    event_id: str,
    event: FireEvent,
    risk: RiskAssessment,
    summary: IncidentSummary,
) -> None:
    """Write a human-readable incident summary markdown file."""
    headline = redact_coordinate_pairs(summary.headline or event_id)
    summary_text = redact_coordinate_pairs(summary.summary)
    action = redact_coordinate_pairs(summary.recommended_action)
    reasoning = redact_coordinate_pairs(summary.reasoning)
    md = f"""# {headline}

**Risk:** {risk.level.upper()} (score {risk.score})
**Location:** {coarse_location(event.latitude, event.longitude)}
**Detected:** {event.acq_date} {event.acq_time}

## Summary

{summary_text}

## Recommended Action

{action}

## Reasoning

{reasoning}

## Risk Factors

"""
    for factor in risk.factors:
        md += f"- {factor}\n"

    with open(path, "w") as f:
        f.write(md)


def _redact_summary(summary: IncidentSummary) -> IncidentSummary:
    """Return a copy with coordinate pairs removed from free text fields."""
    return summary.model_copy(update={
        "headline": redact_coordinate_pairs(summary.headline),
        "summary": redact_coordinate_pairs(summary.summary),
        "recommended_action": redact_coordinate_pairs(summary.recommended_action),
        "reasoning": redact_coordinate_pairs(summary.reasoning),
    })
