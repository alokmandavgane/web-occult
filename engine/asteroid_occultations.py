#!/usr/bin/env python3
"""
Asteroid occultations: an asteroid passes in front of a star, and its shadow — as wide as the asteroid — sweeps a
narrow path across the Earth. The data behind occult.alokm.com's monthly asteroid pages.

  orbits    catalog/asteroids.csv: every asteroid JPL's Small-Body Database gives a diameter of 15 km or more, with
            its osculating elements (committed, so months regenerate from DE431 and the star file alone).
  stars     ephemeris/catalog/gaia_g12.5.npz: Gaia DR3 to G 12.5 over the whole sky, fetched from the ESA archive in
            192 HEALPix pieces (gitignored, ~5 million stars).
  month     data/asteroids-<YYYY-MM>.json: integrate every orbit through the month (DE431 planets and Moon; Ceres,
            Pallas, Vesta and Hygiea; the Sun's relativistic term), find the stars inside each shadow's reach of the
            Earth, solve every candidate exactly, keep those whose path crosses the audience's land at night, and
            store for each its path, its 1-sigma lines and the elements the page's JS solves any place from.

Geometry (`Event`). In the barycentric frame, starlight reaching an observer at O(t) passed the asteroid's distance
at t_a = t - (A - O)·k/c; the observer is in the shadow when that ray passes within the asteroid's radius of
A(t_a). Star and asteroid directions carry the Sun's, Jupiter's and Saturn's light deflection; aberration shifts
both alike and drops out. The star is carried from Gaia's epoch exactly as Skyfield's Star does it.

`local()` is the Python twin of the page's JS solver (scripts/build_asteroids.py SOLVER_JS) — change them TOGETHER.
Checked against Occult4's predictions as published by IOTA-India for September–October 2026
(tests/test_asteroid_occultations.py): path widths to 0.5 km, star positions to ~2 mas, Earth-crossing times to the
minute, and centre lines a rigid sideways shift of the size the orbit solutions themselves differ by.

Usage (repo root):
  .venv/bin/python engine/asteroid_occultations.py orbits
  .venv/bin/python engine/asteroid_occultations.py stars
  .venv/bin/python engine/asteroid_occultations.py month 2026-10
  .venv/bin/python engine/asteroid_occultations.py range 2026-10 2027-09
"""

import argparse
import csv
import datetime as dt
import glob
import gzip
import io
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from skyfield.api import load, load_file
from skyfield.framelib import itrs
from skyfield.relativity import add_deflection

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from ephem_paths import DE431, EPHEM_DIR, REPO, require_de431  # noqa: E402

ORBITS = os.path.join(REPO, "catalog", "asteroids.csv")
COVS = os.path.join(REPO, "catalog", "asteroid-cov.json")
MPCS = os.path.join(REPO, "catalog", "asteroid-mpc.json")
STAR_DIR = os.path.join(EPHEM_DIR, "catalog", "gaia_g12.5")
STAR_NPZ = os.path.join(EPHEM_DIR, "catalog", "gaia_g12.5.npz")
FIELD_DIR = os.path.join(EPHEM_DIR, "catalog", "fields")
OUT_DIR = os.path.join(REPO, "data")

D_MIN_KM, G_LIMIT = 15.0, 12.5
AU_KM = 149597870.7
C_KMS = 299792.458
C_AUD = C_KMS * 86400.0 / AU_KM
MAS = math.pi / 180 / 3600e3
ASEC2RAD = math.pi / 180 / 3600
A_E, F_E = 6378.137, 1 / 298.257223563
W_EARTH = math.radians(360.98564736629) / 86400.0     # rad/s about the CIP axis (the rate MonthModel uses)
EPS_J2000 = math.radians(84381.448 / 3600.0)           # SBDB and MPC ecliptic of J2000
GAIA_EPOCH = 2457389.0                                 # J2016.0
EMRAT = 81.3005690699
GMS = 2.9591220828559115e-04                           # au^3/day^2, DE430/431
PLANETS = [("sun", GMS), ("mercury barycenter", 4.9125474514508118e-11), ("venus barycenter", 7.2434524861627027e-10),
           ("earth", 8.9970116036316091e-10 * EMRAT / (1 + EMRAT)), ("moon", 8.9970116036316091e-10 / (1 + EMRAT)),
           ("mars barycenter", 9.5495351057792580e-11), ("jupiter barycenter", 2.8253459095242264e-07),
           ("saturn barycenter", 8.4597151856806587e-08), ("uranus barycenter", 1.2920249167819693e-08),
           ("neptune barycenter", 1.5243589007842762e-08), ("pluto barycenter", 2.1886997654259696e-12)]
GMP = np.array([gm for _, gm in PLANETS])
KM3S2 = 86400.0 ** 2 / AU_KM ** 3
BIG = {"1": 62.6284 * KM3S2, "2": 13.665878 * KM3S2, "4": 17.288245 * KM3S2, "10": 5.78 * KM3S2}   # SB441-N16 GMs

# which events a month file keeps
SUN_ALT_MAX, STAR_ALT_MIN = -6.0, 10.0         # somewhere on the audience's land the path is in a dark enough sky ...
DROP_MIN, DROP_MIN_LONG, LONG_S = 0.1, 0.05, 10.0   # ... the star visibly fades (a longer event can be timed at less)
DUR_MIN_S = 0.3
CITY_KM = 100.0                                 # ... within this of one of the audience's cities, in that dark sky ...
WIDTH_OVER_SIGMA = 1.0                          # ... and the path is at least as wide as its 1-sigma uncertainty
STEP_DAYS = 0.5                                 # integration step and node spacing
# JPL's formal covariance is far tighter than orbits really are: over the 44 events checked against Occult4 (September–
# October 2026) JPL's and the Minor Planet Center's orbits put the path an RMS 14 mas apart, i.e. ~10 mas each. So the
# orbit term of the 1-sigma path is the largest of: the formal covariance, half-quadrature of the JPL–MPC disagreement for
# that very event (|d|/sqrt 2), and this floor.
ORBIT_FLOOR_MAS = 10.0
# the finder chart each page draws: Gaia stars around the target, and the asteroid's track through the field
FIELD_ARCMIN, FIELD_GLIM, TRACK_H, FIELD_STARS = 15.0, 14.0, 12, 200


# ======================================================================================
# orbits
# ======================================================================================

def fetch_orbits():
    fields = "spkid,pdes,name,diameter,H,G,epoch,e,a,i,om,w,ma,class,soln_date,condition_code"
    q = urllib.parse.urlencode({"fields": fields, "sb-cdata": json.dumps({"AND": [f"diameter|GE|{D_MIN_KM:g}"]}),
                                "sb-kind": "a", "full-prec": "true"})
    d = json.load(urllib.request.urlopen("https://ssd-api.jpl.nasa.gov/sbdb_query.api?" + q, timeout=300))
    rows = sorted(d["data"], key=lambda r: (0, int(r[1])) if r[1].isdigit() else (1, r[1]))
    os.makedirs(os.path.dirname(ORBITS), exist_ok=True)
    with open(ORBITS, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["number", "name", "diameter_km", "H", "G", "epoch_tdb", "e", "a", "i", "node", "peri", "M",
                    "class", "soln_date", "U"])
        for r in rows:
            w.writerow([r[1], r[2] or r[1], r[3], r[4], r[5] or "", r[6], *r[7:13], r[13], (r[14] or "")[:10], r[15]])
    print(f"wrote {os.path.relpath(ORBITS, REPO)}: {len(rows)} asteroids with D >= {D_MIN_KM:g} km "
          f"(SBDB, {dt.date.today().isoformat()})")


def load_orbits():
    rows = list(csv.DictReader(open(ORBITS)))
    for r in rows:
        r["R_km"] = float(r["diameter_km"]) / 2
    return rows


def kepler_to_state(a, e, i, node, peri, M):
    """Heliocentric osculating ecliptic-J2000 elements (degrees) -> equatorial ICRF state (n, 6), au and au/day."""
    a, e = np.asarray(a, float), np.asarray(e, float)
    i, node, peri, M = (np.radians(np.asarray(x, float)) for x in (i, node, peri, M))
    E = M.copy()
    for _ in range(60):
        dE = (E - e * np.sin(E) - M) / (1 - e * np.cos(E))
        E -= dE
        if np.max(np.abs(dE)) < 1e-15:
            break
    n = np.sqrt(GMS / a ** 3)
    cE, sE, b = np.cos(E), np.sin(E), np.sqrt(1 - e * e)
    den = 1 - e * cE
    xo, yo, vxo, vyo = a * (cE - e), a * b * sE, -a * n * sE / den, a * n * b * cE / den
    cO, sO, ci, si, cw, sw = np.cos(node), np.sin(node), np.cos(i), np.sin(i), np.cos(peri), np.sin(peri)
    P = np.stack([cO * cw - sO * sw * ci, sO * cw + cO * sw * ci, sw * si], -1)
    Q = np.stack([-cO * sw - sO * cw * ci, -sO * sw + cO * cw * ci, cw * si], -1)
    r = xo[..., None] * P + yo[..., None] * Q
    v = vxo[..., None] * P + vyo[..., None] * Q
    ce, se = math.cos(EPS_J2000), math.sin(EPS_J2000)
    eq = lambda u: np.stack([u[..., 0], ce * u[..., 1] - se * u[..., 2], se * u[..., 1] + ce * u[..., 2]], -1)
    return np.concatenate([eq(r), eq(v)], -1)


