"""The asteroid pages' JS against its Python twins, run under node: `solve()` / `toCentre()` against the engine's
`local()` / `to_centre()` number for number, and `you()` against `you_html()` text for text — for every event of every
month file at a handful of places, inside and far outside the paths. The drawings that solve their own geometry are
checked against the engine's lines too: the centre line and both edges the page traces from the elements against the
ones the engine wrote, and the spots `toOffset()` walks to against the offset they were asked for. Where an event has a
DAMIT outline, the chord the page draws across it is checked against an independent clip of the same line. Data files
only; skips without node."""
import glob
import json
import math
import os
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, os.path.join(REPO, "engine"))

import build_asteroids as ba  # noqa: E402
from asteroid_occultations import local, to_centre  # noqa: E402

PLACES = [(28.6139, 77.2090), (19.0760, 72.8777), (12.9716, 77.5946), (22.5726, 88.3639), (34.0837, 74.7973), (51.5072, -0.1276)]

STATION_F = [-0.8, -0.4, 0.0, 0.4, 0.8]
TRACK_N = 20000

HARNESS = r"""
const fs = require('fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const node = () => ({ addEventListener() {}, textContent: '', innerHTML: '', hidden: false, appendChild() {}, querySelector: () => null });
global.window = {};
global.document = {
  getElementById: (id) => id === 'ast-meta' ? { textContent: JSON.stringify(input.meta) } : node(),
  querySelectorAll: () => ({ forEach() {} }), createDocumentFragment: node, createElement: node };
global.localStorage = { getItem: () => null, setItem() {} };
global.navigator = {};
global.fetch = () => new Promise(() => {});        // the page's own data fetch never resolves here: render() stays idle
eval(input.js);
const A = window.OccultAsteroids, out = [], docs = [];
for (const ev of input.events) for (const p of input.places) {
  const s = A.solve(ev.el, p[0], p[1]), tc = A.toCentre(ev.el, p[0], p[1]);
  // the line of stations the page suggests: walk to the centre line, then out to each fraction of the half width
  const c = A.toOffset(ev.el, p[0], p[1], 0);
  const off = input.stationF.map(function (f) {
    const q = A.toOffset(ev.el, c[0], c[1], f * ev.el.R);
    return A.solve(ev.el, q[0], q[1]).d - f * ev.el.R;
  });
  out.push({ s: s, tc: tc, you: A.you(ev, s, tc), off: off });
}
// the verdict's three outside bands, at places put there on purpose: half a sigma past the edge, one and a half, two and a half
const bands = [], chords = [];
for (const ev of input.events) {                  // tracks across DAMIT outlines: the centre line and halfway to each edge
  if (!ev.shape) continue;
  const c = A.toOffset(ev.el, input.places[0][0], input.places[0][1], 0);
  for (const f of [0, 0.5, -0.5]) {
    const q = A.toOffset(ev.el, c[0], c[1], f * ev.el.R), s = A.solve(ev.el, q[0], q[1]), sc = A.shapeChord(ev, s);
    chords.push({ id: ev.id, lat: q[0], lon: q[1], km: sc.km, sec: sc.s, across: sc.across });
  }
}
for (const ev of input.events) {
  const sig = ev.sigma_km || 0;
  if (sig < 1) continue;
  const c = A.toOffset(ev.el, input.places[0][0], input.places[0][1], 0);
  for (const k of [0.5, 1.5, 2.5]) {
    const q = A.toOffset(ev.el, c[0], c[1], ev.el.R + k * sig), s = A.solve(ev.el, q[0], q[1]), tc = A.toCentre(ev.el, q[0], q[1]);
    bands.push({ id: ev.id, k: k, lat: q[0], lon: q[1], you: A.you(ev, s, tc) });
  }
}
function dense(el, off) {
  const n = input.trackN, o = [];
  for (let i = 0; i <= n; i++) o.push(A.groundAt(el, -el.W + 2 * el.W * i / n, off));
  return o;
}
// Densely. Where the shadow meets the Earth's limb its ground point races, so a sparse track cuts the corner and the
// comparison measures the sampling, not the solver: at 20,000 steps the worst point of a slow, sharply turning path
// agrees to 0.2 km, against 49 km at 4,000. The page itself draws 400 — a corner cut of a pixel or so on a world map.
for (const ev of input.events.slice(0, 3)) docs.push({ id: ev.id, kml: A.kml(ev), gpx: A.gpx(ev),
  tracks: { centre: A.worldTrack(ev.el, input.trackN), left: dense(ev.el, ev.el.R), right: dense(ev.el, -ev.el.R) },
  sky: (function () { const k = A.skyRuns(ev.el, 120); return { dark: k.dark, mids: k.runs.map(function (r) { return [r.cls, r.pts[r.pts.length >> 1]]; }) }; })(),
  band: A.bandRuns(ev.el, [-ev.el.R, -ev.el.R / 2, 0, ev.el.R / 2, ev.el.R], 240).map(function (r) { return r.map(function (l) { return l.length; }); }) });
process.stdout.write(JSON.stringify({ rows: out, docs: docs, bands: bands, chords: chords }));
"""


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
@pytest.mark.parametrize("path", sorted(glob.glob(os.path.join(REPO, "data", "asteroids-*.json"))) or [None])
def test_js_twins_match_python(path):
    if path is None:
        pytest.skip("no asteroid month files")
    d = json.load(open(path))
    meta = {"t0": d["month"] + "-01T00:00:00Z", "defaultPlace": list(ba.DEFAULT_PLACE), "cities": {}, "bbox": d["bbox"], "lat0": 22, "mapW": ba.MAP_W, "src": ""}
    payload = json.dumps({"js": ba.LIB_JS, "meta": meta, "events": d["events"], "places": PLACES,
                          "stationF": STATION_F, "trackN": TRACK_N})
    res = subprocess.run(["node", "-e", HARNESS], input=payload, capture_output=True, text=True, timeout=300)
    assert res.returncode == 0, res.stderr[-2000:]
    got = json.loads(res.stdout)
    _check_downloads(d, got["docs"])
    _check_bands(d, got["bands"])
    _check_chords(d, got["chords"])
    js = iter(got["rows"])
    for ev in d["events"]:
        for lat, lon in PLACES:
            j = next(js)
            s, tc = local(ev["el"], lat, lon), to_centre(ev["el"], lat, lon)
            for key in ("tau", "d", "speed", "dur", "star_alt", "star_az", "sun_alt"):
                assert abs(j["s"][key] - s[key]) < 1e-6 * max(1.0, abs(s[key])), (ev["id"], lat, lon, key, j["s"][key], s[key])
            for key in ("q", "v"):
                for a, b in zip(j["s"][key], s[key]):
                    assert abs(a - b) < 1e-6 * max(1.0, abs(b)), (ev["id"], lat, lon, key, j["s"][key], s[key])
            # the vectors an outline is placed with must say what d already says: the place sits d to the left of the motion.
            # That holds at a true closest approach; a place so far off that it falls outside the event's window gets a
            # clamped time, q no longer square to v, and no outline anywhere near it
            vn = math.hypot(*s["v"])
            assert abs(math.hypot(*s["q"]) - abs(s["d"])) < 1e-6 * max(1.0, abs(s["d"])), (ev["id"], lat, lon)
            if abs(s["tau"]) < ev["el"]["W"] - 1e-6:
                assert abs((s["q"][0] * -s["v"][1] + s["q"][1] * s["v"][0]) / vn - s["d"]) < 1e-3 * max(1.0, abs(s["d"])), (ev["id"], lat, lon)
            assert abs(j["tc"][0] - tc[0]) < 1e-6 * max(1.0, tc[0]) and abs(((j["tc"][1] - tc[1] + 180) % 360) - 180) < 1e-6, (ev["id"], j["tc"], tc)
            assert list(ba.you_html(ev, s, tc)) == j["you"], (ev["id"], lat, lon)
            # every suggested station stands where it says it does: 50 m, even walked from 5,000 km away
            assert max(abs(v) for v in j["off"]) < 0.2, (ev["id"], lat, lon, j["off"])


