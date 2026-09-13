#!/usr/bin/env python3
"""Jupiter's moons diary: one page per month from data/jupiter-moons-<year>.json
(kaalshodh: api/lookup/generate/satellite_events.py, DE431 + JPL jup365).

Every event is geocentric — one UTC instant for the whole Earth — so the page prerenders
the month's events in UTC (crawlable) and the browser turns them into local time and adds
"Jupiter 35° up, dark sky" for the chosen location, from the RA/Dec stored with each event
and sidereal time alone. No ephemeris in the browser.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from build_pages import FOOTER, OUT, ROOT, SITE, SITE_NAME, esc, head

MOON_NAME = {"io": "Io", "europa": "Europa", "ganymede": "Ganymede", "callisto": "Callisto",
             "mimas": "Mimas", "enceladus": "Enceladus", "tethys": "Tethys", "dione": "Dione",
             "rhea": "Rhea", "titan": "Titan", "iapetus": "Iapetus"}
PLANETS = {
    "jupiter": dict(name="Jupiter", moons=["io", "europa", "ganymede", "callisto"], oblate=0.935,
                    colors={"io": "#f59e0b", "europa": "#60a5fa", "ganymede": "#a78bfa", "callisto": "#34d399"},
                    radii_rp={"io": 0.0255, "europa": 0.0218, "ganymede": 0.0368, "callisto": 0.0337},
                    zooms=[30, 8], intro="Jupiter's four big moons put on a show every night: they slip behind the planet and into its "
                    "shadow, cross its face, and drag their shadows across the cloud tops. Any telescope shows it."),
    "saturn": dict(name="Saturn", moons=["mimas", "enceladus", "tethys", "dione", "rhea", "titan", "iapetus"], oblate=0.902,
                   colors={"mimas": "#94a3b8", "enceladus": "#e2e8f0", "tethys": "#fcd34d", "dione": "#60a5fa",
                           "rhea": "#a78bfa", "titan": "#f97316", "iapetus": "#34d399"},
                   radii_rp={"mimas": 0.0033, "enceladus": 0.0042, "tethys": 0.0088, "dione": 0.0093,
                             "rhea": 0.0127, "titan": 0.0427, "iapetus": 0.0122},
                   zooms=[65, 25, 8], intro="Saturn's moons hide behind the globe, cross its face and fall into its shadow only "
                   "in the years around a ring-plane crossing, when their orbits turn edge-on to us — as they are now, after the "
                   "2025 equinox. Titan is easy in any telescope; Rhea, Dione and Tethys need a little more aperture."),
}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]

PHRASE = {
    ("eclipse", "D"): "{m} disappears into {p}'s shadow",
    ("eclipse", "R"): "{m} reappears from {p}'s shadow",
    ("occultation", "D"): "{m} disappears behind {p}",
    ("occultation", "R"): "{m} reappears from behind {p}",
    ("transit", "D"): "{m} begins its transit across the disc",
    ("transit", "R"): "{m}'s transit ends",
    ("shadow", "D"): "{m}'s shadow enters the disc",
    ("shadow", "R"): "{m}'s shadow leaves the disc",
}


def parse(iso):
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def rows_of(ev, pname="Jupiter"):
    """One classical event -> up to two rows (start, end), skipping halves hidden behind the
    disc or in shadow; a mutual event -> one row."""
    c = ev["contacts"]
    if ev["type"] == "mutual":
        a, b = MOON_NAME[ev["a"]], MOON_NAME[ev["b"]]
        verb = "occults" if ev["kind"] == "occults" else "eclipses"
        t0, t1 = parse(c["D1"]), parse(c["R2"])
        dur = (t1 - t0).total_seconds() / 60
        return [{"t": t0, "t2": t1, "moon": ev["a"], "kind": "mutual",
                 "what": f"{a} {verb} {b}",
                 "detail": f"{dur:.1f} min · {ev['covered_frac']*100:.0f}% of {b} covered · drops ≈{ev['mag_drop']:.1f} mag",
                 "ev": ev}]
    out = []
    m = MOON_NAME[ev["moon"]]
    hidden = ev.get("hidden", {})
    for side, first, second in (("D", "D1", "D2"), ("R", "R1", "R2")):
        if first not in c and second not in c:
            continue
        if hidden.get(first, False) and hidden.get(second, False):
            continue
        ta = parse(c.get(first, c.get(second)))
        tb = parse(c.get(second, c.get(first)))
        dur = (tb - ta).total_seconds() / 60
        out.append({"t": ta, "t2": tb, "moon": ev["moon"], "kind": ev["type"],
                    "what": PHRASE[(ev["type"], side)].format(m=m, p=pname),
                    "detail": f"takes {dur:.0f} min" if dur >= 1 else "", "ev": ev})
    return out


def month_page(planet, year, month, rows, all_cities, nav, config=None):
    P = PLANETS[planet]
    pname = P["name"]
    moon_list = ", ".join(MOON_NAME[m] for m in P["moons"][:-1]) + " and " + MOON_NAME[P["moons"][-1]]
    label = f"{MONTHS[month-1]} {year}"
    title = f"{pname}'s moons in {label}"
    desc = (f"Every eclipse, occultation, transit and shadow transit of {moon_list} in "
            f"{label}, with the mutual events, in your local time and filtered to what your sky shows.")
    slug = f"{planet}-moons-{year}-{month:02d}"
    n_mutual = sum(1 for r in rows if r["kind"] == "mutual")
    tr = []
    for r in rows:
        ev = r["ev"]
        j, s = ev.get("planet") or ev["jupiter"], ev["sun"]
        tr.append(f'<tr class="k-{r["kind"]} m-{r["moon"]}" data-utc="{int(r["t"].timestamp())}" data-utc2="{int(r["t2"].timestamp())}" '
                  f'data-ra="{j["ra_deg"]}" data-dec="{j["dec_deg"]}" data-sra="{s["ra_deg"]}" data-sdec="{s["dec_deg"]}">'
                  f'<td class="when"><span class="d">{r["t"].strftime("%b %-d")}</span> <span class="tm">{r["t"].strftime("%H:%M")}</span> <small class="tz">UTC</small></td>'
                  f'<td><span class="dot" style="background:{P["colors"].get(r["moon"], "#94a3b8")}"></span>{esc(r["what"])}{("<small>" + esc(r["detail"]) + "</small>") if r["detail"] else ""}</td>'
                  f'<td class="sky">—</td></tr>')
    city_opts = "".join(f'<option value="{esc(n)}">{esc(n)}</option>' for n in all_cities)
    data = {"cities": all_cities, "planet": planet, "moons": P["moons"], "names": [MOON_NAME[m] for m in P["moons"]],
            "colors": [P["colors"][m] for m in P["moons"]], "radii": [P["radii_rp"][m] for m in P["moons"]],
            "oblate": P["oblate"], "zooms": P["zooms"], "config": config}
    t0 = int(datetime(year, month, 1, tzinfo=timezone.utc).timestamp())
    t1 = int(datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=timezone.utc).timestamp())
    prev_link = f'<a href="/{nav["prev"]}">‹ {nav["prev_label"]}</a>' if nav.get("prev") else "<span></span>"
    next_link = f'<a href="/{nav["next"]}">{nav["next_label"]} ›</a>' if nav.get("next") else "<span></span>"
    page = head(f"{title} · {SITE_NAME}", desc, f"/{slug}", extra=f"<style>{JUPITER_CSS}</style>") + f"""
