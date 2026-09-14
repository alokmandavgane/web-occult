"""Event pages: when the Moon rises or sets during an occultation, a city sees only one half of it, and the page
must say which. Data files only — no DE431 needed."""
import json
import os
import sys
import zoneinfo

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import build_pages as bp  # noqa: E402


def _row(slug, name):
    d = json.load(open(os.path.join(HERE, "..", "data", f"{slug}.json")))
    return d, next(c for c in d["cities"] if c["name"] == name)


def test_moon_rising_leaves_only_the_reappearance():
    d, c = _row("jupiter-2026-10-06", "Mexico City, MX")      # the Moon rises while Jupiter is behind it
    seen, at = bp.horizon_split(d, c)
    assert seen == "rises" and at["D2"][0] < 0 < at["R1"][0]
    row = bp.city_row(c, d, zoneinfo.ZoneInfo("America/Mexico_City"))
    assert "Moon not yet up" in row and "at reappearance" in row and "below the horizon" not in row
    assert bp.verdict_text(c, d).startswith("reappearance only")


def test_moon_setting_leaves_only_the_disappearance():
    d, c = _row("mars-2026-10-05", "Beijing, CN")             # the Moon sets before Mars comes back
    seen, at = bp.horizon_split(d, c)
    assert seen == "sets" and at["D2"][0] > 0 > at["R1"][0]
    row = bp.city_row(c, d, zoneinfo.ZoneInfo("Asia/Shanghai"))
    assert "Moon has set" in row and "at reappearance" not in row


def test_whole_occultation_is_unchanged():
    d, c = _row("venus-2026-09-14", "Mumbai")
    seen, at = bp.horizon_split(d, c)
    assert seen == "both"
    row = bp.city_row(c, d, zoneinfo.ZoneInfo("Asia/Kolkata"))
    assert "not yet up" not in row and "has set" not in row


def test_element_azimuth_matches_the_generator():
    """The element geometry's Moon azimuth against the generator's Skyfield value at disappearance."""
    d, c = _row("venus-2026-09-14", "Mumbai")
    _, at = bp.horizon_split(d, c)
    assert abs(at["D2"][1] - c["moon_az"]) < 0.3 and abs(at["D2"][0] - c["moon_alt"]) < 0.2
