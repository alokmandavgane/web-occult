"""
Lunar occultation of a graha or a bright star: everything one event page needs,
computed from DE431 for one entry of seed.json.

Two stages, the eclipse pattern:

  place-independent  geocentric closest approach + the "any part hidden" region
                     on Earth, its night sub-region, and the boundary split into
                     north/south graze limits and moonrise/moonset curves
  place-dependent    contact times for the audience's city list (full Skyfield
                     search per city, the same math validated on Aldebaran)

The region and limit lines come from a lat/lon grid: for every grid point the
minimum over the window of (separation - moon_sd - target_sd), with the Moon
below the horizon masked out, refined by a parabola through the three samples
around the discrete minimum (separation^2 is a parabola under uniform relative
motion, so this is near-exact). Topocentric vectors are built by hand from the
geocentric apparent vectors and an ITRS->GCRS rotation — one 3x3 per time step,
so a 70k-point grid costs seconds, not minutes.

Mean limb only (R = 1737.4 km): contact times carry ~+/-2 s of limb
topography; limit lines are as good as the grid (~+/-10 km at 0.125 deg).

Usage (from the repo root, with the repo's venv):
  .venv/bin/python engine/occultation_event.py venus-2026-09-14
  .venv/bin/python engine/occultation_event.py --scan 2026-09-11 2029-01-01 --seed   # candidates for the seed

Writes data/<slug>.json and data/<slug>-limb.json. DE431 comes from OCCULT_DE431 (see ephem_paths.py).
"""

import argparse
import datetime as dt
import json
import os
import sys
import zoneinfo

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from skyfield.api import Star, load, load_file, wgs84
from skyfield.framelib import itrs
from skyfield.searchlib import find_discrete, find_minima

from lunar_limb import Limb, face_samples, position_angle as pa_of_vectors  # noqa: E402  (LRO LOLA silhouette; see lunar_limb.py)

_LIMB = None


def limb():
    global _LIMB
    if _LIMB is None:
        _LIMB = Limb()
    return _LIMB

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SEED = os.path.join(REPO, "seed.json")
OUT_DIR = os.path.join(REPO, "data")
from ephem_paths import DE431 as EPHEMERIS_FILE, require_map_file  # noqa: E402

R_MOON_KM = 1737.4      # IAU mean radius — the "mean limb"
R_EARTH_KM = 6378.137
WINDOW_H = 3.0          # +/- hours around geocentric closest approach
STEP_MIN = 3.0          # grid time step
GRAZE_ALT_DEG = 3.0     # boundary vertex with the Moon higher than this = graze limit, else horizon curve

# --- targets -----------------------------------------------------------------
# planets: ephemeris key, mean radius km
GRAHAS = {
    "mercury": ("mercury", 2439.7),
    "venus": ("venus", 6051.8),
    "mars": ("mars barycenter", 3389.5),
    "jupiter": ("jupiter barycenter", 69911.0),
    "saturn": ("saturn barycenter", 58232.0),
}
# stars: SIMBAD/Hipparcos-2 ICRS J2000 astrometry; `nakshatra` is the yogatara index, kept for the scan.
# Only Rohini has been validated against published occultation timings so far.
STARS = {
    "aldebaran": dict(common="Aldebaran", hip=21421, nakshatra=3, mag=0.87,
                      ra=(4, 35, 55.23907), dec=(16, 30, 33.4885),
                      pm_ra=63.45, pm_dec=-188.94, plx=48.94, rv=54.398),
    "antares": dict(common="Antares", hip=80763, nakshatra=17, mag=1.06,
                    ra=(16, 29, 24.46), dec=(-26, 25, 55.2),
                    pm_ra=-12.11, pm_dec=-23.30, plx=5.89, rv=-3.4),
    "spica": dict(common="Spica", hip=65474, nakshatra=13, mag=0.97,
                  ra=(13, 25, 11.579), dec=(-11, 9, 40.75),
                  pm_ra=-42.35, pm_dec=-30.67, plx=13.06, rv=1.0),
    "regulus": dict(common="Regulus", hip=49669, nakshatra=9, mag=1.36,
                    ra=(10, 8, 22.311), dec=(11, 58, 1.95),
                    pm_ra=-248.73, pm_dec=5.59, plx=41.13, rv=5.9),
    "alcyone": dict(common="Alcyone", hip=17702, nakshatra=2, mag=2.87,
                    ra=(3, 47, 29.077), dec=(24, 6, 18.49),
                    pm_ra=19.34, pm_dec=-43.67, plx=8.09, rv=5.4),
}


class Target:
    def __init__(self, key, eph):
        self.key = key
        if key in GRAHAS:
            ek, self.radius_km = GRAHAS[key]
            self.body = eph[ek]
            self.kind = "graha"
            self.names = {"common": ek.split()[0].capitalize()}
            self.astrometry = None
        elif key in STARS:
            s = STARS[key]
            self.body = Star(ra_hours=s["ra"], dec_degrees=s["dec"],
                             ra_mas_per_year=s["pm_ra"], dec_mas_per_year=s["pm_dec"],
                             parallax_mas=s["plx"], radial_km_per_s=s["rv"])
            self.radius_km = 0.0
            self.kind = "star"
            self.names = {"common": s["common"]}
            self.astrometry = {k: s[k] for k in ("hip", "mag", "pm_ra", "pm_dec", "plx", "rv")}
        else:
            raise SystemExit(f"unknown target {key!r}; one of {sorted(GRAHAS) + sorted(STARS)}")