def orbit_states(rows):
    return kepler_to_state([r["a"] for r in rows], [r["e"] for r in rows], [r["i"] for r in rows],
                           [r["node"] for r in rows], [r["peri"] for r in rows], [r["M"] for r in rows])


class Ctx:
    """DE431 and the timescale, loaded once."""

    def __init__(self):
        require_de431()
        self.ts = load.timescale()
        self.eph = load_file(DE431)
        self.earth, self.sun, self.moon = self.eph["earth"], self.eph["sun"], self.eph["moon"]
        self.bodies = [self.eph[name] for name, _ in PLANETS]

    def planet_table(self, jds):
        t = self.ts.tdb_jd(jds)
        pos = np.stack([b.at(t).position.au.T for b in self.bodies], axis=1)
        return pos, self.sun.at(t).velocity.au_per_d.T


def _accel(X, ppos, vsun, pidx, pgm, gr=True):
    r, v = X[:, :3], X[:, 3:]
    d = r[:, None, :] - ppos[None, :, :]
    dn = np.sqrt(np.einsum("nbk,nbk->nb", d, d))
    a = -np.einsum("b,nbk->nk", GMP, d / dn[..., None] ** 3)
    if gr:   # the Sun's post-Newtonian term (heliocentric)
        rs, vs, rn = d[:, 0, :], v - vsun, dn[:, 0]
        a += (GMS / (C_AUD ** 2 * rn ** 3))[:, None] * ((4 * GMS / rn - np.einsum("nk,nk->n", vs, vs))[:, None] * rs
                                                       + 4 * np.einsum("nk,nk->n", rs, vs)[:, None] * vs)
    if len(pidx):
        d = r[:, None, :] - r[pidx][None, :, :]
        dn2 = np.einsum("npk,npk->np", d, d)
        dn2[pidx, np.arange(len(pidx))] = np.inf
        a -= np.einsum("p,npk->nk", pgm, d / (dn2 ** 1.5)[..., None])
    return a


def integrate(ctx, X0, jd0, jd1, h=STEP_DAYS, pidx=(), pgm=(), gr=True, keep=True, chunk=400):
    """RK4 from jd0 to jd1 (either direction). keep: return (node times ascending, states) else the final state."""
    n = max(1, int(math.ceil(abs(jd1 - jd0) / h)))
    hh = (jd1 - jd0) / n
    pidx, pgm = np.asarray(pidx, int), np.asarray(pgm, float)
    X = X0.copy()
    ts_, xs = [jd0], [X.copy()] if keep else None
    done = 0
    while done < n:
        m = min(chunk, n - done)
        jds = jd0 + hh * done + hh / 2 * np.arange(2 * m + 1)
        ppos, vsun = ctx.planet_table(jds)

        def f(j, Y):
            return np.concatenate([Y[:, 3:], _accel(Y, ppos[j], vsun[j], pidx, pgm, gr)], axis=1)
        for s in range(m):
            j = 2 * s
            k1 = f(j, X); k2 = f(j + 1, X + hh / 2 * k1); k3 = f(j + 1, X + hh / 2 * k2); k4 = f(j + 2, X + hh * k3)
            X = X + hh / 6 * (k1 + 2 * k2 + 2 * k3 + k4)
            if keep:
                ts_.append(jd0 + hh * (done + s + 1)); xs.append(X.copy())
        done += m
    if not keep:
        return X
    t, Xs = np.array(ts_), np.array(xs)
    order = np.argsort(t)
    return t[order], Xs[order]


class Dense:
    """Barycentric states at integration nodes, cubic-Hermite interpolated (metres for a main-belt orbit)."""

    def __init__(self, t, X):
        self.t, self.X = t, X

    def __call__(self, jd, idx=None):
        jd = np.atleast_1d(np.asarray(jd, float))
        i = np.clip(np.searchsorted(self.t, jd) - 1, 0, len(self.t) - 2)
        X = self.X if idx is None else self.X[:, idx]
        h = (self.t[i + 1] - self.t[i])[:, None, None]
        s = ((jd - self.t[i]) / (self.t[i + 1] - self.t[i]))[:, None, None]
        p0, v0, p1, v1 = X[i, :, :3], X[i, :, 3:], X[i + 1, :, :3], X[i + 1, :, 3:]
        s2, s3 = s * s, s * s * s
        pos = (2 * s3 - 3 * s2 + 1) * p0 + (s3 - 2 * s2 + s) * h * v0 + (-2 * s3 + 3 * s2) * p1 + (s3 - s2) * h * v1
        vel = ((6 * s2 - 6 * s) * p0 + (3 * s2 - 4 * s + 1) * h * v0 + (-6 * s2 + 6 * s) * p1 + (3 * s2 - 2 * s) * h * v1) / h
        return pos, vel


class Fleet:
    """Every catalogue orbit, carried forward (or back) month by month; the four big ones perturb the rest."""

    def __init__(self, ctx, rows):
        self.ctx, self.rows = ctx, rows
        epochs = {r["epoch_tdb"] for r in rows}
        assert len(epochs) == 1, f"one SBDB epoch expected, got {sorted(epochs)[:5]}"
        self.jd = float(epochs.pop())
        sun = ctx.sun.at(ctx.ts.tdb_jd(self.jd))
        self.X = orbit_states(rows) + np.concatenate([sun.position.au, sun.velocity.au_per_d])[None, :]
        num = [r["number"] for r in rows]
        self.pidx = [num.index(k) for k in BIG if k in num]
        self.pgm = [BIG[num[i]] for i in self.pidx]

    def span(self, jd0, jd1):
        """Dense ephemeris over [jd0, jd1]; the fleet's state moves to jd0 first."""
        if abs(self.jd - jd0) > 1e-9:
            self.X = integrate(self.ctx, self.X, self.jd, jd0, pidx=self.pidx, pgm=self.pgm, keep=False)
            self.jd = jd0
        t, Xs = integrate(self.ctx, self.X, jd0, jd1, pidx=self.pidx, pgm=self.pgm)
        return Dense(t, Xs)


# ======================================================================================
# stars
# ======================================================================================

GAIA_COLS = ("source_id, ra, dec, pmra, pmdec, parallax, ra_error, dec_error, pmra_error, pmdec_error, parallax_error, "
             "radial_velocity, phot_g_mean_mag, bp_rp, ruwe, astrometric_params_solved, duplicated_source")


def fetch_stars(workers=3):
    step = 2 ** 35 * 4 ** 10          # source_id span of one HEALPix level-2 pixel
    os.makedirs(STAR_DIR, exist_ok=True)

    def one(pix):
        path = os.path.join(STAR_DIR, f"l2_{pix:03d}.csv.gz")
        if os.path.exists(path):
            return 0
        q = (f"SELECT {GAIA_COLS} FROM gaiadr3.gaia_source WHERE source_id BETWEEN {pix * step} AND "
             f"{(pix + 1) * step - 1} AND phot_g_mean_mag <= {G_LIMIT}")
        data = urllib.parse.urlencode({"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": q}).encode()
        for attempt in range(5):
            try:
                body = urllib.request.urlopen("https://gea.esac.esa.int/tap-server/tap/sync", data, timeout=600).read()
                if not body.startswith(b"source_id,"):
                    raise RuntimeError(body[:200])
                with gzip.open(path + ".part", "wb") as f:
                    f.write(body)
                os.replace(path + ".part", path)
                return body.count(b"\n") - 1
            except Exception as e:  # noqa: BLE001 — the archive times out now and then
                print(f"   pixel {pix}: {e}; retrying", flush=True)
                time.sleep(10 * (attempt + 1))
        raise SystemExit(f"pixel {pix} failed")
    with ThreadPoolExecutor(workers) as ex:
        n = sum(ex.map(one, range(192)))
    print(f"   fetched {n} stars into {os.path.relpath(STAR_DIR, REPO)}")


def pack_stars():
    cols = {k: [] for k in ("source_id", "ra", "dec", "pmra", "pmdec", "plx", "ra_err", "dec_err", "pmra_err", "pmdec_err",
                            "rv", "g", "bp_rp", "ruwe", "nparam", "dup")}
    f = lambda s, d=np.nan: float(s) if s not in ("", None) else d
    files = sorted(glob.glob(os.path.join(STAR_DIR, "l2_*.csv.gz")))
    assert len(files) == 192, f"{len(files)} of 192 pixel files — run `stars` again to fetch the rest"
    for path in files:
        for r in csv.DictReader(io.TextIOWrapper(gzip.open(path), newline="")):
            cols["source_id"].append(int(r["source_id"])); cols["ra"].append(float(r["ra"])); cols["dec"].append(float(r["dec"]))
            cols["pmra"].append(f(r["pmra"], 0.0)); cols["pmdec"].append(f(r["pmdec"], 0.0)); cols["plx"].append(f(r["parallax"], 0.0))
            cols["ra_err"].append(f(r["ra_error"])); cols["dec_err"].append(f(r["dec_error"]))
            cols["pmra_err"].append(f(r["pmra_error"], 0.0)); cols["pmdec_err"].append(f(r["pmdec_error"], 0.0))
            cols["rv"].append(f(r["radial_velocity"], 0.0)); cols["g"].append(float(r["phot_g_mean_mag"]))
            cols["bp_rp"].append(f(r["bp_rp"])); cols["ruwe"].append(f(r["ruwe"])); cols["nparam"].append(int(r["astrometric_params_solved"]))
            cols["dup"].append(r["duplicated_source"] == "true")
    types = {"source_id": np.int64, "ra": np.float64, "dec": np.float64, "nparam": np.int8, "dup": bool}
    arr = {k: np.array(v, dtype=types.get(k, np.float32)) for k, v in cols.items()}
    order = np.argsort(arr["dec"], kind="stable")
    np.savez(STAR_NPZ, **{k: v[order] for k, v in arr.items()})
    print(f"wrote {os.path.relpath(STAR_NPZ, REPO)}: {len(order)} stars to G {G_LIMIT} (sorted by Dec)")


