"""
Lunar occultations of catalogue stars, month by month — the data behind occult.alokm.com's
"Moon and stars" diary, which computes every occultation for the reader's own lat/lon.

  catalog   merge Gaia DR3 (G <= 9.5, |ecliptic lat| < 7 deg) with Hipparcos-2 for the stars Gaia cannot
            solve (the brightest ones, and 2-parameter solutions), name them from the Yale Bright Star
            Catalogue, write catalog/moonband.csv (committed, so months regenerate from DE431 alone).
  month     data/moon-stars-<YYYY-MM>.json: per UTC day the Moon's and Sun's astrometric geocentric GCRS
            vectors as polynomials (degree 8 / 4), the GCRS->ITRS rotation at the day's start and Earth's
            barycentric velocity; and every star whose geocentric closest approach to the Moon that month
            is within the Moon's reach (semidiameter + horizontal parallax), with its astrometric direction.
            Mean limb. `MonthModel` below is the Python mirror of the page's JS solver; `--validate` checks
            it against in-the-sky.org's 2017-01-09 Aldebaran times and against direct Skyfield searches.

Raw inputs (ephemeris/catalog/, gitignored): gaia_dr3_moonband_g9.5.csv (ESA Gaia archive),
hipparcos2_dec31_hp9.8.csv (Gaia archive public.hipparcos_newreduction), bsc5_catalog.gz (CDS V/50).

Usage (repo root):
  .venv/bin/python engine/star_occultations.py catalog
  .venv/bin/python engine/star_occultations.py month 2026-10 [--validate]
  .venv/bin/python engine/star_occultations.py range 2026-09 2028-12
"""

import argparse
import csv
import datetime as dt
import gzip
import json
import math
import os
import random
import sys

import numpy as np
from skyfield.api import Star, load, load_file, wgs84
from skyfield.framelib import itrs
from skyfield.searchlib import find_discrete

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from ephem_paths import DE431, EPHEM_DIR, REPO, require_de431  # noqa: E402

RAW = os.path.join(EPHEM_DIR, "catalog")
CATALOG = os.path.join(REPO, "catalog", "moonband.csv")
OUT_DIR = os.path.join(REPO, "data")

R_MOON_KM, R_EARTH_KM, C_KMS = 1737.4, 6378.137, 299792.458
ERA_RATE = 360.98564736629 / 1440.0          # deg per minute
BAND_DEG, G_LIMIT = 7.0, 9.5
MOON_DEG, SUN_DEG = 8, 4
EPS = math.radians(23.4392911)

GREEK = {"Alp": "α", "Bet": "β", "Gam": "γ", "Del": "δ", "Eps": "ε", "Zet": "ζ", "Eta": "η", "The": "θ",
         "Iot": "ι", "Kap": "κ", "Lam": "λ", "Mu": "μ", "Nu": "ν", "Xi": "ξ", "Omi": "ο", "Pi": "π",
         "Rho": "ρ", "Sig": "σ", "Tau": "τ", "Ups": "υ", "Phi": "φ", "Chi": "χ", "Psi": "ψ", "Ome": "ω"}
COMMON = {1457: "Aldebaran", 3982: "Regulus", 5056: "Spica", 6134: "Antares", 2990: "Pollux",
          1165: "Alcyone", 1142: "Electra", 1145: "Taygeta", 1149: "Maia", 1156: "Merope", 1178: "Atlas",
          1180: "Pleione", 1791: "Elnath", 5531: "Zubenelgenubi", 4825: "Porrima", 7121: "Nunki",
          5984: "Acrab", 5953: "Dschubba", 4689: "Zaniah"}


# ======================================================================================
# catalogue
# ======================================================================================

def ecliptic_lat(ra_deg, dec_deg):
    ra, dec = np.radians(ra_deg), np.radians(dec_deg)
    return np.degrees(np.arcsin(np.sin(dec) * np.cos(EPS) - np.cos(dec) * np.sin(EPS) * np.sin(ra)))


def g_to_v(g, bp_rp):
    """Gaia DR3 photometric relation (Riello et al. 2021): G - V as a cubic in BP-RP."""
    if bp_rp is None:
        return g + 0.1
    x = min(5.0, max(-0.5, bp_rp))
    return g - (-0.02704 + 0.01424 * x - 0.2156 * x * x + 0.01426 * x ** 3)


