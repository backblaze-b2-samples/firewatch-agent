"""OpenClaw — post-processing agent for FireWatch incident analysis.

Workflow:
1. Check alert rules (Python): risk level == 'high' OR score >= threshold
2. If alert: use pre-computed upload_result (or upload now); send email via Resend
3. Generate ops brief via local LLM (reflects actual storage/delivery method)
4. Return structured output for the OpenClaw skill to present in chat
"""

import json
import logging

import requests

from app.config import (
    MODEL_BASE_URL, MODEL_NAME, MODEL_API_KEY,
    REQUEST_TIMEOUT_SECONDS, REPORTS_DIR, ALERT_SCORE_THRESHOLD,
    EVENTS_DIR,
)
from app.agent.prompts import OPENCLAW_BRIEF_PROMPT
from app.storage.store import make_event_id
from app.tools.upload_reports import upload_reports
from app.tools.send_alert_email import send_alert_email

log = logging.getLogger("firewatch")


def should_alert(scored_events: list[tuple]) -> bool:
    """Return True if any event is high risk or top score >= threshold."""
    for _, _, _, risk in scored_events:
        if risk.level == "high":
            return True
        if risk.score >= ALERT_SCORE_THRESHOLD:
            return True
    return False


def run_openclaw(
    scored_events: list[tuple],
    upload_result: dict | None = None,
    run_id: str | None = None,
) -> dict:
    """Run the OpenClaw workflow after the FireWatch pipeline.

    Args:
        scored_events: Tuples of (fire, weather, evidence, risk) sorted by score.
        upload_result: Pre-computed upload result from the pipeline. If provided,
                       OpenClaw skips re-uploading.
        run_id:        Run ID passed to send_alert_email for fallback file naming.

    Returns:
        dict with keys: alert_needed, upload_result, email_result, ops_brief
    """
    result = {
        "alert_needed": False,
        "upload_result": upload_result,
        "email_result": None,
        "ops_brief": "",
    }

    if not scored_events:
        result["ops_brief"] = "No events to analyze."
        return result

    # 1. Apply alert rules
    result["alert_needed"] = should_alert(scored_events)

    # 2. Read report files for LLM context
    report_context = _read_reports()

    # 3. Upload (if not already done) and email when alert threshold is met
    if result["alert_needed"]:
        if upload_result is None:
            upload_result = upload_reports(run_id=run_id)
            result["upload_result"] = upload_result

        # Resolve report URL based on storage method
        storage = (upload_result or {}).get("storage")
        report_url = _resolve_report_url(upload_result, storage)

        # Build email content from top incident
        fire, _, __, risk = scored_events[0]
        event_id = make_event_id(fire)
        headline, summary_text, action = _get_incident_text(event_id, fire, risk)

        result["email_result"] = send_alert_email(
            headline=headline,
            risk_level=risk.level,
            summary=summary_text,
            recommended_action=action,
            report_url=report_url,
            run_id=run_id,
        )

    # 4. Generate ops brief
    result["ops_brief"] = _generate_ops_brief(scored_events, report_context, result)
    return result


def _resolve_report_url(upload_result: dict | None, storage: str | None) -> str:
    """Return a URL string or descriptive fallback depending on storage method."""
    if not upload_result:
        return "N/A"
    if storage == "b2":
        for item in (upload_result.get("uploaded") or []):
            if "alerts" in item.get("file", ""):
                return item["url"]
        uploaded = upload_result.get("uploaded") or []
        return uploaded[0]["url"] if uploaded else "N/A"
    # Local archive — no public URL
    return "archived locally"


def _get_incident_text(event_id: str, fire, risk) -> tuple[str, str, str]:
    """Return (headline, summary, action) from summary.json or template fallback."""
    summary_path = EVENTS_DIR / event_id / "summary.json"
    if summary_path.exists():
        try:
            data = json.loads(summary_path.read_text())
            return (
                data.get("headline", event_id),
                data.get("summary", ""),
                data.get("recommended_action", ""),
            )
        except (json.JSONDecodeError, OSError):
            pass

    headline = f"{risk.level.upper()} risk fire near ({fire.latitude:.2f}, {fire.longitude:.2f})"
    summary_text = f"Score {risk.score:.0f}. {', '.join(risk.factors[:3])}"
    action = (
        "Immediate monitoring and response required"
        if risk.level == "high"
        else "Monitor closely"
    )
    return headline, summary_text, action


def _read_reports() -> str:
    """Read available report files for LLM context (capped per file)."""
    parts = []
    for fname in ("daily_report.md", "alerts.md"):
        path = REPORTS_DIR / fname
        if path.exists():
            parts.append(f"### {fname}\n{path.read_text()[:2000]}")
    return "\n\n".join(parts) if parts else "No reports available."


def _describe_upload(upload_result: dict | None) -> str:
    """Return a human-readable upload method string for the prompt."""
    if not upload_result:
        return "not attempted"
    storage = upload_result.get("storage")
    n = len(upload_result.get("uploaded") or [])
    if storage == "b2":
        return f"uploaded to B2 ({n} files, public URLs available)"
    if storage == "local":
        return f"archived locally ({n} files, manual distribution needed)"
    return f"failed: {upload_result.get('error', 'unknown error')}"


def _describe_email(email_result: dict | None) -> str:
    """Return a human-readable email delivery string for the prompt."""
    if not email_result:
        return "not sent"
    status = email_result.get("status")
    if status == "sent":
        return "sent via Resend"
    if status == "saved_locally":
        return f"saved locally at {email_result.get('path', 'data/alerts/')}"
    return f"failed: {email_result.get('error', 'unknown error')}"


def _generate_ops_brief(
    scored_events: list[tuple],
    report_context: str,
    action_result: dict,
) -> str:
    """Generate ops brief via local LLM, falling back to template."""
    fire, _, __, risk = scored_events[0]
    total = len(scored_events)
    high_count = sum(1 for _, _, _, r in scored_events if r.level == "high")

    prompt = OPENCLAW_BRIEF_PROMPT.format(
        total_events=total,
        high_count=high_count,
        top_score=risk.score,
        top_level=risk.level,
        top_lat=fire.latitude,
        top_lon=fire.longitude,
        alert_needed=action_result["alert_needed"],
        upload_method=_describe_upload(action_result.get("upload_result")),
        email_method=_describe_email(action_result.get("email_result")),
        report_context=report_context[:1500],
    )

    try:
        resp = requests.post(
            f"{MODEL_BASE_URL}/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {MODEL_API_KEY}",
            },
            json={
                "model": MODEL_NAME,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 400,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.warning("OpenClaw LLM brief failed, using fallback: %s", e)
        return _fallback_brief(scored_events, action_result)


def _fallback_brief(scored_events: list[tuple], action_result: dict) -> str:
    """Template-based ops brief when LLM is unavailable."""
    total = len(scored_events)
    high_count = sum(1 for _, _, _, r in scored_events if r.level == "high")
    fire, _, __, risk = scored_events[0]

    parts = [
        f"OpenClaw Ops Brief: Analyzed {total} wildfire events; {high_count} flagged HIGH risk.",
        f"Top incident: score {risk.score:.0f} ({risk.level}) at ({fire.latitude:.4f}, {fire.longitude:.4f}).",
    ]

    if action_result["alert_needed"]:
        upload_desc = _describe_upload(action_result.get("upload_result"))
        email_desc = _describe_email(action_result.get("email_result"))
        parts.append(f"Alert triggered. Reports: {upload_desc}. Alert: {email_desc}.")
    else:
        parts.append("No alert threshold met. No email sent.")

    return " ".join(parts)
