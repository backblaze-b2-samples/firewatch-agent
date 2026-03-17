"""Pull fire hotspot data from NASA FIRMS API."""

import logging
import requests

from app.config import NASA_FIRMS_API_KEY, FIRE_SOURCE_URL, REQUEST_TIMEOUT_SECONDS, DEFAULT_REGION
from app.models import FireEvent

log = logging.getLogger("firewatch")

# Named region presets — (west, south, east, north)
REGION_PRESETS: dict[str, tuple[float, float, float, float]] = {
    "socal":      (-119.5, 33.5, -117.0, 35.0),
    "norcal":     (-123.0, 37.0, -120.0, 40.5),
    "california": (-124.5, 32.5, -114.0, 42.0),
    "us":         (-125.0, 24.0,  -66.0, 50.0),
}


def fetch_fires(
    source: str = "VIIRS_SNPP_NRT",
    days: int = 1,
    bbox: tuple[float, float, float, float] | None = None,
    region: str | None = None,
) -> list[FireEvent]:
    """Fetch active fire hotspots from NASA FIRMS.

    Args:
        source: Satellite source (VIIRS_SNPP_NRT, MODIS_NRT, etc.)
        days:   Days of hotspot history (1-10).
        bbox:   Explicit (west, south, east, north) — takes priority over region.
        region: Named region key from REGION_PRESETS (e.g. "socal"). Falls back
                to DEFAULT_REGION if neither bbox nor region is given.

    Returns:
        List of FireEvent models.
    """
    if not NASA_FIRMS_API_KEY:
        raise ValueError(
            "NASA_FIRMS_API_KEY required — get one at "
            "https://firms.modaps.eosdis.nasa.gov/api/area/"
        )

    # Resolve bounding box: explicit > named region > env default
    resolved_bbox = bbox or _resolve_region(region or DEFAULT_REGION)
    west, south, east, north = resolved_bbox
    area = f"{west},{south},{east},{north}"
    url = f"{FIRE_SOURCE_URL}/{NASA_FIRMS_API_KEY}/{source}/{area}/{days}"

    log.info(
        "Fetching hotspots from FIRMS (%s, %d day(s), bbox=%s)",
        source, days, area,
    )
    resp = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    resp.raise_for_status()

    return _parse_csv(resp.text, source)


def _resolve_region(region: str) -> tuple[float, float, float, float]:
    """Look up a region name in REGION_PRESETS. Falls back to 'us' if unknown."""
    key = region.lower().strip()
    if key not in REGION_PRESETS:
        log.warning("Unknown region '%s' — falling back to 'us'", region)
        return REGION_PRESETS["us"]
    return REGION_PRESETS[key]


def _parse_csv(csv_text: str, source: str) -> list[FireEvent]:
    """Parse FIRMS CSV into FireEvent list."""
    lines = csv_text.strip().splitlines()
    if len(lines) < 2:
        return []

    headers = [h.strip() for h in lines[0].split(",")]
    events: list[FireEvent] = []

    for line in lines[1:]:
        values = line.split(",")
        row = dict(zip(headers, values))

        try:
            events.append(FireEvent(
                latitude=float(row.get("latitude", 0)),
                longitude=float(row.get("longitude", 0)),
                brightness=float(row.get("bright_ti4", row.get("brightness", 0))),
                confidence=row.get("confidence", "unknown"),
                acq_date=row.get("acq_date", ""),
                acq_time=row.get("acq_time", ""),
                satellite=row.get("satellite", source),
                frp=float(row.get("frp", 0)),
            ))
        except (ValueError, TypeError) as e:
            log.warning("Skipping malformed hotspot row: %s", e)

    return events