def _f(s, default=None):
    return float(s) if s not in ("", None) else default


def read_bsc5():
    stars = []
    with gzip.open(os.path.join(RAW, "bsc5_catalog.gz"), "rt", encoding="latin-1") as f:
        for line in f:
            line = line.rstrip("\n").ljust(200)
            if not line[75:77].strip():
                continue
            hr = int(line[0:4])
            name = line[4:14]
            ra = (int(line[75:77]) + int(line[77:79]) / 60 + float(line[79:83]) / 3600) * 15
            dec = (-1 if line[83] == "-" else 1) * (int(line[84:86]) + int(line[86:88]) / 60 + int(line[88:90]) / 3600)
            vmag = _f(line[102:107].strip())
            flam, bayer, sup, con = name[0:3].strip(), name[3:6].strip(), name[6:7].strip(), name[7:10].strip()
            if bayer in GREEK:
                label = f"{GREEK[bayer]}{sup} {con}"
            elif flam:
                label = f"{flam} {con}"
            else:
                label = f"HR {hr}"
            if hr in COMMON:
                label = f"{COMMON[hr]} ({label})"
            stars.append((hr, ra, dec, vmag, label))
    return stars


def build_catalog():
    gaia = list(csv.DictReader(open(os.path.join(RAW, "gaia_dr3_moonband_g9.5.csv"))))
    hip_rows = list(csv.DictReader(open(os.path.join(RAW, "hipparcos2_dec31_hp9.8.csv"))))
    hip = {}
    for r in hip_rows:
        ra, dec = float(r["ra"]), float(r["dec"])
        if abs(float(ecliptic_lat(ra, dec))) < BAND_DEG and float(r["hp_mag"]) <= G_LIMIT + 0.3:
            hip[r["hip"]] = r

    out, used_hip, dropped = [], set(), 0

    def from_hip(r):
        return dict(id=f"HIP {r['hip']}", src="H", vmag=float(r["hp_mag"]), ra=float(r["ra"]), dec=float(r["dec"]),
                    epoch=1991.25, pmra=_f(r["pm_ra"], 0.0), pmdec=_f(r["pm_de"], 0.0), plx=_f(r["plx"], 0.0), rv=0.0,
                    hip=r["hip"], tyc="")

    for r in gaia:
        g = float(r["phot_g_mean_mag"])
        has_ast = r["parallax"] != ""
        h = r["hip"]
        if h and h in hip and (not has_ast or g < 4.0):
            out.append(from_hip(hip[h])); used_hip.add(h); continue
        if not has_ast and g < 6.0:
            dropped += 1                           # 2-parameter bright sources: often artefacts near bright stars
            continue
        if h:
            used_hip.add(h)
        out.append(dict(id=f"Gaia DR3 {r['source_id']}", src="G" if has_ast else "G2",
                        vmag=round(g_to_v(g, _f(r["bp_rp"])), 2), ra=float(r["ra"]), dec=float(r["dec"]),
                        epoch=2016.0, pmra=_f(r["pmra"], 0.0), pmdec=_f(r["pmdec"], 0.0), plx=_f(r["parallax"], 0.0),
                        rv=_f(r["radial_velocity"], 0.0), hip=h, tyc=r["tyc"]))

    # Hipparcos-2 stars with no Gaia row at all (the brightest), unless a Gaia source sits on top of them
    cell = {}
    for i, s in enumerate(out):
        cell.setdefault((int(s["ra"]), int(s["dec"] + 90)), []).append(i)
    added = 0
    for h, r in hip.items():
        if h in used_hip:
            continue
        ra16 = float(r["ra"]) + _f(r["pm_ra"], 0.0) * 24.75 / 3.6e6 / math.cos(math.radians(float(r["dec"])))
        de16 = float(r["dec"]) + _f(r["pm_de"], 0.0) * 24.75 / 3.6e6
        dup = False
        for dra in (-1, 0, 1):
            for dde in (-1, 0, 1):
                for i in cell.get(((int(ra16) + dra) % 360, int(de16 + 90) + dde), []):
                    s = out[i]
                    if (abs(s["ra"] - ra16) * math.cos(math.radians(de16)) * 3600 < 3 and abs(s["dec"] - de16) * 3600 < 3
                            and abs(s["vmag"] - float(r["hp_mag"])) < 1.5):
                        dup = True
        if not dup:
            out.append(from_hip(r)); added += 1

    # names from the Yale Bright Star Catalogue, matched at epoch 2000 within 30" and 1.2 mag
    bsc = read_bsc5()
    bcell = {}
    for b in bsc:
        bcell.setdefault((int(b[1]), int(b[2] + 90)), []).append(b)
    named = 0
    for s in out:
        yrs = 2000.0 - s["epoch"]
        ra0 = s["ra"] + s["pmra"] * yrs / 3.6e6 / math.cos(math.radians(s["dec"]))
        de0 = s["dec"] + s["pmdec"] * yrs / 3.6e6
        best = None
        for dra in (-1, 0, 1):
            for dde in (-1, 0, 1):
                for b in bcell.get(((int(ra0) + dra) % 360, int(de0 + 90) + dde), []):
                    if b[3] is None:
                        continue
                    sep = math.hypot((b[1] - ra0) * math.cos(math.radians(de0)), b[2] - de0) * 3600
                    if sep < 30 and abs(b[3] - s["vmag"]) < 1.2 and (best is None or sep < best[0]):
                        best = (sep, b)
        if best:
            s["hr"], s["label"] = best[1][0], best[1][4]; named += 1
        else:
            s["hr"] = ""
            s["label"] = f"HIP {s['hip']}" if s["hip"] else (f"TYC {s['tyc']}" if s["tyc"] else s["id"])

    out.sort(key=lambda s: (s["ra"], s["dec"]))
    fields = ["id", "label", "vmag", "src", "ra", "dec", "epoch", "pmra", "pmdec", "plx", "rv", "hip", "tyc", "hr"]
    os.makedirs(os.path.dirname(CATALOG), exist_ok=True)
    with open(CATALOG, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for s in out:
            w.writerow({k: (round(s[k], 9) if k in ("ra", "dec") else s[k]) for k in fields})
    print(f"catalog: {len(out)} stars ({sum(1 for s in out if s['src']=='G')} Gaia, {sum(1 for s in out if s['src']=='G2')} Gaia 2-param, "
          f"{sum(1 for s in out if s['src']=='H')} Hipparcos-2, {added} of them with no Gaia row); dropped {dropped} bright 2-param; "
          f"{named} named from BSC5 -> {os.path.relpath(CATALOG, REPO)} ({os.path.getsize(CATALOG)//1024} KB)")
    for s in sorted(out, key=lambda s: s["vmag"])[:12]:
        print(f"   V {s['vmag']:5.2f}  {s['src']:2s}  {s['label']:28s} beta {float(ecliptic_lat(s['ra'], s['dec'])):+.2f}")


def load_catalog():
    return list(csv.DictReader(open(CATALOG)))


def skyfield_stars(rows, ts):
    """Skyfield Star objects, one per epoch group, and the row order they cover."""
    groups = {}
    for i, r in enumerate(rows):
        groups.setdefault(float(r["epoch"]), []).append(i)
    out = []
    for ep, idx in groups.items():
        g = lambda k, idx=idx: np.array([float(rows[i][k]) for i in idx])
        out.append((idx, Star(ra_hours=g("ra") / 15.0, dec_degrees=g("dec"), ra_mas_per_year=g("pmra"),
                              dec_mas_per_year=g("pmdec"), parallax_mas=np.maximum(g("plx"), 1e-3),
                              radial_km_per_s=g("rv"), epoch=ts.J(ep).tt)))
    return out


def star_units(rows, ts, earth, t):
    """Astrometric geocentric unit vectors (GCRS) of every catalogue star at time t: (N, 3)."""
    u = np.zeros((len(rows), 3))
    e = earth.at(t)
    for idx, st in skyfield_stars(rows, ts):
        p = e.observe(st).position.km
        u[idx] = (p / np.linalg.norm(p, axis=0)).T
    return u


# ======================================================================================
# a month
# ======================================================================================

def month_bounds(ym):
    y, m = (int(x) for x in ym.split("-"))
    t0 = dt.datetime(y, m, 1, tzinfo=dt.timezone.utc)
    t1 = dt.datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=dt.timezone.utc)
    return t0, t1


