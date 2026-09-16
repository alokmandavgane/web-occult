"""Asteroid shapes from DAMIT, turned to the way each asteroid faces at an event and projected onto the fundamental
plane — the outline that actually passes in front of the star — for the asteroid pages' chord diagram.

DAMIT is the Database of Asteroid Models from Inversion Techniques (Astronomical Institute, Charles University, Prague;
Ďurech, Sidorin & Kaasalainen 2010, A&A 513, A46), CC BY 4.0. Each model is a convex polyhedron with a spin axis
(ecliptic J2000 λ, β), a sidereal period, an epoch t0 and the rotation angle φ0 there. DAMIT's documentation gives the
orientation at a light-time-corrected epoch t as

    r_ecl = Rz(λ) · Ry(90° − β) · Rz(φ0 + 2π/P · (t − t0) + ½·υ·(t − t0)²) · r_ast

with anticlockwise rotation matrices and υ the YORP change of rate (rad/day²). That formula is the one thing here that
can be silently wrong, so `lightcurve()` rebuilds DAMIT's own photometry from it — every point of a DAMIT light curve
carries the Sun's and the Earth's directions in the asteroid-centred ecliptic frame — and the tests require the
documented convention to fit clearly better than a reversed spin or a quarter-turn phase error.

The site SHOWS these shapes; its paths, times and durations stay those of a sphere of SBDB's diameter, and the page says
so. Which model is shown (`choose`): only models DAMIT itself rates 2 or better ("few dense light curves with sparse
data") or that predate the rating; of those, only the best-rated tier; and only if every model in that tier agrees on
the pole to within 30°. Quality 1 ("coarse shape models based solely on sparse data, large errors both in the shape and
pole direction") and 0 ("just one possible model out of many") are never drawn, and neither is an unresolved mirror pole.

Usage:
  asteroid_shapes.py tables             refresh DAMIT's asteroid and model tables in the cache
  asteroid_shapes.py month 2026-09 ...  add or refresh `shape` in existing month files (no re-integration)
  asteroid_shapes.py check 2:102 216:1826
                                        fetch these models and their asteroids' light curves for the tests
"""

import csv
import json
import math
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from asteroid_occultations import AU_KM, C_KMS, EPS_J2000, basis, simplify  # noqa: E402
from ephem_paths import EPHEM_DIR, REPO  # noqa: E402

DAMIT = "https://astro.troja.mff.cuni.cz/projects/damit"
CACHE = os.path.join(EPHEM_DIR, "damit")
QUALITY_MIN = 2.0          # DAMIT's scale: 0 one model of many, 1 sparse-only, 2 few dense + sparse, 3 reliable, 4 pole resolved
UNRATED_AS = 2.5           # models older than the rating rank between 2 and 3: mostly dense-light-curve inversions
POLE_AGREE_DEG = 30.0
HULL_TOL = 0.01            # outline simplified to 1% of the diameter
HULL_MAX = 64


def _get(url, path, timeout=120):
    for attempt in range(4):
        try:
            body = urllib.request.urlopen(url, timeout=timeout).read()
            if body[:15].lstrip().lower().startswith(b"<!doctype html"):
                raise RuntimeError(f"{url} returned a web page, not data")
            with open(path + ".part", "wb") as f:
                f.write(body)
            os.replace(path + ".part", path)
            return path
        except Exception as e:  # noqa: BLE001 — a university server, one request at a time mostly works
            err = e
            time.sleep(4 * (attempt + 1))
    raise SystemExit(f"DAMIT fetch failed: {url}: {err}")


def fetch_tables():
    os.makedirs(CACHE, exist_ok=True)
    for t in ("asteroids", "asteroid_models"):
        _get(f"{DAMIT}/exports/table/{t}", os.path.join(CACHE, f"{t}.csv"))
    print(f"   DAMIT tables refreshed in {os.path.relpath(CACHE, REPO)}")


def load_models():
    """{asteroid number: [model rows]} from the cached tables, or {} when there is no cache."""
    a_path, m_path = os.path.join(CACHE, "asteroids.csv"), os.path.join(CACHE, "asteroid_models.csv")
    if not (os.path.exists(a_path) and os.path.exists(m_path)):
        return {}
    ast = {r["id"]: r for r in csv.DictReader(open(a_path, encoding="utf-8-sig"))}
    out = {}
    for m in csv.DictReader(open(m_path, encoding="utf-8-sig")):
        a = ast.get(m["asteroid_id"])
        if not (a and a["number"] and m["lambda"] and m["beta"] and m["period"] and m["jd0"]):
            continue
        m["q"] = float(m["quality_flag"]) if m["quality_flag"] else None
        out.setdefault(a["number"], []).append(m)
    return out