class Stars:
    def __init__(self):
        if not os.path.exists(STAR_NPZ):
            raise SystemExit(f"{STAR_NPZ} missing: run `engine/asteroid_occultations.py stars`")
        z = np.load(STAR_NPZ)
        self.__dict__.update({k: z[k] for k in z.files})
        self.n = len(self.ra)

    def record(self, s):
        return {k: (getattr(self, k)[s].item()) for k in ("source_id", "ra", "dec", "pmra", "pmdec", "plx", "ra_err",
                                                        "dec_err", "pmra_err", "pmdec_err", "rv", "g", "bp_rp", "ruwe",
                                                        "nparam", "dup")}


def star_bcrs(st):
    """Skyfield's Star model: position (au) at Gaia's epoch and space velocity (au/day)."""
    plx = st["plx"] if st["plx"] > 0 else 1e-6
    dist = 1.0 / math.sin(plx * 1e-3 * ASEC2RAD)
    ra, dec = math.radians(st["ra"]), math.radians(st["dec"])
    cra, sra, cdc, sdc = math.cos(ra), math.sin(ra), math.cos(dec), math.sin(dec)
    k = 1.0 / (1.0 - st["rv"] / C_KMS)
    pmr, pmd = st["pmra"] / (plx * 365.25) * k, st["pmdec"] / (plx * 365.25) * k
    rvl = st["rv"] * 86400.0 / AU_KM * k
    p = np.array([dist * cdc * cra, dist * cdc * sra, dist * sdc])
    v = np.array([-pmr * sra - pmd * sdc * cra + rvl * cdc * cra, pmr * cra - pmd * sdc * sra + rvl * cdc * sra, pmd * cdc + rvl * sdc])
    return p, v


def fetch_fields(events, workers=6, log=print):
    """The star field around each target for the pages' finder charts: Gaia DR3 within FIELD_ARCMIN to G FIELD_GLIM,
    cached per target star (positions at Gaia's own epoch — proper motion is invisible at this scale)."""
    os.makedirs(FIELD_DIR, exist_ok=True)
    want = {ev.st["source_id"]: ev.st for ev in events
            if not os.path.exists(os.path.join(FIELD_DIR, f"{ev.st['source_id']}.json"))}

    def one(st):
        q = (f"SELECT ra, dec, phot_g_mean_mag FROM gaiadr3.gaia_source WHERE 1=CONTAINS(POINT('ICRS',ra,dec),"
             f"CIRCLE('ICRS',{st['ra']},{st['dec']},{FIELD_ARCMIN / 60})) AND phot_g_mean_mag <= {FIELD_GLIM}")
        data = urllib.parse.urlencode({"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": q}).encode()
        for attempt in range(4):
            try:
                body = urllib.request.urlopen("https://gea.esac.esa.int/tap-server/tap/sync", data, timeout=300).read().decode()
                if not body.startswith("ra,"):
                    raise RuntimeError(body[:200])
                rows = [[float(r["ra"]), float(r["dec"]), float(r["phot_g_mean_mag"])] for r in csv.DictReader(io.StringIO(body))]
                path = os.path.join(FIELD_DIR, f"{st['source_id']}.json")
                with open(path + ".part", "w") as f:
                    json.dump(rows, f, separators=(",", ":"))
                os.replace(path + ".part", path)
                return
            except Exception as e:  # noqa: BLE001 — the archive times out now and then
                time.sleep(5 * (attempt + 1))
                err = e
        raise SystemExit(f"Gaia field for {st['source_id']} failed: {err}")
    if want:
        with ThreadPoolExecutor(workers) as ex:
            list(ex.map(one, want.values()))
        log(f"   fetched {len(want)} finder fields (Gaia to G {FIELD_GLIM} within {FIELD_ARCMIN:g}')")


def finder(ev, st):
    """The finder chart's contents, in hundredths of an arcminute from the target: the field stars (with their G), and
    the asteroid's track through the field hour by hour (the page labels the hours in the reader's own time)."""
    path = os.path.join(FIELD_DIR, f"{st['source_id']}.json")
    if not os.path.exists(path):
        return None
    cd = math.cos(math.radians(st["dec"]))
    off = lambda ra, dec: [round((((ra - st["ra"] + 180) % 360) - 180) * cd * 6000), round((dec - st["dec"]) * 6000)]
    rows = sorted((r for r in json.load(open(path))
                   if abs(r[0] - st["ra"]) * cd > 3e-5 or abs(r[1] - st["dec"]) > 3e-5), key=lambda r: r[2])
    stars = [off(ra, dec) + [round(g * 10)] for ra, dec, g in rows[:FIELD_STARS]]   # a crowded field only needs its brightest
    jds = ev.jd0 + np.arange(-TRACK_H, TRACK_H + 0.001, 1.0) / 24
    g = ev.geom(jds)
    u = g["a"] / np.linalg.norm(g["a"], axis=1)[:, None]
    ra = np.degrees(np.arctan2(u[:, 1], u[:, 0])) % 360
    dec = np.degrees(np.arcsin(np.clip(u[:, 2], -1, 1)))
    track = [off(r, d) for r, d in zip(ra, dec)]
    return {"r": FIELD_ARCMIN, "lim": FIELD_GLIM, "u": 0.01, "stars": stars, "track": track, "track_h": TRACK_H}


def minute_ticks(ev, t0_utc, bbox, limit=12):
    """Whole minutes of UTC marked along the centre line inside the map frame: [lat, lon, seconds from t0] — the page
    turns each into the reader's own clock, and t0 + seconds is a whole minute exactly."""
    jd, line = ev.fine["jd"], ev.lines[0]
    ok = np.isfinite(line[:, 0])
    if ok.sum() < 2:
        return []
    secs = (jd - ev.jd0) * 86400
    first = -(t0_utc.second % 60)                                  # whole minutes sit this many seconds off t0
    marks = np.arange(math.ceil((secs[ok][0] - first) / 60), math.floor((secs[ok][-1] - first) / 60) + 1) * 60 + first
    lon0, lat0, lon1, lat1 = bbox
    out = []
    for s in marks:
        la = float(np.interp(s, secs[ok], line[ok, 0]))
        lo = float(np.interp(s, secs[ok], line[ok, 1]))
        if lon0 - 2 <= lo <= lon1 + 2 and lat0 - 2 <= la <= lat1 + 2:
            out.append([round(la, 3), round(lo, 3), int(round(s))])
    step = max(1, math.ceil(len(out) / limit))
    return out[::step]


def g_to_v(g, bp_rp):
    """Gaia DR3 G - V as a cubic in BP-RP (Riello et al. 2021), as in star_occultations.py."""
    if bp_rp is None or not np.isfinite(bp_rp):
        return g + 0.1
    x = min(5.0, max(-0.5, bp_rp))
    return g - (-0.02704 + 0.01424 * x - 0.2156 * x * x + 0.01426 * x ** 3)


def asteroid_vmag(H, G, r_au, delta_au, phase_rad):
    t = math.tan(phase_rad / 2)
    phi1, phi2 = math.exp(-3.33 * t ** 0.63), math.exp(-1.87 * t ** 1.22)
    return H + 5 * math.log10(r_au * delta_au) - 2.5 * math.log10((1 - G) * phi1 + G * phi2)


# ======================================================================================
# geometry of one event
# ======================================================================================

def itrs_point(lat, lon, h_km=0.0):
    la, lo = np.radians(lat), np.radians(lon)
    e2 = F_E * (2 - F_E)
    N = A_E / np.sqrt(1 - e2 * np.sin(la) ** 2)
    return np.stack([(N + h_km) * np.cos(la) * np.cos(lo), (N + h_km) * np.cos(la) * np.sin(lo),
                     (N * (1 - e2) + h_km) * np.sin(la)], axis=-1)


def latlon(g):
    lat = np.degrees(np.arctan2(g[..., 2], (1 - F_E) ** 2 * np.hypot(g[..., 0], g[..., 1])))
    return lat, np.degrees(np.arctan2(g[..., 1], g[..., 0]))


def basis(k):
    e1 = np.cross([0.0, 0.0, 1.0], k)
    e1 /= np.linalg.norm(e1)
    return e1, np.cross(k, e1)