def build_month(ym, rows, ts, eph, log=print):
    """-> (month dict for the page, catalogue ids parallel to its star list)"""
    earth, moon, sun = eph["earth"], eph["moon"], eph["sun"]
    t0, t1 = month_bounds(ym)
    T0 = ts.from_datetime(t0)
    total_min = int((t1 - t0).total_seconds() // 60)
    nseg = (t1 - t0).days + 2                   # segment k covers [(k-1) d, k d) from t0: one pad day each side
    seg0 = -1440
    tau = np.linspace(-1, 1, 49)
    moon_c, sun_c, R0s, ves = [], [], [], []
    worst = 0.0
    for k in range(nseg):
        mins = seg0 + 1440 * k + (tau + 1) * 720
        tt = ts.tt_jd(T0.tt + mins / 1440.0)
        e = earth.at(tt)
        vm = e.observe(moon).position.km
        vs = e.observe(sun).position.km
        cm = [np.polynomial.polynomial.polyfit(tau, vm[a], MOON_DEG) for a in range(3)]
        cs = [np.polynomial.polynomial.polyfit(tau, vs[a], SUN_DEG) for a in range(3)]
        for a in range(3):
            worst = max(worst, np.max(np.abs(np.polynomial.polynomial.polyval(tau, cm[a]) - vm[a])) / np.median(np.linalg.norm(vm, axis=0)))
        moon_c.append([[float(f"{x:.10g}") for x in c] for c in cm])
        sun_c.append([[float(f"{x:.9g}") for x in c] for c in cs])
        tk = ts.tt_jd(T0.tt + (seg0 + 1440 * k) / 1440.0)
        R0s.append([round(float(x), 12) for x in itrs.rotation_at(tk).ravel()])
        ves.append([round(float(x), 7) for x in earth.at(ts.tt_jd(T0.tt + (seg0 + 1440 * k + 720) / 1440.0)).velocity.km_per_s])
    assert np.degrees(worst) * 3600 < 1e-3, f"moon fit {np.degrees(worst)*3600} arcsec"

    d = {"schema": 2, "month": ym, "t0": t0.strftime("%Y-%m-%dT%H:%M:%SZ"), "total_min": total_min,
         "seg0_min": seg0, "moon_deg": MOON_DEG, "sun_deg": SUN_DEG, "era_rate_deg_per_min": ERA_RATE,
         "moon": moon_c, "sun": sun_c, "R0": R0s, "v_earth": ves,
         "moon_radius_km": R_MOON_KM, "earth_a_km": 6378.137, "earth_f": 1 / 298.257223563}
    model = MonthModel(d)

    mins = np.arange(-180, total_min + 180, 1.0)
    P = model.moon_geo(mins)
    dist = np.linalg.norm(P, axis=1)
    U = P / dist[:, None]
    hourly = slice(0, len(mins), 60)
    S = star_units(rows, ts, earth, ts.tt_jd(T0.tt + total_min / 2880.0))
    found = []
    for a in range(0, len(rows), 3000):
        cosm = S[a:a + 3000] @ U[hourly].T
        k = np.argmax(cosm, axis=1)
        sep = np.degrees(np.arccos(np.clip(cosm[np.arange(len(k)), k], -1, 1)))
        for j in np.nonzero(sep < 1.95)[0]:
            i = a + j
            c = 60 * k[j]
            w = slice(max(0, c - 90), min(len(mins), c + 91))
            cs_ = U[w] @ S[i]
            q = int(np.argmax(cs_))
            if 0 < q < len(cs_) - 1:
                y0, y1, y2 = [math.degrees(math.acos(min(1.0, float(v)))) for v in cs_[q - 1:q + 2]]
                den = y0 - 2 * y1 + y2
                off = 0.5 * (y0 - y2) / den if den > 1e-12 else 0.0
                smin = y1 - 0.25 * (y0 - y2) * off
            else:
                off, smin = 0.0, math.degrees(math.acos(min(1.0, float(cs_[q]))))
            m_star = float(mins[w][q] + off)
            dd = float(np.interp(m_star, mins, dist))
            reach = math.degrees(math.asin(R_MOON_KM / dd) + math.asin(R_EARTH_KM / dd)) + 0.02
            if smin < reach and 0 <= m_star < total_min:
                found.append((m_star, i))
    found.sort()
    d["stars"] = {"label": [rows[i]["label"] for _, i in found],
                  "vmag": [round(float(rows[i]["vmag"]), 1) for _, i in found],
                  "u": [round(float(x), 9) for _, i in found for x in S[i]],
                  "t": [int(round(m * 10)) for m, _ in found]}          # tenths of a minute from t0
    ids = [rows[i]["id"] for _, i in found]
    log(f"{ym}: {len(found)} stars occultable somewhere on Earth; moon fit {np.degrees(worst)*3600:.2e} arcsec")
    return d, ids


# ======================================================================================
# the solver — mirrored line for line by the page's JS
# ======================================================================================

# What an observer can realistically see: V limits at the dark / bright limb per instrument; the
# dark-limb limit loses 2.5 mag * (illuminated fraction - 0.4) in moonglare, 1 mag in twilight.
INSTRUMENTS = {"eye": ("Naked eye", 3.0, 1.0), "binoculars": ("Binoculars", 6.5, 3.5),
               "scope80": ("Small telescope (80 mm)", 8.5, 5.5), "scope200": ("Telescope (200 mm)", 9.5, 7.0)}


class MonthModel:
    def __init__(self, d):
        self.d = d
        self.moon = np.array(d["moon"])            # (nseg, 3, deg+1)
        self.dmoon = np.array([[np.polynomial.polynomial.polyder(c) for c in seg] for seg in self.moon])
        self.sun = np.array(d["sun"])
        self.R0 = np.array(d["R0"]).reshape(-1, 3, 3)
        self.ve = np.array(d["v_earth"])
        self.seg0 = d["seg0_min"]

    @staticmethod
    def star_list(d):
        st = d["stars"]
        u = np.array(st["u"]).reshape(-1, 3)
        return [(st["label"][i], st["vmag"][i], u[i], st["t"][i] / 10.0) for i in range(len(st["label"]))]

    def _seg(self, m):
        m = np.asarray(m, dtype=float)
        k = np.clip(((m - self.seg0) // 1440).astype(int), 0, len(self.moon) - 1)
        local = m - (self.seg0 + 1440 * k)
        return k, local, local / 720.0 - 1.0

    def moon_geo(self, m):
        k, _, tau = self._seg(m)
        out = np.zeros((len(k), 3))
        for kk in np.unique(k):
            sel = k == kk
            for a in range(3):
                out[sel, a] = np.polynomial.polynomial.polyval(tau[sel], self.moon[kk, a])
        return out

    def observer(self, lat, lon):
        a, f = self.d["earth_a_km"], self.d["earth_f"]
        e2 = f * (2 - f)
        la, lo = math.radians(lat), math.radians(lon)
        N = a / math.sqrt(1 - e2 * math.sin(la) ** 2)
        self.r = np.array([N * math.cos(la) * math.cos(lo), N * math.cos(la) * math.sin(lo), N * (1 - e2) * math.sin(la)])
        self.up = np.array([math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la)])
        w = math.radians(ERA_RATE) / 60.0
        self.wxr = np.array([-w * self.r[1], w * self.r[0], 0.0])
        self.east = np.array([-math.sin(lo), math.cos(lo), 0.0])
        self.north = np.array([-math.sin(la) * math.cos(lo), -math.sin(la) * math.sin(lo), math.cos(la)])
        return self

    def to_gcrs(self, m, v):
        """R(t)^T v for ITRS vector v at minutes m (vectorised) — the rotation geom_vec uses."""
        m = np.atleast_1d(np.asarray(m, dtype=float))
        k, local, _ = self._seg(m)
        th = np.radians(ERA_RATE * local)
        c, s = np.cos(th), np.sin(th)
        w = np.stack([c * v[0] - s * v[1], s * v[0] + c * v[1], np.full_like(c, v[2])], axis=1)
        return np.einsum("nji,nj->ni", self.R0[k], w)

    def geom_vec(self, m):
        """Vectorised over minutes m: topocentric apparent Moon unit vectors (n,3), distance (n),
        Sun unit vectors (n,3), local up (n,3), observer barycentric velocity (n,3)."""
        m = np.atleast_1d(np.asarray(m, dtype=float))
        k, local, tau = self._seg(m)
        th = np.radians(ERA_RATE * local)
        c, s = np.cos(th), np.sin(th)

        def to_gcrs(v):            # R(t)^T v = R0^T Rz(th)^T v
            w = np.stack([c * v[0] - s * v[1], s * v[0] + c * v[1], np.full_like(c, v[2])], axis=1)
            return np.einsum("nji,nj->ni", self.R0[k], w)

        obs, up = to_gcrs(self.r), to_gcrs(self.up)
        vobs = self.ve[k] + to_gcrs(self.wxr)
        P = np.zeros((len(m), 3)); V = np.zeros((len(m), 3)); SN = np.zeros((len(m), 3))
        for kk in np.unique(k):
            sel = k == kk
            for a in range(3):
                P[sel, a] = np.polynomial.polynomial.polyval(tau[sel], self.moon[kk, a])
                V[sel, a] = np.polynomial.polynomial.polyval(tau[sel], self.dmoon[kk, a])
                SN[sel, a] = np.polynomial.polynomial.polyval(tau[sel], self.sun[kk, a])
        V = V / (720 * 60) + self.ve[k]
        dv = P - obs
        dist = np.linalg.norm(dv, axis=1)
        dv = dv + V * (np.sum(obs * dv, axis=1) / dist / C_KMS)[:, None]
        um = dv / np.linalg.norm(dv, axis=1)[:, None]
        um = um + vobs / C_KMS
        um = um / np.linalg.norm(um, axis=1)[:, None]
        sv = SN - obs
        return um, dist, sv / np.linalg.norm(sv, axis=1)[:, None], up, vobs

    def margin_arcsec(self, m, u):
        um, dist, _, _, vobs = self.geom_vec([m])
        us = u + vobs[0] / C_KMS
        us = us / np.linalg.norm(us)
        return (math.degrees(math.acos(max(-1.0, min(1.0, float(um[0] @ us))))) - math.degrees(math.asin(R_MOON_KM / dist[0]))) * 3600

    def contacts(self, star, step=2.0):
        """Scalar reference: D / R minutes (or none), and the closest margin — used by validation."""
        u, tg = star[2], star[3]
        grid = np.arange(tg - 180, tg + 180 + 1e-9, step)
        vals = [self.margin_arcsec(mm, u) for mm in grid]
        out = {}
        for i in range(1, len(grid)):
            if (vals[i] < 0) != (vals[i - 1] < 0):
                lo, hi, flo = grid[i - 1], grid[i], vals[i - 1]
                for _ in range(24):
                    mid = 0.5 * (lo + hi)
                    if (self.margin_arcsec(mid, u) < 0) == (flo < 0):
                        lo = mid
                    else:
                        hi = mid
                out["D" if vals[i] < 0 else "R"] = 0.5 * (lo + hi)
        b = int(np.argmin(vals))
        return out, float(grid[b]), float(vals[b])

    def events(self, stars, lat, lon, step=2.0, graze_arcsec=3.0):
        """Every occultation (and near-graze) of the month's stars for one place, with the circumstances
        at each contact. The page's JS does exactly this."""
        self.observer(lat, lon)
        total = self.d["total_min"]
        grid = np.arange(-180, total + 180 + 1e-9, step)
        UM, DIST, SUNU, UP, VOBS = self.geom_vec(grid)
        SDM = np.degrees(np.arcsin(R_MOON_KM / DIST)) * 3600
        half = int(round(180 / step))
        out = []
        for label, vmag, u, tg in stars:
            c = int(round((tg + 180) / step))
            w = slice(max(0, c - half), min(len(grid), c + half + 1))
            us = u[None, :] + VOBS[w] / C_KMS
            us = us / np.linalg.norm(us, axis=1)[:, None]
            marg = np.degrees(np.arccos(np.clip(np.sum(UM[w] * us, axis=1), -1, 1))) * 3600 - SDM[w]
            j = int(np.argmin(marg))
            if marg[j] > graze_arcsec:
                continue
            cons = {}
            for i in range(1, len(marg)):
                if (marg[i] < 0) != (marg[i - 1] < 0):
                    lo, hi, flo = grid[w][i - 1], grid[w][i], marg[i - 1]
                    for _ in range(22):
                        mid = 0.5 * (lo + hi)
                        if (self.margin_arcsec(mid, u) < 0) == (flo < 0):
                            lo = mid
                        else:
                            hi = mid
                    cons["D" if marg[i] < 0 else "R"] = 0.5 * (lo + hi)
            ev = {"label": label, "vmag": vmag, "min_margin_arcsec": float(marg[j]),
                  "graze": bool(abs(marg[j]) < graze_arcsec), "contacts": {}}
            for key, mm in (cons.items() if cons else [("C", float(grid[w][j]))]):
                ev["contacts"][key] = self.circumstances(mm, u)
            out.append(ev)
        return out

    def circumstances(self, m, u):
        um, dist, su, up, vobs = [x[0] for x in self.geom_vec([m])]
        us = u + vobs / C_KMS
        us = us / np.linalg.norm(us)
        z = np.array([0.0, 0.0, 1.0])
        east = np.cross(z, um); east /= np.linalg.norm(east)
        north = np.cross(um, east)
        pa = lambda v: (math.degrees(math.atan2((v - um) @ east, (v - um) @ north)) + 360) % 360
        pa_star, pa_sun = pa(us), pa(su)
        diff = abs((pa_star - pa_sun + 180) % 360 - 180)                 # 0 = sub-solar limb point
        elong = math.degrees(math.acos(max(-1.0, min(1.0, float(um @ su)))))
        eg, ng = self.to_gcrs([m], self.east)[0], self.to_gcrs([m], self.north)[0]
        az = (math.degrees(math.atan2(float(um @ eg), float(um @ ng))) + 360) % 360
        # unrounded, exactly like the JS: rounding here flips borderline visibility checks and display digits
        return {"m": float(m), "pa": pa_star, "limb": "bright" if diff < 90 else "dark",
                "cusp": abs(90 - diff), "illum": (1 - math.cos(math.radians(elong))) / 2,
                "moon_alt": math.degrees(math.asin(float(um @ up))), "moon_az": az,
                "sun_alt": math.degrees(math.asin(float(su @ up)))}


def visible(ev, instrument):
    """Contacts of `ev` a reader with `instrument` can plausibly observe."""
    _, dark, bright = INSTRUMENTS[instrument]
    keep = {}
    for key, c in ev["contacts"].items():
        if key == "C" or c["moon_alt"] < 5:
            continue
        if c["sun_alt"] > -6 and ev["vmag"] > 1.5:
            continue
        lim = bright if c["limb"] == "bright" else dark - 2.5 * max(0.0, c["illum"] - 0.4)
        if -12 < c["sun_alt"] <= -6:
            lim -= 1.0
        if ev["vmag"] <= lim:
            keep[key] = c
    return keep


# ======================================================================================
# validation
# ======================================================================================

def validate(ym, d, ids, rows, ts, eph, samples=30, seed=1):
    earth, moon = eph["earth"], eph["moon"]
    T0 = ts.from_datetime(month_bounds(ym)[0])
    model = MonthModel(d)
    stars = MonthModel.star_list(d)
    by_id = {r["id"]: r for r in rows}
    rng = random.Random(seed)
    worst, worst_fast, n, tries = 0.0, 0.0, 0, 0
    while n < samples and tries < 4000:
        tries += 1
        i = rng.randrange(len(stars))
        s = stars[i]
        lat, lon = rng.uniform(-60, 60), rng.uniform(-180, 180)
        cons, _, _ = model.observer(lat, lon).contacts(s)
        if not cons:
            continue
        r = by_id[ids[i]]
        st = Star(ra_hours=float(r["ra"]) / 15, dec_degrees=float(r["dec"]), ra_mas_per_year=float(r["pmra"]),
                  dec_mas_per_year=float(r["pmdec"]), parallax_mas=max(float(r["plx"]), 1e-3),
                  radial_km_per_s=float(r["rv"]), epoch=ts.J(float(r["epoch"])).tt)
        obs = earth + wgs84.latlon(lat, lon)

        def hidden(t):
            o = obs.at(t)
            mm = o.observe(moon).apparent()
            ss = o.observe(st).apparent()
            return mm.separation_from(ss).degrees < np.degrees(np.arcsin(R_MOON_KM / mm.distance().km))
        hidden.step_days = 1.0 / 1440
        a, b = ts.tt_jd(T0.tt + (s[3] - 180) / 1440), ts.tt_jd(T0.tt + (s[3] + 180) / 1440)
        tt, vv = find_discrete(a, b, hidden, epsilon=1e-8)
        ref = {("D" if v else "R"): (t.tt - T0.tt) * 1440 for t, v in zip(tt, vv)}
        fast = model.events([s], lat, lon)
        fast_c = {k: c["m"] for k, c in fast[0]["contacts"].items()} if fast else {}
        for key, mval in cons.items():
            if key in ref:
                worst = max(worst, abs(mval - ref[key]) * 60)
            if key in fast_c:
                worst_fast = max(worst_fast, abs(fast_c[key] - ref.get(key, mval)) * 60)
        if set(ref) != set(cons) or set(fast_c) != set(cons):
            print(f"   contact-set mismatch {s[0]} at {lat:.2f},{lon:.2f}: mirror {sorted(cons)} fast {sorted(fast_c)} skyfield {sorted(ref)}")
        n += 1
    print(f"   mirror vs Skyfield topocentric: {n} events, worst {worst:.3f} s; vectorised solver worst {worst_fast:.3f} s")
    return max(worst, worst_fast)


def validate_aldebaran(rows, ts, eph):
    """Whole pipeline on 2017-01 against in-the-sky.org's published disappearances (mean limb)."""
    d, _ = build_month("2017-01", rows, ts, eph, log=lambda s: print("   " + s))
    model = MonthModel(d)
    ald = [s for s in MonthModel.star_list(d) if s[0].startswith("Aldebaran") and 8 * 1440 <= s[3] < 10 * 1440]
    assert ald, "Aldebaran missing from the 2017-01 candidates"
    pub = {"Jaipur": (26.9124, 75.7873, "2017-01-09T12:56:22Z"), "New Delhi": (28.6139, 77.2090, "2017-01-09T13:00:09Z"),
           "Silchar": (24.8333, 92.7789, "2017-01-09T13:26:29Z")}
    worst = 0.0
    for city, (lat, lon, iso) in pub.items():
        ev = model.events(ald, lat, lon)
        t = dt.datetime(2017, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(minutes=ev[0]["contacts"]["D"]["m"])
        diff = (t - dt.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)).total_seconds()
        worst = max(worst, abs(diff))
        print(f"   Aldebaran D {city:9s}: {t.strftime('%H:%M:%S')} UTC vs published {iso[11:19]}  ({diff:+.1f} s)")
    return worst


def counts(ym, lat, lon, name):
    d = json.load(open(os.path.join(OUT_DIR, f"moon-stars-{ym}.json")))
    model = MonthModel(d)
    import time
    t = time.time()
    evs = model.events(MonthModel.star_list(d), lat, lon)
    dt_s = time.time() - t
    occ = [e for e in evs if any(k in e["contacts"] for k in "DR")]
    print(f"{name} {ym}: {len(occ)} occultations + {len(evs) - len(occ)} near-graze misses computed in {dt_s:.1f} s")
    for key, (label, _, _) in INSTRUMENTS.items():
        rows_ = [e for e in occ if visible(e, key)]
        print(f"   {label:26s}: {len(rows_):4d} events  e.g. " +
              "; ".join(f"{e['label']} V{e['vmag']}" for e in sorted(rows_, key=lambda e: e['vmag'])[:3]))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("catalog")
    mp = sub.add_parser("month"); mp.add_argument("ym"); mp.add_argument("--validate", action="store_true")
    rp = sub.add_parser("range"); rp.add_argument("start"); rp.add_argument("end")
    cp = sub.add_parser("counts"); cp.add_argument("ym"); cp.add_argument("lat", type=float); cp.add_argument("lon", type=float); cp.add_argument("name")
    args = ap.parse_args()
    if args.cmd == "catalog":
        build_catalog(); return
    if args.cmd == "counts":
        counts(args.ym, args.lat, args.lon, args.name); return
    require_de431()
    ts = load.timescale()
    eph = load_file(DE431)
    rows = load_catalog()
    months = [args.ym] if args.cmd == "month" else []
    if args.cmd == "range":
        y, m = (int(x) for x in args.start.split("-"))
        while f"{y}-{m:02d}" <= args.end:
            months.append(f"{y}-{m:02d}"); y, m = y + (m == 12), m % 12 + 1
    os.makedirs(OUT_DIR, exist_ok=True)
    for ym in months:
        d, ids = build_month(ym, rows, ts, eph)
        path = os.path.join(OUT_DIR, f"moon-stars-{ym}.json")
        with open(path, "w") as f:
            json.dump(d, f, ensure_ascii=False, separators=(",", ":"))
        print(f"   wrote {os.path.relpath(path, REPO)} ({os.path.getsize(path)//1024} KB)")
        if getattr(args, "validate", False):
            w1 = validate_aldebaran(rows, ts, eph)
            w2 = validate(ym, d, ids, rows, ts, eph)
            assert w1 <= 5 and w2 <= 0.5, (w1, w2)
            print("   VALIDATION OK")


if __name__ == "__main__":
    main()