def _check_chords(d, chords):
    """The page's chord across a DAMIT outline, against a clip of the same line done another way (Cyrus-Beck, against
    each edge's inward normal) from the engine's own q and v. The outline and q, v share e1/e2 — `basis(k)` is the frame
    `local()` builds — so the only thing left to get wrong is the clip."""
    from asteroid_occultations import basis
    by_id = {e["id"]: e for e in d["events"]}
    for c in chords:
        ev = by_id[c["id"]]
        s = local(ev["el"], c["lat"], c["lon"])
        k = ev["el"]["k"]
        e1, e2 = basis(k)
        n1 = math.hypot(-k[1], k[0])
        assert abs(e1[0] + k[1] / n1) < 1e-12 and abs(e1[1] - k[0] / n1) < 1e-12, "basis() is not local()'s frame"
        vn = math.hypot(*s["v"])
        u = (s["v"][0] / vn, s["v"][1] / vn)
        lo, hi = -1e9, 1e9
        h = ev["shape"]["hull"]
        for a, b in zip(h, h[1:] + h[:1]):
            nrm = (-(b[1] - a[1]), b[0] - a[0])                       # inward, for a counter-clockwise outline
            num = nrm[0] * (s["q"][0] - a[0]) + nrm[1] * (s["q"][1] - a[1])
            den = nrm[0] * u[0] + nrm[1] * u[1]
            if abs(den) < 1e-12:
                if num < 0:
                    lo, hi = 1, 0
                continue
            t = -num / den
            lo, hi = (max(lo, t), hi) if den > 0 else (lo, min(hi, t))
        want = max(0.0, hi - lo)
        w = [(-u[1]) * p[0] + u[0] * p[1] for p in h]                  # the outline's extent across the path
        assert abs(c["across"] - (max(w) - min(w))) < 0.01, (c["id"], c["across"], max(w) - min(w))
        assert abs(c["km"] - want) < 0.01 + 1e-6 * want, (c["id"], c["km"], want)
        assert abs(c["sec"] - want / s["speed"]) < 1e-3 + 1e-6 * want, (c["id"], c["sec"])
    if chords:
        across = [c["km"] for c in chords[::3]]                     # the centre-line track of each shaped event
        assert all(k > 0 for k in across), "a centre line that misses its own asteroid's outline"