class Event:
    """One asteroid (row index `ai` of the fleet) and one star (a Stars.record dict)."""

    def __init__(self, ctx, dense, rows, ai, st):
        self.ctx, self.dense, self.row, self.ai, self.st = ctx, dense, rows[ai], ai, st
        self.R = self.row["R_km"]
        self.sp, self.sv = star_bcrs(st)

    def geom(self, jds, rotation=False, deflect=True):
        ts = self.ctx.ts
        t = ts.tdb_jd(jds)
        e = self.ctx.earth.at(t)
        E = e.position.au                                          # (3, n)
        u = self.sp / np.linalg.norm(self.sp)
        sp = (self.sp[:, None] + self.sv[:, None] * (jds + (u @ E) / C_AUD - GAIA_EPOCH)[None, :]) - E
        tau = np.zeros(len(jds))
        for _ in range(3):
            P, V = self.dense(jds - tau, [self.ai])
            d = P[:, 0].T - E
            tau = np.sqrt(np.einsum("kn,kn->n", d, d)) / C_AUD
        if deflect:
            add_deflection(sp, E, self.ctx.eph, t, np.array(False), 3)
            add_deflection(d, E, self.ctx.eph, t, np.array(False), 3)
        out = {"jd": np.asarray(jds, float), "k": (sp / np.linalg.norm(sp, axis=0)).T, "a": d.T * AU_KM,
               "V": V[:, 0] * AU_KM / 86400.0, "E": E.T}
        if rotation:
            out["R"] = np.transpose(itrs.rotation_at(t), (2, 0, 1))          # GCRS -> ITRS, (n, 3, 3)
        return out

    def locate(self, jd_guess, reach_s=1800.0):
        """Geocentric closest approach of the shadow axis: time (TDB JD), distance (km), speed (km/s)."""
        for _ in range(4):
            jds = jd_guess + np.arange(-reach_s, reach_s + 1e-6, reach_s / 30) / 86400
            g = self.geom(jds, deflect=False)       # a few mas: irrelevant here, and track() refines the time
            p = g["a"] - np.einsum("nk,nk->n", g["a"], g["k"])[:, None] * g["k"]
            D = np.linalg.norm(p, axis=1)
            j = int(np.argmin(D))
            if 0 < j < len(D) - 1:
                break
            jd_guess = jds[j]
        j = min(max(j, 1), len(D) - 2)
        w = (p[j + 1] - p[j - 1]) / (2 * reach_s / 30)
        u = -(p[j] @ w) / (w @ w)
        self.jd0 = jds[j] + u / 86400
        self.D0 = float(np.linalg.norm(p[j] + w * u))
        self.v0 = float(np.linalg.norm(w))
        return self.jd0, self.D0, self.v0

    def on_earth(self):
        return self.D0 < A_E + self.R

    def window_s(self):
        return math.sqrt(max(0.0, (A_E + self.R) ** 2 - self.D0 ** 2)) / self.v0 + 60.0

    def track(self, step_s=None):
        """Fine geometry over the Earth crossing, with the Earth's rotation."""
        W = self.window_s()
        step_s = step_s or min(30.0, max(1.0, 15.0 / self.v0))
        n = int(math.ceil(W / step_s))
        self.fine = g = self.geom(self.jd0 + np.arange(-n, n + 1) * step_s / 86400, rotation=True)
        # the geocentric closest approach again, now with light deflection
        p = g["a"] - np.einsum("nk,nk->n", g["a"], g["k"])[:, None] * g["k"]
        j = min(max(int(np.argmin(np.linalg.norm(p, axis=1))), 1), len(p) - 2)
        w = (p[j + 1] - p[j - 1]) / ((g["jd"][j + 1] - g["jd"][j - 1]) * 86400)
        u = -(p[j] @ w) / (w @ w)
        self.jd0, self.D0, self.v0 = g["jd"][j] + u / 86400, float(np.linalg.norm(p[j] + w * u)), float(np.linalg.norm(w))
        return g

    def ground(self, offsets):
        """Ground points (lat, lon; nan off the Earth) of the shadow axis displaced by `offsets` km across the
        relative motion, at every fine sample: (len(offsets), n, 2). The displaced point closes on the axis at that
        instant, so it is exactly the place whose closest approach is that offset."""
        g = self.fine
        k, a, V, R = g["k"], g["a"], g["V"], g["R"]
        n = len(g["jd"])
        e1 = np.cross(np.array([0, 0, 1.0])[None, :], k)
        e1 /= np.linalg.norm(e1, axis=1)[:, None]
        e2 = np.cross(k, e1)
        x, y = np.einsum("nk,nk->n", a, e1), np.einsum("nk,nk->n", a, e2)
        dt_s = np.gradient(g["jd"]) * 86400
        vx, vy = np.gradient(x) / dt_s, np.gradient(y) / dt_s
        out = np.full((len(offsets), n, 2), np.nan)
        scale = np.array([1, 1, 1 / (1 - F_E)])
        for oi, off in enumerate(offsets):
            wx, wy = vx.copy(), vy.copy()
            zeta = np.full(n, A_E)
            for _ in range(3):
                wn = np.hypot(wx, wy)
                nx, ny = -wy / wn, wx / wn                              # left of the relative motion
                px = x + np.einsum("nk,nk->n", V, e1) * zeta / C_KMS + off * nx
                py = y + np.einsum("nk,nk->n", V, e2) * zeta / C_KMS + off * ny
                base = px[:, None] * e1 + py[:, None] * e2                 # GCRS point on the axis plane
                b_it = np.einsum("nij,nj->ni", R, base) * scale
                k_it = np.einsum("nij,nj->ni", R, k) * scale
                Q, B, C = np.einsum("ni,ni->n", k_it, k_it), np.einsum("ni,ni->n", b_it, k_it), np.einsum("ni,ni->n", b_it, b_it) - A_E ** 2
                disc = B * B - Q * C
                lam = (-B + np.sqrt(np.where(disc >= 0, disc, np.nan))) / Q
                gi = np.einsum("nij,nj->ni", R, base + lam[:, None] * k)   # ITRS ground point
                zeta = np.nan_to_num(lam, nan=A_E)
                # observer velocity in GCRS, then the relative motion across the plane
                vg = np.einsum("nji,nj->ni", R, np.stack([-W_EARTH * gi[:, 1], W_EARTH * gi[:, 0], np.zeros(n)], 1))
                wx, wy = vx - np.einsum("nk,nk->n", vg, e1), vy - np.einsum("nk,nk->n", vg, e2)
            la, lo = latlon(gi)
            out[oi, :, 0], out[oi, :, 1] = np.where(disc >= 0, la, np.nan), np.where(disc >= 0, lo, np.nan)
        return out

    def closest(self, lat, lon):
        """Full-model closest approach for ground points: (TDB JD, signed km, relative speed km/s), (m, 3)."""
        g = self.fine
        k, a, V, jd = g["k"], g["a"], g["V"], g["jd"]
        Rt = np.transpose(g["R"], (0, 2, 1))
        G = itrs_point(np.atleast_1d(lat), np.atleast_1d(lon))
        out = []
        for c in range(0, len(G), 64):
            gg = np.einsum("tij,pj->pti", Rt, G[c:c + 64])
            gk = np.einsum("pti,ti->pt", gg, k)
            r = a[None] + V[None] * (gk / C_KMS)[..., None] - gg
            p = r - np.einsum("pti,ti->pt", r, k)[..., None] * k[None]
            dist = np.linalg.norm(p, axis=2)
            j = np.clip(np.argmin(dist, axis=1), 1, len(jd) - 2)
            ii = np.arange(len(j))
            dts = (jd[j + 1] - jd[j - 1]) * 86400
            w = (p[ii, j + 1] - p[ii, j - 1]) / dts[:, None]
            u = np.einsum("pk,pk->p", p[ii, j], w) / np.einsum("pk,pk->p", w, w)
            pm = p[ii, j] - w * u[:, None]
            sgn = np.sign(np.einsum("pk,pk->p", np.cross(pm, w), k[j]))      # + = observer left of the motion
            out.append(np.stack([jd[j] - u / 86400, sgn * np.linalg.norm(pm, axis=1), np.linalg.norm(w, axis=1)], 1))
        return np.concatenate(out)

    # ---------------------------------------------------------------- the browser's compact description

    def elements(self, deg=5):
        g = self.fine
        t0 = self.ctx.ts.tdb_jd(self.jd0)
        t0_utc = t0.utc_datetime().replace(microsecond=0)
        jd_utc0 = self.ctx.ts.from_datetime(t0_utc).tdb
        tau = (g["jd"] - jd_utc0) * 86400
        W = float(np.max(np.abs(tau)))
        i0 = int(np.argmin(np.abs(tau)))
        k = g["k"][i0]
        e1, e2 = basis(k)
        x, y = g["a"] @ e1, g["a"] @ e2
        for deg in (deg, 7, 9):
            cx = np.polynomial.polynomial.polyfit(tau / W, x, deg)
            cy = np.polynomial.polynomial.polyfit(tau / W, y, deg)
            res = max(np.max(np.abs(np.polynomial.polynomial.polyval(tau / W, cx) - x)),
                      np.max(np.abs(np.polynomial.polynomial.polyval(tau / W, cy) - y)))
            if res < 0.01:
                break
        assert res < 0.05, f"element fit residual {res:.3f} km"
        t = self.ctx.ts.from_datetime(t0_utc)
        R0 = itrs.rotation_at(t)
        s = (self.ctx.sun.at(t) - self.ctx.earth.at(t)).position.au
        V = g["V"][i0]
        return {"t0": t0_utc.strftime("%Y-%m-%dT%H:%M:%SZ"), "W": round(W, 1), "k": [round(float(v), 12) for v in k],
                "x": [round(float(c), 4) for c in cx], "y": [round(float(c), 4) for c in cy],
                "vp": [round(float(V @ e1), 5), round(float(V @ e2), 5)],
                "R0": [round(float(v), 12) for v in R0.ravel()], "sun": [round(float(v), 8) for v in s / np.linalg.norm(s)],
                "R": round(self.R, 2)}


