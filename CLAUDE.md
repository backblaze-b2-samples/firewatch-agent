# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup
pip install -r requirements.txt
cp .env.example .env  # then fill in API keys

# Run the full pipeline
python -m app.main

# Run standalone tools
python -m app.tools.upload_reports [file1 file2 ...]
python -m app.tools.send_alert_email --headline "..." --risk-level high --summary "..." --action "..."
```

`python -m app.main` accepts optional args: `source` (satellite), `days` (1-10), `bbox` (west south east north), `top_n` (incidents to LLM-summarize, default 5).

## Architecture

FireWatch is a batch AI pipeline for wildfire detection and alerting. The flow is linear:

```
NASA FIRMS (satellite CSV)
  → ingest/fires.py          # parse CSV → list[FireEvent]
  → ingest/weather.py        # enrich each fire with Open-Meteo → WeatherContext
  → evidence/snapshots.py    # combine into EvidenceAsset with FIRMS map URL
  → scoring/risk.py          # compute 0-100 risk score → RiskAssessment
  → agent/summarize.py       # top-N events → LLM (Nemotron) → IncidentSummary
  → storage/store.py         # save event package to data/events/{event_id}/
  → storage/reports.py       # write daily_report.md + alerts.md to data/reports/
  → agent/openclaw.py        # post-processing: check alert rules → B2 upload + email
```

### Key Files

- `app/config.py` — all config loaded from env vars; single source of truth
- `app/models.py` — Pydantic models: `FireEvent`, `WeatherContext`, `EvidenceAsset`, `RiskAssessment`, `IncidentSummary`
- `app/agent/prompts.py` — LLM prompt templates (edit here to change AI behavior)
- `app/agent/openclaw.py` — orchestrates post-processing: alert rules, uploads, email, ops brief

### Risk Scoring (`scoring/risk.py`)

Weighted formula: `score = (intensity × 0.4) + (confidence × 0.2) + (weather × 0.4)`
- Intensity: VIIRS brightness (300–500K) + Fire Radiative Power (0–200 MW)
- Confidence: low→20, nominal→50, high→90
- Weather: temperature + wind speed (positive) + humidity (inverse)
- Thresholds: high ≥ 70, medium ≥ 40, low < 40

### LLM Integration

Local Nemotron via OpenAI-compatible API (llama.cpp). Set `MODEL_BASE_URL`, `MODEL_NAME`, `MODEL_API_KEY` in `.env`. If unavailable, pipeline falls back to template-based summaries — it won't crash.

### Alert Triggering

In `openclaw.py`: alert fires if any event has `level == "high"` OR `max(score) >= ALERT_SCORE_THRESHOLD` (default 75). When triggered: uploads reports to Backblaze B2 (boto3/S3-compatible), then sends HTML email via Resend.

### Output Structure

```
data/events/{lat}_{lon}_{date}_{time}/   # one dir per fire event
    fire_event.json, weather.json, evidence.json, risk.json, summary.json, summary.md
data/reports/
    daily_report.md, alerts.md
logs/firewatch.log
```

## Environment Variables

Copy `.env.example` to `.env`. Required for full functionality:
- `NASA_FIRMS_API_KEY` — get at firms.modaps.eosdis.nasa.gov
- `MODEL_BASE_URL` / `MODEL_NAME` / `MODEL_API_KEY` — local Nemotron endpoint
- `B2_BUCKET` / `B2_ENDPOINT` / `B2_ACCESS_KEY` / `B2_SECRET_KEY` — Backblaze B2
- `RESEND_API_KEY` / `RESEND_FROM` / `RESEND_TO` — email alerts
- `ALERT_SCORE_THRESHOLD` — default 75
