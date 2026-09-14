"""
Phenomena of the major moons of Jupiter (jup365.bsp) and Saturn (sat441.bsp), from DE431 +
the JPL satellite kernels — for occult.alokm.com.

Four classical phenomena per moon, each with its contacts (D1 first touch, D2 fully
in, R1 first out, R2 fully out), plus the mutual events between moons:

  occultation   the moon passes behind Jupiter's disc          (seen from Earth)
  transit       the moon passes in front of the disc           (seen from Earth)
  eclipse       the moon enters Jupiter's shadow               (Sun-side geometry)
  shadow        the moon's shadow crosses the visible disc     (both)
  mutual        one moon occults another / casts its shadow on another

Everything is GEOCENTRIC: Jupiter and its moons sit at the same distance, so
parallax moves them together and each event has one UTC time for the whole Earth.
A location only decides whether Jupiter is up and the sky dark, which the site
computes from the RA/Dec stored with each event.

Jupiter is an oblate spheroid (71492 x 66854 km) with the IAU pole; its shadow
is a converging cone. Light-time is handled per body by Skyfield for the
Earth-side geometry, and Sun-side geometry is evaluated at each moon's own
emission time. Moons are uniform discs.

Saturn's rings are NOT modelled: a moon "behind Saturn" here means behind the globe; near the
2025 equinox the rings are nearly edge-on, which is exactly when these events happen.

Usage (from the repo root):  .venv/bin/python engine/satellite_events.py 2026 [--planet saturn] [--months 10-12] [--config]
Writes data/<planet>-moons-<year>.json. Kernels: ephemeris/jup365.bsp, ephemeris/sat441.bsp; DE431 from OCCULT_DE431.
"""

import argparse
import datetime as dt
import json
import os
import sys

import numpy as np
from skyfield.api import load, load_file

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SITE_DIR = REPO
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ephem_paths import DE431, EPHEM_DIR  # noqa: E402

R_SUN = 695700.0
STEP_MIN = 2.0          # scan step; the shortest contact-to-contact gap (Io's ingress) is ~3 min

PLANETS = {
    "jupiter": dict(kernel="jup365.bsp", a=71492.0, c=66854.0,
                    pole=(268.056595, -0.006499, 64.495303, 0.002413),        # IAU 2015: RA0, dRA/T, Dec0, dDec/T
                    moons={"io": 1821.6, "europa": 1560.8, "ganymede": 2631.2, "callisto": 2410.3},
                    mag={"io": 5.0, "europa": 5.3, "ganymede": 4.6, "callisto": 5.7},
                    mutual_min_radius=0),
    "saturn": dict(kernel="sat441.bsp", a=60268.0, c=54364.0,
                   pole=(40.589, -0.036, 83.537, -0.004),
                   moons={"mimas": 198.2, "enceladus": 252.1, "tethys": 531.1, "dione": 561.4,
                          "rhea": 763.8, "titan": 2574.7, "iapetus": 734.5},
                   mag={"mimas": 12.9, "enceladus": 11.7, "tethys": 10.2, "dione": 10.4, "rhea": 9.7, "titan": 8.4, "iapetus": 11.0},
                   mutual_min_radius=250),   # mutual events among the moons big enough to matter (no Mimas)
}
# module-level planet constants, set by configure(); the geometry reads them by name
PLANET = "jupiter"
JUP_A, JUP_C = 71492.0, 66854.0
POLE = PLANETS["jupiter"]["pole"]
MOONS = dict(PLANETS["jupiter"]["moons"])
MAG = dict(PLANETS["jupiter"]["mag"])
JUP = os.path.join(EPHEM_DIR, "jup365.bsp")


def configure(planet):
    global PLANET, JUP_A, JUP_C, POLE, MOONS, MAG, JUP
    P = PLANETS[planet]
    PLANET, JUP_A, JUP_C, POLE = planet, P["a"], P["c"], P["pole"]
    MOONS, MAG = dict(P["moons"]), dict(P["mag"])
    JUP = os.path.join(EPHEM_DIR, P["kernel"])

# --- IAU pole of the planet (ICRF), slow drift kept -----------------------------------

