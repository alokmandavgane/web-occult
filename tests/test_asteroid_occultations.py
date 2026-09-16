"""Pins the asteroid-occultation engine (engine/asteroid_occultations.py) and the monthly asteroid data.

  * Orbit elements -> state: the Minor Planet Center publishes (78) Diana's orbit both as Keplerian elements and as a
    Cartesian state at one epoch; the conversion reproduces the state to a metre.
  * Paths against Occult4, as IOTA-India published them for September 2026 (Occult's predictions of 2026 Aug 4.7).
    With MPC's orbits — Occult integrates MPCORB — and the same Gaia DR3 stars, for five events from a 21 km/s to a
    38 km/s shadow: the published centre points lie within half of Occult's own 1-sigma of our centre line, as a
    rigid shift (under 1 km of spread over up to 17,000 km of path), the published limit points lie the asteroid's
    radius beyond it, and the shadow reaches and leaves the Earth within a minute of Occult's stated times.
  * The screen: the hourly prefilter that decides which (asteroid, star) pairs are ever solved, against a plain
    two-minute search over the same two days — nothing it finds may be missing from the screen's candidates.
  * The browser's solver: `local()` from the page's compact elements against the full model, to 0.02 km and 0.1 s.
  * The month files: unique ids, and elements that put each event's listed best point on its centre line.

The reference values are a few published points per event, used only to check — never as input.
The engine tests need DE431 (OCCULT_DE431, default ../kaalshodh/api/de431t.bsp) and skip without it.
"""

import glob
import importlib.util
import json
import math
import os

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, "..")
DE431 = os.environ.get("OCCULT_DE431") or os.path.join(REPO, "..", "kaalshodh", "api", "de431t.bsp")
needs_de431 = pytest.mark.skipif(not os.path.exists(DE431), reason="DE431 not found (set OCCULT_DE431)")
GAIA_NPZ = os.path.join(REPO, "ephemeris", "catalog", "gaia_g12.5.npz")
needs_gaia = pytest.mark.skipif(not os.path.exists(GAIA_NPZ), reason="Gaia catalogue not packed (run `stars`)")

# Two days the month file has listed events on, for the screen test: (asteroid number, Gaia source id) that must survive.
SCREEN_DAYS = ((2026, 9, 15), (2026, 9, 17))
SCREEN_EVENTS = [("78", 2614110850911121024), ("13244", 2866855180766895616), ("21766", 64895512733555328)]

MPC_DIANA = {"epoch_mjd": 61200.0,
             "KEP": [2.6225475578081094, 0.203533016557825, 8.6794845586997, 333.2839129211138, 153.3191772060466, 201.4250701462879],
             "CAR": [2.44196861788914, -1.95646973119368, -0.0991909655772148, 0.00498642011359828, 0.00704608716666272, 0.00130300686941676]}

