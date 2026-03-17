"""FireWatch Agent — main pipeline.

Pipeline order:
  1. Fetch hotspots (FIRMS)           — skip on failure
  2. Pre-filter to top N by conf×brightness (cheap, no API calls)
  3. Enrich with weather (Open-Meteo) — skip per-event on failure
  4. Final scoring + sort
  5. Summarize top N, save event packages + reports
  6. Upload reports to B2 (or local archive fallback)
  7. Alert check + email (or local file fallback)
  8. Write manifest + mark complete

Run:       python -m app.main
Async run: python -m app.main --async   (returns immediately; skill polls status.log)
"""

import argparse
import json
import logging
import os
import sys
import threading
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from app.config import (
    TOP_N_EVENTS, EVENTS_DIR, REPORTS_DIR, PREFILTER_LIMIT, DEFAULT_REGION,
)
from app.ingest.fires import fetch_fires
from app.ingest.weather import fetch_weather
from app.evidence.snapshots import build_evidence
from app.scoring.risk import compute_risk
from app.storage.store import save_event_package, make_event_id
from app.storage.reports import write_daily_report, write_alerts_report
from app.agent.summarize import summarize_incident
from app.agent.openclaw import run_openclaw
from app.models import FireEvent, WeatherContext
from app.tools.upload_reports import upload_reports

# Setup logging
LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "firewatch.log")),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("firewatch")

# Stage labels used by the OpenClaw skill to render chat messages
STAGE_LABELS = {
    "fetching":      "Fetching hotspots from NASA FIRMS...",
    "pre_filtering": "Pre-filtering top candidates...",
    "enriching":     "Enriching with weather data...",
    "scoring":       "Scoring and ranking risks...",
    "summarizing":   "Generating incident summaries...",
    "uploading":     "Uploading reports...",
    "alerting":      "Checking alert thresholds...",
    "complete":      "Pipeline complete.",
}


# ---------------------------------------------------------------------------
# Status tracking — NDJSON log + latest-state JSON
# ---------------------------------------------------------------------------

