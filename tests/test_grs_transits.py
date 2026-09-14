"""The Great Red Spot's central meridian: geometry pinned against JPL Horizons.

Horizons publishes Jupiter's sub-Earth longitude in System III (ObsSub-LON, target 599, geocentric).
The engine's System II central meridian is the same geometry with System II's rotation constants,
so checking it with System III's constants pins the pole, node, sign and light time.
"""
import datetime as dt
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))
import ephem_paths  # noqa: E402

pytestmark = pytest.mark.skipif(not os.path.exists(ephem_paths.DE431), reason="needs de431t.bsp")

# JPL Horizons, 2026-09-14 query: COMMAND=599 CENTER=500@399 QUANTITIES=14, ObsSub-LON (System III, deg)
HORIZONS_SYS_III = {
    "2026-09-01 06:17": 32.640999,
    "2026-09-12 06:17": 246.694183,
    "2026-09-23 06:17": 100.971019,
    "2026-10-04 06:17": 315.492811,
}


@pytest.fixture(scope="module")
def cm():
    import grs_transits
    return grs_transits, grs_transits.CentralMeridian()


def test_system_iii_matches_horizons(cm, monkeypatch):
    G, c = cm
    monkeypatch.setattr(G, "W0", 284.95)
    monkeypatch.setattr(G, "WDOT", 870.5360000)
    for s, want in HORIZONS_SYS_III.items():
        t = c.ts.from_datetime(dt.datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=dt.timezone.utc))
        got = float(c.cm2(t))
        assert abs((got - want + 180) % 360 - 180) < 0.01, (s, got, want)


def test_transit_solver_lands_on_the_spot(cm):
    G, c = cm
    cfg = {"lon_II": 91.0, "date": "2026-06-01", "drift_deg_per_month": 1.75}
    s0 = dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc).timestamp()
    tt = G.transits(c, cfg, s0, s0 + 3 * 86400)
    assert 6 <= len(tt) <= 8                                   # one every 9 h 55.5 min
    gaps = [b - a for a, b in zip(tt, tt[1:])]
    assert all(abs(g - 35729) < 60 for g in gaps), gaps
    for t in tt:
        tm = c.ts.from_datetime(dt.datetime.fromtimestamp(t, dt.timezone.utc))
        off = (float(c.cm2(tm)) - G.grs_lon(cfg, t) + 180) % 360 - 180
        assert abs(off) < 0.05, (t, off)                        # 0.05° = 5 s