# --- helpers -----------------------------------------------------------------

def sd_deg(radius_km, dist_km):
    return np.degrees(np.arcsin(radius_km / dist_km))


def iso(t):
    return t.utc_iso(places=0)


def geocentric_min(ts, earth, moon, target, t0, t1):
    def f(t):
        e = earth.at(t)
        return e.observe(moon).apparent().separation_from(e.observe(target.body).apparent()).degrees
    f.step_days = 0.05
    tt, vv = find_minima(t0, t1, f, epsilon=1e-7)
    if len(tt) == 0:
        raise SystemExit("no closest approach in the window")
    i = int(np.argmin(vv))
    return tt[i], float(vv[i])


def grid_field(ts, eph, earth, moon, target, t_min, bbox, grid_deg):
    """Minimum over the window of (sep - sd_moon - sd_target) per grid point,
    Moon-below-horizon masked, plus per-point diagnostics at that minimum."""
    lon0, lat0, lon1, lat1 = bbox
    lons = np.round(np.arange(lon0, lon1 + 1e-9, grid_deg), 6)
    lats = np.round(np.arange(lat0, lat1 + 1e-9, grid_deg), 6)
    LON, LAT = np.meshgrid(lons, lats)
    lon_r, lat_r = np.radians(LON.ravel()), np.radians(LAT.ravel())
    n = lon_r.size

    # observer ITRS position + local up vector (geodetic), km
    obs_itrs = wgs84.latlon(LAT.ravel(), LON.ravel()).itrs_xyz.km          # (3, n)
    up_itrs = np.vstack([np.cos(lat_r) * np.cos(lon_r), np.cos(lat_r) * np.sin(lon_r), np.sin(lat_r)])

    steps = int(round(2 * WINDOW_H * 60 / STEP_MIN)) + 1
    times = ts.tt_jd(t_min.tt + (np.arange(steps) - (steps - 1) / 2) * STEP_MIN / 1440.0)
    sun = eph["sun"]

    sep = np.full((steps, n), np.inf, dtype=np.float32)   # sep - sd_moon - sd_target, deg; inf = Moon down
    for i in range(steps):
        t = times[i]
        e = earth.at(t)
        m_geo = e.observe(moon).position.km            # GCRS, km, astrometric (see fit_elements)
        s_geo = e.observe(target.body).position.km
        R = itrs.rotation_at(t)                                     # GCRS -> ITRS
        obs = R.T @ obs_itrs                                        # (3, n) GCRS
        up = R.T @ up_itrs
        m_top = m_geo[:, None] - obs                                # (3, n)
        m_dist = np.linalg.norm(m_top, axis=0)
        m_unit = m_top / m_dist
        alt_m = np.degrees(np.arcsin(np.einsum("ij,ij->j", m_unit, up)))
        if target.kind == "graha":
            s_top = s_geo[:, None] - obs
            s_dist = np.linalg.norm(s_top, axis=0)
            s_unit = s_top / s_dist
            sd_t = sd_deg(target.radius_km, s_dist)
        else:                                                       # star: parallax already in the apparent vector
            s_unit = np.broadcast_to((s_geo / np.linalg.norm(s_geo))[:, None], (3, n))
            sd_t = 0.0
        cosang = np.clip(np.einsum("ij,ij->j", m_unit, s_unit), -1, 1)
        d = np.degrees(np.arccos(cosang)) - sd_deg(R_MOON_KM, m_dist) - sd_t
        sep[i] = np.where(alt_m > 0, d, np.inf)

    # discrete minimum + parabolic refinement of (sep + sd)^2 ~ parabola. We refine
    # the raw margin d directly; near the minimum d is smooth enough for 3-min steps.
    i_min = np.argmin(sep, axis=0)
    idx = np.arange(n)
    d0 = sep[i_min, idx]
    m_field = d0.astype(np.float64)
    t_off = np.zeros(n)
    inner = (i_min > 0) & (i_min < steps - 1)
    ii = i_min[inner]
    fm, f0, fp = sep[ii - 1, idx[inner]], sep[ii, idx[inner]], sep[ii + 1, idx[inner]]
    ok = np.isfinite(fm) & np.isfinite(fp)
    denom = fp - 2 * f0 + fm
    good = ok & (denom > 1e-9)
    # vertex of the parabola through (−1,fm),(0,f0),(+1,fp), in step units
    x = np.zeros_like(f0, dtype=np.float64)
    x[good] = -(fp[good] - fm[good]) / (2 * denom[good])
    fmin = f0.astype(np.float64)
    fmin[good] = f0[good] - (fp[good] - fm[good]) ** 2 / (8 * denom[good])
    m_field[inner] = fmin
    t_off[inner] = x * STEP_MIN / 1440.0

    # diagnostics at the minimum: Moon alt, Sun alt, north/south side — one pass per distinct step
    alt_m_at = np.full(n, np.nan)
    alt_s_at = np.full(n, np.nan)
    north_at = np.zeros(n, dtype=np.int8)
    for i in np.unique(i_min):
        sel = idx[i_min == i]
        t = times[i]
        e = earth.at(t)
        m_geo = e.observe(moon).position.km
        s_geo = e.observe(target.body).position.km
        sun_geo = e.observe(sun).position.km
        R = itrs.rotation_at(t)
        obs = R.T @ obs_itrs[:, sel]
        up = R.T @ up_itrs[:, sel]
        m_top = m_geo[:, None] - obs
        m_unit = m_top / np.linalg.norm(m_top, axis=0)
        s_top = (s_geo[:, None] - obs) if target.kind == "graha" else np.broadcast_to(s_geo[:, None], m_top.shape)
        s_unit = s_top / np.linalg.norm(s_top, axis=0)
        sun_unit = (sun_geo[:, None] - obs)
        sun_unit = sun_unit / np.linalg.norm(sun_unit, axis=0)
        alt_m_at[sel] = np.degrees(np.arcsin(np.einsum("ij,ij->j", m_unit, up)))
        alt_s_at[sel] = np.degrees(np.arcsin(np.einsum("ij,ij->j", sun_unit, up)))
        # target north of the Moon's centre (GCRS declination) => it grazes the NORTH limb
        north_at[sel] = np.where(np.arcsin(s_unit[2]) > np.arcsin(m_unit[2]), 1, -1)

    shape = LON.shape
    return dict(lons=lons, lats=lats,
                m=m_field.reshape(shape), alt_m=alt_m_at.reshape(shape),
                alt_s=alt_s_at.reshape(shape), north=north_at.reshape(shape),
                t_at=(times.tt[i_min] + t_off).reshape(shape))