def _poly(c, u):
    v = 0.0
    for a in reversed(c):
        v = v * u + a
    return v


def _dpoly(c, u):
    v = 0.0
    for i in range(len(c) - 1, 0, -1):
        v = v * u + i * c[i]
    return v


def local(el, lat, lon):
    """Twin of the page's JS `solve()`: closest approach of the shadow axis to a place, from the elements.
    Returns seconds from t0, signed distance (km, fundamental plane), relative speed, duration (0 outside), the star's
    and Sun's altitude and the star's azimuth there at that moment — and, in the fundamental plane's e1/e2 km, `q` the place's
    offset from the shadow's axis and `v` the shadow's motion past it (km/s), which a model outline needs: q · (left normal
    of v) is d."""
    la, lo = math.radians(lat), math.radians(lon)
    r = itrs_point(lat, lon)
    up = [math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la)]
    east = [-math.sin(lo), math.cos(lo), 0.0]
    north = [-math.sin(la) * math.cos(lo), -math.sin(la) * math.sin(lo), math.cos(la)]
    k = el["k"]
    e1 = [-k[1], k[0], 0.0]
    n1 = math.hypot(e1[0], e1[1])
    e1 = [e1[0] / n1, e1[1] / n1, 0.0]
    e2 = [k[1] * e1[2] - k[2] * e1[1], k[2] * e1[0] - k[0] * e1[2], k[0] * e1[1] - k[1] * e1[0]]
    R0, W, vp = el["R0"], el["W"], el["vp"]
    dot = lambda p, q: p[0] * q[0] + p[1] * q[1] + p[2] * q[2]

    def G(tau, v):      # ITRS -> GCRS at t0 + tau: R0^T Rz(theta)
        th = W_EARTH * tau
        c, s = math.cos(th), math.sin(th)
        w0, w1, w2 = c * v[0] - s * v[1], s * v[0] + c * v[1], v[2]
        return [R0[0] * w0 + R0[3] * w1 + R0[6] * w2, R0[1] * w0 + R0[4] * w1 + R0[7] * w2, R0[2] * w0 + R0[5] * w1 + R0[8] * w2]

    wxr = [-W_EARTH * r[1], W_EARTH * r[0], 0.0]

    def state(tau):
        u = max(-1.0, min(1.0, tau / W))
        g, gd = G(tau, r), G(tau, wxr)
        zeta, dzeta = dot(g, k), dot(gd, k)
        px = _poly(el["x"], u) + vp[0] * zeta / C_KMS - dot(g, e1)
        py = _poly(el["y"], u) + vp[1] * zeta / C_KMS - dot(g, e2)
        wx = _dpoly(el["x"], u) / W + vp[0] * dzeta / C_KMS - dot(gd, e1)
        wy = _dpoly(el["y"], u) / W + vp[1] * dzeta / C_KMS - dot(gd, e2)
        return px, py, wx, wy

    tau = 0.0
    for _ in range(8):
        px, py, wx, wy = state(tau)
        step = (px * wx + py * wy) / (wx * wx + wy * wy)
        tau = max(-W, min(W, tau - step))
        if abs(step) < 1e-3:
            break
    px, py, wx, wy = state(tau)
    speed = math.hypot(wx, wy)
    d = math.hypot(px, py)
    sgn = 1.0 if (wy * px - wx * py) >= 0 else -1.0          # + = the place lies left of the shadow's motion
    upg, eg, ng = G(tau, up), G(tau, east), G(tau, north)
    R = el["R"]
    return {"tau": tau, "d": sgn * d, "speed": speed, "dur": 2 * math.sqrt(R * R - d * d) / speed if d < R else 0.0,
            "star_alt": math.degrees(math.asin(max(-1.0, min(1.0, dot(k, upg))))),
            "star_az": (math.degrees(math.atan2(dot(k, eg), dot(k, ng))) + 360) % 360,
            "sun_alt": math.degrees(math.asin(max(-1.0, min(1.0, dot(el["sun"], upg))))),
            "q": [-px, -py], "v": [wx, wy]}


def to_centre(el, lat, lon, h=0.02):
    """Ground distance (km) and compass bearing from a place to the centre line — twin of the JS `toCentre()`."""
    d0 = local(el, lat, lon)["d"]
    dn = (local(el, lat + h, lon)["d"] - local(el, lat - h, lon)["d"]) / (2 * h * 111.195)
    de = (local(el, lat, lon + h)["d"] - local(el, lat, lon - h)["d"]) / (2 * h * 111.195 * math.cos(math.radians(lat)))
    grad = math.hypot(dn, de)
    return abs(d0) / grad, (math.degrees(math.atan2(-d0 * de, -d0 * dn)) + 360) % 360


# ======================================================================================
# the month
# ======================================================================================

class LandMask:
    """The audience's land (geo/<audience>.json) rasterised at 0.05°."""

    def __init__(self, audience="india", res=0.05):
        g = json.load(open(os.path.join(REPO, "geo", f"{audience}.json")))
        self.lon0, self.lat0, self.lon1, self.lat1 = g["bbox"]
        self.res = res
        nx, ny = int(round((self.lon1 - self.lon0) / res)), int(round((self.lat1 - self.lat0) / res))
        lon = self.lon0 + (np.arange(nx) + 0.5) * res
        lat = self.lat0 + (np.arange(ny) + 0.5) * res
        LO, LA = np.meshgrid(lon, lat)
        inside = np.zeros(LO.shape, bool)
        for ring in g["land"]:
            ring = np.asarray(ring)
            if len(ring) < 3:
                continue
            x0, y0 = ring[:, 0], ring[:, 1]
            x1, y1 = np.roll(x0, -1), np.roll(y0, -1)
            bb = (LO >= x0.min()) & (LO <= x0.max()) & (LA >= y0.min()) & (LA <= y0.max())
            if not bb.any():
                continue
            px, py = LO[bb], LA[bb]
            cross = np.zeros(px.shape, bool)
            for a0, b0, a1, b1 in zip(x0, y0, x1, y1):
                m = (b0 > py) != (b1 > py)
                if m.any():
                    xi = a0 + (py[m] - b0) * (a1 - a0) / (b1 - b0)
                    c = np.zeros(px.shape, bool)
                    c[m] = px[m] < xi
                    cross ^= c
            inside[bb] ^= cross
        self.mask = inside

    def contains(self, lat, lon):
        lat, lon = np.asarray(lat), np.asarray(lon)
        ok = np.isfinite(lat) & (lon >= self.lon0) & (lon < self.lon1) & (lat >= self.lat0) & (lat < self.lat1)
        i = np.clip(((np.nan_to_num(lat) - self.lat0) / self.res).astype(int), 0, self.mask.shape[0] - 1)
        j = np.clip(((np.nan_to_num(lon) - self.lon0) / self.res).astype(int), 0, self.mask.shape[1] - 1)
        return ok & self.mask[i, j]


def month_bounds(ym):
    y, m = (int(x) for x in ym.split("-"))
    a = dt.datetime(y, m, 1, tzinfo=dt.timezone.utc)
    b = dt.datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=dt.timezone.utc)
    return a, b


