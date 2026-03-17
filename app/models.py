"""Typed data models for the FireWatch pipeline."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class FireEvent(BaseModel):
    """A single wildfire hotspot detection."""
    latitude: float
    longitude: float
    brightness: float = 0.0
    confidence: str = "unknown"
    acq_date: str = ""
    acq_time: str = ""
    satellite: str = "unknown"
    frp: float = 0.0  # fire radiative power (MW)


class WeatherContext(BaseModel):
    """Weather conditions at a fire location."""
    temperature_c: Optional[float] = None
    windspeed_kmh: Optional[float] = None
    wind_direction_deg: Optional[float] = None
    humidity_pct: Optional[float] = None
    error: Optional[str] = None


class EvidenceAsset(BaseModel):
    """Metadata record for one piece of fire evidence."""
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    source: str = "NASA FIRMS"
    source_url: Optional[str] = None
    latitude: float = 0.0
    longitude: float = 0.0
    brightness: Optional[float] = None
    confidence: Optional[str] = None
    frp: Optional[float] = None
    acq_date: Optional[str] = None
    acq_time: Optional[str] = None
    weather: Optional[WeatherContext] = None


class RiskAssessment(BaseModel):
    """Explainable risk score for a fire event."""
    score: float = 0.0
    level: str = "low"  # low / medium / high
    factors: list[str] = Field(default_factory=list)


class IncidentSummary(BaseModel):
    """LLM-generated summary of a fire incident."""
    headline: str = ""
    summary: str = ""
    recommended_action: str = ""
    reasoning: str = ""
