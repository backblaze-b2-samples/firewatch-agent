"""Send a wildfire alert email via Resend.

On Resend failure, falls back to saving the alert as local HTML + TXT files.

Return contract:
  Resend success: {"status": "sent",         "id": "...",  "path": null, "error": null}
  Local fallback: {"status": "saved_locally", "id": null,  "path": "...", "error": null}
  Hard failure:   {"status": "error",         "id": null,  "path": null, "error": "..."}

Callable as:
  - Python module: send_alert_email(headline, risk_level, summary, action, url, run_id) -> dict
  - CLI script:    python -m app.tools.send_alert_email --headline "..." ...
"""

import argparse
import json
import logging
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

from app.config import RESEND_API_KEY, RESEND_FROM, RESEND_TO, ALERTS_DIR

log = logging.getLogger("firewatch")

RESEND_URL = "https://api.resend.com/emails"
_RISK_COLORS = {"high": "#dc2626", "medium": "#d97706", "low": "#16a34a"}


def send_alert_email(
    headline: str,
    risk_level: str,
    summary: str,
    recommended_action: str,
    report_url: str,
    run_id: str | None = None,
) -> dict:
    """Send an alert email via Resend. Falls back to local file on failure.

    Returns:
        dict with 'status', 'id', 'path', and 'error' fields.
    """
    html = _build_html(headline, risk_level, summary, recommended_action, report_url)

    if all([RESEND_API_KEY, RESEND_FROM, RESEND_TO]):
        result = _send_via_resend(headline, risk_level, html)
        if result["status"] == "sent":
            return result
        log.warning("Resend failed (%s) — saving alert locally", result.get("error"))

    return _save_locally(run_id, headline, risk_level, summary, recommended_action, report_url, html)


def _build_html(
    headline: str,
    risk_level: str,
    summary: str,
    recommended_action: str,
    report_url: str,
) -> str:
    color = _RISK_COLORS.get(risk_level.lower(), "#6b7280")
    link = (
        f'<a href="{report_url}" style="color: #2563eb;">View Full Report &rarr;</a>'
        if report_url and report_url != "archived locally"
        else "<em>Report archived locally — manual distribution needed.</em>"
    )
    return f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
      <h2 style="color: {color};">&#x1F525; FireWatch Alert: {headline}</h2>
      <p><strong>Risk Level:</strong> <span style="color: {color};">{risk_level.upper()}</span></p>
      <h3>Summary</h3>
      <p>{summary}</p>
      <h3>Recommended Action</h3>
      <p>{recommended_action}</p>
      <hr>
      <p>{link}</p>
      <p style="color: #6b7280; font-size: 12px;">Sent by FireWatch Agent</p>
    </div>
    """


def _send_via_resend(headline: str, risk_level: str, html: str) -> dict:
    """POST to Resend API. Returns dict with 'status' key."""
    try:
        resp = requests.post(
            RESEND_URL,
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from": RESEND_FROM,
                "to": [RESEND_TO],
                "subject": f"[FireWatch] {risk_level.upper()} Alert: {headline}",
                "html": html,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        log.info("Alert email sent: id=%s", data.get("id"))
        return {"status": "sent", "id": data.get("id"), "path": None, "error": None}
    except requests.RequestException as e:
        return {"status": "error", "id": None, "path": None, "error": str(e)}


def _save_locally(
    run_id: str | None,
    headline: str,
    risk_level: str,
    summary: str,
    recommended_action: str,
    report_url: str,
    html: str,
) -> dict:
    """Save alert as HTML + TXT when Resend is unavailable."""
    ALERTS_DIR.mkdir(parents=True, exist_ok=True)
    prefix = run_id or "unknown"

    html_path = ALERTS_DIR / f"{prefix}_alert.html"
    txt_path = ALERTS_DIR / f"{prefix}_alert.txt"

    html_path.write_text(html)
    txt_path.write_text("\n".join([
        f"FireWatch Alert: {headline}",
        f"Risk Level: {risk_level.upper()}",
        f"Summary: {summary}",
        f"Recommended Action: {recommended_action}",
        f"Report: {report_url}",
    ]))

    log.warning("Resend unavailable — alert saved to data/alerts/%s_alert.*", prefix)
    return {"status": "saved_locally", "id": None, "path": str(html_path), "error": None}


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)

    parser = argparse.ArgumentParser(description="Send a FireWatch alert email")
    parser.add_argument("--headline", required=True)
    parser.add_argument("--risk-level", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--action", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()

    result = send_alert_email(
        headline=args.headline,
        risk_level=args.risk_level,
        summary=args.summary,
        recommended_action=args.action,
        report_url=args.url,
        run_id=args.run_id,
    )
    print(json.dumps(result, indent=2))
