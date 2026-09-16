"""The asteroid pages' JS against its Python twins, run under node: `solve()` / `toCentre()` against the engine's
`local()` / `to_centre()` number for number, and `you()` against `you_html()` text for text — for every event of every
month file at a handful of places, inside and far outside the paths. The drawings that solve their own geometry are
checked against the engine's lines too: the centre line and both edges the page traces from the elements against the
ones the engine wrote, and the spots `toOffset()` walks to against the offset they were asked for. Data files only;
skips without node."""
import glob
import json
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
  band: A.bandRuns(ev.el, [-ev.el.R, -ev.el.R / 2, 0, ev.el.R / 2, ev.el.R], 240).map(function (r) { return r.map(function (l) { return l.length; }); }) });
process.stdout.write(JSON.stringify({ rows: out, docs: docs }));
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
    js = iter(got["rows"])
    for ev in d["events"]:
        for lat, lon in PLACES:
            j = next(js)
            s, tc = local(ev["el"], lat, lon), to_centre(ev["el"], lat, lon)
            for key in ("tau", "d", "speed", "dur", "star_alt", "star_az", "sun_alt"):
                assert abs(j["s"][key] - s[key]) < 1e-6 * max(1.0, abs(s[key])), (ev["id"], lat, lon, key, j["s"][key], s[key])
            assert abs(j["tc"][0] - tc[0]) < 1e-6 * max(1.0, tc[0]) and abs(((j["tc"][1] - tc[1] + 180) % 360) - 180) < 1e-6, (ev["id"], j["tc"], tc)
            assert list(ba.you_html(ev, s, tc)) == j["you"], (ev["id"], lat, lon)
            # every suggested station stands where it says it does: 50 m, even walked from 5,000 km away
            assert max(abs(v) for v in j["off"]) < 0.2, (ev["id"], lat, lon, j["off"])


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
