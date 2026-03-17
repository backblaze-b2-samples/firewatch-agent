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
from datetime import datetime
from pathlib import Path

from app.config import EVENTS_DIR
from app.models import (
    FireEvent, WeatherContext, EvidenceAsset,
    RiskAssessment, IncidentSummary,
)

log = logging.getLogger("firewatch")


def make_event_id(event: FireEvent) -> str:
    """Deterministic event ID from location + acquisition timestamp."""
    date = event.acq_date or datetime.utcnow().strftime("%Y-%m-%d")
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
        _write_json(event_dir / "summary.json", summary.model_dump())
        _write_markdown(event_dir / "summary.md", event_id, fire_event, risk, summary)

    log.info("Saved event package: %s", event_dir)
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
    md = f"""# {summary.headline or event_id}

**Risk:** {risk.level.upper()} (score {risk.score})
**Location:** {event.latitude:.4f}, {event.longitude:.4f}
**Detected:** {event.acq_date} {event.acq_time}

## Summary

{summary.summary}

## Recommended Action

{summary.recommended_action}

## Reasoning

{summary.reasoning}

## Risk Factors

"""
    for factor in risk.factors:
        md += f"- {factor}\n"

    with open(path, "w") as f:
        f.write(md)