def _check_bands(d, bands):
    """The verdict outside the path comes in three bands — within 1σ worth watching, within 2σ a long shot, beyond that
    a plain miss — and the text is written twice. Places chosen at 0.5, 1.5 and 2.5σ past the edge land one in each, and
    the two halves must agree word for word there, since the fixed test places rarely fall between 1σ and 2σ."""
    by_id = {e["id"]: e for e in d["events"]}
    want = {0.5: "near", 1.5: "chance", 2.5: "out"}
    assert bands, "no event with a sigma to test"
    for b in bands:
        ev = by_id[b["id"]]
        s, tc = local(ev["el"], b["lat"], b["lon"]), to_centre(ev["el"], b["lat"], b["lon"])
        py = list(ba.you_html(ev, s, tc))
        assert py == b["you"], (b["id"], b["k"], py, b["you"])
        if s["star_alt"] >= 0:
            assert py[0] == want[b["k"]], (b["id"], b["k"], py[0])


def _check_downloads(d, docs):
    """The KML and GPX the page hands a path chaser: well-formed, one track per run of every line, points on the map."""
    import xml.etree.ElementTree as ET

    by_id = {e["id"]: e for e in d["events"]}
    lon0, lat0, lon1, lat1 = d["bbox"]
    for doc in docs:
        ev = by_id[doc["id"]]
        runs = sum(len(ev["lines"].get(k) or []) for k in ("centre", "left", "right", "left_1s", "right_1s"))
        pts = sum(len(r) for k in ("centre", "left", "right", "left_1s", "right_1s") for r in (ev["lines"].get(k) or []))
        kml = ET.fromstring(doc["kml"])
        ns = "{http://www.opengis.net/kml/2.2}"
        marks = kml.findall(f".//{ns}Placemark")
        assert len(marks) == runs, (doc["id"], len(marks), runs)
        coords = [c for m in marks for c in m.find(f".//{ns}coordinates").text.split()]
        assert len(coords) == pts
        for c in coords:
            lon, lat, _ = (float(v) for v in c.split(","))
            assert lon0 - 4 <= lon <= lon1 + 4 and lat0 - 4 <= lat <= lat1 + 4, (doc["id"], lat, lon)
        gpx = ET.fromstring(doc["gpx"])
        g = "{http://www.topografix.com/GPX/1/1}"
        assert len(gpx.findall(f".//{g}trk")) == runs
        assert len(gpx.findall(f".//{g}trkpt")) == pts
        for name in ("centre", "left", "right"):
            _check_track(ev, name, doc["tracks"][name])
        for run in doc["band"]:                      # a ribbon needs its two edges sampled at the same instants
            assert len(set(run)) == 1 and run[0] > 1, (doc["id"], run)
        _check_sky(ev, doc["sky"])


