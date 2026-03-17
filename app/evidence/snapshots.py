"""Build evidence metadata records for fire events."""

from app.models import FireEvent, WeatherContext, EvidenceAsset


def build_evidence(event: FireEvent, weather: WeatherContext) -> EvidenceAsset:
    """Create an evidence metadata record for one fire event.

    MVP: stores metadata and a FIRMS source URL — no image downloads.
    """
    source_url = (
        f"https://firms.modaps.eosdis.nasa.gov/map/"
        f"#d:24hrs;l:fires_viirs_snpp;@{event.longitude},{event.latitude},12z"
    )

    return EvidenceAsset(
        source="NASA FIRMS",
        source_url=source_url,
        latitude=event.latitude,
        longitude=event.longitude,
        brightness=event.brightness,
        confidence=event.confidence,
        frp=event.frp,
        acq_date=event.acq_date,
        acq_time=event.acq_time,
        weather=weather,
    )