# Occult4 via IOTA-India: centre points [lat, lon], one point on each limit, the diameter and 1-sigma it used, and the
# minutes its title gives for the shadow on the Earth. MPC heliocentric ecliptic states; Gaia DR3 astrometry.
REF = {
    "430 Hybris": {"number": "430", "date": (2026, 9, 6), "window": ("19:51", "20:13"), "dia": 33, "sigma_mas": 17,
                   "mpc": (61200.0, [2.33233812742212, -1.32527611625838, 0.687763639117249, 0.00273242313466587, 0.0101172480066706, -0.000270291769342142]),
                   "gaia": (347.78503886173206, 19.872416997077842, 27.907925259208515, 2.873179871527866, 3.2169222300100504, -38.21954),
                   "centre": [[-19.5798, -23.5], [14.8225, 59], [16.8715, 141.25]], "limits": [[14.6679, 59], [14.9045, 58.75]]},
    "509 Iolanda": {"number": "509", "date": (2026, 9, 12), "window": ("13:52", "13:56"), "dia": 58, "sigma_mas": 13,
                    "mpc": (61200.0, [-3.03110553713635, -1.42050345718435, -0.197448515631423, 0.00371506643342762, -0.00778498263423286, 0.00232647572505722]),
                    "gaia": (206.47463571744208, -10.496135599378121, 24.461955203825024, -16.12188617579146, 2.543716312811119, 24.44444),
                    "centre": [[27.7537, 69.25], [28.6787, 79.5], [30.2883, 89.75]], "limits": [[29.0555, 79.5], [28.3357, 79.75]]},
    "78 Diana": {"number": "78", "date": (2026, 9, 15), "window": ("22:20", "22:37"), "dia": 125, "sigma_mas": 12,
                 "mpc": (61200.0, MPC_DIANA["CAR"]),
                 "gaia": (331.70208492082185, -10.669527908151903, -6.661153727923906, -9.799969905260717, 0.6566824558704105, -2.4926739),
                 "centre": [[-2.0532, -62.5], [4.3667, 12.75], [22.2751, 87.75]], "limits": [[3.7187, 12.5], [4.9075, 12.5]]},
    "42 Isis": {"number": "42", "date": (2026, 9, 22), "window": ("23:20", "23:25"), "dia": 113, "sigma_mas": 19,
                "mpc": (61000.0, [0.12607668841191, 2.66649389584688, 0.0217811158148268, -0.00960805235592455, 0.0024772643742526, 0.00146787824186859]),
                "gaia": (155.79850554862068, 16.146641844632992, -48.001502386573456, -24.934346008585404, 0.8445465955586711, 304.16095),
                "centre": [[19.0956, 68.75], [21.9715, 80], [24.0558, 91.25]], "limits": [[22.4962, 80], [21.5021, 80.25]]},
    "1 Ceres": {"number": "1", "date": (2026, 9, 28), "window": ("23:11", "23:21"), "dia": 952, "sigma_mas": 25,
                "mpc": (61000.0, [2.72077753170503, 0.92580050470423, -0.471929778443405, -0.003553885052683, 0.00909332165722517, 0.000942585268159591]),
                "gaia": (106.53390865500606, 23.18497679616793, -4.41334382885953, -2.7380979459500425, 0.6105480148376466, 59.411026),
                "centre": [[3.5732, 20], [18.7853, 56.75], [28.2441, 93.25]], "limits": [[23.0901, 55.75], [14.4445, 57.5]]},
}


# JPL Horizons, fetched 2026-09-16: heliocentric ICRF vectors (CENTER='500@10', REF_PLANE='FRAME'), au and au/day, for
# the same JPL solutions catalog/asteroids.csv carries. T0 is the catalogue's epoch; T1 is 448 days on, the end of the
# months the site covers. None of these four is one of the four perturbers, so they are pure test particles here.
HORIZONS_T0, HORIZONS_T1 = 2461200.5, 2461648.5
HORIZONS = {
    "78": {  # 78 Diana (A863 EA), JPL#133
        "state0": [2.44196856673481, -1.75556982455064, -0.869245157302715, 0.00498642027486249, 0.00594635203172114, 0.00399825843754287],
        "pos1": [1.52167342543679, 1.52987181002781, 1.04765446490437]},
    "512": {  # 512 Taurinensis (A903 MC), JPL#105
        "state0": [-0.677859047936536, -1.97767245472902, -0.647091370326794, 0.0114849809924518, -6.47196424081642e-05, -0.00183193645376462],
        "pos1": [0.136006947042048, 1.91428577979064, 0.708211439264122]},
    "2363": {  # 2363 Cebriones (1977 TJ3), JPL#88 — a Trojan, out at 5 au
        "state0": [1.68574668443498, 5.1566356337303, 0.0722675119362276, -0.00656976792901498, 0.00225094891164758, -0.00209510008610907],
        "pos1": [-1.38228930206385, 5.17555038913126, -0.822268038428063]},
    "324": {  # 324 Bamberga (A892 DA), JPL#178 — eccentric, 0.34
        "state0": [0.751758568939821, -1.84798837355229, -1.10169023328124, 0.00966392997632642, 0.00568844002191187, 0.00486049884471324],
        "pos1": [-0.63737076310961, 1.98985187639471, 1.207375311444]},
}


def _engine():
    spec = importlib.util.spec_from_file_location("asteroid_occultations", os.path.join(REPO, "engine", "asteroid_occultations.py"))
    A = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(A)
    return A


def _ecl_to_eq(A, v):
    ce, se = math.cos(A.EPS_J2000), math.sin(A.EPS_J2000)
    R = np.array([[1, 0, 0], [0, ce, -se], [0, se, ce]])
    return np.concatenate([R @ v[:3], R @ v[3:]])


