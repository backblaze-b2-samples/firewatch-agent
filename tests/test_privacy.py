from app.privacy import coarse_location, redact_coordinate_pairs


def test_redacts_parenthesized_coordinate_pair():
    text = "Top incident at (34.1234, -118.5678)."

    assert redact_coordinate_pairs(text) == "Top incident at [coordinates redacted]."


def test_redacts_bare_coordinate_pair():
    text = "Top incident at 34.1234, -118.5678."

    assert redact_coordinate_pairs(text) == "Top incident at [coordinates redacted]."


def test_coarse_location_avoids_exact_precision():
    assert coarse_location(34.1234, -118.5678) == "34.12, -118.57 (coarse)"