def screen(ctx, dense, rows, stars, jd0, jd1, log=print):
    """Candidate (asteroid, star, jd) triples: every star within the shadow's reach of the Earth from the geocentric
    track, sampled hourly and interpolated linearly, day by day in Dec-sorted boxes."""
    hours = np.arange(jd0, jd1 + 1e-9, 1 / 24)
    E = ctx.earth.at(ctx.ts.tdb_jd(hours)).position.au.T                  # (h, 3)
    R = np.array([r["R_km"] for r in rows])
    dec_sorted = stars.dec
    mid_yr = ((jd0 + jd1) / 2 - GAIA_EPOCH) / 365.25
    cands = {}
    B = 256
    for b0 in range(0, len(rows), B):
        idx = list(range(b0, min(len(rows), b0 + B)))
        P, V = dense(hours, idx)
        d = P - E[:, None, :]
        d = d - V * (np.linalg.norm(d, axis=2) / C_AUD)[..., None]           # light time to first order: km-level, plenty here
        dist = np.linalg.norm(d, axis=2)                                    # au (h, n)
        U = d / dist[..., None]
        reach = (A_E + R[idx][None, :] + 200.0) / (dist * AU_KM) + 1.0 * ASEC2RAD
        ra = np.degrees(np.arctan2(U[..., 1], U[..., 0])) % 360
        dec = np.degrees(np.arcsin(np.clip(U[..., 2], -1, 1)))
        for c, ai in enumerate(idx):
            for h0 in range(0, len(hours) - 1, 24):
                sl = slice(h0, min(len(hours), h0 + 25))
                rd = np.degrees(reach[sl, c].max())
                d_lo, d_hi = dec[sl, c].min() - rd - 0.01, dec[sl, c].max() + rd + 0.01
                lo, hi = np.searchsorted(dec_sorted, [d_lo, d_hi])
                if hi <= lo:
                    continue
                cosd = max(0.05, math.cos(math.radians(max(abs(d_lo), abs(d_hi)))))
                rac = ra[sl, c]
                ref = rac[len(rac) // 2]
                rel = (rac - ref + 540) % 360 - 180
                srel = (stars.ra[lo:hi] + stars.pmra[lo:hi] * mid_yr / 3.6e6 / cosd - ref + 540) % 360 - 180
                pad = (rd + 0.01) / cosd
                sdec = stars.dec[lo:hi] + stars.pmdec[lo:hi] * mid_yr / 3.6e6
                m = (srel >= rel.min() - pad) & (srel <= rel.max() + pad) & (sdec >= d_lo) & (sdec <= d_hi)
                if not m.any():
                    continue
                sidx = np.nonzero(m)[0] + lo
                sra, sde = np.radians(ref + srel[m]), np.radians(sdec[m])
                S = np.stack([np.cos(sde) * np.cos(sra), np.cos(sde) * np.sin(sra), np.sin(sde)], 1)
                u0, u1 = U[sl, c][:-1], U[sl, c][1:]
                seg = u1 - u0
                lam = (np.einsum("sk,hk->sh", S, seg) - np.einsum("hk,hk->h", u0, seg)[None, :]) / np.einsum("hk,hk->h", seg, seg)[None, :]
                lam = np.clip(lam, 0, 1)
                near = u0[None] + lam[..., None] * seg[None]
                sep = np.linalg.norm(S[:, None, :] - near, axis=2)
                j = np.argmin(sep, axis=1)
                ok = sep[np.arange(len(j)), j] < reach[sl, c][j]
                for s, jj, lj in zip(sidx[ok], j[ok], lam[np.arange(len(j)), j][ok]):
                    key = (ai, int(s))
                    if key not in cands:
                        cands[key] = hours[h0 + jj] + lj / 24
    log(f"   screened {len(rows)} asteroids × {stars.n} stars: {len(cands)} candidates")
    return cands


def orbit_sigma(ctx, rows, events, log=print):
    """1-sigma cross-track (km) and along-track (s) path uncertainty from each asteroid's JPL covariance, carried
    linearly to the event by integrating the six Cholesky-displaced orbits beside the nominal one."""
    cache = json.load(open(COVS)) if os.path.exists(COVS) else {}
    by_ast = {}
    for ev in events:
        by_ast.setdefault(ev.ai, []).append(ev)
    stale = [rows[ai] for ai in by_ast if cache.get(rows[ai]["number"], {}).get("soln_date") != rows[ai]["soln_date"]]

    def fetch(row):
        for attempt in range(4):
            try:
                d = json.load(urllib.request.urlopen(f"https://ssd-api.jpl.nasa.gov/sbdb.api?sstr={urllib.parse.quote(row['number'])}"
                                                     f"&cov=mat&full-prec=1", timeout=90))
                break
            except OSError:
                time.sleep(5 * (attempt + 1))
        else:
            raise SystemExit(f"SBDB covariance for {row['number']} failed")
        cov = d["orbit"].get("covariance")
        if not cov:
            return row["number"], {"soln_date": row["soln_date"], "none": True}
        el = {e["name"]: float(e["value"]) for e in cov["elements"]}
        M = np.array([[float(v) for v in r] for r in cov["data"]])
        return row["number"], {"soln_date": row["soln_date"], "epoch": float(cov["epoch"]),
                               "elements": [el["e"], el["q"], el["tp"], el["om"], el["w"], el["i"]],
                               "tri": [float(f"{M[i, j]:.7g}") for i in range(6) for j in range(i + 1)]}   # labels e q tp node peri i
    with ThreadPoolExecutor(8) as ex:
        for num, c in ex.map(fetch, stale):
            cache[num] = c
    changed = bool(stale)
    for ai, evs in by_ast.items():
        c = cache[rows[ai]["number"]]
        if c.get("none"):
            for ev in evs:
                ev.sigma_orbit_km, ev.sigma_orbit_s = None, None
            continue
        e, q, tp, node, peri, inc = c["elements"]
        C = np.zeros((6, 6))
        C[np.tril_indices(6)] = c["tri"]
        C = C + np.tril(C, -1).T
        w_, Vv = np.linalg.eigh(C)
        L = Vv * np.sqrt(np.clip(w_, 0, None))[None, :]                      # L L^T = C
        sets = [np.array([e, q, tp, node, peri, inc])] + [np.array([e, q, tp, node, peri, inc]) + L[:, j] for j in range(6)]
        el = np.array(sets)
        a = el[:, 1] / (1 - el[:, 0])
        M = np.degrees(np.sqrt(GMS / a ** 3) * (c["epoch"] - el[:, 2]))
        X = kepler_to_state(a, el[:, 0], el[:, 5], el[:, 3], el[:, 4], M)
        sun = ctx.sun.at(ctx.ts.tdb_jd(c["epoch"]))
        X = X + np.concatenate([sun.position.au, sun.velocity.au_per_d])[None, :]
        jds = sorted(ev.jd0 for ev in evs)
        # differences of a linear map: a 2-day RK4 step is ample, and planets-only is ample
        t, Xs = integrate(ctx, X, c["epoch"], jds[-1] + 2 if jds[-1] > c["epoch"] else jds[0] - 2, h=2.0, gr=False)
        dense = Dense(t, Xs)
        for ev in evs:
            P, _ = dense(ev.jd0)
            dP = (P[0, 1:] - P[0, 0]) * AU_KM                                 # (6, 3)
            i0 = int(np.argmin(np.abs(ev.fine["jd"] - ev.jd0)))
            e1, e2 = basis(ev.fine["k"][i0])
            D2 = np.stack([dP @ e1, dP @ e2], 1)
            Cp = D2.T @ D2
            x, y = ev.fine["a"] @ e1, ev.fine["a"] @ e2
            vel = np.array([np.gradient(x)[i0], np.gradient(y)[i0]])
            vel /= np.linalg.norm(vel)
            nrm = np.array([-vel[1], vel[0]])
            ev.sigma_orbit_km = float(math.sqrt(nrm @ Cp @ nrm))
            ev.sigma_orbit_s = float(math.sqrt(vel @ Cp @ vel) / ev.v0)
    if changed:
        with open(COVS, "w") as f:
            json.dump(dict(sorted(cache.items(), key=lambda kv: (len(kv[0]), kv[0]))), f, separators=(",", ":"))
    orbit_disagreement(ctx, rows, by_ast, log)
    log(f"   orbit uncertainty for {len(by_ast)} asteroids")


def orbit_disagreement(ctx, rows, by_ast, log=print):
    """Where the Minor Planet Center's orbit puts the same event, across (km) and along (s) the path, relative to JPL's.
    Both orbits are carried with the same planets-only force model, so the model's own shortfall cancels."""
    cache = json.load(open(MPCS)) if os.path.exists(MPCS) else {}
    missing = [rows[ai]["number"] for ai in by_ast if rows[ai]["number"] not in cache]

    def fetch(num):
        req = urllib.request.Request("https://data.minorplanetcenter.net/api/get-orb", method="GET",
                                     data=json.dumps({"desig": num}).encode(), headers={"Content-Type": "application/json"})
        for attempt in range(4):
            try:
                d = json.load(urllib.request.urlopen(req, timeout=90))
                break
            except OSError:
                time.sleep(5 * (attempt + 1))
        else:
            return num, None
        o = (d[0] or {}).get("mpc_orb") if d else None
        o = o[0] if isinstance(o, list) and o else o
        if not o or "CAR" not in o or o.get("system_data", {}).get("refsys") != "Ecliptic":
            return num, None
        return num, {"fitted": str(o.get("software_data", {}).get("fitting_datetime", ""))[:10],
                     "epoch": o["epoch_data"]["epoch"] + 2400000.5, "car": o["CAR"]["coefficient_values"]}
    with ThreadPoolExecutor(8) as ex:
        for num, m in ex.map(fetch, missing):
            cache[num] = m
    if missing:
        with open(MPCS, "w") as f:
            json.dump(dict(sorted(cache.items(), key=lambda kv: (len(kv[0]), kv[0]))), f, separators=(",", ":"))
    ce, se = math.cos(EPS_J2000), math.sin(EPS_J2000)
    Rx = np.array([[1, 0, 0], [0, ce, -se], [0, se, ce]])
    for ai, evs in by_ast.items():
        m = cache.get(rows[ai]["number"])
        for ev in evs:
            ev.jpl_mpc_km, ev.jpl_mpc_s = None, None
        if not m:
            continue
        jds = sorted(ev.jd0 for ev in evs)
        pos = []
        for jd_ep, helio in ((float(rows[ai]["epoch_tdb"]), orbit_states([rows[ai]])[0]),
                             (m["epoch"], np.concatenate([Rx @ np.array(m["car"][:3]), Rx @ np.array(m["car"][3:])]))):
            sun = ctx.sun.at(ctx.ts.tdb_jd(jd_ep))
            X = (helio + np.concatenate([sun.position.au, sun.velocity.au_per_d]))[None, :]
            lo, hi = min(jds[0], jd_ep) - 2, max(jds[-1], jd_ep) + 2
            segs = [integrate(ctx, X, jd_ep, end, h=2.0, gr=False) for end in (lo, hi) if abs(end - jd_ep) > 1e-9]
            t = np.concatenate([s[0] for s in segs]); Xs = np.concatenate([s[1] for s in segs])
            t, i = np.unique(t, return_index=True)
            pos.append(Dense(t, Xs[i]))
        for ev in evs:
            dP = (pos[1](ev.jd0)[0][0, 0] - pos[0](ev.jd0)[0][0, 0]) * AU_KM
            i0 = int(np.argmin(np.abs(ev.fine["jd"] - ev.jd0)))
            e1, e2 = basis(ev.fine["k"][i0])
            x, y = ev.fine["a"] @ e1, ev.fine["a"] @ e2
            vel = np.array([np.gradient(x)[i0], np.gradient(y)[i0]])
            vel /= np.linalg.norm(vel)
            d2 = np.array([dP @ e1, dP @ e2])
            ev.jpl_mpc_km = float(d2 @ np.array([-vel[1], vel[0]]))
            ev.jpl_mpc_s = float(d2 @ vel / ev.v0)


def simplify(points, tol=0.01):
    """Douglas-Peucker on (lat, lon) degrees. A closed ring starts and ends at the same place, so its first baseline has
    no direction: measure from that point instead, or the whole ring collapses to it."""
    pts = np.asarray(points)
    if len(pts) < 3:
        return pts.tolist()
    keep = np.zeros(len(pts), bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        a, b = pts[i], pts[j]
        ab = b - a
        L = np.hypot(*ab)
        seg = pts[i + 1:j]
        d = (np.hypot(seg[:, 0] - a[0], seg[:, 1] - a[1]) if L < 1e-12
             else np.abs(ab[0] * (seg[:, 1] - a[1]) - ab[1] * (seg[:, 0] - a[0])) / L)
        k = int(np.argmax(d))
        if d[k] > tol:
            keep[i + 1 + k] = True
            stack += [(i, i + 1 + k), (i + 1 + k, j)]
    return [[round(float(p[0]), 3), round(float(p[1]), 3)] for p in pts[keep]]


def clip_runs(lat, lon, bbox, pad=3.0):
    """Runs of finite points inside the padded bbox, each simplified."""
    lon0, lat0, lon1, lat1 = bbox
    ok = np.isfinite(lat) & (lon >= lon0 - pad) & (lon <= lon1 + pad) & (lat >= lat0 - pad) & (lat <= lat1 + pad)
    runs, cur = [], []
    for o, la, lo in zip(ok, lat, lon):
        if o:
            cur.append((la, lo))
        elif cur:
            runs.append(cur); cur = []
    if cur:
        runs.append(cur)
    return [simplify(r) for r in runs if len(r) > 1]


def evaluate(ctx, dense, rows, ai, st, jd, jd0, jd1, land, cities=None):
    """Solve one screened (asteroid, star) candidate and apply the listing rules that don't need the path's uncertainty:
    (Event, "listed") or (None, why not). `cities`: unit vectors of the audience's cities (None skips that rule)."""
    ts = ctx.ts
    ev = Event(ctx, dense, rows, ai, st)
    ev.locate(jd)
    if not (jd0 <= ev.jd0 < jd1):
        return None, "outside the month"
    if not ev.on_earth():
        return None, "misses the Earth"
    # cheap cuts before the ground geometry: the brightness drop and the duration
    g0 = ev.geom(np.array([ev.jd0]))
    delta = float(np.linalg.norm(g0["a"][0])) / AU_KM
    sun_h = ctx.sun.at(ts.tdb_jd(ev.jd0)).position.au - g0["E"][0]
    r_h = float(np.linalg.norm(sun_h - g0["a"][0] / AU_KM))
    phase = math.acos(max(-1, min(1, float(np.dot(-g0["a"][0] / AU_KM, sun_h - g0["a"][0] / AU_KM)) / (delta * r_h))))
    va = asteroid_vmag(float(rows[ai]["H"]), float(rows[ai]["G"] or 0.15), r_h, delta, phase)
    vs = g_to_v(st["g"], st["bp_rp"])
    drop = va + 2.5 * math.log10(10 ** (-0.4 * vs) + 10 ** (-0.4 * va))
    dur = 2 * ev.R / ev.v0
    if dur < DUR_MIN_S:
        return None, f"lasts only {dur:.2f} s"
    if not (drop >= DROP_MIN or (drop >= DROP_MIN_LONG and dur >= LONG_S)):
        return None, f"the star fades only {drop:.2f} mag"
    ev.track()
    lines = ev.ground([0.0, ev.R, -ev.R])
    R_it = ev.fine["R"]
    k_it = np.einsum("nij,nj->ni", R_it, ev.fine["k"])
    s_g = ctx.sun.at(ts.tdb_jd(ev.fine["jd"])).position.au.T - ev.fine["E"]
    s_it = np.einsum("nij,nj->ni", R_it, s_g / np.linalg.norm(s_g, axis=1)[:, None])
    good = np.zeros(len(ev.fine["jd"]), bool)
    for li in range(3):
        la, lo = lines[li, :, 0], lines[li, :, 1]
        upv = np.stack([np.cos(np.radians(la)) * np.cos(np.radians(lo)), np.cos(np.radians(la)) * np.sin(np.radians(lo)), np.sin(np.radians(la))], 1)
        star_alt = np.degrees(np.arcsin(np.clip(np.einsum("ni,ni->n", upv, k_it), -1, 1)))
        sun_alt = np.degrees(np.arcsin(np.clip(np.einsum("ni,ni->n", upv, s_it), -1, 1)))
        g = land.contains(la, lo) & (star_alt >= STAR_ALT_MIN) & (sun_alt <= SUN_ALT_MAX)
        if li == 0:
            good_centre = g
        good |= g
    if not good.any():
        return None, "no stretch over land with the star up in a dark sky"
    if cities is not None:
        la, lo = np.radians(lines[0, good_centre, 0]), np.radians(lines[0, good_centre, 1])
        if not len(la):
            return None, "the centre line is never over land in a dark sky"
        P = np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)], 1)
        near = float(np.min(np.linalg.norm(P[:, None, :] - cities[None, :, :], axis=2))) * 6371.0
        if near > CITY_KM:
            return None, f"passes {near:.0f} km from the nearest listed city in a dark sky"
    ev.va, ev.vs, ev.drop, ev.dur, ev.delta, ev.r_h, ev.phase = va, vs, drop, dur, delta, r_h, phase
    ev.lines, ev.good = lines, good
    ev.star_alt_it, ev.sun_it = k_it, s_it
    return ev, "listed"