def _check_sky(ev, sky):
    """The map draws the track bright only where the star is up in a dark sky. The page classifies each ground point
    from the elements, on the same rule the engine selects events with — star at least 10° up, Sun at least 6° down —
    and every listed event crosses India at night, so a stretch of every track must come out dark."""
    assert sky["dark"], ev["id"]
    for cls, (lat, lon) in sky["mids"]:
        s = local(ev["el"], lat, lon)
        want = "low" if s["star_alt"] < 10 else "bright" if s["sun_alt"] > -6 else "dark"
        assert want == cls, (ev["id"], lat, lon, cls, want, s["star_alt"], s["sun_alt"])


def _check_track(ev, name, track):
    """The map and the world inset solve the shadow's ground track in the browser, from the elements alone: the centre
    line and both edges must retrace the ones the engine wrote. The edges are the real test of the offset geometry —
    the light time to the ground point and the normal taken across the motion relative to the turning Earth. Drop
    either and this moves by a kilometre or more (much more for a big asteroid)."""
    import math
    pts = [p for p in track if p]
    assert len(pts) > 20, ev["id"]
    # near the Earth's limb the sub-shadow point races, so samples there are far apart: measure against every segment
    segs = [(a, b) for a, b in zip(pts, pts[1:]) if abs(((b[1] - a[1] + 180) % 360) - 180) < 90]
    for run in ev["lines"].get(name) or []:
        for lat, lon in run:
            kx = 111.32 * math.cos(math.radians(lat))
            best = min(_seg_km(lat, lon, a, b, kx) for a, b in segs)
            assert best < 0.3, (ev["id"], name, lat, lon, best)


def _seg_km(lat, lon, a, b, kx):
    ax, ay = (((a[1] - lon + 180) % 360) - 180) * kx, (a[0] - lat) * 111.32
    bx, by = (((b[1] - lon + 180) % 360) - 180) * kx, (b[0] - lat) * 111.32
    dx, dy = bx - ax, by - ay
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / (dx * dx + dy * dy)))
    return ((ax + t * dx) ** 2 + (ay + t * dy) ** 2) ** 0.5


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_path_colours_follow_occult4():
    """IOTA observers read a prediction in Occult4's colours: green centre line, blue edges of the shadow, red 1σ lines. The
    map takes them from the --map-* tokens, and the KML the page writes must give each kind of line its own of them —
    a swap of edge and sigma is the easy mistake."""
    import re
    tokens = dict(re.findall(r"--map-(centre|edge|sigma): (#[0-9a-f]{6})", ba.AST_CSS))
    hue = lambda h: max(zip((int(h[i:i + 2], 16) for i in (1, 3, 5)), ("red", "green", "blue")))[1]
    assert {k: hue(v) for k, v in tokens.items()} == {"centre": "green", "edge": "blue", "sigma": "red"}
    ev = next(e for f in sorted(glob.glob(os.path.join(REPO, "data", "asteroids-*.json"))) for e in json.load(open(f))["events"]
              if all(e["lines"].get(k) for k in ("centre", "left", "right", "left_1s", "right_1s")))
    harness = ("const fs = require('fs'); const input = JSON.parse(fs.readFileSync(0, 'utf8')); global.window = {}; global.document = {};"
               "eval(input.js); process.stdout.write(window.OccultAsteroids.kml(input.ev, input.colours));")
    res = subprocess.run(["node", "-e", harness], input=json.dumps({"js": ba.LIB_JS, "ev": ev, "colours": tokens}),
                         capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr[-2000:]
    styles = dict(re.findall(r'<Style id="(\w+)"><LineStyle><color>(\w{8})</color>', res.stdout))
    kml = lambda h: "ff" + h[5:7] + h[3:5] + h[1:3]
    assert styles == {k: kml(v) for k, v in tokens.items()}
    used = dict(re.findall(r"<name>([^<]+)</name><styleUrl>#(\w+)</styleUrl>", res.stdout))
    assert used == {"Centre line": "centre", "North edge": "edge", "South edge": "edge", "North 1 sigma": "sigma", "South 1 sigma": "sigma"}