def jupiter_pole(t):
    T = (t.tt - 2451545.0) / 36525.0
    ra = np.radians(POLE[0] + POLE[1] * T)
    dec = np.radians(POLE[2] + POLE[3] * T)
    return np.array([np.cos(dec) * np.cos(ra), np.cos(dec) * np.sin(ra), np.sin(dec)])


def _unit(v):
    return v / np.linalg.norm(v, axis=0)


def silhouette_radius(s, axis, pole):
    """Radius (km) of Jupiter's silhouette in the direction of the in-plane offset s, when
    viewed along `axis`: an ellipse with semi-axes a (equatorial) and
    b = sqrt(a^2 sin^2(beta) + c^2 cos^2(beta)), beta = sub-observer latitude."""
    pa = np.sum(pole * axis, axis=0)
    beta = np.arcsin(np.clip(np.abs(pa), 0, 1))
    b = np.sqrt(JUP_A ** 2 * np.sin(beta) ** 2 + JUP_C ** 2 * np.cos(beta) ** 2)
    e2 = pole - pa * axis                       # projected pole, in the plane
    e2n = np.linalg.norm(e2, axis=0)
    e2 = np.where(e2n > 1e-9, e2 / np.where(e2n > 1e-9, e2n, 1), 0.0)
    sn = np.linalg.norm(s, axis=0)
    cosphi = np.where(sn > 0, np.sum(s * e2, axis=0) / np.where(sn > 0, sn, 1), 0.0)   # along projected pole
    sinphi2 = 1 - cosphi ** 2
    return 1.0 / np.sqrt(sinphi2 / JUP_A ** 2 + cosphi ** 2 / b ** 2)