def build_month(ym, ctx, fleet, rows, stars, audience="india", log=print):
    a, b = month_bounds(ym)
    ts = ctx.ts
    jd0, jd1 = ts.from_datetime(a).tdb, ts.from_datetime(b).tdb
    aud = json.load(open(os.path.join(REPO, "seed.json")))["audiences"][audience]
    land = LandMask(audience)
    cl = json.load(open(os.path.join(REPO, aud["cities"])))
    la, lo = np.radians([c["lat"] for c in cl]), np.radians([c["lon"] for c in cl])
    cities = np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)], 1)
    t_start = time.time()
    dense = fleet.span(jd0 - 1.0, jd1 + 1.0)
    log(f"   {ym}: orbits integrated ({time.time() - t_start:.0f} s)")
    cands = screen(ctx, dense, rows, stars, jd0 - 0.05, jd1 + 0.05, log)
    kept, n_earth = [], 0
    for (ai, s), jd in sorted(cands.items(), key=lambda kv: kv[1]):
        ev, why = evaluate(ctx, dense, rows, ai, stars.record(s), jd, jd0, jd1, land, cities)
        n_earth += why not in ("outside the month", "misses the Earth")
        if ev:
            kept.append(ev)
    log(f"   {n_earth} shadows touch the Earth this month; {len(kept)} pass within {CITY_KM:g} km of a city in {aud['label']} "
        f"at night with a drop >= {DROP_MIN} mag and >= {DUR_MIN_S} s")
    orbit_sigma(ctx, rows, kept, log)
    # the width cut needs only the uncertainty, so it comes first: no Gaia query for the finder field, and no record, for
    # a path that is about to be dropped
    kept = [ev for ev in kept if wide_enough(ev, rows)]
    log(f"   {len(kept)} of them with a path at least as wide as its 1-sigma uncertainty")
    fetch_fields(kept, log=log)
    import asteroid_shapes
    asteroid_shapes.prepare([rows[ev.ai]["number"] for ev in kept], log)
    out = [event_record(ctx, ev, rows, aud) for ev in kept]
    for rec in out:                      # from the record's own fields, exactly as `asteroid_shapes.py month` backfills them
        rec["shape"] = asteroid_shapes.shape_record(rec)
    out.sort(key=lambda e: e["el"]["t0"])
    return {"month": ym, "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "audience": audience, "bbox": aud["bbox"],
            "engine": {"ephemeris": "JPL DE431", "orbits": f"JPL SBDB, fetched {orbit_date()}", "stars": f"Gaia DR3 to G {G_LIMIT}",
                       "asteroids": len(rows), "d_min_km": D_MIN_KM, "shadows_on_earth": n_earth,
                       "rules": {"sun_alt_max": SUN_ALT_MAX, "star_alt_min": STAR_ALT_MIN, "drop_min": DROP_MIN,
                                 "drop_min_long": DROP_MIN_LONG, "long_s": LONG_S, "dur_min_s": DUR_MIN_S,
                                 "city_km": CITY_KM, "width_over_sigma": WIDTH_OVER_SIGMA, "orbit_floor_mas": ORBIT_FLOOR_MAS}},
            "events": out}


