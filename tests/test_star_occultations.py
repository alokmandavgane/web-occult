"""Pins the Moon-and-stars pipeline (engine/star_occultations.py).

  * Aldebaran, 2017-01-09, run through the WHOLE monthly pipeline — merged catalogue, day polynomials,
    the vectorised solver the page's JS mirrors — against in-the-sky.org's published disappearance
    times for Jaipur / New Delhi / Silchar (±5 s; they publish whole seconds, mean limb).
  * October 2026: the solver against direct Skyfield topocentric searches at random places (±0.5 s).

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


def test_monthly_solver_matches_skyfield(env):
    so, ts, eph, rows = env
    d, ids = so.build_month("2026-10", rows, ts, eph, log=lambda s: None)
    assert so.validate("2026-10", d, ids, rows, ts, eph, samples=12, seed=7) <= 0.5
