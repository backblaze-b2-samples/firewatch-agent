# FireWatch Agent

> **NVIDIA Hack for Impact — Eco Impact Track | OpenClaw Bounty**

FireWatch is an AI-powered wildfire detection, risk assessment, and automated alert pipeline. It ingests real-time satellite hotspot data, enriches it with live weather, scores each fire on an explainable 0–100 risk scale, generates natural-language incident summaries via a local **Nemotron** LLM, and dispatches stakeholder alerts — all orchestrated by the **OpenClaw** post-processing agent.

---

## What It Does

1. **Pulls live satellite hotspots** from NASA FIRMS (VIIRS/MODIS) for a configurable region and time window
2. **Enriches each detection** with real-time weather (temperature, wind speed, humidity) from Open-Meteo
3. **Scores every event** on a transparent 0–100 risk scale with human-readable factor explanations
4. **Summarizes top incidents** in plain language using a locally-hosted Nemotron model
5. **Publishes structured reports** — a full daily digest and a filtered alerts view
6. **Triggers automated alerts** when risk thresholds are exceeded: uploads reports to Backblaze B2 and sends HTML email via Resend
7. **Generates an operational brief** via OpenClaw summarizing what happened, what was done, and what responders should do next

---

## Services & Integrations

| Service | Role |
|---------|------|
| **NASA FIRMS** | Real-time satellite fire hotspot data (VIIRS SNPP/NOAA-20, MODIS) |
| **Open-Meteo** | Free weather API — temperature, wind speed/direction, humidity at fire coordinates |
| **Nemotron (local LLM)** | NVIDIA's Nemotron model served via llama.cpp OpenAI-compatible API; generates incident summaries and the ops brief |
| **OpenClaw** | Post-processing agent that applies alert rules, coordinates uploads/email, and synthesizes the final operational brief |
| **Backblaze B2** | S3-compatible object storage for published reports (with public URLs for email links) |
| **Resend** | Transactional email delivery for stakeholder alert notifications |

---

## Pipeline Architecture

```
NASA FIRMS (satellite CSV)
        │
        ▼
  ingest/fires.py          Fetch & parse hotspots → list[FireEvent]
        │
        ▼
  [Pre-filter]             Top N by confidence × brightness (before API calls)
        │
        ▼
  ingest/weather.py        Enrich each fire with Open-Meteo → WeatherContext
        │
        ▼
  evidence/snapshots.py    Build EvidenceAsset (coords, metadata, FIRMS map URL)
        │
        ▼
  scoring/risk.py          Compute 0–100 risk score → RiskAssessment
        │
        ▼
  agent/summarize.py       Top-N → Nemotron LLM → IncidentSummary (headline, summary, action)
        │
        ▼
  storage/store.py         Persist event packages to data/events/{event_id}/
  storage/reports.py       Write daily_report.md + alerts.md
        │
        ▼
  tools/upload_reports.py  Upload reports to Backblaze B2 (falls back to local archive)
        │
        ▼
  agent/openclaw.py        Check alert rules → send email → generate ops brief
```

Each stage writes progress to `data/reports/status.log` (NDJSON) so the pipeline can be run asynchronously and polled by the OpenClaw Claude Code skill.

---

## Risk Scoring

Scores are computed from three weighted components — no black box:

| Component | Weight | Signal |
|-----------|--------|--------|
| Fire intensity | 40% | VIIRS brightness (300–500 K) + Fire Radiative Power (0–200 MW) |
| Detection confidence | 20% | FIRMS confidence: low → 20, nominal → 50, high → 90 |
| Weather conditions | 40% | Temperature (20–45 °C), wind speed (0–50 km/h), humidity (inverted) |

**Risk levels:** `high` ≥ 70 · `medium` ≥ 40 · `low` < 40

Each `RiskAssessment` includes a `factors[]` list explaining *why* the score is what it is (e.g., `"Strong winds (38 km/h)"`, `"Very low humidity (12%)"`, `"High detection confidence"`).

---

## How OpenClaw Works