<nav class="subnav">
  <div class="subnav-row">
    <div class="subnav-links">{prev_link}<a href="/#{planet}">All months</a>{next_link}</div>
    <button class="chip" id="loc-chip" type="button" aria-haspopup="dialog"><span class="chip-pin">📍</span><span id="chip-name">Choose location</span><span class="chip-sub" id="chip-sub"></span></button>
  </div>
</nav>
<dialog id="loc-sheet" class="sheet" aria-label="Location">
  <form method="dialog" class="sheet-body">
    <div class="sheet-title">Location</div>
    <label>City <select id="loc-city"><option value="">—</option>{city_opts}</select></label>
    <div class="loc-row">
      <label>Lat <input id="loc-lat" type="number" step="any" min="-90" max="90" placeholder="19.076"></label>
      <label>Lon <input id="loc-lon" type="number" step="any" min="-180" max="180" placeholder="72.878"></label>
    </div>
    <div class="loc-row">
      <button class="btn btn-primary" id="loc-go" type="button">Apply</button>
      <button class="btn" id="loc-geo" type="button">Use my location</button>
      <button class="btn" value="cancel">Close</button>
    </div>
  </form>
</dialog>
<main class="wrap">
  <h1>{esc(title)}</h1>
  <p class="sub">{" · ".join(MOON_NAME[m] for m in P["moons"])} — eclipses, occultations, transits, shadows{f", and {n_mutual} mutual events" if n_mutual else ""}</p>
  <p class="lead">{P["intro"]}
  {"This is a mutual-event season — the moons' orbits are edge-on to the Sun and they eclipse and occult <em>each other</em>. " if n_mutual else ""}
  Times are for the whole Earth; pick a location and the list keeps only what your sky shows.</p>
  <h2 id="config">Where the moons are</h2>
  <div class="config-card">
    <div class="limb-controls"><span class="limb-readout" id="config-time"></span>
      <span><button class="btn" id="config-play" type="button">Play</button> <button class="btn" id="config-zoom" type="button">Zoom in</button></span></div>
    <svg id="config-svg" viewBox="0 0 800 170" class="config-svg" role="img" aria-label="{pname} and its moons" data-t0="{t0}" data-t1="{t1}"></svg>
    <input type="range" id="config-slider" min="0" max="100" value="0" step="1" aria-label="Time">
  </div>
  <p class="hint">{pname}'s equator horizontal, east to the left as in binoculars. Drag through the month, or tap any
  line in the list below to jump there. Moons behind the planet fade. {"Positions ±0.1 Jupiter radii — for the picture; the times come from JPL." if planet == "jupiter" else "Positions are JPL's, sampled hourly; the rings are not drawn."}</p>

  <h2>Events</h2>
  <div class="filters">
    <label class="toggle"><input type="checkbox" id="only-visible" checked> Only what I can see from <span id="only-where">here</span></label>
    <span class="chips" id="moon-chips">
      {"".join(f'<label class="chipbox m-{m}" style="border-color:{P["colors"][m]}"><input type="checkbox" value="{m}" checked> {MOON_NAME[m]}</label>' for m in P["moons"])}
      <label class="chipbox k-mutual"><input type="checkbox" value="mutual" checked> Mutual</label>
    </span>
  </div>
  <p class="hint" id="count-line"></p>
  <div class="table-wrap">
    <table id="diary"><thead><tr><th>When <small id="tz-label">(UTC)</small></th><th>Event</th><th title="How high Jupiter stands above your horizon at that moment, and whether the sky is dark">Jupiter in your sky</th></tr></thead>
    <tbody>{''.join(tr)}</tbody></table>
  </div>
  <h2>Reading the list</h2>
  <p class="method">Each <em>disappears / reappears</em> line is the moment the moon's disc is fully in or first out; the
  "takes N min" is how long the disc takes to cross the edge. Halves that happen behind {pname} or inside its
  shadow are left out, since nobody can see them. Positions are from JPL DE431 and the {"jup365" if planet == "jupiter" else "sat441"} satellite ephemeris,
  {pname} as an oblate spheroid with its shadow cone{"; the rings are not modelled, so a moon 'behind Saturn' means behind the globe" if planet == "saturn" else ""}; mutual-event magnitude drops assume uniform discs and are
  estimates. Events are geocentric — the same instant everywhere on Earth to well under a second.</p>
  <script type="application/json" id="diary-data">{json.dumps(data, ensure_ascii=False, separators=(",", ":"))}</script>