def test_elements_reproduce_the_mpc_state():
    A = _engine()
    X = A.kepler_to_state(*[[v] for v in MPC_DIANA["KEP"][:1]], *[[v] for v in MPC_DIANA["KEP"][1:]])[0]
    ref = _ecl_to_eq(A, np.array(MPC_DIANA["CAR"]))
    assert np.linalg.norm(X[:3] - ref[:3]) * A.AU_KM < 0.001
    assert np.linalg.norm(X[3:] - ref[3:]) * A.AU_KM * 1000 / 86400 < 1e-6


@pytest.fixture(scope="module")
def env():
    A = _engine()
    ctx = A.Ctx()
    rows = A.load_orbits()
    big = [r for r in rows if r["number"] in A.BIG]
    return A, ctx, big


def _event(env, ref):
    """The MPC orbit integrated with the engine's force model (the big four perturbers, minus the target itself)."""
    A, ctx, big = env
    keep = [r for r in big if r["number"] != ref["number"]]
    gm = [A.BIG[r["number"]] for r in keep]
    jd_big = float(keep[0]["epoch_tdb"])
    sun = lambda jd: np.concatenate([ctx.sun.at(ctx.ts.tdb_jd(jd)).position.au, ctx.sun.at(ctx.ts.tdb_jd(jd)).velocity.au_per_d])
    Xb = A.orbit_states(keep) + sun(jd_big)[None, :]
    jd_ep = ref["mpc"][0] + 2400000.5
    if abs(jd_ep - jd_big) > 1e-9:
        Xb = A.integrate(ctx, Xb, jd_big, jd_ep, pidx=range(len(keep)), pgm=gm, keep=False)
    X0 = np.vstack([Xb, _ecl_to_eq(A, np.array(ref["mpc"][1])) + sun(jd_ep)])
    h0, m0 = map(int, ref["window"][0].split(":"))
    h1, m1 = map(int, ref["window"][1].split(":"))
    jd_guess = ctx.ts.utc(*ref["date"], 0, (h0 * 60 + m0 + h1 * 60 + m1) / 2).tdb
    t, Xs = A.integrate(ctx, X0, jd_ep, jd_guess + 1, pidx=range(len(keep)), pgm=gm)
    ra, dec, pmra, pmdec, plx, rv = ref["gaia"]
    st = {"source_id": 0, "ra": ra, "dec": dec, "pmra": pmra, "pmdec": pmdec, "plx": plx, "rv": rv}
    rows = [None] * len(keep) + [{"R_km": ref["dia"] / 2}]
    ev = A.Event(ctx, A.Dense(t, Xs), rows, len(keep), st)
    ev.locate(jd_guess)
    ev.track()
    return A, ctx, ev, jd_guess


