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

MOON_NAME = {"io": "Io", "europa": "Europa", "ganymede": "Ganymede", "callisto": "Callisto"}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]

PHRASE = {
    ("eclipse", "D"): "{m} disappears into Jupiter's shadow",
    ("eclipse", "R"): "{m} reappears from Jupiter's shadow",
    ("occultation", "D"): "{m} disappears behind Jupiter",
    ("occultation", "R"): "{m} reappears from behind Jupiter",
    ("transit", "D"): "{m} begins its transit across the disc",
    ("transit", "R"): "{m}'s transit ends",
    ("shadow", "D"): "{m}'s shadow enters the disc",
    ("shadow", "R"): "{m}'s shadow leaves the disc",
}


def parse(iso):
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def rows_of(ev):
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
                    "what": PHRASE[(ev["type"], side)].format(m=m),
                    "detail": f"takes {dur:.0f} min" if dur >= 1 else "", "ev": ev})
    return out


def month_page(year, month, rows, all_cities, nav):
    label = f"{MONTHS[month-1]} {year}"
    title = f"Jupiter's moons in {label}"
    desc = (f"Every eclipse, occultation, transit and shadow transit of Io, Europa, Ganymede and Callisto in "
            f"{label}, with the mutual events, in your local time and filtered to what your sky shows.")
    slug = f"jupiter-moons-{year}-{month:02d}"
    n_mutual = sum(1 for r in rows if r["kind"] == "mutual")
    tr = []
    for r in rows:
        ev = r["ev"]
        j, s = ev["jupiter"], ev["sun"]
        tr.append(f'<tr class="k-{r["kind"]} m-{r["moon"]}" data-utc="{int(r["t"].timestamp())}" data-utc2="{int(r["t2"].timestamp())}" '
                  f'data-ra="{j["ra_deg"]}" data-dec="{j["dec_deg"]}" data-sra="{s["ra_deg"]}" data-sdec="{s["dec_deg"]}">'
                  f'<td class="when"><span class="d">{r["t"].strftime("%b %-d")}</span> <span class="tm">{r["t"].strftime("%H:%M")}</span> <small class="tz">UTC</small></td>'
                  f'<td><span class="dot m-{r["moon"]}"></span>{esc(r["what"])}{("<small>" + esc(r["detail"]) + "</small>") if r["detail"] else ""}</td>'
                  f'<td class="sky">—</td></tr>')
    city_opts = "".join(f'<option value="{esc(n)}">{esc(n)}</option>' for n in all_cities)
    data = {"cities": all_cities, "elong": rows[0]["ev"]["jupiter"]["elongation_deg"] if rows else None}
    prev_link = f'<a href="/{nav["prev"]}">‹ {nav["prev_label"]}</a>' if nav.get("prev") else "<span></span>"
    next_link = f'<a href="/{nav["next"]}">{nav["next_label"]} ›</a>' if nav.get("next") else "<span></span>"
    page = head(f"{title} · {SITE_NAME}", desc, f"/{slug}", extra=f"<style>{JUPITER_CSS}</style>") + f"""
<nav class="subnav">
  <div class="subnav-row">
    <div class="subnav-links">{prev_link}<a href="/#jupiter">All months</a>{next_link}</div>
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
  <p class="sub">Io · Europa · Ganymede · Callisto — eclipses, occultations, transits, shadows{f", and {n_mutual} mutual events" if n_mutual else ""}</p>
  <p class="lead">Jupiter's four big moons put on a show every night: they slip behind the planet and into its
  shadow, cross its face, and drag their shadows across the cloud tops. Any telescope shows it.
  {"This is a mutual-event season — every six years the moons' orbits turn edge-on to the Sun and they eclipse and occult <em>each other</em>. " if n_mutual else ""}
  Times are for the whole Earth; pick a location and the list keeps only what your sky shows.</p>
  <div class="filters">
    <label class="toggle"><input type="checkbox" id="only-visible" checked> Only what I can see from <span id="only-where">here</span></label>
    <span class="chips" id="moon-chips">
      <label class="chipbox m-io"><input type="checkbox" value="io" checked> Io</label>
      <label class="chipbox m-europa"><input type="checkbox" value="europa" checked> Europa</label>
      <label class="chipbox m-ganymede"><input type="checkbox" value="ganymede" checked> Ganymede</label>
      <label class="chipbox m-callisto"><input type="checkbox" value="callisto" checked> Callisto</label>
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
  "takes N min" is how long the disc takes to cross the edge. Halves that happen behind Jupiter or inside its
  shadow are left out, since nobody can see them. Positions are from JPL DE431 and the jup365 satellite ephemeris,
  Jupiter as an oblate spheroid with its shadow cone; mutual-event magnitude drops assume uniform discs and are
  estimates. Events are geocentric — the same instant everywhere on Earth to well under a second.</p>
  <script type="application/json" id="diary-data">{json.dumps(data, ensure_ascii=False, separators=(",", ":"))}</script>
</main>
{FOOTER}
<script>
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
    return {"slug": slug, "label": label, "year": year, "month": month, "n": len(rows), "n_mutual": n_mutual}


def build_all(all_cities):
    files = sorted(ROOT.glob("data/jupiter-moons-*.json"))
    months = {}
    for f in files:
        d = json.loads(f.read_text())
        for ev in d["events"]:
            for r in rows_of(ev):
                months.setdefault((r["t"].year, r["t"].month), []).append(r)
    keys = sorted(months)
    built = []
    for i, (y, m) in enumerate(keys):
        rows = sorted(months[(y, m)], key=lambda r: r["t"])
        nav = {}
        if i > 0:
            py, pm = keys[i - 1]; nav["prev"] = f"jupiter-moons-{py}-{pm:02d}"; nav["prev_label"] = MONTHS[pm-1][:3]
        if i < len(keys) - 1:
            ny, nm = keys[i + 1]; nav["next"] = f"jupiter-moons-{ny}-{nm:02d}"; nav["next_label"] = MONTHS[nm-1][:3]
        built.append(month_page(y, m, rows, all_cities, nav))
        print(f"wrote site/{built[-1]['slug']}.html: {len(rows)} rows, {built[-1]['n_mutual']} mutual")
    return built


JUPITER_CSS = """
    .filters { display: flex; flex-wrap: wrap; gap: 0.6rem 1.2rem; align-items: center; margin: 0.8rem 0 0.3rem; font-size: 0.9rem; }
    .toggle { display: inline-flex; gap: 0.4rem; align-items: center; }
    .chips { display: inline-flex; flex-wrap: wrap; gap: 0.35rem; }
    .chipbox { display: inline-flex; align-items: center; gap: 0.3rem; border: 1px solid var(--line); border-radius: 999px; padding: 0.15rem 0.6rem; font-size: 0.85rem; cursor: pointer; }
    .chipbox input { accent-color: var(--accent); }
    td.when { white-space: nowrap; } td.when .tz { color: var(--muted); font-size: 0.72rem; }
    td .dot { display: inline-block; width: 0.55em; height: 0.55em; border-radius: 50%; margin-right: 0.45em; vertical-align: 0.05em; background: var(--muted); }
    .m-io .dot, .chipbox.m-io { border-color: #f59e0b; } .m-io .dot { background: #f59e0b; }
    .m-europa .dot, .chipbox.m-europa { border-color: #60a5fa; } .m-europa .dot { background: #60a5fa; }
    .m-ganymede .dot, .chipbox.m-ganymede { border-color: #a78bfa; } .m-ganymede .dot { background: #a78bfa; }
    .m-callisto .dot, .chipbox.m-callisto { border-color: #34d399; } .m-callisto .dot { background: #34d399; }
    tr.k-mutual td:nth-child(2) { font-weight: 600; }
    td.sky.good { color: var(--c-visible); } td.sky.meh { color: var(--c-limit); } td.sky.bad { color: var(--muted); }
    #diary td small { display: block; color: var(--muted); font-size: 0.75rem; white-space: normal; }
    #diary td:nth-child(2) { white-space: normal; min-width: 16rem; }
"""