</main>
{FOOTER}
<script>
(function () {{
  // ---- Galilean configuration: Meeus, Astronomical Algorithms ch. 44 (low-accuracy method).
  // Checked against JPL jup365: 0.02 R_J rms along the orbit line, 0.08 across — a picture, not a timing.
  var RAD = Math.PI / 180, sin = Math.sin, cos = Math.cos;
  function galilean(ms) {{
    var d = ms / 86400000 + 2440587.5 - 2451545.0;
    var V = 172.74 + 0.00111588 * d, M = 357.529 + 0.9856003 * d;
    var N = 20.020 + 0.0830853 * d + 0.329 * sin(V * RAD), J = 66.115 + 0.9025179 * d - 0.329 * sin(V * RAD);
    var A = 1.915 * sin(M * RAD) + 0.020 * sin(2 * M * RAD), B = 5.555 * sin(N * RAD) + 0.168 * sin(2 * N * RAD);
    var K = J + A - B, R = 1.00014 - 0.01671 * cos(M * RAD) - 0.00014 * cos(2 * M * RAD);
    var r = 5.20872 - 0.25208 * cos(N * RAD) - 0.00611 * cos(2 * N * RAD);
    var D = Math.sqrt(r * r + R * R - 2 * r * R * cos(K * RAD)), psi = Math.asin(R / D * sin(K * RAD)) / RAD;
    var lam = 34.35 + 0.083091 * d + 0.329 * sin(V * RAD) + B;
    var DS = 3.12 * sin((lam + 42.8) * RAD);
    var DE = DS - 2.22 * sin(psi * RAD) * cos((lam + 22) * RAD) - 1.30 * (r - D) / D * sin((lam - 100.5) * RAD);
    var dd = d - D / 173;
    var u = [163.8069 + 203.4058646 * dd + psi - B, 358.4140 + 101.2916335 * dd + psi - B, 5.7176 + 50.2345180 * dd + psi - B, 224.8092 + 21.4879800 * dd + psi - B];
    var G = 331.18 + 50.310482 * dd, H = 87.45 + 21.569231 * dd;
    u[0] += 0.473 * sin(2 * (u[0] - u[1]) * RAD); u[1] += 1.065 * sin(2 * (u[1] - u[2]) * RAD); u[2] += 0.165 * sin(G * RAD); u[3] += 0.843 * sin(H * RAD);
    var rr = [5.9057 - 0.0244 * cos(2 * (u[0] - u[1]) * RAD), 9.3966 - 0.0882 * cos(2 * (u[1] - u[2]) * RAD), 14.9883 - 0.0216 * cos(G * RAD), 26.3613 - 0.1935 * cos(H * RAD)];
    var out = [];
    for (var i = 0; i < 4; i++) out.push({{ x: rr[i] * sin(u[i] * RAD), y: -rr[i] * cos(u[i] * RAD) * sin(DE * RAD), front: cos(u[i] * RAD) > 0 }});
    return out;   // x in Jupiter radii, positive WEST; y positive north; front = nearer to Earth than Jupiter
  }}
  var DD = JSON.parse(document.getElementById('diary-data').textContent);
  function sampled(ms) {{   // linear interpolation of the hourly JPL samples
    var c = DD.config, i = (ms / 1000 - c.t0) / (c.step_min * 60), i0 = Math.floor(i), f = i - i0, out = [];
    c.moons.forEach(function (k) {{
      var a = c.xyf[k], n = a.length / 3, j = Math.max(0, Math.min(n - 2, i0)), g = i0 < 0 ? 0 : i0 > n - 2 ? 1 : f;
      out.push({{ x: (a[3*j] * (1-g) + a[3*j+3] * g) / 100, y: (a[3*j+1] * (1-g) + a[3*j+4] * g) / 100, front: (g < 0.5 ? a[3*j+2] : a[3*j+5]) === 1 }});
    }});
    return out;
  }}
  var positions = DD.config ? sampled : galilean;
  var NS = 'http://www.w3.org/2000/svg', svg = document.getElementById('config-svg'), sl = document.getElementById('config-slider');
  var out = document.getElementById('config-time'), zoomBtn = document.getElementById('config-zoom'), playBtn = document.getElementById('config-play');
  var T0 = +svg.dataset.t0 * 1000, T1 = +svg.dataset.t1 * 1000, STEP = 5 * 60000;
  var NAMES = DD.names, COL = DD.colors, RAD_RJ = DD.radii, ZOOMS = DD.zooms, zi = 0;
  var half = ZOOMS[0], W = 800, Hh = 170, cx = W / 2, cy = Hh / 2, timer = null;
  function el(n, a) {{ var e = document.createElementNS(NS, n); for (var k in a) e.setAttribute(k, a[k]); return e; }}
  function draw() {{
    var ms = T0 + (+sl.value) * STEP, pos = positions(ms), s = (W / 2 - 20) / half;
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    svg.appendChild(el('line', {{ x1: 0, y1: cy, x2: W, y2: cy, class: 'cfg-line' }}));
    var behind = pos.filter(function (p) {{ return !p.front; }}), front = pos.filter(function (p) {{ return p.front; }});
    function moon(p, i, dim) {{
      var g = el('g', {{ class: 'cfg-moon' + (dim ? ' dim' : '') }});
      var r = Math.max(4, RAD_RJ[i] * s);
      g.appendChild(el('circle', {{ cx: cx + p.x * s, cy: cy - p.y * s, r: r, fill: COL[i] }}));
      var t = el('text', {{ x: cx + p.x * s, y: cy - p.y * s - r - 4, 'text-anchor': 'middle', class: 'cfg-lbl' }}); t.textContent = NAMES[i].length > 5 ? NAMES[i].slice(0, 2) : NAMES[i][0]; g.appendChild(t);
      svg.appendChild(g);
    }}
    pos.forEach(function (p, i) {{ if (!p.front) moon(p, i, Math.abs(p.x) < 1 && Math.abs(p.y) < 1); }});
    svg.appendChild(el('ellipse', {{ cx: cx, cy: cy, rx: s, ry: s * DD.oblate, class: 'cfg-jup' }}));
    pos.forEach(function (p, i) {{ if (p.front) moon(p, i, false); }});
    var e = el('text', {{ x: 8, y: 14, class: 'cfg-lbl' }}); e.textContent = 'E'; svg.appendChild(e);
    var w = el('text', {{ x: W - 8, y: 14, 'text-anchor': 'end', class: 'cfg-lbl' }}); w.textContent = 'W'; svg.appendChild(w);
    var d = new Date(ms);
    out.textContent = d.toLocaleDateString(undefined, {{ month: 'short', day: 'numeric' }}) + ' ' + d.toLocaleTimeString(undefined, {{ hour: '2-digit', minute: '2-digit' }})
      + (zi === 0 ? '' : ' · ±' + half + ' radii');
  }}
  sl.max = Math.round((T1 - T0) / STEP); sl.value = Math.round(Math.min(Math.max(Date.now(), T0), T1) - T0) / STEP | 0;
  sl.addEventListener('input', draw);
  zoomBtn.addEventListener('click', function () {{ zi = (zi + 1) % ZOOMS.length; half = ZOOMS[zi]; zoomBtn.textContent = zi === ZOOMS.length - 1 ? 'Zoom out' : 'Zoom in'; draw(); }});
  playBtn.addEventListener('click', function () {{
    if (timer) {{ clearInterval(timer); timer = null; playBtn.textContent = 'Play'; return; }}
    playBtn.textContent = 'Pause';
    timer = setInterval(function () {{ var v = +sl.value + 3; if (v > +sl.max) v = 0; sl.value = v; draw(); }}, 80);
  }});
  // a diary row sets the diagram to that moment
  document.querySelectorAll('#diary tbody tr').forEach(function (tr) {{
    tr.style.cursor = 'pointer';
    tr.addEventListener('click', function () {{
      sl.value = Math.round((+tr.dataset.utc * 1000 - T0) / STEP); draw();
      document.getElementById('config').scrollIntoView({{ block: 'nearest', behavior: 'smooth' }});
    }});
  }});
  draw();
}})();