def _pole(m):
    lam, bet = math.radians(float(m["lambda"])), math.radians(float(m["beta"]))
    return np.array([math.cos(bet) * math.cos(lam), math.cos(bet) * math.sin(lam), math.sin(bet)])


def choose(models):
    """The model worth drawing for one asteroid, or None (see the module docstring)."""
    rank = lambda m: m["q"] if m["q"] is not None else UNRATED_AS
    ok = [m for m in models if rank(m) >= QUALITY_MIN]
    if not ok:
        return None
    top = max(rank(m) for m in ok)
    tier = [m for m in ok if rank(m) == top]
    poles = [_pole(m) for m in tier]
    if any(float(a @ b) < math.cos(math.radians(POLE_AGREE_DEG)) for a in poles for b in poles):
        return None
    return max(tier, key=lambda m: (m["modified"] or m["created"] or "", int(m["id"])))


def shape_path(model_id):
    return os.path.join(CACHE, "shapes", f"{model_id}.obj")


def fetch_shapes(model_ids, workers=3, log=print):
    os.makedirs(os.path.join(CACHE, "shapes"), exist_ok=True)
    want = [i for i in model_ids if not os.path.exists(shape_path(i))]
    if want:
        with ThreadPoolExecutor(workers) as ex:
            list(ex.map(lambda i: _get(f"{DAMIT}/generated_files/open/AsteroidModel/{i}/shape.obj", shape_path(i)), want))
        log(f"   fetched {len(want)} DAMIT shapes")


def load_shape(model_id):
    """Vertices (n, 3) and 0-based triangular facets (m, 3), anticlockwise seen from outside."""
    V, F = [], []
    for line in open(shape_path(model_id)):
        p = line.split()
        if p and p[0] == "v":
            V.append([float(x) for x in p[1:4]])
        elif p and p[0] == "f":
            F.append([int(x.split("/")[0]) - 1 for x in p[1:4]])
    return np.array(V), np.array(F)


def lightcurve_path(number):
    return os.path.join(CACHE, "lc", f"{number}.json")


def load_lightcurves(number, min_points=20):
    """DAMIT's dense light curves for an asteroid: [array of (JD, flux, Sun xyz, Earth xyz)], or [] with no cache."""
    path = lightcurve_path(number)
    if not os.path.exists(path):
        return []
    out = []
    for lc in json.load(open(path)):
        rows = [[float(x) for x in r.split()] for r in lc["LightCurve"]["points"].strip().split("\n") if r.strip()]
        if len(rows) >= min_points:
            out.append(np.array(rows))
    return out


def fetch_check(pairs, log=print):
    """`number:model_id` pairs: the tables, those shapes, and each asteroid's light curves (DAMIT asteroid id)."""
    if not os.path.exists(os.path.join(CACHE, "asteroid_models.csv")):
        fetch_tables()
    ast = {r["number"]: r["id"] for r in csv.DictReader(open(os.path.join(CACHE, "asteroids.csv"), encoding="utf-8-sig"))}
    os.makedirs(os.path.join(CACHE, "lc"), exist_ok=True)
    fetch_shapes([m for _, m in pairs], log=log)
    for number, _ in pairs:
        if not os.path.exists(lightcurve_path(number)):
            _get(f"{DAMIT}/light_curves/exportAllForAsteroid/{ast[number]}/json", lightcurve_path(number), timeout=300)
    log(f"   light curves cached for {', '.join(n for n, _ in pairs)}")


def _rz(t):
    c, s = math.cos(t), math.sin(t)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def _ry(t):
    c, s = math.cos(t), math.sin(t)
    return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])


def ast_to_ecl(m, jd, spin=1.0, phase_deg=0.0):
    """DAMIT's documented body -> ecliptic rotation at light-time-corrected JD `jd`. `spin` and `phase_deg` exist only so
    the tests can show that the wrong ones fit DAMIT's photometry worse."""
    dt = jd - float(m["jd0"])
    phi = math.radians(float(m["phi0"] or 0.0) + phase_deg) + 2 * math.pi / (float(m["period"]) / 24.0) * dt \
        + 0.5 * float(m["yorp"] or 0.0) * dt * dt
    return _rz(math.radians(float(m["lambda"]))) @ _ry(math.radians(90.0 - float(m["beta"]))) @ _rz(spin * phi)


def lightcurve(m, V, F, points, **wrong):
    """Relative brightness of the model at DAMIT light-curve points (JD, flux, Sun xyz, Earth xyz — asteroid-centred
    ecliptic): Lommel-Seeliger plus DAMIT's Lambert weight, facets lit and seen. Convex, so no shadowing."""
    cr = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]]) / 2
    area = np.linalg.norm(cr, axis=1)
    n = cr / area[:, None]
    c = float(m["lsm_p1"] or 0.1)
    out = []
    for p in points:
        R = ast_to_ecl(m, p[0], **wrong)
        s, e = R.T @ np.asarray(p[2:5]), R.T @ np.asarray(p[5:8])
        mu0, mu = n @ (s / np.linalg.norm(s)), n @ (e / np.linalg.norm(e))
        lit = (mu0 > 0) & (mu > 0)
        out.append(float(np.sum(area[lit] * mu0[lit] * mu[lit] * (1.0 / (mu[lit] + mu0[lit]) + c))))
    return np.array(out)