class Geometry:
    def __init__(self):
        self.ts = load.timescale()
        self.eph = load_file(DE431)
        self.jup = load_file(JUP)
        self.earth, self.sun = self.eph["earth"], self.eph["sun"]
        self.jupiter = self.jup[PLANET]
        self.moon = {k: self.jup[k] for k in MOONS}

    # ---- Earth-side: occultation (+) / transit (-) ------------------------------------
    def sky(self, t, key):
        """Signed margin (km) of the moon's centre from Jupiter's limb in the sky plane,
        negative = inside the silhouette; plus behind (True) / in front."""
        e = self.earth.at(t)
        J = e.observe(self.jupiter).apparent().position.km
        M = e.observe(self.moon[key]).apparent().position.km
        dJ, dM = np.linalg.norm(J, axis=0), np.linalg.norm(M, axis=0)
        l = J / dJ
        s = M / dM * dJ - J                     # moon direction scaled to Jupiter's distance
        s = s - np.sum(s * l, axis=0) * l
        margin = np.linalg.norm(s, axis=0) - silhouette_radius(s, l, jupiter_pole(t))
        return margin, dM > dJ

    # ---- Sun-side: eclipse in Jupiter's shadow ----------------------------------------
    def shadow(self, t, key):
        """Signed margin (km) of the moon's centre from the edge of Jupiter's umbra, at the
        moon's own emission time; negative = inside. Only meaningful behind Jupiter."""
        e = self.earth.at(t)
        astro = e.observe(self.moon[key])
        te = self.ts.tt_jd(t.tt - astro.light_time)
        S, J, M = self.sun.at(te).position.km, self.jupiter.at(te).position.km, self.moon[key].at(te).position.km
        u = _unit(J - S)                        # shadow axis, away from the Sun
        rel = M - J
        d = np.sum(rel * u, axis=0)
        s = rel - d * u
        shrink = d * (R_SUN - JUP_A) / np.linalg.norm(J - S, axis=0)      # umbra cone
        margin = np.linalg.norm(s, axis=0) - (silhouette_radius(s, u, jupiter_pole(te)) - shrink)
        return np.where(d > 0, margin, np.abs(margin) + JUP_A), d > 0

    # ---- the moon's shadow on the visible disc ----------------------------------------
    def shadow_transit(self, t, key):
        """Signed margin (km) of the moon's shadow centre from the edge of the part of the disc
        that is BOTH sunlit and Earth-facing (negative = shadow on the visible disc), and the
        umbra radius of that shadow. The shadow enters at the limb and leaves at the terminator
        (or the reverse), so the margin is the larger of the two: the limb margin in the Earth
        sky plane and the terminator margin in the Sun view."""
        e = self.earth.at(t)
        te = self.ts.tt_jd(t.tt - e.observe(self.jupiter).light_time)
        S, J, M = self.sun.at(te).position.km, self.jupiter.at(te).position.km, self.moon[key].at(te).position.km
        E = self.earth.at(t).position.km
        p = jupiter_pole(te)                      # (3,) or (3, N): jupiter_pole follows the Time's shape
        v = _unit(M - S)                          # the shadow ray
        rel = M - J
        # Sun view: where the shadow axis crosses Jupiter's Sun-facing silhouette
        d_along = np.sum(rel * v, axis=0)         # moon is on the Sun side: d_along < 0
        s_sun = rel - d_along * v
        m_sun = np.linalg.norm(s_sun, axis=0) - silhouette_radius(s_sun, v, p)
        # the shadow point on the ellipsoid (first intersection from the Sun side)
        vp, rp = np.sum(v * p, axis=0), np.sum(rel * p, axis=0)
        v_eq, r_eq = v - vp * p, rel - rp * p
        A = np.sum(v_eq * v_eq, axis=0) / JUP_A ** 2 + vp ** 2 / JUP_C ** 2
        B = 2 * (np.sum(v_eq * r_eq, axis=0) / JUP_A ** 2 + vp * rp / JUP_C ** 2)
        C = np.sum(r_eq * r_eq, axis=0) / JUP_A ** 2 + rp ** 2 / JUP_C ** 2 - 1
        disc = B * B - 4 * A * C
        hit = (disc > 0) & (d_along < 0)
        lam = np.where(hit, (-B - np.sqrt(np.where(hit, disc, 0))) / (2 * A), 0.0)
        q = rel + lam * v
        # Earth view: margin of that point inside the sky silhouette
        l = _unit(J - E)
        s_sky = q - np.sum(q * l, axis=0) * l
        m_sky = np.linalg.norm(s_sky, axis=0) - silhouette_radius(s_sky, l, p)
        qp = np.sum(q * p, axis=0)
        n = (q - qp * p) / JUP_A ** 2 + qp * p / JUP_C ** 2
        facing = np.sum(n * (E - (J + q)), axis=0) > 0
        m_sky = np.where(facing, m_sky, np.abs(m_sky) + JUP_A)     # far side: push outside
        margin = np.where(hit, np.maximum(m_sky, m_sun), np.abs(m_sun) + JUP_A * (d_along >= 0))
        r_umbra = MOONS[key] - np.abs(lam) * (R_SUN - MOONS[key]) / np.linalg.norm(M - S, axis=0)
        return margin, np.maximum(r_umbra, 0.0)

    # ---- mutual events ----------------------------------------------------------------
    def mutual_sky(self, t, a, b):
        """Sky-plane separation (km at Jupiter's distance) between moons a and b, and
        whether a is nearer (a occults b)."""
        e = self.earth.at(t)
        A = e.observe(self.moon[a]).apparent().position.km
        B = e.observe(self.moon[b]).apparent().position.km
        dA, dB = np.linalg.norm(A, axis=0), np.linalg.norm(B, axis=0)
        sep = np.arccos(np.clip(np.sum(A * B, axis=0) / (dA * dB), -1, 1)) * (dA + dB) / 2
        return sep, dA < dB

    def mutual_shadow(self, t, a, b):
        """Distance (km) of moon b's centre from moon a's shadow axis, at b's emission time,
        and whether b is on the far side of a from the Sun."""
        e = self.earth.at(t)
        te = self.ts.tt_jd(t.tt - e.observe(self.moon[b]).light_time)
        S, A, B = self.sun.at(te).position.km, self.moon[a].at(te).position.km, self.moon[b].at(te).position.km
        u = _unit(A - S)
        rel = B - A
        d = np.sum(rel * u, axis=0)
        s = rel - d * u
        return np.linalg.norm(s, axis=0), d > 0


# --- event search ------------------------------------------------------------------------