@needs_de431
@pytest.mark.parametrize("name", list(REF))
def test_path_matches_occult4(env, name):
    ref = REF[name]
    A, ctx, ev, _ = _event(env, ref)
    c = np.array(ref["centre"])
    d = ev.closest(c[:, 0], c[:, 1])[:, 1]
    km_per_mas = float(np.linalg.norm(ev.fine["a"][len(ev.fine["a"]) // 2])) * A.MAS
    offset = float(np.mean(d))
    assert abs(offset) < 0.5 * ref["sigma_mas"] * km_per_mas, (name, offset, ref["sigma_mas"] * km_per_mas)
    assert np.std(d) < 1.0, (name, d)
    lim = np.array(ref["limits"])
    dl = ev.closest(lim[:, 0], lim[:, 1])[:, 1] - offset
    assert np.all(np.abs(np.abs(dl) - ref["dia"] / 2) < 1.0), (name, dl)
    assert dl[0] * dl[1] < 0
    on = np.isfinite(ev.ground([0.0])[0, :, 0])
    jd_on = ev.fine["jd"][on]
    for jd, hm in ((jd_on[0], ref["window"][0]), (jd_on[-1], ref["window"][1])):
        t = ctx.ts.tdb_jd(jd).utc_datetime()
        h, m = map(int, hm.split(":"))
        minutes = t.hour * 60 + t.minute + t.second / 60 - (h * 60 + m)
        assert abs(minutes) <= 1.0, (name, t, hm)


@needs_de431
def test_browser_solver_matches_the_full_model(env):
    A, ctx, ev, _ = _event(env, REF["42 Isis"])
    el = ev.elements()
    t0 = ctx.ts.utc(*[int(x) for x in el["t0"][:10].split("-")], int(el["t0"][11:13]), int(el["t0"][14:16]), int(el["t0"][17:19])).tdb
    rng = np.random.default_rng(7)
    base = np.array(REF["42 Isis"]["centre"])
    pts = np.vstack([base[i] + rng.normal(0, 1.5, (8, 2)) for i in range(len(base))])
    full = ev.closest(pts[:, 0], pts[:, 1])
    for (lat, lon), (jd, d, _) in zip(pts, full):
        s = A.local(el, lat, lon)
        assert abs(s["d"] - d) < 0.02 and abs(s["tau"] - (jd - t0) * 86400) < 0.1, (lat, lon, s, d)


@needs_de431
def test_integrator_matches_horizons(env):
    """The engine's own RK4 — DE431's planets and Moon, Ceres/Pallas/Vesta/Hygiea, the Sun's relativistic term — against
    JPL's integration of the very same state, 448 days on. Both ends are heliocentric through the same ephemeris, so what
    is left is the force model and the stepping: about a hundred metres."""
    A, ctx, big = env
    gm = [A.BIG[r["number"]] for r in big]
    sun = lambda jd: np.concatenate([ctx.sun.at(ctx.ts.tdb_jd(jd)).position.au, ctx.sun.at(ctx.ts.tdb_jd(jd)).velocity.au_per_d])
    S0, S1 = sun(HORIZONS_T0), sun(HORIZONS_T1)
    Xb = A.orbit_states(big) + S0[None, :]
    for num, h in HORIZONS.items():
        X0 = np.vstack([Xb, np.array(h["state0"]) + S0])
        _, Xs = A.integrate(ctx, X0, HORIZONS_T0, HORIZONS_T1, pidx=range(len(big)), pgm=gm)
        km = np.linalg.norm((Xs[-1, -1, :3] - S1[:3] - np.array(h["pos1"])) * A.AU_KM)
        assert km < 1.0, (num, km)


@needs_de431
def test_catalogue_positions_match_horizons(env):
    """The pipeline as it actually runs — the whole fleet carried from the elements the Small-Body Database publishes —
    against Horizons at the end of the months the site covers. A few kilometres remain, and they are there at the epoch
    itself: SBDB's published osculating elements and Horizons' own for the same solution differ by about 1e-6 degrees in
    the angles (4 km along-track for Ceres). That is under 4 mas at these distances, well inside the 10 mas the paths
    already carry for the orbit — so don't chase it."""
    A, ctx, _ = env
    rows = A.load_orbits()
    idx = {r["number"]: i for i, r in enumerate(rows)}
    dense = A.Fleet(ctx, rows).span(HORIZONS_T0 - 1, HORIZONS_T1 + 1)
    S1 = ctx.sun.at(ctx.ts.tdb_jd(HORIZONS_T1)).position.au
    for num, h in HORIZONS.items():
        P, _ = dense(np.array([HORIZONS_T1]), [idx[num]])
        km = np.linalg.norm((P[0, 0] - S1 - np.array(h["pos1"])) * A.AU_KM)
        assert km < 10.0, (num, km)


@needs_de431
@needs_gaia
def test_screen_keeps_every_pair_a_plain_search_finds():
    """The month build screens every asteroid against every star on an HOURLY grid, interpolated along each hour, with
    every star carried to the middle of the month — and only the survivors are ever solved, so a pair the screen drops
    is an event the site never hears about. Over two days, find the pairs again the plain way: a two-minute grid, each
    star at the window's own epoch, boxes padded well past the screen's. Everything that search finds must be among the
    screen's candidates, and so must the events the month file actually lists for those days. The screen may keep more
    than the plain search does — it interpolates within the hour, so it catches approaches that fall between two-minute
    samples; extra candidates cost solving time, not events."""
    A = _engine()
    ctx, rows, stars, ts = A.Ctx(), A.load_orbits(), A.Stars(), None
    ts = ctx.ts
    jd0, jd1 = ts.utc(*SCREEN_DAYS[0]).tdb, ts.utc(*SCREEN_DAYS[1]).tdb
    dense = A.Fleet(ctx, rows).span(jd0 - 1.0, jd1 + 1.0)
    cands = A.screen(ctx, dense, rows, stars, jd0, jd1, log=lambda *a: None)

    by_number = {r["number"]: i for i, r in enumerate(rows)}
    for number, gaia in SCREEN_EVENTS:            # the month file's own events for these days
        s = int(np.searchsorted(stars.source_id, gaia)) if (stars.source_id[:-1] <= stars.source_id[1:]).all() \
            else int(np.nonzero(stars.source_id == gaia)[0][0])
        assert stars.source_id[s] == gaia, gaia
        assert (by_number[number], s) in cands, (number, gaia)

    step, pad = 2.0 / 1440, 0.05                  # two minutes; a degree pad twenty times the screen's own
    jds = np.arange(jd0, jd1 + 1e-9, step)
    E = ctx.earth.at(ts.tdb_jd(jds)).position.au.T
    R = np.array([r["R_km"] for r in rows])
    yr = ((jd0 + jd1) / 2 - A.GAIA_EPOCH) / 365.25
    cosd = np.maximum(np.cos(np.radians(stars.dec)), 0.02)
    s_ra, s_de = stars.ra + stars.pmra * yr / 3.6e6 / cosd, stars.dec + stars.pmdec * yr / 3.6e6
    found, B = [], 256
    for b0 in range(0, len(rows), B):
        idx = list(range(b0, min(len(rows), b0 + B)))
        P, V = dense(jds, idx)
        d = P - E[:, None, :]
        d = d - V * (np.linalg.norm(d, axis=2) / A.C_AUD)[..., None]        # light time, first order
        dist = np.linalg.norm(d, axis=2)
        U = d / dist[..., None]
        reach = np.degrees((A.A_E + R[idx][None, :] + 200.0) / (dist * A.AU_KM) + 1.0 * A.ASEC2RAD)
        ra = np.degrees(np.arctan2(U[..., 1], U[..., 0])) % 360
        dec = np.degrees(np.arcsin(np.clip(U[..., 2], -1, 1)))
        for c, ai in enumerate(idx):
            rd = reach[:, c].max() + pad
            d_lo, d_hi = dec[:, c].min() - rd, dec[:, c].max() + rd
            lo, hi = np.searchsorted(stars.dec, [d_lo, d_hi])
            if hi <= lo:
                continue
            cw = max(0.02, math.cos(math.radians(max(abs(d_lo), abs(d_hi)))))
            ref = ra[len(jds) // 2, c]
            rel = (ra[:, c] - ref + 540) % 360 - 180
            srel = (s_ra[lo:hi] - ref + 540) % 360 - 180
            m = ((srel >= rel.min() - rd / cw) & (srel <= rel.max() + rd / cw)
                 & (s_de[lo:hi] >= d_lo) & (s_de[lo:hi] <= d_hi))
            if not m.any():
                continue
            k = np.nonzero(m)[0]
            x, y = np.radians(ref + srel[k]), np.radians(s_de[lo:hi][k])
            S = np.stack([np.cos(y) * np.cos(x), np.cos(y) * np.sin(x), np.sin(y)], 1)
            sep = np.degrees(np.linalg.norm(S[:, None, :] - U[None, :, c, :], axis=2))
            for j in np.nonzero((sep < reach[None, :, c]).any(axis=1))[0]:
                found.append((ai, int(k[j] + lo), float(sep[j].min())))
    assert len(found) > 100, len(found)          # a day of the sky: if this collapses, the search has stopped searching
    missed = [(rows[ai]["number"], int(stars.source_id[s]), sep) for ai, s, sep in found if (ai, s) not in cands]
    assert not missed, missed[:10]


def test_month_files():
    paths = sorted(glob.glob(os.path.join(REPO, "data", "asteroids-*.json")))
    if not paths:
        pytest.skip("no asteroid month files")
    A = _engine()
    for path in paths:
        d = json.load(open(path))
        ids = [e["id"] for e in d["events"]]
        assert len(ids) == len(set(ids)), os.path.basename(path)
        for ev in d["events"]:
            b = ev["best"]
            s = A.local(ev["el"], b["lat"], b["lon"])
            # `best` is rounded to 0.01°, about a kilometre
            assert abs(s["d"]) < 1.5, (ev["id"], s["d"])
            assert abs(s["star_alt"] - b["star_alt"]) < 0.5, (ev["id"], s["star_alt"], b["star_alt"])
            assert ev["lines"]["centre"], ev["id"]
