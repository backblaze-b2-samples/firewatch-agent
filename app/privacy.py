"""Helpers for avoiding precise location data in persisted text."""

import re


_COORDINATE_PAIR_RE = re.compile(
    r"(?P<open>\(?)"
    r"(?P<lat>[+-]?(?:[0-8]?\d(?:\.\d+)?|90(?:\.0+)?))"
    r"\s*,\s*"
    r"(?P<lon>[+-]?(?:1[0-7]\d(?:\.\d+)?|[0-9]?\d(?:\.\d+)?|180(?:\.0+)?))"
    r"(?P<close>\)?)"
)


def coarse_location(latitude: float, longitude: float) -> str:
    """Return a coarse location string suitable for persisted markdown."""
    return f"{latitude:.2f}, {longitude:.2f} (coarse)"


def redact_coordinate_pairs(text: str) -> str:
    """Replace coordinate pairs in text, with or without parentheses."""
    return _COORDINATE_PAIR_RE.sub("[coordinates redacted]", text)