def silhouette(m, V, F, jd, k, diameter_km):
    """The model's outline in the fundamental plane at light-time-corrected JD `jd`, as the star direction `k` (ICRF)
    sees it: [[x, y], ...] km along e1 (east) and e2 (north) from the asteroid's centre — the same axes as the page's
    shadow geometry — scaled so the model's volume is that of a sphere of `diameter_km`."""
    vol = float(np.sum(np.einsum("ij,ij->i", V[F[:, 0]], np.cross(V[F[:, 1]], V[F[:, 2]])))) / 6.0
    scale = diameter_km / (2.0 * (3.0 * vol / (4.0 * math.pi)) ** (1 / 3))
    ecl = V @ ast_to_ecl(m, jd).T * scale          # vertices are radius vectors from the centre of mass: no centring
    ce, se = math.cos(EPS_J2000), math.sin(EPS_J2000)
    eq = np.stack([ecl[:, 0], ce * ecl[:, 1] - se * ecl[:, 2], se * ecl[:, 1] + ce * ecl[:, 2]], 1)
    e1, e2 = basis(np.asarray(k, float))
    pts = sorted(set(map(tuple, np.round(np.stack([eq @ e1, eq @ e2], 1), 3))))
    hull = _hull(pts)
    tol = HULL_TOL * diameter_km
    ring = simplify(hull + [hull[0]], tol)[:-1]
    while len(ring) > HULL_MAX:
        tol *= 1.5
        ring = simplify(hull + [hull[0]], tol)[:-1]
    return [[round(x, 1), round(y, 1)] for x, y in ring]


def _hull(pts):
    """Andrew's monotone chain; counter-clockwise."""
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return [list(p) for p in lower[:-1] + upper[:-1]]


_MODELS = {}
_TS = []


def shape_record(rec):
    """`shape` for one month-file event record — built from the record's own stored fields, so a fresh month build and a
    backfill of an existing file give the same bytes — or None when the asteroid has no model worth drawing (or there
    is no DAMIT cache)."""
    if not _MODELS:
        _MODELS["all"] = load_models()
    m = choose(_MODELS["all"].get(rec["asteroid"]["number"], []))
    if m is None or not os.path.exists(shape_path(m["id"])):
        return None
    if not _TS:
        from skyfield.api import load
        _TS.append(load.timescale(builtin=True))
    t = rec["el"]["t0"]
    jd = _TS[0].utc(int(t[:4]), int(t[5:7]), int(t[8:10]), int(t[11:13]), int(t[14:16]), int(t[17:19])).tt
    jd -= rec["asteroid"]["dist_au"] * AU_KM / C_KMS / 86400.0          # the asteroid as it was when it cut the starlight
    V, F = load_shape(m["id"])
    return {"model": int(m["id"]), "q": m["q"], "pole": [float(m["lambda"]), float(m["beta"])],
            "period_h": float(m["period"]),
            "hull": silhouette(m, V, F, jd, rec["el"]["k"], rec["asteroid"]["diameter_km"])}


def prepare(numbers, log=print):
    """Make sure the tables and the shapes for these asteroids' chosen models are in the cache."""
    if not os.path.exists(os.path.join(CACHE, "asteroid_models.csv")):
        fetch_tables()
    _MODELS.clear()
    models = load_models()
    chosen = [choose(models.get(n, [])) for n in set(numbers)]
    fetch_shapes(sorted({m["id"] for m in chosen if m}, key=int), log=log)


def backfill(ym, log=print):
    path = os.path.join(REPO, "data", f"asteroids-{ym}.json")
    d = json.load(open(path))
    prepare([e["asteroid"]["number"] for e in d["events"]], log)
    n = 0
    for e in d["events"]:
        e["shape"] = shape_record(e)
        n += e["shape"] is not None
    with open(path + ".part", "w") as f:
        json.dump(d, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(path + ".part", path)
    log(f"   {ym}: {n} of {len(d['events'])} events drawn with a DAMIT shape")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "tables":
        fetch_tables()
    elif len(sys.argv) >= 3 and sys.argv[1] == "check":
        fetch_check([tuple(a.split(":")) for a in sys.argv[2:]])
    elif len(sys.argv) >= 3 and sys.argv[1] == "month":
        for ym in sys.argv[2:]:
            backfill(ym)
    else:
        raise SystemExit(__doc__)