def _bisect(fn, t_lo, t_hi, target, ts, iters=28):
    """Time at which the scalar fn(t) crosses `target`, given a bracket."""
    f_lo = fn(t_lo) - target
    for _ in range(iters):
        mid = ts.tt_jd((t_lo.tt + t_hi.tt) / 2)
        fm = fn(mid) - target
        if (fm < 0) == (f_lo < 0):
            t_lo, f_lo = mid, fm
        else:
            t_hi = mid
    return ts.tt_jd((t_lo.tt + t_hi.tt) / 2)


def scan_phenomenon(g, kind, key, t0, t1, log):
    """One phenomenon for one moon over [t0, t1]: list of dicts with contacts."""
    ts = g.ts
    n = int((t1.tt - t0.tt) * 1440 / STEP_MIN) + 1
    grid = ts.tt_jd(t0.tt + np.arange(n) * STEP_MIN / 1440.0)
    r = MOONS[key]
    if kind == "occultation":
        m, flag = g.sky(grid, key)
        m = np.where(flag, m, np.abs(m) + JUP_A)
        fn = lambda t: (lambda mm, ff: mm if ff else abs(mm) + JUP_A)(*g.sky(t, key))
        rin, rout = r, r
    elif kind == "transit":
        m, flag = g.sky(grid, key)
        m = np.where(~flag, m, np.abs(m) + JUP_A)
        fn = lambda t: (lambda mm, ff: mm if not ff else abs(mm) + JUP_A)(*g.sky(t, key))
        rin, rout = r, r
    elif kind == "eclipse":
        m, _ = g.shadow(grid, key)
        fn = lambda t: g.shadow(t, key)[0]
        rin, rout = r, r
    elif kind == "shadow":
        m, ru = g.shadow_transit(grid, key)
        fn = lambda t: g.shadow_transit(t, key)[0]
        rin, rout = None, None      # contact radii vary along the disc: taken per event below
    state = np.where(m < -(rin if rin is not None else r), 2, np.where(m < (rout if rout is not None else r), 1, 0))
    events, cur = [], None
    for i in range(1, n):
        if state[i] == state[i - 1]:
            continue
        prev, now = int(state[i - 1]), int(state[i])
        if kind == "shadow":
            ru_i = float(g.shadow_transit(grid[i], key)[1])
            rin = rout = ru_i
        # which threshold was crossed
        crossings = []
        if prev == 0 and now >= 1: crossings.append(("D1", +rout))
        if prev <= 1 and now == 2: crossings.append(("D2", -rin))
        if prev == 2 and now <= 1: crossings.append(("R1", -rin))
        if prev >= 1 and now == 0: crossings.append(("R2", +rout))
        for name, thr in crossings:
            tc = _bisect(fn, grid[i - 1], grid[i], thr, ts)
            if name == "D1" or (name == "D2" and cur is None):
                if cur:
                    events.append(cur)
                cur = {"moon": key, "type": kind, "contacts": {}}
            if cur is None:
                cur = {"moon": key, "type": kind, "contacts": {}}
            cur["contacts"][name] = tc
            if name == "R2" or (name == "R1" and rout == rin and False):
                events.append(cur)
                cur = None
    if cur:
        events.append(cur)
    # a contact set spanning under two minutes is numerical noise at a limb/terminator junction,
    # not a phenomenon (Io's own ingress alone takes 3.5 min)
    events = [ev for ev in events
              if max(t.tt for t in ev["contacts"].values()) - min(t.tt for t in ev["contacts"].values()) > 2 / 1440]
    log(f"  {key:9s} {kind:12s} {len(events):4d}")
    return events


def scan_mutual(g, t0, t1, log):
    ts = g.ts
    n = int((t1.tt - t0.tt) * 1440 / STEP_MIN) + 1
    grid = ts.tt_jd(t0.tt + np.arange(n) * STEP_MIN / 1440.0)
    keys = [k for k in MOONS if MOONS[k] >= PLANETS[PLANET]["mutual_min_radius"]]
    out = []
    for i, a in enumerate(keys):
        for b in keys:
            if a == b:
                continue
            ra, rb = MOONS[a], MOONS[b]
            # a occults b
            sep, near = g.mutual_sky(grid, a, b)
            inside = (sep < ra + rb) & near
            out += _mutual_intervals(g, ts, grid, inside, "occults", a, b, lambda t: g.mutual_sky(t, a, b)[0], ra + rb)
            # a eclipses b
            dist, behind = g.mutual_shadow(grid, a, b)
            inside = (dist < ra + rb) & behind
            out += _mutual_intervals(g, ts, grid, inside, "eclipses", a, b, lambda t: g.mutual_shadow(t, a, b)[0], ra + rb)
    log(f"  mutual events: {len(out)}")
    return out


