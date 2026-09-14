"""Pins the occultation generator's contact times.

Two anchors:
  * 2017-01-09, the Moon occults Aldebaran (Rohini) — disappearance times that
    in-the-sky.org published per Indian city, an INDEPENDENT prediction. This
    is the regression guard: any change to the ephemeris, the timescale, the
    limb radius or the search that moves these by more than 5 s is a real
    change in what the pages say.
  * 2026-09-14, the Moon occults Venus — the first published event page. Pinned
    to what the page shipped with, so a regeneration that disagrees is noticed.

Needs DE431 (OCCULT_DE431, default ../kaalshodh/api/de431t.bsp) — skipped without it.
"""

import importlib.util
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, "..")
GEN = os.path.join(REPO, "engine", "occultation_event.py")
DE431 = os.environ.get("OCCULT_DE431") or os.path.join(REPO, "..", "kaalshodh", "api", "de431t.bsp")

pytestmark = pytest.mark.skipif(not os.path.exists(DE431), reason="DE431 not found (set OCCULT_DE431)")


@pytest.fixture(scope="module")
def oe():
    spec = importlib.util.spec_from_file_location("occultation_event", GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def sky(oe):
    ts = oe.load.timescale()
    eph = oe.load_file(oe.EPHEMERIS_FILE)
    return ts, eph, eph["earth"], eph["moon"]


def _secs(iso_a, iso_b):
    from datetime import datetime
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return abs((datetime.strptime(iso_a, fmt) - datetime.strptime(iso_b, fmt)).total_seconds())


# in-the-sky.org, "Lunar occultation of Aldebaran", 9 Jan 2017 — disappearance, IST -> UTC
ALDEBARAN_2017 = {
    "Jaipur": ((26.9124, 75.7873), "2017-01-09T12:56:22Z"),
    "New Delhi": ((28.6139, 77.2090), "2017-01-09T13:00:09Z"),
    "Silchar": ((24.8333, 92.7789), "2017-01-09T13:26:29Z"),
}


def test_aldebaran_2017_matches_independent_predictions(oe, sky):
    ts, eph, earth, moon = sky
    target = oe.Target("aldebaran", eph)
    t_min, sep = oe.geocentric_min(ts, earth, moon, target, ts.utc(2017, 1, 8), ts.utc(2017, 1, 11))
    assert sep < 1.0
    for city, ((lat, lon), published_d) in ALDEBARAN_2017.items():
        row = oe.local_circumstances(ts, eph, earth, moon, target, t_min, lat, lon)
        assert row["verdict"] == "visible", city
        # a star has no disc: the search reports D2/R1 straight from state 0 -> 2. in-the-sky.org
        # predicts for the mean limb, so compare the mean-limb contacts; the LOLA-refined ones may
        # legitimately differ by a few seconds.
        assert _secs(row["contacts_mean_limb"]["D2"], published_d) <= 5, (city, row["contacts_mean_limb"])
        assert _secs(row["contacts"]["D2"], published_d) <= 30, (city, row["contacts"])


# what /occultation/venus-2026-09-14 shipped with
VENUS_2026 = {
    "Mumbai": ((19.0760, 72.8777), {"D2": "2026-09-14T11:43:44Z", "R1": "2026-09-14T12:45:15Z"}),
    "Kolkata": ((22.5726, 88.3639), {"D2": "2026-09-14T12:23:44Z", "R1": "2026-09-14T12:54:24Z"}),
}


def test_venus_2026_page_values(oe, sky):
    ts, eph, earth, moon = sky
    target = oe.Target("venus", eph)
    t_min, sep = oe.geocentric_min(ts, earth, moon, target, ts.utc(2026, 9, 13), ts.utc(2026, 9, 16))
    assert abs(sep - 0.4803) < 0.001
    for city, ((lat, lon), pinned) in VENUS_2026.items():
        row = oe.local_circumstances(ts, eph, earth, moon, target, t_min, lat, lon)
        for k, v in pinned.items():
            assert _secs(row["contacts_mean_limb"][k], v) <= 5, (city, k, row["contacts_mean_limb"])
    # Delhi sits ~2' outside the north limit: the page's headline claim
    delhi = oe.local_circumstances(ts, eph, earth, moon, target, t_min, 28.6139, 77.2090)
    assert delhi["verdict"] == "miss"
    assert 1.0 < delhi["sep_arcmin"] - delhi["moon_sd_arcmin"] < 3.0