def update_status(stage: str, detail: dict | None = None) -> None:
    """Append a status line to status.log and overwrite status.json.

    status.log  — newline-delimited JSON; one object per event; skill tails this
    status.json — latest state only; for quick reads
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "stage": stage,
        "ts": datetime.utcnow().isoformat() + "Z",
        "detail": detail or {},
    }
    line = json.dumps(entry)

    # Append to log
    with open(REPORTS_DIR / "status.log", "a") as f:
        f.write(line + "\n")

    # Overwrite latest state
    (REPORTS_DIR / "status.json").write_text(json.dumps(entry, indent=2))
    log.debug("Status → %s %s", stage, detail or "")


# ---------------------------------------------------------------------------
# Pre-filter helpers
# ---------------------------------------------------------------------------

def _confidence_numeric(conf: str) -> float:
    """Map FIRMS confidence (string or numeric) to float for sorting."""
    mapping = {"low": 20.0, "nominal": 50.0, "high": 90.0}
    try:
        return mapping.get(conf.lower(), float(conf))
    except (ValueError, AttributeError):
        return 30.0


def _prefilter_hotspots(fires: list[FireEvent], limit: int) -> list[FireEvent]:
    """Sort raw hotspots by confidence × brightness, return top N."""
    ranked = sorted(
        fires,
        key=lambda f: _confidence_numeric(f.confidence) * f.brightness,
        reverse=True,
    )
    kept = ranked[:limit]
    if len(fires) > limit:
        log.info("Pre-filter: %d → %d hotspots (by confidence×brightness)", len(fires), len(kept))
    return kept


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    source: str = "VIIRS_SNPP_NRT",
    days: int = 1,
    bbox: tuple[float, float, float, float] | None = None,
    region: str | None = None,
    top_n: int | None = None,
) -> dict:
    """Execute the full FireWatch pipeline. Returns a results dict."""
    top_n = top_n or TOP_N_EVENTS
    region = region or DEFAULT_REGION
    run_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    sources_status: dict = {}

    # Clear status.log for this run
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "status.log").write_text("")

    log.info(
        "FireWatch pipeline starting (run_id=%s, source=%s, region=%s, days=%d)",
        run_id, source, region, days,
    )

    # ------------------------------------------------------------------
    # Stage 1: Fetch hotspots
    # ------------------------------------------------------------------
    update_status("fetching", {"source": source, "region": region, "days": days})
    fires: list[FireEvent] = []
    try:
        fires = fetch_fires(source=source, days=days, bbox=bbox, region=region)
        sources_status["firms"] = {"status": "ok", "count": len(fires)}
        log.info("Fetched %d hotspots from FIRMS", len(fires))
    except Exception as e:
        sources_status["firms"] = {"status": "skipped", "error": str(e)}
        log.warning("Skipping FIRMS: %s", e)

    if not fires:
        update_status("complete", {"run_id": run_id, "events": 0, "sources": sources_status})
        log.warning("No hotspots found — exiting")
        return {"run_id": run_id, "total_events": 0, "saved_dirs": []}

    # ------------------------------------------------------------------
    # Stage 2: Pre-filter to top PREFILTER_LIMIT
    # ------------------------------------------------------------------
    raw_count = len(fires)
    update_status("pre_filtering", {"raw_count": raw_count, "limit": PREFILTER_LIMIT})
    fires = _prefilter_hotspots(fires, limit=PREFILTER_LIMIT)

    # ------------------------------------------------------------------
    # Stage 3: Enrich with weather
    # ------------------------------------------------------------------
    update_status("enriching", {"count": len(fires), "progress": f"0/{len(fires)}"})
    weather_ok = 0
    weather_failed = 0
    scored_events: list[tuple] = []
    total_fires = len(fires)

    for i, fire in enumerate(fires):
        try:
            weather = fetch_weather(fire)
            if weather.error:
                weather_failed += 1
            else:
                weather_ok += 1
        except Exception as e:
            log.warning("Weather fetch error for event %d: %s", i, e)
            weather = WeatherContext(error=str(e))
            weather_failed += 1

        evidence = build_evidence(fire, weather)
        risk = compute_risk(fire, weather)
        scored_events.append((fire, weather, evidence, risk))

        # Progress update every 10 events so the skill can show incremental progress
        if (i + 1) % 10 == 0:
            update_status("enriching", {
                "count": total_fires,
                "progress": f"{i + 1}/{total_fires}",
            })

    sources_status["open_meteo"] = {
        "status": "ok" if weather_ok > 0 else "skipped",
        "ok": weather_ok,
        "failed": weather_failed,
    }

    # ------------------------------------------------------------------
    # Stage 4: Final scoring — sort by risk score descending
    # ------------------------------------------------------------------
    update_status("scoring")
    scored_events.sort(key=lambda x: x[3].score, reverse=True)

    # ------------------------------------------------------------------
    # Stage 5: Summarize top N, save all event packages
    # ------------------------------------------------------------------
    update_status("summarizing", {"top_n": top_n, "total": len(scored_events)})
    saved_dirs: list[str] = []
    for idx, (fire, weather, evidence, risk) in enumerate(scored_events):
        event_id = make_event_id(fire)
        summary = summarize_incident(fire, weather, risk) if idx < top_n else None
        event_dir = save_event_package(event_id, fire, weather, evidence, risk, summary)
        saved_dirs.append(str(event_dir))

    write_daily_report(scored_events)
    write_alerts_report(scored_events)

    # ------------------------------------------------------------------
    # Stage 6: Upload reports to B2 (or local archive fallback)
    # ------------------------------------------------------------------
    update_status("uploading", {"run_id": run_id})
    upload_result = upload_reports(run_id=run_id)

    # ------------------------------------------------------------------
    # Stage 7: Alert check + email via OpenClaw
    # ------------------------------------------------------------------
    update_status("alerting")
    oc_result = run_openclaw(scored_events, upload_result=upload_result, run_id=run_id)

    # ------------------------------------------------------------------
    # Stage 8: Write manifest + mark complete
    # ------------------------------------------------------------------
    high_count = sum(1 for _, _, _, r in scored_events if r.level == "high")
    manifest = {
        "run_id": run_id,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "sources": sources_status,
        "hotspots_raw": raw_count,
        "hotspots_processed": len(scored_events),
        "events_saved": len(saved_dirs),
        "upload": upload_result,
        "alert_triggered": oc_result.get("alert_needed"),
        "email": oc_result.get("email_result"),
        "ops_brief": oc_result.get("ops_brief", ""),
    }
    (REPORTS_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))

    # Final status.log line includes the full manifest for the skill
    update_status("complete", {
        "run_id": run_id,
        "events": len(saved_dirs),
        "high_risk": high_count,
        "alert_triggered": oc_result.get("alert_needed"),
        "upload_storage": upload_result.get("storage"),
        "email_status": (oc_result.get("email_result") or {}).get("status"),
    })

    log.info("Pipeline complete — %d events saved (run_id=%s)", len(saved_dirs), run_id)

    return _build_results_dict(scored_events, saved_dirs, top_n, oc_result, run_id)


def _build_results_dict(
    scored_events: list[tuple],
    saved_dirs: list[str],
    top_n: int,
    oc_result: dict,
    run_id: str,
) -> dict:
    """Build a structured results dict for the OpenClaw skill to present."""
    total = len(scored_events)
    top_incidents = []
    for i in range(min(top_n, total)):
        fire, _, __, risk = scored_events[i]
        top_incidents.append({
            "rank": i + 1,
            "event_id": make_event_id(fire),
            "level": risk.level,
            "score": risk.score,
            "lat": fire.latitude,
            "lon": fire.longitude,
        })

    return {
        "run_id": run_id,
        "total_events": total,
        "high_risk_count": sum(1 for _, _, _, r in scored_events if r.level == "high"),
        "top_incidents": top_incidents,
        "events_dir": str(EVENTS_DIR),
        "alert_triggered": oc_result.get("alert_needed"),
        "upload_result": oc_result.get("upload_result"),
        "email_result": oc_result.get("email_result"),
        "ops_brief": oc_result.get("ops_brief", ""),
    }


# ---------------------------------------------------------------------------
# Async entry point — starts pipeline in background thread
# ---------------------------------------------------------------------------

def run_pipeline_async(
    source: str = "VIIRS_SNPP_NRT",
    days: int = 1,
    bbox: tuple[float, float, float, float] | None = None,
    region: str | None = None,
    top_n: int | None = None,
) -> Path:
    """Start the pipeline in a background thread. Returns path to status.log.

    The caller (OpenClaw skill) polls status.log line by line for progress.
    Each line is a JSON object: {"stage": "...", "ts": "...", "detail": {...}}
    Final line stage is "complete".
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = REPORTS_DIR / "status.log"
    log_path.write_text("")  # Clear previous run log

    t = threading.Thread(
        target=run_pipeline,
        kwargs={"source": source, "days": days, "bbox": bbox, "region": region, "top_n": top_n},
        daemon=False,  # Non-daemon so pipeline finishes even if main thread exits
    )
    t.start()
    return log_path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FireWatch pipeline")
    parser.add_argument(
        "--async", dest="async_mode", action="store_true",
        help="Start in background thread and print status.log path, then exit",
    )
    parser.add_argument("--source", default="VIIRS_SNPP_NRT")
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--region", default=None, help="Named region (socal, norcal, california, us)")
    parser.add_argument("--top-n", type=int, default=None)
    args = parser.parse_args()

    kwargs = {"source": args.source, "days": args.days, "region": args.region, "top_n": args.top_n}

    if args.async_mode:
        log_path = run_pipeline_async(**kwargs)
        print(str(log_path))
        sys.exit(0)

    try:
        run_pipeline(**kwargs)
    except Exception as e:
        log.error("Pipeline failed: %s", e)
        sys.exit(1)