def contours(field):
    """Region rings (any part hidden, Moon up), night rings, and labelled boundary lines."""
    import contourpy
    lons, lats = field["lons"], field["lats"]
    m = np.where(np.isfinite(field["m"]), field["m"], 10.0)
    alt_s = np.where(np.isfinite(field["alt_s"]), field["alt_s"], 90.0)

    def rings_of(z):
        cg = contourpy.contour_generator(x=lons, y=lats, z=z, fill_type=contourpy.FillType.OuterOffset)
        pts_list, off_list = cg.filled(-1e9, 0.0)
        rings = []
        for pts, off in zip(pts_list, off_list):
            for a, b in zip(off[:-1], off[1:]):
                ring = pts[a:b]
                rings.append([[round(float(y), 2), round(float(x), 2)] for x, y in ring])
        return rings

    region = rings_of(m)
    night = rings_of(np.maximum(m, alt_s + 6.0))          # negative only where hidden AND Sun < -6

    cg = contourpy.contour_generator(x=lons, y=lats, z=m, line_type=contourpy.LineType.Separate)
    lines = cg.lines(0.0)
    dlon, dlat = lons[1] - lons[0], lats[1] - lats[0]
    labelled = []
    for line in lines:
        cur_kind, cur = None, []
        for x, y in line:
            j = int(np.clip(round((x - lons[0]) / dlon), 0, len(lons) - 1))
            i = int(np.clip(round((y - lats[0]) / dlat), 0, len(lats) - 1))
            # the vertex sits on the boundary: look at the nearest *inside* cell for the geometry
            alt = field["alt_m"][i, j]
            north = field["north"][i, j]
            if not np.isfinite(alt) or alt <= GRAZE_ALT_DEG:
                kind = "horizon"
            else:
                kind = "north" if north > 0 else "south"
            if kind != cur_kind and cur:
                labelled.append({"kind": cur_kind, "points": cur})
                cur = [cur[-1]]
            cur_kind = kind
            cur.append([round(float(y), 2), round(float(x), 2)])
        if cur:
            labelled.append({"kind": cur_kind, "points": cur})
    # drop 2-point stubs produced by label flicker at junctions
    labelled = [l for l in labelled if len(l["points"]) > 2]
    return region, night, labelled


def position_angle(frm, to):
    """PA of `to` as seen from `frm`, degrees east of north (equatorial)."""
    ra1, dec1, _ = frm.radec()
    ra2, dec2, _ = to.radec()
    a1, d1, a2, d2 = ra1.radians, dec1.radians, ra2.radians, dec2.radians
    y = np.cos(d2) * np.sin(a2 - a1)
    x = np.sin(d2) * np.cos(d1) - np.cos(d2) * np.sin(d1) * np.cos(a2 - a1)
    return float(np.degrees(np.arctan2(y, x)) % 360.0)


POLY_DEG = 6
ERA_RATE_DEG_PER_MIN = 360.98564736629 / 1440.0     # Earth rotation angle rate (UT1)


def fit_elements(ts, eph, earth, moon, target, t_min):
    """Everything a browser needs to compute local circumstances for ANY lat/lon: the
    geocentric apparent GCRS vectors (km) of the Moon, the target and the Sun over the
    window as degree-POLY_DEG polynomials in tau = (t - t0) / half_window, plus the
    GCRS->ITRS rotation at t0. Over six hours precession/nutation/polar motion are constant
    to well under 0.01", so R(t) = Rz(ERA rate * dt) . R0 — one matrix and one rate.
    The same first-order topocentric math as grid_field(), so it inherits its validation."""
    half_d = WINDOW_H / 24.0
    n = 61
    tt = ts.tt_jd(t_min.tt + np.linspace(-half_d, half_d, n))
    tau = np.linspace(-1, 1, n)
    e = earth.at(tt)
    # ASTROMETRIC geocentric vectors. The solver rebuilds the topocentric APPARENT direction itself:
    # light-time difference geocentre->observer (the body moves ~30 km/s barycentrically during those
    # <=21 ms: up to 0.33") and first-order aberration for the observer's barycentric velocity. Without
    # both, contacts drift 0.1-0.25" from Skyfield's topocentric apparent — seconds at a graze.
    vecs = {"moon": e.observe(moon).position.km,
            "target": e.observe(target.body).position.km,
            "sun": e.observe(eph["sun"]).position.km}
    v_earth = earth.at(t_min).velocity.km_per_s
    out = {"t0": t_min.utc_iso(places=3), "half_hours": WINDOW_H, "deg": POLY_DEG,
           "v_earth_km_s": [round(float(v), 9) for v in v_earth],
           "era_rate_deg_per_min": ERA_RATE_DEG_PER_MIN,
           "R0": [round(float(v), 12) for v in itrs.rotation_at(t_min).ravel()],
           "moon_radius_km": R_MOON_KM, "target_radius_km": target.radius_km,
           "earth_a_km": 6378.137, "earth_f": 1 / 298.257223563}
    worst = 0.0     # angular: residual / distance, so a star at 1e14 km is judged like the Moon
    for k, v in vecs.items():
        coef = []
        for axis in range(3):
            c = np.polynomial.polynomial.polyfit(tau, v[axis], POLY_DEG)
            resid = float(np.max(np.abs(np.polynomial.polynomial.polyval(tau, c) - v[axis])))
            worst = max(worst, resid / float(np.median(np.linalg.norm(v, axis=0))))
            coef.append([float(x) for x in c])
        out[k] = coef
    out["fit_residual_arcsec"] = round(float(np.degrees(worst) * 3600), 6)
    assert worst < 5e-9, f"polynomial fit residual {np.degrees(worst)*3600:.5f} arcsec"
    return out


