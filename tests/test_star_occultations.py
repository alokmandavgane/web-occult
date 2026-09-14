"""Pins the Moon-and-stars pipeline (engine/star_occultations.py).

  * Aldebaran, 2017-01-09, run through the WHOLE monthly pipeline — merged catalogue, day polynomials,
    the vectorised solver the page's JS mirrors — against in-the-sky.org's published disappearance
    times for Jaipur / New Delhi / Silchar (±5 s; they publish whole seconds, mean limb).
  * October 2026: the solver against direct Skyfield topocentric searches at random places (±0.5 s), and the
    renderer's libration / lunar-pole position angle against JPL Horizons (0.02° / 0.3°).

Needs DE431 (OCCULT_DE431, default ../kaalshodh/api/de431t.bsp) — skipped without it.
"""

import importlib.util
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, "..")
DE431 = os.environ.get("OCCULT_DE431") or os.path.join(REPO, "..", "kaalshodh", "api", "de431t.bsp")

pytestmark = pytest.mark.skipif(not os.path.exists(DE431), reason="DE431 not found (set OCCULT_DE431)")


@pytest.fixture(scope="module")
def env():
    spec = importlib.util.spec_from_file_location("star_occultations", os.path.join(REPO, "engine", "star_occultations.py"))
    so = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(so)
    from skyfield.api import load, load_file
    return so, load.timescale(), load_file(so.DE431), so.load_catalog()


def test_aldebaran_2017_through_the_monthly_pipeline(env):
    so, ts, eph, rows = env
    assert so.validate_aldebaran(rows, ts, eph) <= 5.0


@pytest.fixture(scope="module")
def october(env):
    so, ts, eph, rows = env
    return so.build_month("2026-10", rows, ts, eph, log=lambda s: None)


def test_monthly_solver_matches_skyfield(env, october):
    so, ts, eph, rows = env
    d, ids = october
    assert so.validate("2026-10", d, ids, rows, ts, eph, samples=12, seed=7) <= 0.5


# JPL Horizons, Moon from the geocentre, quantities 14 + 17 (fetched 2026-09-14): 12:00 UT on the given day ->
# (ObsSub-LON east-positive, ObsSub-LAT, north-pole position angle). Horizons measures the pole PA from the
# true-of-date north; the month file uses ICRS north, so ~0.2 deg of precession separates them.
HORIZONS_2026_10 = {1: (359.378110, -6.534864, 351.3116), 8: (4.770658, 2.322054, 21.5709),
                    15: (1.512039, 6.283599, 6.0815), 22: (353.987699, -1.659906, 339.0907),
                    29: (0.834256, -5.972094, 355.5112)}


def test_libration_matches_horizons(october):
    d, _ = october
    for day, (lon, lat, pa) in HORIZONS_2026_10.items():
        mlat, mlon, mpa = d["lib"][day]          # segment k is centred on day k at 12:00 UT
        dlon = (mlon - lon + 540) % 360 - 180
        dpa = (mpa - pa + 540) % 360 - 180
        assert abs(dlon) < 0.02 and abs(mlat - lat) < 0.02, (day, mlon, mlat, lon, lat)
        assert abs(dpa) < 0.3, (day, mpa, pa)