def orbit_date():
    return dt.datetime.fromtimestamp(os.path.getmtime(ORBITS), dt.timezone.utc).strftime("%Y-%m-%d")


def path_sigma(ev):
    """The path's 1-sigma: across it in km, along it in seconds, and the star's own share in km. Gaia's position and
    proper-motion error carried to the event, combined with an orbit term — the largest of JPL's formal covariance,
    |JPL - MPC| / sqrt 2 and ORBIT_FLOOR_MAS. Needs orbit_sigma() to have run over the event first."""
    yrs = (ev.jd0 - GAIA_EPOCH) / 365.25
    e = {k: float(np.nan_to_num(ev.st[k], nan=0.0)) for k in ("ra_err", "dec_err", "pmra_err", "pmdec_err")}
    sig_star_mas = math.sqrt((e["ra_err"] ** 2 + e["dec_err"] ** 2) / 2 + ((e["pmra_err"] ** 2 + e["pmdec_err"] ** 2) / 2) * yrs ** 2)
    km_per_mas = ev.delta * AU_KM * MAS
    sig_star_km = sig_star_mas * km_per_mas
    orbit_km = max(ORBIT_FLOOR_MAS * km_per_mas, ev.sigma_orbit_km or 0.0, abs(ev.jpl_mpc_km or 0.0) / math.sqrt(2))
    orbit_s = max(ORBIT_FLOOR_MAS * km_per_mas / ev.v0, ev.sigma_orbit_s or 0.0, abs(ev.jpl_mpc_s or 0.0) / math.sqrt(2))
    return math.sqrt(orbit_km ** 2 + sig_star_km ** 2), orbit_s, sig_star_km


def wide_enough(ev, rows):
    """The asteroid at least as wide as its path's 1-sigma — on the rounded sigma the month file carries, so the cut
    made here is exactly the cut the records would show."""
    return float(rows[ev.ai]["diameter_km"]) >= WIDTH_OVER_SIGMA * round(path_sigma(ev)[0], 1)


def event_record(ctx, ev, rows, aud):
    ts = ctx.ts
    row, st = rows[ev.ai], ev.st
    el = ev.elements()
    t0 = ts.tdb_jd(ev.jd0)
    so = ev.sigma_orbit_km
    sigma, orbit_s, sig_star_km = path_sigma(ev)
    # ±1-sigma lines beside the limits
    extra = ev.ground([ev.R + sigma, -(ev.R + sigma)]) if sigma else None
    names = ["centre", "left", "right"]
    lines = {n: clip_runs(ev.lines[i, :, 0], ev.lines[i, :, 1], aud["bbox"]) for i, n in enumerate(names)}
    if extra is not None:
        lines["left_1s"] = clip_runs(extra[0, :, 0], extra[0, :, 1], aud["bbox"])
        lines["right_1s"] = clip_runs(extra[1, :, 0], extra[1, :, 1], aud["bbox"])
    # the stretch over the audience's land at night
    jd_good = ev.fine["jd"][ev.good]
    ce = ev.lines[0]
    ok = np.isfinite(ce[:, 0]) & ev.good
    best = None
    if ok.any():
        la, lo = ce[ok, 0], ce[ok, 1]
        upv = np.stack([np.cos(np.radians(la)) * np.cos(np.radians(lo)), np.cos(np.radians(la)) * np.sin(np.radians(lo)), np.sin(np.radians(la))], 1)
        alt = np.degrees(np.arcsin(np.clip(np.einsum("ni,ni->n", upv, ev.star_alt_it[ok]), -1, 1)))
        j = int(np.argmax(alt))
        best = {"lat": round(float(la[j]), 2), "lon": round(float(lo[j]), 2), "star_alt": round(float(alt[j]), 1)}
    moon = (ctx.moon.at(t0) - ctx.earth.at(t0)).position.au
    sun = (ctx.sun.at(t0) - ctx.earth.at(t0)).position.au
    kk = ev.fine["k"][int(np.argmin(np.abs(ev.fine["jd"] - ev.jd0)))]
    ang = lambda v: math.degrees(math.acos(max(-1, min(1, float(kk @ (v / np.linalg.norm(v)))))))
    moon_illum = (1 - float((moon / np.linalg.norm(moon)) @ (sun / np.linalg.norm(sun)))) / 2     # (1 - cos elongation) / 2
    ra_s, dec_s = math.degrees(math.atan2(kk[1], kk[0])) % 360, math.degrees(math.asin(kk[2]))
    utc = lambda jd: ts.tdb_jd(jd).utc_strftime("%Y-%m-%dT%H:%M:%SZ")
    left_lat = np.nanmean(ev.lines[1, :, 0]) if np.isfinite(ev.lines[1, :, 0]).any() else 0
    right_lat = np.nanmean(ev.lines[2, :, 0]) if np.isfinite(ev.lines[2, :, 0]).any() else 0
    import re
    # one asteroid can hide two stars on one date: the star's Gaia id tail keeps the id unique (and stable across rebuilds)
    slug = (f"{ts.tdb_jd(ev.jd0).utc_strftime('%Y-%m-%d')}-{row['number']}-{re.sub(r'[^a-z0-9]+', '-', row['name'].lower()).strip('-')}"
            f"-{str(st['source_id'])[-6:]}")
    return {
        "id": slug,
        "asteroid": {"number": row["number"], "name": row["name"], "diameter_km": float(row["diameter_km"]),
                     "H": float(row["H"]), "class": row["class"], "soln_date": row["soln_date"], "mag": round(ev.va, 1),
                     "dist_au": round(ev.delta, 4)},
        "star": {"gaia": str(st["source_id"]), "g": round(st["g"], 2), "v": round(ev.vs, 2),
                 "bp_rp": None if not np.isfinite(st["bp_rp"]) else round(st["bp_rp"], 2),
                 "ruwe": None if not np.isfinite(st["ruwe"]) else round(st["ruwe"], 2), "dup": bool(st["dup"]),
                 "params": int(st["nparam"]), "ra": round(ra_s, 5), "dec": round(dec_s, 5)},
        "drop": round(ev.drop, 2), "combined_mag": round(-2.5 * math.log10(10 ** (-0.4 * ev.vs) + 10 ** (-0.4 * ev.va)), 2),
        "dur_max_s": round(ev.dur, 2), "speed_kms": round(ev.v0, 2),
        "sigma_km": round(sigma, 1), "sigma_s": round(orbit_s, 1),
        "sigma_formal_km": None if so is None else round(so, 1), "sigma_star_km": round(sig_star_km, 1),
        "jpl_mpc_km": None if ev.jpl_mpc_km is None else round(ev.jpl_mpc_km, 1),
        "jpl_mpc_s": None if ev.jpl_mpc_s is None else round(ev.jpl_mpc_s, 1),
        "sun_elong": round(ang(sun), 0), "moon_sep": round(ang(moon), 0), "moon_illum": round(moon_illum, 2),
        "t_geo": utc(ev.jd0), "earth": [utc(ev.fine["jd"][0] + 60 / 86400), utc(ev.fine["jd"][-1] - 60 / 86400)],
        "over_land": [utc(jd_good[0]), utc(jd_good[-1])], "best": best,
        "north_is": "left" if left_lat >= right_lat else "right",
        "el": el, "lines": lines, "ticks": minute_ticks(ev, dt.datetime.strptime(el["t0"], "%Y-%m-%dT%H:%M:%SZ"), aud["bbox"]),
        "field": finder(ev, st),
    }


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("orbits")
    sub.add_parser("stars")
    mp = sub.add_parser("month"); mp.add_argument("ym")
    rp = sub.add_parser("range"); rp.add_argument("start"); rp.add_argument("end")
    args = ap.parse_args()
    if args.cmd == "orbits":
        fetch_orbits(); return
    if args.cmd == "stars":
        fetch_stars(); pack_stars(); return
    months = [args.ym] if args.cmd == "month" else []
    if args.cmd == "range":
        y, m = (int(x) for x in args.start.split("-"))
        while f"{y}-{m:02d}" <= args.end:
            months.append(f"{y}-{m:02d}"); y, m = y + (m == 12), m % 12 + 1
    ctx = Ctx()
    rows = load_orbits()
    stars = Stars()
    fleet = Fleet(ctx, rows)
    os.makedirs(OUT_DIR, exist_ok=True)
    for ym in months:
        t = time.time()
        d = build_month(ym, ctx, fleet, rows, stars)
        path = os.path.join(OUT_DIR, f"asteroids-{ym}.json")
        with open(path, "w") as f:
            json.dump(d, f, ensure_ascii=False, separators=(",", ":"))
        print(f"   wrote {os.path.relpath(path, REPO)}: {len(d['events'])} events ({os.path.getsize(path) // 1024} KB, {time.time() - t:.0f} s)")


if __name__ == "__main__":
    main()