(function () {{
  var D = JSON.parse(document.getElementById('diary-data').textContent), RAD = Math.PI / 180;
  var rows = [].slice.call(document.querySelectorAll('#diary tbody tr')), LOC = null;
  var onlyVis = document.getElementById('only-visible'), chips = document.querySelectorAll('#moon-chips input');
  var chip = document.getElementById('loc-chip'), chipName = document.getElementById('chip-name'), chipSub = document.getElementById('chip-sub');
  var sheet = document.getElementById('loc-sheet'), latI = document.getElementById('loc-lat'), lonI = document.getElementById('loc-lon'), sel = document.getElementById('loc-city');
  var tzName = (function () {{ try {{ return new Intl.DateTimeFormat(undefined, {{ timeZoneName: 'short' }}).formatToParts(new Date()).filter(function (p) {{ return p.type === 'timeZoneName'; }})[0].value; }} catch (e) {{ return 'local'; }} }})();
  function gmst(ms) {{ var jd = ms / 86400000 + 2440587.5, d = jd - 2451545, T = d / 36525; return ((280.46061837 + 360.98564736629 * d + 0.000387933 * T * T) % 360 + 360) % 360; }}
  function alt(ms, ra, dec, lat, lon) {{ var ha = (gmst(ms) + lon - ra) * RAD; return Math.asin(Math.sin(lat * RAD) * Math.sin(dec * RAD) + Math.cos(lat * RAD) * Math.cos(dec * RAD) * Math.cos(ha)) / RAD; }}
  function fmt(ms) {{ var d = new Date(ms); return {{ d: d.toLocaleDateString(undefined, {{ month: 'short', day: 'numeric' }}), t: d.toLocaleTimeString(undefined, {{ hour: '2-digit', minute: '2-digit' }}) }}; }}
  function render() {{
    var moons = {{}}; chips.forEach(function (c) {{ moons[c.value] = c.checked; }});
    var shown = 0, total = 0;
    rows.forEach(function (tr) {{
      var ms = +tr.dataset.utc * 1000, f = fmt(ms), ok = true;
      tr.querySelector('.d').textContent = f.d; tr.querySelector('.tm').textContent = f.t; tr.querySelector('.tz').textContent = tzName;
      var moon = tr.className.match(/m-(\\w+)/)[1], kind = tr.className.match(/k-(\\w+)/)[1];
      if (kind === 'mutual') ok = moons.mutual; else ok = moons[moon];
      var cell = tr.querySelector('.sky');
      if (LOC) {{
        var a = alt(ms, +tr.dataset.ra, +tr.dataset.dec, LOC.lat, LOC.lon), s = alt(ms, +tr.dataset.sra, +tr.dataset.sdec, LOC.lat, LOC.lon);
        var txt = a <= 0 ? 'below the horizon' : a.toFixed(0) + '° up · ' + (s > 0 ? 'daylight' : s > -6 ? 'twilight' : s > -12 ? 'dusk' : 'dark sky');
        cell.textContent = txt; cell.className = 'sky ' + (a > 10 && s < -6 ? 'good' : a > 0 && s < 0 ? 'meh' : 'bad');
        if (onlyVis.checked && !(a > 10 && s < -6)) ok = false;
      }} else {{ cell.textContent = '—'; cell.className = 'sky'; }}
      total++; tr.hidden = !ok; if (ok) shown++;
    }});
    document.getElementById('tz-label').textContent = '(' + tzName + ')';
    document.getElementById('count-line').textContent = shown + ' of ' + total + ' events' + (LOC && onlyVis.checked ? ' with Jupiter more than 10° up in a dark sky from ' + LOC.label : '');
  }}
  function setLoc(lat, lon, label) {{
    lat = +lat; lon = +lon; if (!isFinite(lat) || !isFinite(lon)) return;
    LOC = {{ lat: lat, lon: lon, label: label || (lat.toFixed(2) + ', ' + lon.toFixed(2)) }};
    latI.value = lat.toFixed(4); lonI.value = lon.toFixed(4);
    chipName.textContent = LOC.label; chipSub.textContent = ''; document.getElementById('only-where').textContent = LOC.label;
    try {{ localStorage.setItem('occult-loc', JSON.stringify(LOC)); }} catch (e) {{}}
    render();
  }}
  chip.addEventListener('click', function () {{ sheet.showModal(); }});
  sheet.addEventListener('click', function (e) {{ if (e.target === sheet) sheet.close(); }});
  document.getElementById('loc-go').addEventListener('click', function () {{ setLoc(latI.value, lonI.value); sheet.close(); }});
  sel.addEventListener('change', function () {{ var c = D.cities[sel.value]; if (c) {{ setLoc(c[0], c[1], sel.value); sheet.close(); }} }});
  var geoBtn = document.getElementById('loc-geo');
  if (!navigator.geolocation) geoBtn.hidden = true;
  geoBtn.addEventListener('click', function () {{
    geoBtn.disabled = true; geoBtn.textContent = 'Locating…';
    navigator.geolocation.getCurrentPosition(function (p) {{ geoBtn.disabled = false; geoBtn.textContent = 'Use my location'; setLoc(p.coords.latitude, p.coords.longitude); sheet.close(); }},
      function () {{ geoBtn.disabled = false; geoBtn.textContent = 'Location unavailable'; }});
  }});
  onlyVis.addEventListener('change', render); chips.forEach(function (c) {{ c.addEventListener('change', render); }});
  var saved = null; try {{ saved = JSON.parse(localStorage.getItem('occult-loc')); }} catch (e) {{}}
  if (saved && isFinite(saved.lat)) setLoc(saved.lat, saved.lon, saved.label); else render();
}})();
</script>
</body>
</html>
"""
    (OUT / f"{slug}.html").write_text(page)
    return {"slug": slug, "label": label, "year": year, "month": month, "n": len(rows), "n_mutual": n_mutual, "planet": planet}


def build_all(all_cities, planet="jupiter"):
    files = sorted(ROOT.glob(f"data/{planet}-moons-*.json"))
    months, configs = {}, {}
    for f in files:
        d = json.loads(f.read_text())
        for ev in d["events"]:
            for r in rows_of(ev, PLANETS[planet]["name"]):
                months.setdefault((r["t"].year, r["t"].month), []).append(r)
        if d.get("config"):
            # slice the year's hourly samples per month
            c = d["config"]; t0 = parse(c["t0"]); step = c["step_min"]
            n = len(next(iter(c["xyf"].values()))) // 3
            for i in range(n):
                t = datetime.fromtimestamp(t0.timestamp() + i * step * 60, tz=timezone.utc)
                cm = configs.setdefault((t.year, t.month), {"t0": None, "step_min": step, "moons": c["moons"], "xyf": {k: [] for k in c["moons"]}})
                if cm["t0"] is None:
                    cm["t0"] = int(t.timestamp())
                for k in c["moons"]:
                    cm["xyf"][k].extend(c["xyf"][k][3*i:3*i+3])
    keys = sorted(months)
    built = []
    for i, (y, m) in enumerate(keys):
        rows = sorted(months[(y, m)], key=lambda r: r["t"])
        nav = {}
        if i > 0:
            py, pm = keys[i - 1]; nav["prev"] = f"{planet}-moons-{py}-{pm:02d}"; nav["prev_label"] = MONTHS[pm-1][:3]
        if i < len(keys) - 1:
            ny, nm = keys[i + 1]; nav["next"] = f"{planet}-moons-{ny}-{nm:02d}"; nav["next_label"] = MONTHS[nm-1][:3]
        built.append(month_page(planet, y, m, rows, all_cities, nav, configs.get((y, m))))
        print(f"wrote site/{built[-1]['slug']}.html: {len(rows)} rows, {built[-1]['n_mutual']} mutual")
    return built


JUPITER_CSS = """
    .config-card { background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 0.6rem 0.8rem; }
    .config-svg { width: 100%; height: auto; display: block; background: var(--sea); border-radius: 8px; margin: 0.4rem 0; }
    .cfg-line { stroke: var(--line); stroke-width: 0.6; }
    .cfg-jup { fill: #d9b98a; stroke: #b08a55; stroke-width: 0.8; }
    .cfg-moon.dim { opacity: 0.25; }
    .cfg-lbl { font: 600 13px -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif; fill: var(--muted); }
    .filters { display: flex; flex-wrap: wrap; gap: 0.6rem 1.2rem; align-items: center; margin: 0.8rem 0 0.3rem; font-size: 0.9rem; }
    .toggle { display: inline-flex; gap: 0.4rem; align-items: center; }
    .chips { display: inline-flex; flex-wrap: wrap; gap: 0.35rem; }
    .chipbox { display: inline-flex; align-items: center; gap: 0.3rem; border: 1px solid var(--line); border-radius: 999px; padding: 0.15rem 0.6rem; font-size: 0.85rem; cursor: pointer; }
    .chipbox input { accent-color: var(--accent); }
    td.when { white-space: nowrap; } td.when .tz { color: var(--muted); font-size: 0.72rem; }
    td .dot { display: inline-block; width: 0.55em; height: 0.55em; border-radius: 50%; margin-right: 0.45em; vertical-align: 0.05em; background: var(--muted); }

    tr.k-mutual td:nth-child(2) { font-weight: 600; }
    td.sky.good { color: var(--c-visible); } td.sky.meh { color: var(--c-limit); } td.sky.bad { color: var(--muted); }
    #diary td small { display: block; color: var(--muted); font-size: 0.75rem; white-space: normal; }
    #diary td:nth-child(2) { white-space: normal; min-width: 16rem; }
"""