def _poly(coef, tau):
    return np.array([np.polynomial.polynomial.polyval(tau, c) for c in coef])


def _parse_t0(el):
    return dt.datetime.strptime(el["t0"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=dt.timezone.utc)


def element_geometry(el, lat, lon):
    """geom(minutes from t0) -> sep / semidiameters / altitudes, from the elements alone.
    Mirrors the JS in build_pages.py line for line."""
    half_min = el["half_hours"] * 60.0
    a, f = el["earth_a_km"], el["earth_f"]
    e2 = f * (2 - f)
    lat_r, lon_r = np.radians(lat), np.radians(lon)
    N = a / np.sqrt(1 - e2 * np.sin(lat_r) ** 2)
    r_itrs = np.array([N * np.cos(lat_r) * np.cos(lon_r), N * np.cos(lat_r) * np.sin(lon_r), N * (1 - e2) * np.sin(lat_r)])
    up_itrs = np.array([np.cos(lat_r) * np.cos(lon_r), np.cos(lat_r) * np.sin(lon_r), np.sin(lat_r)])
    R0 = np.array(el["R0"]).reshape(3, 3)

    C = 299792.458
    v_earth = np.array(el["v_earth_km_s"])
    omega = np.radians(el["era_rate_deg_per_min"]) / 60.0          # rad/s about the ITRS z axis

    def geom(m):                       # m = minutes from t0
        tau = m / half_min
        th = np.radians(el["era_rate_deg_per_min"] * m)
        Rz = np.array([[np.cos(th), np.sin(th), 0], [-np.sin(th), np.cos(th), 0], [0, 0, 1]])
        RT = (Rz @ R0).T               # ITRS -> GCRS
        obs, up = RT @ r_itrs, RT @ up_itrs
        east_g = RT @ np.array([-np.sin(lon_r), np.cos(lon_r), 0.0])
        north_g = RT @ np.array([-np.sin(lat_r) * np.cos(lon_r), -np.sin(lat_r) * np.sin(lon_r), np.cos(lat_r)])
        v_obs = v_earth + RT @ np.cross([0, 0, omega], r_itrs)     # observer's barycentric velocity

        def topo_dir(coef):
            P = _poly(coef, tau)
            v = _poly([np.polynomial.polynomial.polyder(c) for c in coef], tau) / (half_min * 60) + v_earth
            d = P - obs
            dist = np.linalg.norm(d)
            # light left the body earlier/later than for the geocentre by (obs . dir)/c; it moved meanwhile
            d = d + v * (obs @ (d / dist)) / C
            u = d / np.linalg.norm(d)
            u = u + v_obs / C                                         # first-order aberration
            return u / np.linalg.norm(u), dist

        um, md = topo_dir(el["moon"])
        us, sd_ = topo_dir(el["target"])
        su = _poly(el["sun"], tau) - obs
        sud = np.linalg.norm(su)
        mt, st = um * md, us * sd_
        sep = np.degrees(np.arccos(np.clip(um @ us, -1, 1)))
        sdm = np.degrees(np.arcsin(el["moon_radius_km"] / md))
        sdt = np.degrees(np.arcsin(el["target_radius_km"] / sd_)) if el["target_radius_km"] else 0.0
        return dict(sep=sep, sdm=sdm, sdt=sdt,
                    alt_m=np.degrees(np.arcsin(mt @ up / md)), alt_s=np.degrees(np.arcsin(su @ up / sud)),
                    az_m=np.degrees(np.arctan2(um @ east_g, um @ north_g)) % 360.0)
    return geom


def solve_from_elements(el, lat, lon, step_s=30.0):
    """Reference implementation of the browser solver: contacts (UTC ISO) + diagnostics."""
    t0 = _parse_t0(el)
    half_min = el["half_hours"] * 60.0
    geom = element_geometry(el, lat, lon)

    def state(g):
        return 2 if g["sep"] < g["sdm"] - g["sdt"] else (1 if g["sep"] < g["sdm"] + g["sdt"] else 0)

    grid = np.arange(-half_min, half_min + 1e-9, step_s / 60.0)
    gs = [geom(m) for m in grid]
    contacts, prev = {}, state(gs[0])
    for i in range(1, len(grid)):
        cur = state(gs[i])
        if cur != prev:
            lo, hi = grid[i - 1], grid[i]
            for _ in range(40):
                mid = (lo + hi) / 2
                if state(geom(mid)) == prev:
                    lo = mid
                else:
                    hi = mid
            m = (lo + hi) / 2
            key = {(0, 1): "D1", (0, 2): "D2", (1, 2): "D2", (2, 1): "R1", (2, 0): "R1", (1, 0): "R2"}[(prev, cur)]
            if (prev, cur) == (0, 2):
                contacts["D1"] = m
            if (prev, cur) == (2, 0):
                contacts["R2"] = m
            contacts[key] = m
            prev = cur
    out = {"contacts": {k: (t0 + dt.timedelta(minutes=v)).strftime("%Y-%m-%dT%H:%M:%SZ") for k, v in contacts.items()},
           "contacts_min": contacts}
    i = int(np.argmin([g["sep"] for g in gs]))
    out["closest"] = dict(m=float(grid[i]), **{k: float(v) for k, v in gs[i].items()})
    return out


def exact_limits(ts, eph, earth, moon, target, t_min, limits, log=print):
    """Re-trace each north/south graze limit against the LOLA silhouette. For every vertex
    of the mean-limb line, find the latitude offset at which the closest approach just
    touches the real limb (radius at the target's PA, for that observer's libration)."""
    out = []
    for lim in limits:
        if lim["kind"] not in ("north", "south"):
            continue
        pts = lim["points"][::max(1, len(lim["points"]) // 120)]     # ~120 vertices per line
        exact = []
        for lat0, lon0 in pts:
            def graze_margin(lat):
                obs = earth + wgs84.latlon(lat, lon0)

                def sep(t):
                    o = obs.at(t)
                    return o.observe(moon).apparent().separation_from(o.observe(target.body).apparent()).degrees
                sep.step_days = 0.01
                tm, vm = find_minima(ts.tt_jd(t_min.tt - WINDOW_H / 24), ts.tt_jd(t_min.tt + WINDOW_H / 24), sep, epsilon=1e-6)
                if len(tm) == 0:
                    return 1.0
                i = int(np.argmin(vm))
                t = tm[i]
                o = obs.at(t)
                m = o.observe(moon).apparent()
                sv = o.observe(target.body).apparent()
                mv = m.position.km
                pa = pa_of_vectors(mv / np.linalg.norm(mv), sv.position.km / np.linalg.norm(sv.position.km))
                rk = limb().radius_km(t, mv, pa)
                st = sd_deg(target.radius_km, sv.distance().km) if target.kind == "graha" else 0.0
                return float(vm[i]) - np.degrees(np.arcsin(rk / m.distance().km)) - st   # any contact at all

            lo, hi = lat0 - 0.4, lat0 + 0.4
            f_lo, f_hi = graze_margin(lo), graze_margin(hi)
            if (f_lo < 0) == (f_hi < 0):
                continue
            for _ in range(14):                      # 0.8 deg / 2^14 ~ 5 m
                mid = (lo + hi) / 2
                if (graze_margin(mid) < 0) == (f_lo < 0):
                    lo = mid
                else:
                    hi = mid
            exact.append([round((lo + hi) / 2, 4), round(lon0, 2)])
        if len(exact) > 2:
            shift = [(e[0] - p[0]) * 111.0 for e, p in zip(exact, pts) if abs(e[1] - p[1]) < 1e-6]
            out.append({"kind": lim["kind"], "points": exact,
                        "shift_km": {"min": round(min(shift), 1), "max": round(max(shift), 1)} if shift else None})
            log(f"  exact {lim['kind']} limit: {len(exact)} vertices, moved by {min(shift):+.1f}..{max(shift):+.1f} km vs mean limb")
    return out


LIMB_PA_STEP = 0.1          # deg of position angle (~3 km of limb)
LIMB_NODE_STEP = 0.6        # deg of libration between profile nodes
LIMB_NODES = 2              # nodes each side: 5 x 5 grid, +/-1.2 deg — covers the topocentric spread


def limb_profiles(ts, earth, moon, t_min):
    """The silhouette on a small grid of librations around the geocentric one at t_min, for the
    browser's graze chart: it interpolates to the observer's own topocentric libration. Also the
    ICRF -> MOON_ME rotation at t_min and the Moon's spin rate, so the browser can find that
    libration from the topocentric Moon vector it already computes."""
    L = limb()
    m_geo = earth.at(t_min).observe(moon).apparent().position.km
    R = L.orient.rotation(t_min)
    o0 = R @ (-m_geo / np.linalg.norm(m_geo))                 # sub-Earth direction in the DEM frame
    lat0, lon0 = np.degrees(np.arcsin(o0[2])), np.degrees(np.arctan2(o0[1], o0[0]))
    pa = np.arange(0, 360, LIMB_PA_STEP)
    offsets = [k * LIMB_NODE_STEP for k in range(-LIMB_NODES, LIMB_NODES + 1)]
    profiles = []
    for dlat in offsets:
        row = []
        for dlon in offsets:
            la, lo = np.radians(lat0 + dlat), np.radians(lon0 + dlon)
            o_me = np.array([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)])
            v = -(R.T @ o_me) * np.linalg.norm(m_geo)          # a synthetic Moon vector seen from that libration
            prof = L.profile(t_min, v, pa)
            row.append([int(x) for x in np.round(prof * 100)])  # 10 m units
        profiles.append(row)
    return {"pa_step": LIMB_PA_STEP, "node_step": LIMB_NODE_STEP, "nodes": len(offsets),
            "sub_earth": [round(float(lat0), 4), round(float(lon0), 4)],
            "R_me": [round(float(x), 12) for x in R.ravel()],
            "spin_deg_per_min": 360.0 / (27.321661 * 1440),
            "dem": f"LRO LOLA LDEM_{L.dem.res}", "units": "0.01 km above the 1737.4 km sphere",
            "profiles": profiles}


def local_circumstances(ts, eph, earth, moon, target, t_min, lat, lon, elev_m=0.0):
    """Contacts for one site. D1/D2 = limb first touches / fully hides the target,
    R1/R2 = starts to / fully reappears. A star has only D2 and R1."""
    obs = earth + wgs84.latlon(lat, lon, elevation_m=elev_m)
    sun = eph["sun"]

    def state(t):
        o = obs.at(t)
        m = o.observe(moon).apparent()
        s = o.observe(target.body).apparent()
        sep = m.separation_from(s).degrees
        sm = sd_deg(R_MOON_KM, m.distance().km)
        st = sd_deg(target.radius_km, s.distance().km) if target.kind == "graha" else 0.0
        return np.where(sep < sm - st, 2, np.where(sep < sm + st, 1, 0))
    state.step_days = 0.002

    a, b = ts.tt_jd(t_min.tt - WINDOW_H / 24), ts.tt_jd(t_min.tt + WINDOW_H / 24)
    tt, vv = find_discrete(a, b, state, epsilon=1e-7)
    contacts, prev = {}, 0
    for t, v in zip(tt, vv):
        v = int(v)
        if prev == 0 and v >= 1:
            contacts["D1"] = t
        if prev <= 1 and v == 2:
            contacts["D2"] = t
        if prev == 2 and v <= 1:
            contacts["R1"] = t
        if prev >= 1 and v == 0:
            contacts["R2"] = t
        prev = v

    def at(t):
        o = obs.at(t)
        m = o.observe(moon).apparent()
        s = o.observe(target.body).apparent()
        alt, az, _ = m.altaz()
        return dict(moon_alt=round(float(alt.degrees), 1), moon_az=round(float(az.degrees), 1),
                    sun_alt=round(float(o.observe(sun).apparent().altaz()[0].degrees), 1),
                    sep_arcmin=round(float(m.separation_from(s).degrees * 60), 2),
                    moon_sd_arcmin=round(float(sd_deg(R_MOON_KM, m.distance().km) * 60), 2))

    # Refine each mean-limb contact against the LOLA silhouette: the limb radius at the
    # target's position angle, for THIS observer's libration, at that moment. Root of
    # sep - (R(PA) +/- r_target)/dist near the mean-limb time.
    def limb_margin(t, key):
        o = obs.at(t)
        m = o.observe(moon).apparent()
        sv = o.observe(target.body).apparent()
        mv = m.position.km
        pa = pa_of_vectors(mv / np.linalg.norm(mv), sv.position.km / np.linalg.norm(sv.position.km))
        rk = limb().radius_km(t, mv, pa)
        st = sd_deg(target.radius_km, sv.distance().km) if target.kind == "graha" else 0.0
        edge = np.degrees(np.arcsin(rk / m.distance().km)) + (st if key in ("D1", "R2") else -st)
        return m.separation_from(sv).degrees - edge

    refined = {}
    for key, t_mean in contacts.items():
        lo, hi = ts.tt_jd(t_mean.tt - 60 / 86400), ts.tt_jd(t_mean.tt + 60 / 86400)   # +/- 60 s bracket
        f_lo, f_hi = limb_margin(lo, key), limb_margin(hi, key)
        if (f_lo < 0) == (f_hi < 0):          # relief so large the bracket misses: widen once
            lo, hi = ts.tt_jd(t_mean.tt - 300 / 86400), ts.tt_jd(t_mean.tt + 300 / 86400)
            f_lo, f_hi = limb_margin(lo, key), limb_margin(hi, key)
        if (f_lo < 0) == (f_hi < 0):
            refined[key] = t_mean
            continue
        for _ in range(22):
            mid = ts.tt_jd((lo.tt + hi.tt) / 2)
            if (limb_margin(mid, key) < 0) == (f_lo < 0):
                lo = mid
            else:
                hi = mid
        refined[key] = ts.tt_jd((lo.tt + hi.tt) / 2)
    row = {"contacts": {k: iso(t) for k, t in refined.items()},
           "contacts_mean_limb": {k: iso(t) for k, t in contacts.items()},
           "limb_shift_s": {k: round((refined[k].tt - contacts[k].tt) * 86400, 1) for k in contacts},
           "_contacts_t": contacts}
    if contacts:
        ref = next(contacts[k] for k in ("D2", "D1", "R1", "R2") if k in contacts)
        row.update(at(ref))
        row["at"] = "D2" if "D2" in contacts else next(iter(contacts))
        if "D2" in contacts and "R1" in contacts:
            row["hidden_min"] = round((refined["R1"].tt - refined["D2"].tt) * 1440, 1)
        alts = [at(t)["moon_alt"] for t in contacts.values()]
        row["verdict"] = "visible" if max(alts) > 0 else "moon_down"
    else:
        # closest topocentric approach, for "passes N arcmin from the limb"
        def f(t):
            o = obs.at(t)
            return o.observe(moon).apparent().separation_from(o.observe(target.body).apparent()).degrees
        f.step_days = 0.02
        tm, vm = find_minima(a, b, f, epsilon=1e-6)
        if len(tm):
            i = int(np.argmin(vm))
            row.update(at(tm[i]))
            row["at"] = "closest"
            row["closest"] = iso(tm[i])
            row["verdict"] = "miss" if row["moon_alt"] > 0 else "moon_down"
        else:
            row["verdict"] = "moon_down"
    return row


def load_cities(audience_cfg, region_rings):
    src = audience_cfg["cities"]
    if src == "world":
        # the eclipse app's GeoNames extract (OCCULT_MAP_DIR), sorted by population: name,lat,lng,cc,tz,pop,utcoff,country
        import csv
        out, seen = [], set()
        with open(require_map_file("cities.csv")) as f:
            for row in csv.reader(f):
                name, lat, lon, cc, tz, pop = row[0], float(row[1]), float(row[2]), row[3], row[4], int(row[5] or 0)
                if pop < 1_000_000 or (name, cc) in seen:
                    continue
                seen.add((name, cc))
                out.append({"name": f"{name}, {cc}", "lat": lat, "lon": lon, "tz": tz})
        return out[:400]
    with open(os.path.join(REPO, src)) as f:
        return json.load(f)


def build_event(seed, entry, scan_only=False):
    ts = load.timescale()
    eph = load_file(EPHEMERIS_FILE)
    earth, moon = eph["earth"], eph["moon"]
    target = Target(entry["target"], eph)
    aud = seed["audiences"][entry["audience"]]

    y, mo, d = (int(x) for x in entry["date"].split("-"))
    t_min, min_sep = geocentric_min(ts, earth, moon, target, ts.utc(y, mo, d - 1), ts.utc(y, mo, d + 2))
    e = earth.at(t_min)
    m = e.observe(moon).apparent()
    s = e.observe(target.body).apparent()
    sun = e.observe(eph["sun"]).apparent()
    m_dist = float(m.distance().km)
    reach = sd_deg(R_MOON_KM, m_dist) + sd_deg(R_EARTH_KM, m_dist)
    if min_sep >= reach:
        raise SystemExit(f"closest approach {min_sep:.3f} deg exceeds {reach:.3f}: no occultation anywhere on Earth")
    from skyfield import almanac
    illum = float(almanac.fraction_illuminated(eph, "moon", t_min))
    # age: time since the last new moon
    phases_t, phases_v = almanac.find_discrete(ts.tt_jd(t_min.tt - 32), t_min, almanac.moon_phases(eph))
    new_moons = [t for t, v in zip(phases_t, phases_v) if v == 0]
    age_days = float(t_min.tt - new_moons[-1].tt) if new_moons else None

    print(f"{entry['slug']}: closest approach {iso(t_min)} at {min_sep:.3f} deg (reach {reach:.3f})")

    maps = {}
    for name in dict.fromkeys([entry["audience"], "world"]):
        cfg = seed["audiences"][name]
        field = grid_field(ts, eph, earth, moon, target, t_min, cfg["bbox"], cfg["grid_deg"])
        region, night, limits = contours(field)
        maps[name] = {"bbox": cfg["bbox"], "grid_deg": cfg["grid_deg"],
                      "region": region, "region_night": night, "limits": limits}
        if name == entry["audience"]:
            maps[name]["limits_exact"] = exact_limits(ts, eph, earth, moon, target, t_min, limits, log=print)
        print(f"  map {name}: {len(region)} region rings, {len(night)} night rings, "
              f"{len(limits)} boundary pieces ({', '.join(sorted({l['kind'] for l in limits}))})")

    elements = fit_elements(ts, eph, earth, moon, target, t_min)
    print(f"  elements: degree {POLY_DEG} fit, worst residual {elements['fit_residual_arcsec']} arcsec")

    cities = []
    worst_dt = 0.0
    for c in load_cities(aud, maps[entry["audience"]]["region"]):
        row = {"name": c["name"], "lat": c["lat"], "lon": c["lon"], "tz": c.get("tz", aud["tz"])}
        row.update(local_circumstances(ts, eph, earth, moon, target, t_min, c["lat"], c["lon"]))
        # the browser recomputes every location from the elements: at each Skyfield contact instant the
        # element geometry must sit on the limb too. Angular, so a grazing chord cannot inflate it.
        geom = element_geometry(elements, c["lat"], c["lon"])
        for k, t_c in row.pop("_contacts_t").items():
            g = geom((t_c.tt - t_min.tt) * 1440.0)
            edge = g["sdm"] + (g["sdt"] if k in ("D1", "R2") else -g["sdt"])
            worst_dt = max(worst_dt, abs(g["sep"] - edge) * 3600)
        cities.append(row)
    assert worst_dt <= 0.05, f"element geometry off the limb by {worst_dt:.3f} arcsec at a contact"
    print(f"  element geometry at Skyfield contact instants: worst {worst_dt:.3f} arcsec")
    n_vis = sum(1 for c in cities if c["verdict"] == "visible")
    shifts = [abs(v) for c in cities for v in c.get("limb_shift_s", {}).values()]
    print(f"  cities: {len(cities)} computed, {n_vis} see it; limb corrections up to {max(shifts) if shifts else 0:.1f} s")

    out = {
        "schema": 1,
        "slug": entry["slug"],
        "audience": entry["audience"],
        "note": entry.get("note", ""),
        "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "engine": {"ephemeris": os.path.basename(EPHEMERIS_FILE), "limb": f"LRO LOLA LDEM_{limb().dem.res} silhouette (contacts, exact limits); mean sphere elsewhere",
                   "moon_radius_km": R_MOON_KM,
                   "delta_t_s": round(float(t_min.delta_t), 1), "grid_time_step_min": STEP_MIN},
        "target": {"kind": target.kind, "key": target.key, "names": target.names,
                   "radius_km": target.radius_km, "astrometry": target.astrometry},
        "geocentric": {
            "t_min": iso(t_min), "min_sep_deg": round(min_sep, 4),
            "moon_dist_km": round(m_dist), "moon_sd_arcmin": round(sd_deg(R_MOON_KM, m_dist) * 60, 2),
            "target_sd_arcsec": round(sd_deg(target.radius_km, float(s.distance().km)) * 3600, 1) if target.kind == "graha" else 0,
            "target_illum_pct": round(float(almanac.fraction_illuminated(eph, GRAHAS[target.key][0], t_min)) * 100)
                                if target.kind == "graha" else None,
            "illum_pct": round(illum * 100, 1), "moon_age_days": round(age_days, 1) if age_days else None,
            "elongation_deg": round(float(sun.separation_from(s).degrees), 1),
            "target_mag": target.astrometry["mag"] if target.astrometry else None,
            # PA of the bright limb (Moon -> Sun) and of the target at closest approach, degrees E of N:
            # the limb diagram draws the phase from these
            "bright_limb_pa": round(position_angle(m, sun), 1),
            "target_pa": round(position_angle(m, s), 1),
        },
        "window": {"start": iso(ts.tt_jd(t_min.tt - WINDOW_H / 24)), "end": iso(ts.tt_jd(t_min.tt + WINDOW_H / 24))},
        "elements": elements,
        "lib": face_samples(ts, earth, moon, t_min),
        "maps": maps,
        "cities": cities,
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    lp = limb_profiles(ts, earth, moon, t_min)
    with open(os.path.join(OUT_DIR, f"{entry['slug']}-limb.json"), "w") as f:
        json.dump(lp, f, separators=(",", ":"))
    print(f"  limb profiles: {lp['nodes']}x{lp['nodes']} librations x {int(360 / LIMB_PA_STEP)} PAs")
    path = os.path.join(OUT_DIR, f"{entry['slug']}.json")
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"  wrote {os.path.relpath(path)} ({os.path.getsize(path)//1024} KB)")


def scan(start, end, as_seed=False):
    """Candidate list for the seed: every occultable-anywhere close approach, with an Ujjain flag.
    --seed prints JSON entries instead: planets everywhere, stars only when India sees them at night."""
    ts = load.timescale()
    eph = load_file(EPHEMERIS_FILE)
    earth, moon = eph["earth"], eph["moon"]
    ujjain = earth + wgs84.latlon(23.1765, 75.7885)
    t0 = ts.utc(*[int(x) for x in start.split("-")])
    t1 = ts.utc(*[int(x) for x in end.split("-")])
    rows = []
    for key in list(GRAHAS) + list(STARS):
        tg = Target(key, eph)

        def f(t, tg=tg):
            e = earth.at(t)
            return e.observe(moon).apparent().separation_from(e.observe(tg.body).apparent()).degrees
        f.step_days = 0.08
        tt, vv = find_minima(t0, t1, f, epsilon=1e-6)
        for t, v in zip(tt, vv):
            d = float(earth.at(t).observe(moon).apparent().distance().km)
            if v >= sd_deg(R_MOON_KM, d) + sd_deg(R_EARTH_KM, d):
                continue
            row = local_circumstances(ts, eph, earth, moon, tg, t, 23.1765, 75.7885)
            row.pop("_contacts_t", None)
            flag = row["verdict"]
            if flag == "visible":
                flag += " (day)" if row["sun_alt"] > -6 else " (night)"
            india_night = row["verdict"] == "visible" and row["sun_alt"] < -6
            india_day = row["verdict"] == "visible" and row["sun_alt"] >= -6
            entry = {"slug": f"{key}-{t.utc_strftime('%Y-%m-%d')}", "target": key, "date": t.utc_strftime("%Y-%m-%d"),
                     "audience": "india" if row["verdict"] in ("visible", "miss") else "world",
                     "note": (f"The Moon hides {tg.names['common']}"
                              + (" — visible from India in a dark sky." if india_night else
                                 " — visible from India in daylight." if india_day else
                                 " — a near miss from central India; the limit line decides." if row["verdict"] == "miss" else
                                 " — not visible from India."))}
            keep = tg.kind == "graha" or india_night
            rows.append((t.tt, f"{t.utc_strftime('%Y-%m-%d %H:%M')}  {key:<10} {tg.names['common']:<10} "
                                f"geo {v:5.2f} deg   Ujjain: {flag}", entry, keep))
    if as_seed:
        print(json.dumps([e for _, _, e, k in sorted(rows, key=lambda r: r[0]) if k], indent=2, ensure_ascii=False))
        return
    for _, r, _, _ in sorted(rows, key=lambda r: r[0]):
        print(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--scan", nargs=2, metavar=("START", "END"))
    ap.add_argument("--seed", action="store_true", help="with --scan: print seed entries as JSON")
    args = ap.parse_args()
    if args.scan:
        scan(*args.scan, as_seed=args.seed)
        return
    with open(SEED) as f:
        seed = json.load(f)
    entries = [e for e in seed["events"] if args.slug in (None, e["slug"])]
    if not entries:
        raise SystemExit(f"no seed entry {args.slug!r}")
    for e in entries:
        build_event(seed, e)


if __name__ == "__main__":
    main()
