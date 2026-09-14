"""Great Red Spot transits: when the GRS crosses Jupiter's central meridian, seen from Earth.

The central meridian in System II comes from DE431 and the IAU pole: the sub-Earth point at the
light-time-corrected instant, measured from the equator's ascending node, against
W_II = 43.3° + 870.270°/day (Explanatory Supplement; days TDB from J2000). The GRS is not
ephemeris — it drifts in System II, so its longitude is an *observed* value (catalog/grs.json:
longitude at a reference date and a drift per month, with the source), extrapolated no further
than that file's `valid_until`. Transit times are then as good as that longitude: 1° is 1.65 min.

    python engine/grs_transits.py                 # writes data/jupiter-grs.json
    python engine/grs_transits.py --check T1 T2…  # implied GRS longitude at given UTC transit times

Output: transits [epoch_s, jup_ra, jup_dec, sun_ra, sun_dec] (apparent geocentric degrees, what the
page needs to place a transit in someone's sky) and the central meridian at every 00:00 UTC, which
the diagram interpolates to draw the spot on the disc.
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
from skyfield.api import load, load_file

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ephem_paths import DE431, require_de431  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "catalog" / "grs.json"
OUT = REPO / "data" / "jupiter-grs.json"
POLE = (268.056595, -0.006499, 64.495303, 0.002413)   # IAU 2015 Jupiter pole: RA0, dRA/T, Dec0, dDec/T
W0, WDOT = 43.3, 870.270                              # System II
DAY = 86400.0


class CentralMeridian:
    def __init__(self):
        self.ts = load.timescale()
        require_de431()
        self.eph = load_file(DE431)
        self.earth, self.jup, self.sun = self.eph["earth"], self.eph["jupiter barycenter"], self.eph["sun"]

    def cm2(self, t):
        """System II longitude of the central meridian at Time(s) t, degrees."""
        a = self.earth.at(t).observe(self.jup)
        v = -a.position.au                                  # Jupiter -> Earth, ICRF
        d = t.tdb - a.light_time - 2451545.0                # rotation at emission
        T = d / 36525.0
        ra, dec = np.radians(POLE[0] + POLE[1] * T), np.radians(POLE[2] + POLE[3] * T)
        P = np.array([np.cos(dec) * np.cos(ra), np.cos(dec) * np.sin(ra), np.sin(dec)])
        Q = np.array([-np.sin(ra), np.cos(ra), np.zeros_like(ra)])       # equator's ascending node on the ICRF equator
        R = np.cross(P, Q, axis=0)
        ang = np.degrees(np.arctan2(np.sum(v * R, axis=0), np.sum(v * Q, axis=0)))
        return (W0 + WDOT * d - ang) % 360.0

    def radec(self, t):
        e = self.earth.at(t)
        jr, jd, _ = e.observe(self.jup).apparent().radec()
        sr, sd, _ = e.observe(self.sun).apparent().radec()
        return jr._degrees, jd.degrees, sr._degrees, sd.degrees


def grs_lon(cfg, epoch_s):
    ref = dt.datetime.fromisoformat(cfg["date"]).replace(tzinfo=dt.timezone.utc).timestamp()
    return (cfg["lon_II"] + cfg["drift_deg_per_month"] * (epoch_s - ref) / (30.436875 * DAY)) % 360.0


def transits(cm, cfg, s0, s1, step=1800.0):
    """Epoch seconds when CM_II(t) = GRS longitude(t), between s0 and s1."""
    s = np.arange(s0, s1 + step, step)
    f = lambda secs: (cm.cm2(cm.ts.from_datetimes([dt.datetime.fromtimestamp(x, dt.timezone.utc) for x in secs]))
                      - grs_lon(cfg, np.asarray(secs)) + 180.0) % 360.0 - 180.0
    y = f(s)
    idx = np.where((y[:-1] < 0) & (y[1:] >= 0) & (y[1:] - y[:-1] < 90))[0]
    t = s[idx] - y[idx] * step / (y[idx + 1] - y[idx])        # linear: CM runs at a near-constant 18°/30 min
    for _ in range(2):                                       # two Newton steps on the real function
        t = t - f(t) / (WDOT / DAY)
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", nargs="*", help="UTC times 'YYYY-MM-DD HH:MM' of published transits")
    a = ap.parse_args()
    cfg = json.loads(CONFIG.read_text())
    cm = CentralMeridian()
    if a.check:
        for x in a.check:
            d = dt.datetime.strptime(x, "%Y-%m-%d %H:%M").replace(tzinfo=dt.timezone.utc)
            v = float(cm.cm2(cm.ts.from_datetime(d)))
            print(f"{x}  CM II {v:7.2f}   model GRS {grs_lon(cfg, d.timestamp()):7.2f}")
        return
    s0 = dt.datetime.fromisoformat(cfg["from"]).replace(tzinfo=dt.timezone.utc).timestamp()
    s1 = (dt.datetime.fromisoformat(cfg["valid_until"]) + dt.timedelta(days=1)).replace(tzinfo=dt.timezone.utc).timestamp()
    tt = transits(cm, cfg, s0, s1)
    tm = cm.ts.from_datetimes([dt.datetime.fromtimestamp(x, dt.timezone.utc) for x in tt])
    jr, jd, sr, sd = cm.radec(tm)
    days = np.arange(s0, s1 + DAY, DAY)
    cmd = cm.cm2(cm.ts.from_datetimes([dt.datetime.fromtimestamp(x, dt.timezone.utc) for x in days]))
    OUT.write_text(json.dumps({
        "schema": 1,
        "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "engine": {"ephemeris": "de431t.bsp", "system_II": [W0, WDOT], "pole": POLE},
        "grs": cfg,
        "transits": [[int(round(t)), round(float(a), 4), round(float(b), 4), round(float(c), 3), round(float(e), 3)]
                     for t, a, b, c, e in zip(tt, jr, jd, sr, sd)],
        "cm_daily": {"t0": int(s0), "values": [round(float(v), 2) for v in cmd]},
    }, separators=(",", ":")))
    print(f"wrote {OUT.relative_to(REPO)}: {len(tt)} transits {cfg['from']} .. {cfg['valid_until']}")


if __name__ == "__main__":
    main()
