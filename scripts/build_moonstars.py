#!/usr/bin/env python3
"""The Moon and the stars: one page per month listing every lunar occultation of a catalogue star
(Gaia DR3 to G 9.5, Hipparcos-2 for the brightest) that the reader can see from their own location.

  data/moon-stars-<YYYY-MM>.json   engine/star_occultations.py (DE431: Moon/Sun polynomials + the month's stars)
  -> site/moon-stars-<YYYY-MM>.html, site/data/moon-stars-<YYYY-MM>.json

The JS in SOLVER_JS is the browser twin of `MonthModel` / `visible` in engine/star_occultations.py —
change them TOGETHER. The page prerenders New Delhi with the Python model (crawlers and first paint);
the browser recomputes for the chosen place and instrument. Needs the repo's venv (numpy).
"""

import json
import sys
import zoneinfo
from datetime import datetime, timedelta, timezone

from build_pages import FOOTER, OUT, ROOT, SITE_NAME, esc, head

sys.path.insert(0, str(ROOT / "engine"))

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]
DEFAULT_PLACE = ("New Delhi", 28.6139, 77.2090, "Asia/Kolkata")
DEFAULT_INSTRUMENT = "scope80"
COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def compass(az):
    return COMPASS[int((az + 11.25) // 22.5) % 16]


def sky_text(sun_alt):
    if sun_alt > 0:
        return f"daylight, Sun {sun_alt:+.0f}°"
    if sun_alt > -6:
        return "twilight"
    if sun_alt > -12:
        return "dusk"
    return "dark sky"


def row_html(ev, vis, t0, tz):
    keys = [k for k in ("D", "R") if k in vis]
    verb = {"D": "Disappears", "R": "Reappears"}
    c0 = vis[keys[0]]
    t = (t0 + timedelta(minutes=c0["m"])).astimezone(tz)
    what = f"{verb[keys[0]]} at the {c0['limb']} limb"
    if len(keys) == 2:
        c1 = vis[keys[1]]
        t1 = (t0 + timedelta(minutes=c1["m"])).astimezone(tz)
        what += f"<small>{verb[keys[1]].lower()} {t1.strftime('%H:%M:%S')} at the {c1['limb']} limb</small>"
    graze = ' <span class="badge">graze</span>' if ev["graze"] else ""
    return (f'<tr class="lim-{c0["limb"]}"><td class="when"><span class="d">{t.strftime("%a %-d %b")}</span> '
            f'<span class="tm">{t.strftime("%H:%M:%S")}</span></td>'
            f'<td><b>{esc(ev["label"])}</b> <small>V {ev["vmag"]:.1f}</small>{graze}</td>'
            f'<td>{what}</td>'
            f'<td>{c0["moon_alt"]:.0f}° up in the {compass(c0["moon_az"])}<small>{sky_text(c0["sun_alt"])}</small></td>'
            f'<td class="det">PA {c0["pa"]:.0f}° · cusp {c0["cusp"]:.0f}°<small>Moon {c0["illum"] * 100:.0f}% lit</small></td></tr>')


MS_CSS = """
    .filters { display: flex; flex-wrap: wrap; gap: 0.4rem; margin: 1rem 0 0.3rem; }
    .chipbox { display: inline-flex; align-items: center; gap: 0.35rem; border: 1px solid var(--line); border-radius: 999px; padding: 0.2rem 0.7rem; font-size: 0.85rem; cursor: pointer; }
    .chipbox input { accent-color: var(--accent); }
    .chipbox:has(input:checked) { border-color: var(--accent); color: var(--accent); }
    #ms-table td small { display: block; color: var(--muted); font-size: 0.75rem; white-space: normal; }
    #ms-table td:nth-child(3) { white-space: normal; min-width: 11rem; }
    #ms-table td.when .tm { font-weight: 600; }
    #ms-table tr.lim-dark td:nth-child(3) { color: var(--text); }
    #ms-table tr.lim-bright td:nth-child(3) { color: var(--c-limit); }
    .badge { display: inline-block; font-size: 0.65rem; letter-spacing: 0.05em; text-transform: uppercase; border: 1px solid var(--c-limit); color: var(--c-limit); border-radius: 999px; padding: 0 0.4rem; margin-left: 0.3rem; vertical-align: 0.1em; }
    .rules { font-size: 0.85rem; color: var(--muted); }
    .rules td, .rules th { padding: 0.25rem 0.6rem; }
"""

SOLVER_JS = r"""
(function () {
  var META = JSON.parse(document.getElementById('ms-meta').textContent);
  var C = 299792.458, RAD = Math.PI / 180, ERA = 360.98564736629 / 1440, RM = 1737.4, T0 = Date.parse(META.t0);
  // ---------- twin of MonthModel (engine/star_occultations.py) ----------
  function pv(c, t) { var v = 0; for (var i = c.length - 1; i >= 0; i--) v = v * t + c[i]; return v; }
  function deriv(c) { var o = []; for (var i = 1; i < c.length; i++) o.push(i * c[i]); return o; }
  function dot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
  function unit(a) { var n = Math.sqrt(dot(a, a)); return [a[0] / n, a[1] / n, a[2] / n]; }
  function clamp(x) { return Math.max(-1, Math.min(1, x)); }
  function Model(d) {
    this.d = d; this.moon = d.moon; this.sun = d.sun; this.R0 = d.R0; this.ve = d.v_earth; this.seg0 = d.seg0_min; this.n = d.moon.length;
    this.dmoon = d.moon.map(function (seg) { return seg.map(deriv); });
  }
  Model.prototype.observer = function (lat, lon) {
    var a = this.d.earth_a_km, f = this.d.earth_f, e2 = f * (2 - f), la = lat * RAD, lo = lon * RAD;
    var N = a / Math.sqrt(1 - e2 * Math.sin(la) * Math.sin(la)), w = ERA * RAD / 60;
    this.r = [N * Math.cos(la) * Math.cos(lo), N * Math.cos(la) * Math.sin(lo), N * (1 - e2) * Math.sin(la)];
    this.up = [Math.cos(la) * Math.cos(lo), Math.cos(la) * Math.sin(lo), Math.sin(la)];
    this.wxr = [-w * this.r[1], w * this.r[0], 0];
    this.east = [-Math.sin(lo), Math.cos(lo), 0];
    this.north = [-Math.sin(la) * Math.cos(lo), -Math.sin(la) * Math.sin(lo), Math.cos(la)];
  };
  Model.prototype.geom = function (m) {
    var k = Math.floor((m - this.seg0) / 1440); if (k < 0) k = 0; if (k > this.n - 1) k = this.n - 1;
    var local = m - (this.seg0 + 1440 * k), tau = local / 720 - 1, th = ERA * local * RAD, c = Math.cos(th), s = Math.sin(th), R = this.R0[k];
    function G(v) { var w0 = c * v[0] - s * v[1], w1 = s * v[0] + c * v[1], w2 = v[2];
      return [R[0] * w0 + R[3] * w1 + R[6] * w2, R[1] * w0 + R[4] * w1 + R[7] * w2, R[2] * w0 + R[5] * w1 + R[8] * w2]; }
    var obs = G(this.r), up = G(this.up), wr = G(this.wxr), ve = this.ve[k], vobs = [ve[0] + wr[0], ve[1] + wr[1], ve[2] + wr[2]];
    var mc = this.moon[k], dc = this.dmoon[k], sc = this.sun[k];
    var P = [pv(mc[0], tau), pv(mc[1], tau), pv(mc[2], tau)];
    var V = [pv(dc[0], tau) / 43200 + ve[0], pv(dc[1], tau) / 43200 + ve[1], pv(dc[2], tau) / 43200 + ve[2]];
    var d0 = P[0] - obs[0], d1 = P[1] - obs[1], d2 = P[2] - obs[2], dist = Math.sqrt(d0 * d0 + d1 * d1 + d2 * d2);
    var lt = (obs[0] * d0 + obs[1] * d1 + obs[2] * d2) / dist / C;
    d0 += V[0] * lt; d1 += V[1] * lt; d2 += V[2] * lt;
    var n = Math.sqrt(d0 * d0 + d1 * d1 + d2 * d2), u0 = d0 / n + vobs[0] / C, u1 = d1 / n + vobs[1] / C, u2 = d2 / n + vobs[2] / C;
    n = Math.sqrt(u0 * u0 + u1 * u1 + u2 * u2);
    var s0 = pv(sc[0], tau) - obs[0], s1 = pv(sc[1], tau) - obs[1], s2 = pv(sc[2], tau) - obs[2], sn = Math.sqrt(s0 * s0 + s1 * s1 + s2 * s2);
    return { um: [u0 / n, u1 / n, u2 / n], dist: dist, su: [s0 / sn, s1 / sn, s2 / sn], up: up, vobs: vobs, G: G };
  };
  Model.prototype.margin = function (m, u) {
    var g = this.geom(m), v = g.vobs, a = u[0] + v[0] / C, b = u[1] + v[1] / C, cc = u[2] + v[2] / C, nn = Math.sqrt(a * a + b * b + cc * cc);
    return (Math.acos(clamp((g.um[0] * a + g.um[1] * b + g.um[2] * cc) / nn)) - Math.asin(RM / g.dist)) / RAD * 3600;
  };
  Model.prototype.circ = function (m, u) {
    var g = this.geom(m), v = g.vobs, um = g.um, us = unit([u[0] + v[0] / C, u[1] + v[1] / C, u[2] + v[2] / C]);
    var east = unit([-um[1], um[0], 0]), north = [um[1] * east[2] - um[2] * east[1], um[2] * east[0] - um[0] * east[2], um[0] * east[1] - um[1] * east[0]];
    function pa(x) { var dd = [x[0] - um[0], x[1] - um[1], x[2] - um[2]]; return ((Math.atan2(dot(dd, east), dot(dd, north)) / RAD) + 360) % 360; }
    var ps = pa(us), pS = pa(g.su), diff = Math.abs((((ps - pS + 180) % 360) + 360) % 360 - 180);
    var el = Math.acos(clamp(dot(um, g.su))), e = g.G(this.east), nn = g.G(this.north);
    return { m: m, pa: ps, limb: diff < 90 ? 'bright' : 'dark', cusp: Math.abs(90 - diff), illum: (1 - Math.cos(el)) / 2,
             moon_alt: Math.asin(clamp(dot(um, g.up))) / RAD, moon_az: ((Math.atan2(dot(um, e), dot(um, nn)) / RAD) + 360) % 360,
             sun_alt: Math.asin(clamp(dot(g.su, g.up))) / RAD };
  };
  Model.prototype.events = function (stars, lat, lon) {
    this.observer(lat, lon);
    var step = 2, n = Math.floor((this.d.total_min + 360) / step) + 1, UM = new Float64Array(3 * n), VO = new Float64Array(3 * n), SDM = new Float64Array(n), i, g;
    for (i = 0; i < n; i++) { g = this.geom(-180 + i * step);
      UM[3 * i] = g.um[0]; UM[3 * i + 1] = g.um[1]; UM[3 * i + 2] = g.um[2]; VO[3 * i] = g.vobs[0]; VO[3 * i + 1] = g.vobs[1]; VO[3 * i + 2] = g.vobs[2];
      SDM[i] = Math.asin(RM / g.dist) / RAD * 3600; }
    var out = [], half = 90, self = this;
    for (var si = 0; si < stars.length; si++) {
      var st = stars[si], u = st.u, c = Math.round((st.t + 180) / step), w0 = Math.max(0, c - half), w1 = Math.min(n - 1, c + half);
      var marg = new Float64Array(w1 - w0 + 1), best = 1e9, bj = w0, j;
      for (j = w0; j <= w1; j++) {
        var a = u[0] + VO[3 * j] / C, b = u[1] + VO[3 * j + 1] / C, cc = u[2] + VO[3 * j + 2] / C, nn = Math.sqrt(a * a + b * b + cc * cc);
        var mg = Math.acos(clamp((UM[3 * j] * a + UM[3 * j + 1] * b + UM[3 * j + 2] * cc) / nn)) / RAD * 3600 - SDM[j];
        marg[j - w0] = mg; if (mg < best) { best = mg; bj = j; }
      }
      if (best > 3) continue;
      var cons = {};
      for (j = 1; j < marg.length; j++) {
        if ((marg[j] < 0) !== (marg[j - 1] < 0)) {
          var lo = -180 + (w0 + j - 1) * step, hi = -180 + (w0 + j) * step, flo = marg[j - 1];
          for (var it = 0; it < 22; it++) { var mid = 0.5 * (lo + hi); if ((this.margin(mid, u) < 0) === (flo < 0)) lo = mid; else hi = mid; }
          cons[marg[j] < 0 ? 'D' : 'R'] = 0.5 * (lo + hi);
        }
      }
      var ev = { label: st.label, vmag: st.vmag, graze: Math.abs(best) < 3, contacts: {} }, keys = Object.keys(cons);
      if (!keys.length) ev.contacts.C = this.circ(-180 + bj * step, u);
      keys.forEach(function (k) { ev.contacts[k] = self.circ(cons[k], u); });
      out.push(ev);
    }
    return out;
  };
  function visible(ev, inst) {   // twin of visible()
    var L = META.instruments[inst], keep = {};
    Object.keys(ev.contacts).forEach(function (key) {
      var c = ev.contacts[key];
      if (key === 'C' || c.moon_alt < 5) return;
      if (c.sun_alt > -6 && ev.vmag > 1.5) return;
      var lim = c.limb === 'bright' ? L[2] : L[1] - 2.5 * Math.max(0, c.illum - 0.4);
      if (c.sun_alt > -12 && c.sun_alt <= -6) lim -= 1;
      if (ev.vmag <= lim) keep[key] = c;
    });
    return keep;
  }
  window.OccultMonth = { Model: Model, visible: visible };

  // ---------- page ----------
  var COMPASS = ['N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSW','SW','WSW','W','WNW','NW','NNW'];
  function compass(az) { return COMPASS[Math.floor(((az + 11.25) % 360) / 22.5) % 16]; }
  function sky(a) { return a > 0 ? 'daylight, Sun +' + a.toFixed(0) + '°' : a > -6 ? 'twilight' : a > -12 ? 'dusk' : 'dark sky'; }
  function fmt(ms, tz, opts) { try { return new Date(ms).toLocaleString('en-GB', Object.assign({ timeZone: tz }, opts)); } catch (e) { return new Date(ms).toLocaleString('en-GB', opts); } }
  function fD(ms, tz) { return fmt(ms, tz, { weekday: 'short', day: 'numeric', month: 'short' }).replace(',', ''); }
  function fT(ms, tz) { return fmt(ms, tz, { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }); }
  function tzLabel(tz) { try { return new Intl.DateTimeFormat('en-GB', { timeZone: tz, timeZoneName: 'short' }).formatToParts(new Date(T0 + 864e6)).filter(function (p) { return p.type === 'timeZoneName'; })[0].value; } catch (e) { return tz; } }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (ch) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch]; }); }
  function row(ev, vis, tz) {
    var keys = ['D', 'R'].filter(function (k) { return vis[k]; }), verb = { D: 'Disappears', R: 'Reappears' }, c0 = vis[keys[0]];
    var what = verb[keys[0]] + ' at the ' + c0.limb + ' limb';
    if (keys.length === 2) { var c1 = vis[keys[1]]; what += '<small>' + verb[keys[1]].toLowerCase() + ' ' + fT(T0 + c1.m * 60000, tz) + ' at the ' + c1.limb + ' limb</small>'; }
    return '<tr class="lim-' + c0.limb + '"><td class="when"><span class="d">' + fD(T0 + c0.m * 60000, tz) + '</span> <span class="tm">' + fT(T0 + c0.m * 60000, tz) + '</span></td>'
      + '<td><b>' + esc(ev.label) + '</b> <small>V ' + ev.vmag.toFixed(1) + '</small>' + (ev.graze ? ' <span class="badge">graze</span>' : '') + '</td>'
      + '<td>' + what + '</td>'
      + '<td>' + c0.moon_alt.toFixed(0) + '° up in the ' + compass(c0.moon_az) + '<small>' + sky(c0.sun_alt) + '</small></td>'
      + '<td class="det">PA ' + c0.pa.toFixed(0) + '° · cusp ' + c0.cusp.toFixed(0) + '°<small>Moon ' + (c0.illum * 100).toFixed(0) + '% lit</small></td></tr>';
  }
  var model = null, stars = null, cache = {}, INST = META.defaultInstrument, LOC = null;
  var countLine = document.getElementById('count-line'), tbody = document.querySelector('#ms-table tbody');
  try { var si = localStorage.getItem('occult-instrument'); if (si && META.instruments[si]) INST = si; } catch (e) {}
  try { var sl = JSON.parse(localStorage.getItem('occult-loc')); if (sl && isFinite(sl.lat)) LOC = sl; } catch (e) {}
  if (!LOC) LOC = { lat: META.defaultPlace[1], lon: META.defaultPlace[2], label: META.defaultPlace[0] };
  function tzOf(loc) { var c = META.cities[loc.label]; return (c && c[2]) || (loc.label === META.defaultPlace[0] ? META.defaultPlace[3] : Intl.DateTimeFormat().resolvedOptions().timeZone); }
  document.querySelectorAll('#inst-chips input').forEach(function (r) { r.checked = r.value === INST; r.addEventListener('change', function () { INST = r.value; try { localStorage.setItem('occult-instrument', INST); } catch (e) {} render(); }); });
  function render() {
    if (!model) return;
    var key = LOC.lat.toFixed(4) + ',' + LOC.lon.toFixed(4);
    if (!cache[key]) cache[key] = model.events(stars, LOC.lat, LOC.lon);
    var evs = cache[key], tz = tzOf(LOC), occ = 0, list = [];
    evs.forEach(function (ev) { if (ev.contacts.D || ev.contacts.R) occ++; var v = visible(ev, INST); if (v.D || v.R) list.push([ev, v]); });
    list.sort(function (a, b) { return (a[1].D || a[1].R).m - (b[1].D || b[1].R).m; });
    tbody.innerHTML = list.map(function (x) { return row(x[0], x[1], tz); }).join('') || '<tr><td colspan="5">Nothing your instrument can show from here this month — try a larger one.</td></tr>';
    document.getElementById('tz-label').textContent = '(' + tzLabel(tz) + ')';
    document.getElementById('chip-name').textContent = LOC.label;
    countLine.textContent = list.length + ' occultations you can see from ' + LOC.label + ' with ' + META.instruments[INST][0].toLowerCase() + ' this month · ' + occ + ' in all from there';
  }
  var sheet = document.getElementById('loc-sheet'), latI = document.getElementById('loc-lat'), lonI = document.getElementById('loc-lon'), sel = document.getElementById('loc-city');
  function setLoc(lat, lon, label) { lat = +lat; lon = +lon; if (!isFinite(lat) || !isFinite(lon)) return;
    LOC = { lat: lat, lon: lon, label: label || (lat.toFixed(2) + ', ' + lon.toFixed(2)) };
    try { localStorage.setItem('occult-loc', JSON.stringify(LOC)); } catch (e) {}
    countLine.textContent = 'Computing for ' + LOC.label + '…'; setTimeout(render, 10); }
  document.getElementById('loc-chip').addEventListener('click', function () { latI.value = LOC.lat.toFixed(4); lonI.value = LOC.lon.toFixed(4); sheet.showModal(); });
  sheet.addEventListener('click', function (e) { if (e.target === sheet) sheet.close(); });
  document.getElementById('loc-go').addEventListener('click', function () { setLoc(latI.value, lonI.value); sheet.close(); });
  sel.addEventListener('change', function () { var c = META.cities[sel.value]; if (c) { setLoc(c[0], c[1], sel.value); sheet.close(); } });
  var geo = document.getElementById('loc-geo'); if (!navigator.geolocation) geo.hidden = true;
  geo.addEventListener('click', function () { geo.disabled = true; geo.textContent = 'Locating…';
    navigator.geolocation.getCurrentPosition(function (p) { geo.disabled = false; geo.textContent = 'Use my location'; setLoc(p.coords.latitude, p.coords.longitude); sheet.close(); },
      function () { geo.disabled = false; geo.textContent = 'Location unavailable'; }); });
  fetch(META.src).then(function (r) { return r.json(); }).then(function (d) {
    model = new Model(d);
    var s = d.stars; stars = s.label.map(function (l, i) { return { label: l, vmag: s.vmag[i], u: [s.u[3 * i], s.u[3 * i + 1], s.u[3 * i + 2]], t: s.t[i] / 10 }; });
    if (!(LOC.label === META.defaultPlace[0] && INST === META.defaultInstrument)) countLine.textContent = 'Computing for ' + LOC.label + '…';
    setTimeout(render, 10);
  });
})();
"""


TEMPLATE = """
<nav class="subnav">
  <div class="subnav-row">
    <div class="subnav-links">__PREV__<a href="/#moon-stars">All months</a>__NEXT__</div>
    <button class="chip" id="loc-chip" type="button" aria-haspopup="dialog"><span class="chip-pin">📍</span><span id="chip-name">__PLACE__</span><span class="chip-sub" id="chip-sub"></span></button>
  </div>
</nav>
<dialog id="loc-sheet" class="sheet" aria-label="Location">
  <form method="dialog" class="sheet-body">
    <div class="sheet-title">Location</div>
    <label>City <select id="loc-city"><option value="">—</option>__CITY_OPTS__</select></label>
    <div class="loc-row">
      <label>Lat <input id="loc-lat" type="number" step="any" min="-90" max="90" placeholder="28.614"></label>
      <label>Lon <input id="loc-lon" type="number" step="any" min="-180" max="180" placeholder="77.209"></label>
    </div>
    <div class="loc-row">
      <button class="btn btn-primary" id="loc-go" type="button">Apply</button>
      <button class="btn" id="loc-geo" type="button">Use my location</button>
      <button class="btn" value="cancel">Close</button>
    </div>
  </form>
</dialog>
<main class="wrap">
  <h1>__TITLE__</h1>
  <p class="sub">Lunar occultations of stars to magnitude 9.5, computed for your location</p>
  <p class="lead">Every night the Moon slides in front of stars. A star doesn't fade behind it — it switches off, then
  switches back on at the other edge, often an hour later. Pick your place and what you observe with; the list keeps
  what you can realistically see.</p>
  <div class="filters" id="inst-chips">__INST_CHIPS__</div>
  <p class="hint" id="count-line">__COUNT__</p>
  <div class="table-wrap">
    <table id="ms-table"><thead><tr><th>When <small id="tz-label">(__TZL__)</small></th><th>Star</th><th>Event</th><th>Where to look</th><th>Details</th></tr></thead>
    <tbody>__ROWS__</tbody></table>
  </div>
  <h2>Reading the list</h2>
  <p class="method">A <em>dark-limb</em> event — the star vanishing into, or popping out of, the unlit edge of the Moon — is
  easy to see. At the <em>bright</em> limb only bright stars show against the glare. <em>PA</em> is where on the limb it
  happens, measured from north through east; the <em>cusp angle</em> is the distance from the nearest horn of the crescent.
  <span class="badge">graze</span> marks a star passing within 3″ of the edge from your place: a few kilometres from a graze
  line, where it may blink several times behind mountains.</p>
  <table class="rules"><thead><tr><th>Instrument</th><th>dark limb</th><th>bright limb</th></tr></thead><tbody>__RULES__</tbody></table>
  <p class="method">Those limits are rules of thumb: the dark-limb limit drops by 2.5 magnitudes × (lit fraction − 0.4) in
  moonglare and by 1 in twilight; events with the Moon under 5° are left out, and daylight events except for the
  brightest stars. Stars are from Gaia DR3 to G 9.5, with Hipparcos-2 for the brightest and the Yale Bright Star
  Catalogue for names; the Moon is from the JPL DE431 ephemeris. Times are for the Moon's mean limb, ±2 s — mountains at
  the edge can move a contact by a few seconds, and much more near a graze.</p>
  <script type="application/json" id="ms-meta">__META__</script>
</main>
__FOOTER__
<script>
__JS__
</script>
</body>
</html>
"""


def month_page(ym, d, cities, nav):
    from star_occultations import INSTRUMENTS, MonthModel, visible
    y, mo = (int(x) for x in ym.split("-"))
    label = f"{MONTHS[mo - 1]} {y}"
    slug = f"moon-stars-{ym}"
    title = f"The Moon and the stars — {label}"
    t0 = datetime.strptime(d["t0"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    name, lat, lon, tzname = DEFAULT_PLACE
    tz = zoneinfo.ZoneInfo(tzname)
    model = MonthModel(d)
    evs = model.events(MonthModel.star_list(d), lat, lon)
    occ = sum(1 for e in evs if any(k in e["contacts"] for k in "DR"))
    shown = []
    for ev in evs:
        vis = visible(ev, DEFAULT_INSTRUMENT)
        if "D" in vis or "R" in vis:
            shown.append((min(c["m"] for k, c in vis.items()), ev, vis))
    shown.sort(key=lambda x: x[0])
    rows = "".join(row_html(ev, vis, t0, tz) for _, ev, vis in shown)
    inst_label = INSTRUMENTS[DEFAULT_INSTRUMENT][0]
    chips = "".join(f'<label class="chipbox"><input type="radio" name="inst" value="{k}"{" checked" if k == DEFAULT_INSTRUMENT else ""}> {esc(v[0])}</label>'
                    for k, v in INSTRUMENTS.items())
    rules = "".join(f"<tr><td>{esc(v[0])}</td><td>V ≤ {v[1]:.1f}</td><td>V ≤ {v[2]:.1f}</td></tr>" for v in INSTRUMENTS.values())
    meta = {"src": f"/data/{slug}.json", "t0": d["t0"], "defaultPlace": list(DEFAULT_PLACE), "defaultInstrument": DEFAULT_INSTRUMENT,
            "instruments": {k: list(v) for k, v in INSTRUMENTS.items()}, "cities": cities}
    prev_link = f'<a href="/{nav["prev"]}">‹ {nav["prev_label"]}</a>' if nav.get("prev") else "<span></span>"
    next_link = f'<a href="/{nav["next"]}">{nav["next_label"]} ›</a>' if nav.get("next") else "<span></span>"
    desc = (f"Every lunar occultation of a star to magnitude 9.5 in {label}, computed for your location: disappearance and "
            f"reappearance times, dark or bright limb, and where to look.")
    page = head(f"{title} · {SITE_NAME}", desc, f"/{slug}", extra=f"<style>{MS_CSS}</style>")
    body = TEMPLATE
    for k, v in {"__PREV__": prev_link, "__NEXT__": next_link, "__PLACE__": esc(name), "__TITLE__": esc(title),
                 "__CITY_OPTS__": "".join(f'<option value="{esc(n)}">{esc(n)}</option>' for n in cities),
                 "__INST_CHIPS__": chips, "__TZL__": "IST",
                 "__COUNT__": f"{len(shown)} occultations you can see from {esc(name)} with {esc(inst_label.lower())} this month · {occ} in all from there",
                 "__ROWS__": rows, "__RULES__": rules,
                 "__META__": json.dumps(meta, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"),
                 "__FOOTER__": FOOTER, "__JS__": SOLVER_JS}.items():
        body = body.replace(k, v)
    (OUT / f"{slug}.html").write_text(page + body)
    (OUT / "data").mkdir(exist_ok=True)
    (OUT / "data" / f"{slug}.json").write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")))
    print(f"wrote site/{slug}.html: {len(shown)} rows for {name} ({inst_label}), {occ} occultations there")
    return {"slug": slug, "label": label, "year": y, "month": mo, "n": len(shown), "planet": "moon-stars"}


def build_all(cities, only=None):
    files = sorted((ROOT / "data").glob("moon-stars-*.json"))
    yms = [f.stem[len("moon-stars-"):] for f in files]
    if only:
        yms = [ym for ym in yms if ym in only]
    built = []
    for i, ym in enumerate(yms):
        nav = {}
        if i > 0:
            nav["prev"], nav["prev_label"] = f"moon-stars-{yms[i - 1]}", MONTHS[int(yms[i - 1][5:]) - 1][:3]
        if i < len(yms) - 1:
            nav["next"], nav["next_label"] = f"moon-stars-{yms[i + 1]}", MONTHS[int(yms[i + 1][5:]) - 1][:3]
        built.append(month_page(ym, json.loads((ROOT / "data" / f"moon-stars-{ym}.json").read_text()), cities, nav))
    return built