def _mutual_intervals(g, ts, grid, inside, verb, a, b, fn, thr):
    out = []
    n = len(grid)
    i = 1
    while i < n:
        if inside[i] and not inside[i - 1]:
            t_start = _bisect(fn, grid[i - 1], grid[i], thr, ts)
            j = i
            while j < n and inside[j]:
                j += 1
            if j >= n:
                break
            t_end = _bisect(fn, grid[j - 1], grid[j], thr, ts)
            # depth: closest approach inside the interval
            seg = ts.tt_jd(np.atleast_1d(grid.tt[i:j]))      # a 1-element slice is still an array
            vals = np.atleast_1d(fn(seg))
            k = int(np.argmin(vals))
            ra, rb = MOONS[a], MOONS[b]
            dmin = float(vals[k])
            covered = _disc_overlap(ra, rb, dmin) / (np.pi * rb * rb)     # fraction of b hidden/shadowed
            fa, fb = 10 ** (-0.4 * MAG[a]), 10 ** (-0.4 * MAG[b])
            if verb == "occults":      # the pair is seen as one point of light: a stays, b loses `covered`
                drop = -2.5 * np.log10((fa + fb * (1 - covered)) / (fa + fb))
            else:                      # only b dims; uniform discs, no penumbra shading — an estimate
                drop = -2.5 * np.log10(max(1e-3, 1 - covered))
            out.append({"type": "mutual", "kind": verb, "a": a, "b": b,
                        "contacts": {"D1": t_start, "R2": t_end}, "mid": seg[k],
                        "min_sep_km": round(dmin, 1), "covered_frac": round(float(covered), 3),
                        "mag_drop": round(float(drop), 2)})
            i = j
        else:
            i += 1
    return out


def _disc_overlap(r1, r2, d):
    if d >= r1 + r2:
        return 0.0
    if d <= abs(r1 - r2):
        return np.pi * min(r1, r2) ** 2
    a1 = np.arccos((d * d + r1 * r1 - r2 * r2) / (2 * d * r1))
    a2 = np.arccos((d * d + r2 * r2 - r1 * r1) / (2 * d * r2))
    return r1 * r1 * a1 + r2 * r2 * a2 - 0.5 * np.sqrt((-d + r1 + r2) * (d + r1 - r2) * (d - r1 + r2) * (d + r1 + r2))


# --- sampled configuration: moon positions in the planet's equatorial sky frame -----------

def sample_config(g, t0, t1, step_min=60):
    """x along the planet's equator (west positive), y toward its north pole, in planet
    radii, plus in-front flags; hourly. The browser interpolates. x = (l x y) is the
    convention that matches Meeus's Galilean X (checked against jup365)."""
    ts = g.ts
    n = int((t1.tt - t0.tt) * 1440 / step_min) + 1
    tt = ts.tt_jd(t0.tt + np.arange(n) * step_min / 1440.0)
    e = g.earth.at(tt)
    Jp = e.observe(g.jupiter).apparent().position.km
    dJ = np.linalg.norm(Jp, axis=0)
    l = Jp / dJ
    p = jupiter_pole(tt)
    y = p - np.sum(p * l, axis=0) * l
    y = y / np.linalg.norm(y, axis=0)
    x = np.cross(l, y, axis=0)
    out = {"t0": t0.utc_iso(places=0), "step_min": step_min, "moons": list(MOONS), "xyf": {}}
    for key in MOONS:
        Mp = e.observe(g.moon[key]).apparent().position.km
        dM = np.linalg.norm(Mp, axis=0)
        off = Mp / dM * dJ - Jp
        X, Y = np.sum(off * x, axis=0) / JUP_A, np.sum(off * y, axis=0) / JUP_A
        front = (dM < dJ).astype(int)
        out["xyf"][key] = [int(v) for v in np.round(np.stack([X * 100, Y * 100, front], axis=1).ravel())]
    return out


