"""Generate daily and alerts markdown reports from scored pipeline events."""

import logging
from datetime import datetime
from pathlib import Path

from app.config import REPORTS_DIR, ALERT_SCORE_THRESHOLD
from app.storage.store import make_event_id

log = logging.getLogger("firewatch")


def write_daily_report(scored_events: list[tuple]) -> Path:
    """Write a daily summary of all events to data/reports/daily_report.md."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / "daily_report.md"

    today = datetime.utcnow().strftime("%Y-%m-%d")
    total = len(scored_events)
    high = sum(1 for _, _, _, r in scored_events if r.level == "high")
    medium = sum(1 for _, _, _, r in scored_events if r.level == "medium")

    lines = [
        f"# FireWatch Daily Report — {today}",
        "",
        f"**Total Events:** {total}  ",
        f"**High Risk:** {high}  ",
        f"**Medium Risk:** {medium}  ",
        f"**Low Risk:** {total - high - medium}",
        "",
        "---",
        "",
        "## Incidents by Risk Level",
        "",
    ]

    for fire, weather, _, risk in scored_events:
        event_id = make_event_id(fire)
        lines += [
            f"### {event_id}",
            f"- **Risk:** {risk.level.upper()} (score {risk.score:.0f})",
            f"- **Location:** {fire.latitude:.4f}, {fire.longitude:.4f}",
            f"- **Detected:** {fire.acq_date} {fire.acq_time}",
            f"- **Brightness:** {fire.brightness:.0f}K | FRP: {fire.frp:.1f} MW",
            f"- **Temp:** {weather.temperature_c or 'N/A'}°C | Wind: {weather.windspeed_kmh or 'N/A'} km/h",
        ]
        if risk.factors:
            lines.append(f"- **Factors:** {', '.join(risk.factors)}")
        lines.append("")

    path.write_text("\n".join(lines))
    log.info("Daily report written: %s", path)
    return path


def write_alerts_report(scored_events: list[tuple]) -> Path:
    """Write an alerts report for high-priority events to data/reports/alerts.md.

    Includes events where level == 'high' or score >= ALERT_SCORE_THRESHOLD.
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / "alerts.md"

    alerts = [
        (fire, weather, evidence, risk)
        for fire, weather, evidence, risk in scored_events
        if risk.level == "high" or risk.score >= ALERT_SCORE_THRESHOLD
    ]

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# FireWatch Alerts — {now}",
        "",
        f"**Alert Count:** {len(alerts)}",
        "",
        "---",
        "",
    ]

    if not alerts:
        lines.append("*No high-priority incidents detected.*")
    else:
        for fire, weather, _, risk in alerts:
            event_id = make_event_id(fire)
            lines += [
                f"## {event_id}",
                f"- **Risk:** {risk.level.upper()} (score {risk.score:.0f})",
                f"- **Location:** {fire.latitude:.4f}, {fire.longitude:.4f}",
                f"- **Detected:** {fire.acq_date} {fire.acq_time}",
                f"- **Brightness:** {fire.brightness:.0f}K | FRP: {fire.frp:.1f} MW",
                f"- **Temp:** {weather.temperature_c or 'N/A'}°C | Wind: {weather.windspeed_kmh or 'N/A'} km/h",
            ]
            if risk.factors:
                lines.append(f"- **Factors:** {', '.join(risk.factors)}")
            lines.append("")

    path.write_text("\n".join(lines))
    log.info("Alerts report written: %s (%d alerts)", path, len(alerts))
    return path