OpenClaw is the intelligent post-processing agent that runs after the main pipeline completes. It acts as the decision layer between raw analysis and real-world action.

**Workflow:**

1. **Alert rule evaluation** — checks if any event has `level == "high"` OR `score >= ALERT_SCORE_THRESHOLD` (default 50 for demo, 75 in production)
2. **Report upload** — if alert triggered, sends `daily_report.md` and `alerts.md` to Backblaze B2; falls back to local archive if B2 is not configured
3. **Email dispatch** — sends a color-coded HTML alert email via Resend to configured recipients, including the headline, risk level, summary, recommended action, and a link to the published report
4. **Ops brief generation** — calls Nemotron with full context (event counts, top incident details, what actions were taken) to produce a concise, actionable operational brief for first responders; falls back to a template if the LLM is unreachable

OpenClaw is designed to be **resilient**: every external service call has a fallback path. If B2 is not configured, reports are archived locally. If Resend is not configured, the email is saved to `data/alerts/`. If Nemotron is down, a deterministic template is used. The pipeline never crashes on a missing integration.

---

## UX — What Users See

FireWatch is designed to be operated as a Claude Code skill (run `python -m app.main` or trigger it from the OpenClaw Claude Code integration):

- **During the run**: Stage-by-stage progress is streamed (`fetching → pre_filtering → enriching → scoring → summarizing → uploading → alerting → complete`)
- **After the run**: A structured results dict is returned with ranked incidents, risk levels, scores, alert status, and the ops brief
- **Alert email**: HTML email with color-coded risk level (red/amber/green), the AI-generated headline and summary, recommended action, and a link to the full report on B2
- **Reports in `data/reports/`**:
  - `daily_report.md` — all events ranked by risk with weather context
  - `alerts.md` — filtered view of high-risk incidents only
  - `manifest.json` — machine-readable run summary (sources, counts, upload URLs, email status)

---

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# Fill in NASA_FIRMS_API_KEY (required) and optionally B2/Resend/Nemotron credentials
```

**Run:**
```bash
python -m app.main                         # Sync run, continental US default
python -m app.main --region socal          # Southern California
python -m app.main --region california --days 3 --top-n 10
python -m app.main --async                 # Background thread; prints status.log path
```

**Standalone tools:**
```bash
python -m app.tools.upload_reports [file1 file2 ...]
python -m app.tools.send_alert_email --headline "..." --risk-level high --summary "..." --action "..."
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `NASA_FIRMS_API_KEY` | Yes | Get at [firms.modaps.eosdis.nasa.gov](https://firms.modaps.eosdis.nasa.gov/api/area/) |
| `MODEL_BASE_URL` | For LLM | Local Nemotron endpoint (e.g., `http://localhost:30000/v1`) |
| `MODEL_NAME` | For LLM | Model name (e.g., `nemotron`) |
| `ALERT_SCORE_THRESHOLD` | No | Default `50` (demo) / `75` (production) |
| `B2_BUCKET` / `B2_ENDPOINT` / `B2_ACCESS_KEY` / `B2_SECRET_KEY` | For cloud upload | Backblaze B2 credentials |
| `RESEND_API_KEY` / `RESEND_FROM` / `RESEND_TO` | For email | Resend delivery credentials |
| `DEFAULT_REGION` | No | `socal` \| `norcal` \| `california` \| `us` |

---

## Output Structure

```
data/
├── events/{lat}_{lon}_{date}_{time}/
│   ├── fire_event.json      # Raw satellite detection
│   ├── weather.json         # Weather context at fire location
│   ├── evidence.json        # Combined metadata + FIRMS map URL
│   ├── risk.json            # Risk score, level, and factor explanations
│   ├── summary.json         # Nemotron-generated incident summary
│   └── summary.md           # Human-readable markdown
└── reports/
    ├── daily_report.md      # All events ranked by risk
    ├── alerts.md            # High-risk incidents only
    ├── manifest.json        # Run metadata and action results
    └── status.log           # NDJSON pipeline progress (for async polling)
```