# --- output ------------------------------------------------------------------------------

def iso(t):
    return t.utc_iso(places=0)


def describe(g, ev):
    """Add what the site needs to place the event in someone's sky."""
    c = ev["contacts"]
    mid = ev["mid"] if "mid" in ev else g.ts.tt_jd(np.mean([t.tt for t in c.values()]))   # a Time has no truth value
    e = g.earth.at(mid)
    J = e.observe(g.jupiter).apparent()
    S = e.observe(g.sun).apparent()
    ra, dec, dist = J.radec()
    sra, sdec, _ = S.radec()
    out = {k: v for k, v in ev.items() if k not in ("contacts", "mid")}
    out["contacts"] = {k: iso(t) for k, t in c.items()}
    if ev["type"] in ("eclipse", "occultation"):
        hidden = {}
        for k, t in c.items():
            if ev["type"] == "eclipse":
                m, behind = g.sky(t, ev["moon"])
                hidden[k] = bool(behind and m < MOONS[ev["moon"]])          # behind the disc at that moment
            else:
                m, _ = g.shadow(t, ev["moon"])
                hidden[k] = bool(m < MOONS[ev["moon"]])                     # in Jupiter's shadow at that moment
        out["hidden"] = hidden
    out["mid"] = iso(mid)
    out["planet"] = {"ra_deg": round(float(ra._degrees), 4), "dec_deg": round(float(dec.degrees), 4),
                      "dist_au": round(float(dist.au), 4), "elongation_deg": round(float(J.separation_from(S).degrees), 1)}
    out["sun"] = {"ra_deg": round(float(sra._degrees), 3), "dec_deg": round(float(sdec.degrees), 3)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("year", type=int)
    ap.add_argument("--planet", default="jupiter", choices=list(PLANETS))
    ap.add_argument("--months", default="1-12", help="e.g. 10-12")
    ap.add_argument("--moons", default=None)
    ap.add_argument("--kinds", default="occultation,transit,eclipse,shadow,mutual")
    ap.add_argument("--config", action="store_true", help="also store hourly moon positions for the diagram")
    args = ap.parse_args()
    configure(args.planet)
    if args.moons is None:
        args.moons = ",".join(MOONS)
    m0, m1 = (int(x) for x in args.months.split("-"))
    g = Geometry()
    t0 = g.ts.utc(args.year, m0, 1)
    t1 = g.ts.utc(args.year + (1 if m1 == 12 else 0), 1 if m1 == 12 else m1 + 1, 1)
    log = lambda s: print(s, flush=True)
    log(f"{PLANET.capitalize()} {args.year} months {m0}-{m1}")
    events = []
    kinds = args.kinds.split(",")
    for key in args.moons.split(","):
        for kind in [k for k in kinds if k != "mutual"]:
            events += scan_phenomenon(g, kind, key, t0, t1, log)
    if "mutual" in kinds:
        events += scan_mutual(g, t0, t1, log)
    events = [describe(g, ev) for ev in events]
    events.sort(key=lambda ev: ev["mid"])
    out = {"schema": 1, "planet": PLANET, "year": args.year, "months": [m0, m1],
           "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "engine": {"planets": "de431t.bsp", "satellites": os.path.basename(JUP), "planet_km": [JUP_A, JUP_C],
                      "moon_radii_km": MOONS, "step_min": STEP_MIN, "rings": "not modelled"},
           "events": events}
    if args.config:
        out["config"] = sample_config(g, t0, t1)
        log(f"  config: hourly positions for {len(MOONS)} moons")
    os.makedirs(os.path.join(SITE_DIR, "data"), exist_ok=True)
    path = os.path.join(SITE_DIR, "data", f"{PLANET}-moons-{args.year}.json")
    with open(path, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    log(f"wrote {os.path.relpath(path)}: {len(events)} events")


if __name__ == "__main__":
    main()
