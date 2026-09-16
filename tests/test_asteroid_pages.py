"""The asteroid pages' JS against its Python twins, run under node: `solve()` / `toCentre()` against the engine's
`local()` / `to_centre()` number for number, and `you()` against `you_html()` text for text — for every event of every
month file at a handful of places, inside and far outside the paths. Data files only; skips without node."""
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
  out.push({ s: s, tc: tc, you: A.you(ev, s, tc) });
}
for (const ev of input.events.slice(0, 3)) docs.push({ id: ev.id, kml: A.kml(ev), gpx: A.gpx(ev) });
process.stdout.write(JSON.stringify({ rows: out, docs: docs }));
"""


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
@pytest.mark.parametrize("path", sorted(glob.glob(os.path.join(REPO, "data", "asteroids-*.json"))) or [None])
def test_js_twins_match_python(path):
    if path is None:
        pytest.skip("no asteroid month files")
    d = json.load(open(path))
    meta = {"t0": d["month"] + "-01T00:00:00Z", "defaultPlace": list(ba.DEFAULT_PLACE), "cities": {}, "bbox": d["bbox"], "lat0": 22, "mapW": ba.MAP_W, "src": ""}
    payload = json.dumps({"js": ba.SOLVER_JS, "meta": meta, "events": d["events"], "places": PLACES})
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
