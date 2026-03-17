"""Centralized configuration loaded from environment variables."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Project root (two levels up from this file)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# LLM endpoint (local Nemotron via llama.cpp)
MODEL_BASE_URL: str = os.getenv("MODEL_BASE_URL", "http://localhost:30000/v1")
MODEL_NAME: str = os.getenv("MODEL_NAME", "nemotron")
MODEL_API_KEY: str = os.getenv("MODEL_API_KEY", "dummy")

# Default geographic region for fire detection (matched against REGION_PRESETS in fires.py)
DEFAULT_REGION: str = os.getenv("DEFAULT_REGION", "socal")

# Data sources
FIRE_SOURCE_URL: str = os.getenv(
    "FIRE_SOURCE_URL", "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
)
NASA_FIRMS_API_KEY: str = os.getenv("NASA_FIRMS_API_KEY", "")
WEATHER_SOURCE_BASE_URL: str = os.getenv(
    "WEATHER_SOURCE_BASE_URL", "https://api.open-meteo.com/v1/forecast"
)

# Storage paths
EVENTS_DIR: Path = PROJECT_ROOT / os.getenv("EVENTS_DIR", "data/events")
RAW_DIR: Path = PROJECT_ROOT / os.getenv("RAW_DIR", "data/raw")

# Pipeline settings
TOP_N_EVENTS: int = int(os.getenv("TOP_N_EVENTS", "5"))
REQUEST_TIMEOUT_SECONDS: int = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))
# Cap raw hotspots before expensive enrichment (sorted by confidence × brightness)
PREFILTER_LIMIT: int = int(os.getenv("PREFILTER_LIMIT", "100"))

# Reports output directory
REPORTS_DIR: Path = PROJECT_ROOT / os.getenv("REPORTS_DIR", "data/reports")

# Alert threshold — send if any incident is high OR top score >= this
ALERT_SCORE_THRESHOLD: int = int(os.getenv("ALERT_SCORE_THRESHOLD", "75"))

# Backblaze B2 (S3-compatible)
B2_BUCKET: str = os.getenv("B2_BUCKET", "")
B2_ENDPOINT: str = os.getenv("B2_ENDPOINT", "")
B2_ACCESS_KEY: str = os.getenv("B2_ACCESS_KEY", "")
B2_SECRET_KEY: str = os.getenv("B2_SECRET_KEY", "")
B2_PUBLIC_BASE_URL: str = os.getenv("B2_PUBLIC_BASE_URL", "")

# Resend email delivery
RESEND_API_KEY: str = os.getenv("RESEND_API_KEY", "")
RESEND_FROM: str = os.getenv("RESEND_FROM", "")
RESEND_TO: str = os.getenv("RESEND_TO", "")

# Fallback storage paths (used when B2/Resend unavailable)
LOCAL_ARCHIVE_DIR: Path = REPORTS_DIR / "local_archive"
ALERTS_DIR: Path = PROJECT_ROOT / os.getenv("ALERTS_DIR", "data/alerts")
