#!/usr/bin/env python3
"""Asteroid occultations: one page per month listing every asteroid shadow that crosses India at night, with a small
map of its path and — for the reader's own place — how far the path passes, when, and for how long the star vanishes.

  data/asteroids-<YYYY-MM>.json   engine/asteroid_occultations.py (DE431 + JPL orbits + Gaia DR3)
  -> site/asteroids-<YYYY-MM>.html, site/data/asteroids-<YYYY-MM>.json

The JS `solve()` / `toCentre()` in SOLVER_JS are the twins of `local()` / `to_centre()` in the engine, and `you()` is
the twin of `you_html()` here, with the same rounding (floor(x + 0.5)) — change them TOGETHER. The page prerenders
New Delhi; the browser recomputes for the chosen place and regroups the nights in its timezone.
"""

import json
import math
import sys
import zoneinfo
from datetime import datetime, timedelta, timezone

from build_pages import FOOTER, OUT, ROOT, SITE_NAME, Proj, esc, head

sys.path.insert(0, str(ROOT / "engine"))

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]
DEFAULT_PLACE = ("New Delhi", 28.6139, 77.2090, "Asia/Kolkata")
COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MAP_W = 400


def _hash(content):
    import hashlib
    return hashlib.sha1(content if isinstance(content, bytes) else content.encode()).hexdigest()[:10]


def r0(x):
    """Round half up, exactly like the JS Math.floor(x + 0.5)."""
    return int(math.floor(x + 0.5))


def r1(x):
    return f"{math.floor(x * 10 + 0.5) / 10:.1f}"


def compass(az):
    return COMPASS[int((az + 11.25) // 22.5) % 16]


def sky_text(sun_alt):
    return "daylight" if sun_alt > 0 else "twilight" if sun_alt > -6 else "dusk" if sun_alt > -12 else "dark sky"


def star_label(st):
    return "Gaia DR3 …" + st["gaia"][-7:]


def you_html(ev, s, tc):
    """The place-dependent lines of a card: (verdict class, what you see, where to look). Twin of JS you()."""
    R, sig = ev["el"]["R"], ev["sigma_km"] or 0.0
    d = abs(s["d"])
    ground, brg = tc
    look = f"Star {r0(s['star_alt'])}° up in the {compass(s['star_az'])} · {sky_text(s['sun_alt'])}"
    if s["star_alt"] < 0:
        return "below", "The star is below your horizon then", f"Star {r0(-s['star_alt'])}° below the horizon"
    edge = ground * (d - R) / d if d > 0 else 0.0
    if d <= R:
        return "in", (f"You are inside the path, {r0(ground)} km from its centre line: "
                      f"the star vanishes for up to {r1(s['dur'])} s"), look
    if d <= R + sig:
        return "near", (f"The predicted edge passes {r0(edge)} km to the {compass(brg)} — "
                        f"within its 1σ uncertainty of {r0(sig)} km, worth watching"), look
    return "out", f"The path passes {r0(edge)} km to the {compass(brg)}", look


def path_d(proj, runs, close=False, tol=0.14):
    """SVG path data for [lat, lon] runs, simplified to `tol` degrees and in whole map units (a card map is 132 px for 400
    units, so a unit is a third of a pixel and 0.08° is a third of a pixel too) — the data files keep full precision."""
    from asteroid_occultations import simplify
    parts = []
    for run in runs:
        xy = []
        for lat, lon in (simplify(run, tol) if len(run) > 2 else run):
            p = tuple(round(v) for v in proj.xy(lat, lon))
            if not xy or p != xy[-1]:
                xy.append(p)
        if len(xy) > 1:
            parts.append("M" + " ".join(f"{x},{y}" for x, y in xy) + ("Z" if close else ""))
    return "".join(parts)


WORLD_FILE = "world-coarse.json"
_WORLD = {}


def world_url():
    """A coarse world outline (rings of [lat, lon]) for the panels' inset: one small file, written once and fetched by
    the page the first time a reader opens a panel — too big to sit in every page's HTML."""
    if not _WORLD:
        from asteroid_occultations import simplify
        g = json.loads((ROOT / "geo" / "world.json").read_text())
        rings = []
        for r in g["land"]:
            if max(p[0] for p in r) - min(p[0] for p in r) < 3 and max(p[1] for p in r) - min(p[1] for p in r) < 3:
                continue
            s = simplify([[p[1], p[0]] for p in r], 0.8)
            if len(s) > 3:
                rings.append([[round(la, 1), round(lo, 1)] for la, lo in s])
        text = json.dumps(rings, separators=(",", ":"))
        (OUT / "data").mkdir(parents=True, exist_ok=True)
        (OUT / "data" / WORLD_FILE).write_text(text)
        _WORLD["url"] = f"/data/{WORLD_FILE}?v={_hash(text)}"
        print(f"wrote site/data/{WORLD_FILE}: {len(rings)} rings, {len(text) // 1024} KB")
    return _WORLD["url"]


def land_svg(proj, geo):
    """The audience's land for the thumbnails: a card map is 132 px wide, so islands under a degree and detail finer
    than about half a pixel are dropped."""
    rings = [[[la, lo] for lo, la in r] for r in geo["land"]
             if max(p[0] for p in r) - min(p[0] for p in r) >= 1.0 or max(p[1] for p in r) - min(p[1] for p in r) >= 1.0]
    out = f'<path class="land" d="{path_d(proj, rings, close=True, tol=0.12)}"/>'
    b = path_d(proj, [[[la, lo] for lo, la in l] for l in geo.get("borders", [])], tol=0.12)
    return out + (f'<path class="border" d="{b}"/>' if b else "")


def card_static(ev, proj, land_id="ast-land"):
    a, st = ev["asteroid"], ev["star"]
    W, H = proj.W, proj.H
    L = ev["lines"]
    svg = [f'<svg class="ast-map" viewBox="0 0 {W:.0f} {H:.0f}" role="img" aria-label="Path of the shadow across India">'
           f'<use href="#{land_id}"/>']
    # the thumbnail carries the band and its edges only: the 1-sigma lines live in the panel's larger map and its
    # cross-section, where they can be read, and they cost a busy month a kilobyte here
    if len(L.get("left", [])) == 1 and len(L.get("right", [])) == 1:
        svg.append(f'<path class="ast-band" d="{path_d(proj, [L["left"][0] + L["right"][0][::-1]], close=True, tol=0.18)}"/>')
    for key, cls in (("left", "ast-lim"), ("right", "ast-lim"), ("centre", "ast-cl")):
        d = path_d(proj, L.get(key, []), tol=0.18)
        if d:
            svg.append(f'<path class="{cls}" d="{d}"/>')
    svg.append('<circle class="ast-pin" r="7" cx="-20" cy="-20"/></svg>')
    flags = []
    if st["ruwe"] is not None and st["ruwe"] > 1.4:
        flags.append(f'<span class="badge" title="Gaia RUWE {st["ruwe"]}: the star may be double">RUWE {st["ruwe"]}</span>')
    if st["dup"]:
        flags.append('<span class="badge" title="Gaia flags a duplicated source">dup</span>')
    sig = f' ± {r0(ev["sigma_km"])} km (1σ)' if ev["sigma_km"] is not None else ""
    tsig = f' · time ± {r1(ev["sigma_s"])} s' if ev.get("sigma_s") is not None else ""
    title = (f'<b class="ast-name">({esc(a["number"])}) {esc(a["name"])}</b> <small>{r0(a["diameter_km"])} km</small> '
             f'hides <b class="ast-star" title="Gaia DR3 {esc(st["gaia"])}, RA {st["ra"]:.4f}° Dec {st["dec"]:+.4f}°">{esc(star_label(st))}</b> '
             f'<small>V {r1(st["v"])}</small>{"".join(flags)}')
    facts = (f'Drop {r1(ev["drop"])} mag (to V {r1(a["mag"])}) · up to {r1(ev["dur_max_s"])} s · path {r0(a["diameter_km"])} km wide{sig}{tsig} · '
             f'Moon {r0(ev["moon_illum"] * 100)}% lit, {r0(ev["moon_sep"])}° away')
    return "".join(svg), title, facts


def card_html(ev, proj, s, tc, tz):
    svg, title, facts = card_static(ev, proj)
    cls, what, look = you_html(ev, s, tc)
    t = datetime.strptime(ev["el"]["t0"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) + timedelta(seconds=s["tau"])
    # the panel itself is built by the JS on first open — the prerender only carries the button
    more = '<button class="ast-more" type="button" aria-expanded="false">Chart &amp; map</button>' if ev.get("field") else ""
    return (f'<article class="ast v-{cls}" id="{esc(ev["id"])}" data-id="{esc(ev["id"])}">{svg}<div class="ast-body">'
            f'<div class="ast-top"><span class="ast-time">{t.astimezone(tz).strftime("%H:%M:%S")}</span> {title}</div>'
            f'<div class="ast-you">{what}</div><div class="ast-look">{look}</div>'
            f'<div class="ast-facts">{facts}</div>{more}</div></article>')


def night_key(ev, tz):
    t = datetime.strptime(ev["t_geo"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (t.astimezone(tz) - timedelta(hours=12)).date()


AST_CSS = """
    :root { --t-ast: #a8324e; }
    @media (prefers-color-scheme: dark) { :root { --t-ast: #f08aa3; } }
    .filters { display: flex; flex-wrap: wrap; gap: 0.4rem; margin: 1rem 0 0.3rem; }
    .chipbox { display: inline-flex; align-items: center; gap: 0.35rem; border: 1px solid var(--line); border-radius: 999px; padding: 0.2rem 0.7rem; font-size: 0.85rem; cursor: pointer; }
    .chipbox input { accent-color: var(--t-ast); }
    .chipbox:has(input:checked) { border-color: var(--t-ast); color: var(--t-ast); }
    .cal { display: grid; grid-template-columns: repeat(7, 1fr); gap: 4px; margin: 0.9rem 0 1.2rem; }
    .cal-wd { font-size: 0.68rem; color: var(--muted); text-align: center; text-transform: uppercase; letter-spacing: 0.06em; }
    .cal-cell { display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 6px 0 5px; border-radius: 10px; background: var(--card); border: 1px solid var(--border); color: var(--muted); min-height: 50px; }
    .cal-cell.empty { background: none; border: 0; }
    .cal-cell.has { color: var(--text); border-color: color-mix(in srgb, var(--t-ast) 55%, var(--border)); }
    .cal-cell.mine { background: color-mix(in srgb, var(--t-ast) 16%, var(--card)); }
    a.cal-cell:hover { text-decoration: none; border-color: var(--t-ast); }
    .cal-d { font-size: 0.78rem; font-weight: 600; line-height: 1; }
    .cal-n { font-size: 0.75rem; font-weight: 700; color: var(--t-ast); min-height: 0.9rem; line-height: 0.9rem; }
    .night { margin: 1.4rem 0 0; scroll-margin-top: 72px; }
    .night-head { display: flex; align-items: baseline; justify-content: space-between; gap: 0.3rem 0.8rem; flex-wrap: wrap; border-bottom: 1px solid var(--border); padding-bottom: 0.2rem; }
    .night-head h3 { font-size: 1.05rem; margin: 0; }
    .ast { display: grid; grid-template-columns: 132px 1fr; gap: 0.9rem; align-items: start; background: var(--card); border: 1px solid var(--border);
           border-left: 3px solid var(--border); border-radius: 12px; padding: 0.7rem 0.9rem; margin: 0.6rem 0; scroll-margin-top: 72px; }
    .ast.v-in { border-left-color: var(--c-visible); } .ast.v-near { border-left-color: var(--c-limit); }
    .ast-map { width: 132px; height: auto; display: block; border-radius: 6px; background: var(--sea); }
    .ast-map .land { stroke-width: 0.5; } .ast-map .border { stroke-width: 0.5; }
    .ast-band { fill: color-mix(in srgb, var(--t-ast) 30%, transparent); stroke: none; }
    .ast-lim { fill: none; stroke: var(--t-ast); stroke-width: 2.2; stroke-linejoin: round; }
    .ast-sig { fill: none; stroke: var(--t-ast); stroke-width: 1.4; stroke-dasharray: 5 4; opacity: 0.75; }
    .ast-cl { fill: none; stroke: var(--t-ast); stroke-width: 0.9; opacity: 0.8; }
    .ast-pin { fill: var(--c-limit); stroke: var(--card); stroke-width: 2.5; }
    .ast-time { font-weight: 700; font-size: 1.05rem; font-variant-numeric: tabular-nums; }
    .ast-top small { color: var(--muted); white-space: nowrap; }
    .ast-name { font-family: var(--serif); }
    .ast-star { white-space: nowrap; }
    .ast-you { font-size: 0.92rem; margin-top: 0.1rem; }
    .v-in .ast-you { color: var(--c-visible); font-weight: 600; } .v-near .ast-you { color: var(--c-limit); font-weight: 600; } .v-below .ast-you { color: var(--c-down); }
    .ast-look, .ast-facts { font-size: 0.78rem; color: var(--muted); }
    .badge { display: inline-block; font-size: 0.65rem; letter-spacing: 0.05em; text-transform: uppercase; border: 1px solid var(--c-limit); color: var(--c-limit); border-radius: 999px; padding: 0 0.4rem; margin-left: 0.3rem; vertical-align: 0.1em; }
    .ast-more { margin-top: 0.4rem; background: none; border: 0; padding: 0; font: inherit; font-size: 0.78rem; color: var(--t-ast); cursor: pointer; }
    .ast-more:hover { text-decoration: underline; }
    .ast-detail { grid-column: 1 / -1; margin-top: 0.6rem; border-top: 1px dotted var(--line); padding-top: 0.7rem; }
    .ast-panes { display: grid; grid-template-columns: 300px 1fr; gap: 0.9rem; align-items: start; }
    .ast-panes2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 0.9rem; margin-top: 0.8rem; align-items: start; }
    @media (max-width: 620px) { .ast-panes { grid-template-columns: 1fr; } }
    .chord, .curve, .world, .strip { width: 100%; height: auto; display: block; }
    .chord, .curve, .world { background: var(--sea); border-radius: 8px; }
    .pane-cap { font-size: 0.76rem; color: var(--muted); margin-top: 0.25rem; }
    .ch-disc { fill: color-mix(in srgb, var(--t-ast) 22%, transparent); stroke: var(--t-ast); stroke-width: 1.2; }
    .ch-chord { stroke: var(--c-limit); stroke-width: 2.4; stroke-linecap: round; }
    .ch-miss { stroke: var(--muted); stroke-width: 1.6; stroke-dasharray: 5 4; }
    .ch-sig { stroke: var(--t-ast); stroke-width: 1; stroke-dasharray: 4 3; opacity: 0.7; fill: none; }
    .st-band { fill: color-mix(in srgb, var(--t-ast) 30%, transparent); }
    .st-sig { fill: color-mix(in srgb, var(--t-ast) 12%, transparent); }
    .st-axis { stroke: var(--line); stroke-width: 1; }
    .st-you { fill: var(--c-limit); }
    .st-lbl { font: 500 9px -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif; fill: var(--muted); }
    .cv-line { fill: none; stroke: var(--c-limit); stroke-width: 2; stroke-linejoin: round; }
    .cv-line.centre { stroke: var(--muted); stroke-dasharray: 5 4; stroke-width: 1.6; }
    .cv-axis { stroke: var(--line); stroke-width: 1; }
    .cv-sig { fill: color-mix(in srgb, var(--c-limit) 20%, transparent); }
    .wd-land { fill: var(--land); stroke: var(--land-line); stroke-width: 0.3; }
    .wd-path { fill: none; stroke: var(--t-ast); stroke-width: 1.6; }
    .wd-frame { fill: none; stroke: var(--c-limit); stroke-width: 0.8; }
    .finder, .ast-big { width: 100%; height: auto; display: block; background: var(--sea); border-radius: 8px; }
    .fd-edge { fill: none; stroke: var(--line); stroke-width: 0.8; }
    .fd-star { fill: var(--text); }
    .fd-target { fill: none; stroke: var(--c-limit); stroke-width: 1.6; }
    .fd-track { fill: none; stroke: var(--t-ast); stroke-width: 1.2; stroke-dasharray: 4 3; }
    .fd-tick { fill: var(--t-ast); }
    .fd-lbl, .bm-lbl { font: 500 8px -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif; fill: var(--muted); }
    .fd-cap { font: 500 9px -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif; fill: var(--muted); }
    .bm-city { fill: var(--muted); opacity: 0.55; }
    .bm-tick { stroke: var(--t-ast); stroke-width: 1; opacity: 0.8; }
    .ast-dl { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.6rem; }
    .ast-dl .btn { font-size: 0.78rem; padding: 0.25rem 0.7rem; }
    .ast-note { font-size: 0.78rem; color: var(--muted); margin-top: 0.5rem; }
    @media (max-width: 560px) { .ast { grid-template-columns: 92px 1fr; gap: 0.6rem; } .ast-map { width: 92px; } .cal-cell { min-height: 44px; } }
    .rules td, .rules th { padding: 0.25rem 0.6rem; font-size: 0.85rem; white-space: normal; }
"""

SOLVER_JS = r"""
(function () {
  var META = JSON.parse(document.getElementById('ast-meta').textContent);
  var C = 299792.458, AE = 6378.137, FE = 1 / 298.257223563, RAD = Math.PI / 180, WE = 360.98564736629 * RAD / 86400;
  function dot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
  function clamp(x) { return Math.max(-1, Math.min(1, x)); }
  function poly(c, u) { var v = 0; for (var i = c.length - 1; i >= 0; i--) v = v * u + c[i]; return v; }
  function dpoly(c, u) { var v = 0; for (var i = c.length - 1; i > 0; i--) v = v * u + i * c[i]; return v; }
  // ---------- twin of local() (engine/asteroid_occultations.py) ----------
  function solve(el, lat, lon) {
    var la = lat * RAD, lo = lon * RAD, e2 = FE * (2 - FE), N = AE / Math.sqrt(1 - e2 * Math.sin(la) * Math.sin(la));
    var r = [N * Math.cos(la) * Math.cos(lo), N * Math.cos(la) * Math.sin(lo), N * (1 - e2) * Math.sin(la)];
    var up = [Math.cos(la) * Math.cos(lo), Math.cos(la) * Math.sin(lo), Math.sin(la)], east = [-Math.sin(lo), Math.cos(lo), 0];
    var north = [-Math.sin(la) * Math.cos(lo), -Math.sin(la) * Math.sin(lo), Math.cos(la)];
    var k = el.k, n1 = Math.hypot(-k[1], k[0]), e1 = [-k[1] / n1, k[0] / n1, 0];
    var ee = [k[1] * e1[2] - k[2] * e1[1], k[2] * e1[0] - k[0] * e1[2], k[0] * e1[1] - k[1] * e1[0]];
    var R0 = el.R0, W = el.W, vp = el.vp, wxr = [-WE * r[1], WE * r[0], 0];
    function G(tau, v) { var th = WE * tau, c = Math.cos(th), s = Math.sin(th), w0 = c * v[0] - s * v[1], w1 = s * v[0] + c * v[1], w2 = v[2];
      return [R0[0] * w0 + R0[3] * w1 + R0[6] * w2, R0[1] * w0 + R0[4] * w1 + R0[7] * w2, R0[2] * w0 + R0[5] * w1 + R0[8] * w2]; }
    function state(tau) {
      var u = Math.max(-1, Math.min(1, tau / W)), g = G(tau, r), gd = G(tau, wxr), z = dot(g, k), dz = dot(gd, k);
      return [poly(el.x, u) + vp[0] * z / C - dot(g, e1), poly(el.y, u) + vp[1] * z / C - dot(g, ee),
              dpoly(el.x, u) / W + vp[0] * dz / C - dot(gd, e1), dpoly(el.y, u) / W + vp[1] * dz / C - dot(gd, ee)];
    }
    var tau = 0, s;
    for (var it = 0; it < 8; it++) {
      s = state(tau);
      var step = (s[0] * s[2] + s[1] * s[3]) / (s[2] * s[2] + s[3] * s[3]);
      tau = Math.max(-W, Math.min(W, tau - step));
      if (Math.abs(step) < 1e-3) break;
    }
    s = state(tau);
    var speed = Math.hypot(s[2], s[3]), d = Math.hypot(s[0], s[1]), sgn = (s[3] * s[0] - s[2] * s[1]) >= 0 ? 1 : -1, R = el.R;
    var ug = G(tau, up), eg = G(tau, east), ng = G(tau, north);
    return { tau: tau, d: sgn * d, speed: speed, dur: d < R ? 2 * Math.sqrt(R * R - d * d) / speed : 0,
             star_alt: Math.asin(clamp(dot(k, ug))) / RAD, star_az: ((Math.atan2(dot(k, eg), dot(k, ng)) / RAD) + 360) % 360,
             sun_alt: Math.asin(clamp(dot(el.sun, ug))) / RAD };
  }
  function toCentre(el, lat, lon) {   // twin of to_centre()
    var h = 0.02, d0 = solve(el, lat, lon).d;
    var dn = (solve(el, lat + h, lon).d - solve(el, lat - h, lon).d) / (2 * h * 111.195);
    var de = (solve(el, lat, lon + h).d - solve(el, lat, lon - h).d) / (2 * h * 111.195 * Math.cos(lat * RAD));
    return [Math.abs(d0) / Math.hypot(dn, de), ((Math.atan2(-d0 * de, -d0 * dn) / RAD) + 360) % 360];
  }
  // tests/test_asteroid_pages.py runs these against their Python twins and against the engine's own path lines
  window.OccultAsteroids = { solve: solve, toCentre: toCentre, you: you, kml: kml, gpx: gpx, worldTrack: worldTrack };

  // ---------- page ----------
  var COMPASS = ['N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSW','SW','WSW','W','WNW','NW','NNW'];
  function compass(az) { return COMPASS[Math.floor((az + 11.25) / 22.5) % 16]; }
  function r0(x) { return Math.floor(x + 0.5); }
  function r1(x) { return (Math.floor(x * 10 + 0.5) / 10).toFixed(1); }
  function sky(a) { return a > 0 ? 'daylight' : a > -6 ? 'twilight' : a > -12 ? 'dusk' : 'dark sky'; }
  function you(ev, s, tc) {   // twin of you_html()
    var R = ev.el.R, sig = ev.sigma_km || 0, d = Math.abs(s.d), ground = tc[0], brg = tc[1];
    var look = 'Star ' + r0(s.star_alt) + '° up in the ' + compass(s.star_az) + ' · ' + sky(s.sun_alt);
    if (s.star_alt < 0) return ['below', 'The star is below your horizon then', 'Star ' + r0(-s.star_alt) + '° below the horizon'];
    var edge = d > 0 ? ground * (d - R) / d : 0;
    if (d <= R) return ['in', 'You are inside the path, ' + r0(ground) + ' km from its centre line: the star vanishes for up to ' + r1(s.dur) + ' s', look];
    if (d <= R + sig) return ['near', 'The predicted edge passes ' + r0(edge) + ' km to the ' + compass(brg) + ' — within its 1σ uncertainty of ' + r0(sig) + ' km, worth watching', look];
    return ['out', 'The path passes ' + r0(edge) + ' km to the ' + compass(brg), look];
  }
  function fmt(ms, tz, opts) { try { return new Date(ms).toLocaleString('en-GB', Object.assign({ timeZone: tz }, opts)); } catch (e) { return new Date(ms).toLocaleString('en-GB', opts); } }
  function fT(ms, tz) { return fmt(ms, tz, { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }); }
  function tzLabel(tz) { try { return new Intl.DateTimeFormat('en-GB', { timeZone: tz, timeZoneName: 'short' }).formatToParts(new Date(Date.parse(META.t0) + 864e6)).filter(function (p) { return p.type === 'timeZoneName'; })[0].value; } catch (e) { return tz; } }
  function dateKey(ms, tz) { try { return new Intl.DateTimeFormat('en-CA', { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(ms)); } catch (e) { return new Date(ms).toISOString().slice(0, 10); } }
  function keyLabel(k) { var p = k.split('-'); return new Date(Date.UTC(+p[0], +p[1] - 1, +p[2], 12)).toLocaleDateString('en-GB', { timeZone: 'UTC', weekday: 'short', day: 'numeric', month: 'short' }).replace(',', ''); }
  var B = META.bbox, K = Math.cos(META.lat0 * RAD), SC = META.mapW / ((B[2] - B[0]) * K);
  function xy(lat, lon) { return [(lon - B[0]) * K * SC, (B[3] - lat) * SC]; }

  // ---------- the expanded panel: finder chart, the path over India, and the path to take with you ----------
  var byId = {};
  function fHM(ms, tz) { return fT(ms, tz).slice(0, 5); }
  function finderSvg(ev, tz) {
    var f = ev.field;
    if (!f) return '';
    var S = 300, c = S / 2, edge = c - 8, k = edge / f.r, t0 = Date.parse(ev.el.t0), out = [];
    out.push('<svg class="finder" viewBox="0 0 ' + S + ' ' + S + '" role="img" aria-label="Finder chart for the star">');
    out.push('<circle class="fd-edge" cx="' + c + '" cy="' + c + '" r="' + edge + '"/>');
    f.stars.forEach(function (s) {
      var x = c - s[0] * f.u * k, y = c - s[1] * f.u * k;
      if (Math.hypot(x - c, y - c) > edge) return;
      out.push('<circle class="fd-star" cx="' + x.toFixed(1) + '" cy="' + y.toFixed(1) + '" r="' + Math.max(0.7, 3.4 - 0.36 * (s[2] / 10 - 8.5)).toFixed(1) + '"/>');
    });
    var pts = f.track.map(function (t) { return [c - t[0] * f.u * k, c - t[1] * f.u * k]; });
    out.push('<path class="fd-track" d="M' + pts.map(function (q) { return q[0].toFixed(1) + ',' + q[1].toFixed(1); }).join(' ') + '"/>');
    var last = null;                         // a slow asteroid crosses little of the field: only label what fits
    pts.forEach(function (q, i) {
      var h = i - f.track_h;
      if (h % 3 !== 0 || Math.hypot(q[0] - c, q[1] - c) > edge - 2) return;
      out.push('<circle class="fd-tick" cx="' + q[0].toFixed(1) + '" cy="' + q[1].toFixed(1) + '" r="1.6"/>');
      if (last && Math.hypot(q[0] - last[0], q[1] - last[1]) < 45) return;
      last = q;
      out.push('<text class="fd-lbl" x="' + (q[0] + 4).toFixed(1) + '" y="' + (q[1] - 3).toFixed(1) + '">' + fHM(t0 + h * 36e5, tz) + '</text>');
    });
    var a = pts[pts.length - 1], b0 = pts[pts.length - 2];       // which way it is moving
    if (a && b0) {
      var dx = a[0] - b0[0], dy = a[1] - b0[1], n = Math.hypot(dx, dy) || 1, ax = a[0] + dx / n * 6, ay = a[1] + dy / n * 6;
      out.push('<path class="fd-track" style="stroke-dasharray:none" d="M' + (ax - dx / n * 6 - dy / n * 3).toFixed(1) + ',' + (ay - dy / n * 6 + dx / n * 3).toFixed(1)
               + ' ' + ax.toFixed(1) + ',' + ay.toFixed(1) + ' ' + (ax - dx / n * 6 + dy / n * 3).toFixed(1) + ',' + (ay - dy / n * 6 - dx / n * 3).toFixed(1) + '"/>');
    }
    out.push('<circle class="fd-target" cx="' + c + '" cy="' + c + '" r="7"/>');
    out.push('<text class="fd-cap" x="6" y="' + (S - 6) + '">' + (2 * f.r) + '′ field · stars to G ' + f.lim + ' · N up, E left · track ' + (2 * f.track_h) + ' h</text>');
    return out.join('') + '</svg>';
  }
  function bigMap(ev, tz) {
    var W = META.mapW, H = (B[3] - B[1]) * SC, L = ev.lines, t0 = Date.parse(ev.el.t0), out = [];
    function d(runs, close) {
      return (runs || []).map(function (r) {
        return 'M' + r.map(function (q) { var p = xy(q[0], q[1]); return p[0].toFixed(1) + ',' + p[1].toFixed(1); }).join(' ') + (close ? 'Z' : '');
      }).join('');
    }
    out.push('<svg class="ast-big" viewBox="0 0 ' + W + ' ' + H.toFixed(0) + '" role="img" aria-label="The shadow path across India"><use href="#ast-land"/>');
    Object.keys(META.cities).forEach(function (n) {
      var c = META.cities[n], q = xy(c[0], c[1]);
      if (q[0] >= 0 && q[0] <= W && q[1] >= 0 && q[1] <= H) out.push('<circle class="bm-city" cx="' + q[0].toFixed(1) + '" cy="' + q[1].toFixed(1) + '" r="1.6"/>');
    });
    if (L.left && L.left.length === 1 && L.right && L.right.length === 1) out.push('<path class="ast-band" d="' + d([L.left[0].concat(L.right[0].slice().reverse())], true) + '"/>');
    ['left_1s', 'right_1s'].forEach(function (k) { if (L[k]) out.push('<path class="ast-sig" d="' + d(L[k]) + '"/>'); });
    ['left', 'right'].forEach(function (k) { if (L[k]) out.push('<path class="ast-lim" d="' + d(L[k]) + '"/>'); });
    if (L.centre) out.push('<path class="ast-cl" d="' + d(L.centre) + '"/>');
    var ticks = ev.ticks || [];
    ticks.forEach(function (t, i) {
      var nb = ticks[i + 1] || ticks[i - 1];
      if (!nb) return;
      var q = xy(t[0], t[1]), r = xy(nb[0], nb[1]), dx = r[0] - q[0], dy = r[1] - q[1], n = Math.hypot(dx, dy) || 1;
      var ux = -dy / n * 5, uy = dx / n * 5;
      out.push('<path class="bm-tick" d="M' + (q[0] - ux).toFixed(1) + ',' + (q[1] - uy).toFixed(1) + ' ' + (q[0] + ux).toFixed(1) + ',' + (q[1] + uy).toFixed(1) + '"/>');
      if (i % 2 === 0) out.push('<text class="bm-lbl" x="' + (q[0] + ux + 2).toFixed(1) + '" y="' + (q[1] + uy + 3).toFixed(1) + '">' + fHM(t0 + t[2] * 1000, tz) + '</text>');
    });
    var me = xy(LOC.lat, LOC.lon);
    out.push('<circle class="ast-pin" cx="' + me[0].toFixed(1) + '" cy="' + me[1].toFixed(1) + '" r="5"/>');
    return out.join('') + '</svg>';
  }
  function xml(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function pathLines(ev) {
    var L = ev.lines, n = ev.north_is === 'left' ? 'left' : 'right', s = n === 'left' ? 'right' : 'left';
    return [['Centre line', L.centre], ['North edge', L[n]], ['South edge', L[s]], ['North 1 sigma', L[n + '_1s']], ['South 1 sigma', L[s + '_1s']]]
      .filter(function (r) { return r[1] && r[1].length; });
  }
  function evTitle(ev) { return '(' + ev.asteroid.number + ') ' + ev.asteroid.name + ' hides Gaia DR3 ' + ev.star.gaia + ' — ' + ev.el.t0; }
  function kml(ev) {
    var t = ['<?xml version="1.0" encoding="UTF-8"?>', '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>', '<name>' + xml(evTitle(ev)) + '</name>',
             '<Style id="p"><LineStyle><color>ffa38af0</color><width>3</width></LineStyle></Style>'];
    pathLines(ev).forEach(function (l) {
      l[1].forEach(function (run) {
        t.push('<Placemark><name>' + xml(l[0]) + '</name><styleUrl>#p</styleUrl><LineString><tessellate>1</tessellate><coordinates>'
               + run.map(function (q) { return q[1] + ',' + q[0] + ',0'; }).join(' ') + '</coordinates></LineString></Placemark>');
      });
    });
    return t.join('\n') + '\n</Document></kml>\n';
  }
  function gpx(ev) {
    var t = ['<?xml version="1.0" encoding="UTF-8"?>', '<gpx version="1.1" creator="occult.alokm.com" xmlns="http://www.topografix.com/GPX/1/1">',
             '<metadata><name>' + xml(evTitle(ev)) + '</name></metadata>'];
    pathLines(ev).forEach(function (l) {
      l[1].forEach(function (run) {
        t.push('<trk><name>' + xml(l[0]) + '</name><trkseg>' + run.map(function (q) { return '<trkpt lat="' + q[0] + '" lon="' + q[1] + '"/>'; }).join('') + '</trkseg></trk>');
      });
    });
    return t.join('\n') + '\n</gpx>\n';
  }
  function save(name, text, type) {
    var b = new Blob([text], { type: type }), u = URL.createObjectURL(b), a = document.createElement('a');
    a.href = u; a.download = name; document.body.appendChild(a); a.click();
    setTimeout(function () { URL.revokeObjectURL(u); a.remove(); }, 1000);
  }
  // ---------- where you sit across the path, the chord you would time, and the whole path on Earth ----------
  function stripSvg(ev, s) {
    var R = ev.el.R, sig = ev.sigma_km || 0, d = s.d, W = 300, H = 40, c = W / 2;
    var span = Math.max(R + sig, Math.abs(d)) * 1.3 || 1, k = (W / 2 - 12) / span, o = [];
    o.push('<svg class="strip" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Where you are across the path">');
    o.push('<rect class="st-sig" x="' + (c - (R + sig) * k).toFixed(1) + '" y="8" width="' + (2 * (R + sig) * k).toFixed(1) + '" height="14"/>');
    o.push('<rect class="st-band" x="' + (c - R * k).toFixed(1) + '" y="8" width="' + (2 * R * k).toFixed(1) + '" height="14"/>');
    o.push('<path class="st-axis" d="M' + (c).toFixed(1) + ',4 ' + c.toFixed(1) + ',26"/>');
    var x = c + d * k;
    o.push('<path class="st-you" d="M' + x.toFixed(1) + ',6 ' + (x - 4).toFixed(1) + ',-1 ' + (x + 4).toFixed(1) + ',-1Z" transform="translate(0,2)"/>');
    o.push('<text class="st-lbl" x="' + c.toFixed(1) + '" y="36" text-anchor="middle">centre</text>');
    o.push('<text class="st-lbl" x="' + (c + R * k + 2).toFixed(1) + '" y="36">edge</text>');
    o.push('<text class="st-lbl" x="' + x.toFixed(1) + '" y="36" text-anchor="middle" style="fill:var(--c-limit)">you</text>');
    return o.join('') + '</svg>';
  }
  function chordSvg(ev, s) {
    var R = ev.el.R, sig = ev.sigma_km || 0, d = s.d, S = 210, c = S / 2;
    var k = (c - 18) / Math.max(R, Math.abs(d), 1), y = c - d * k, o = [];
    o.push('<svg class="chord" viewBox="0 0 ' + S + ' ' + S + '" role="img" aria-label="Your chord across the asteroid">');
    o.push('<circle class="ch-disc" cx="' + c + '" cy="' + c + '" r="' + (R * k).toFixed(1) + '"/>');
    [d - sig, d + sig].forEach(function (v) {
      o.push('<path class="ch-sig" d="M8,' + (c - v * k).toFixed(1) + ' ' + (S - 8) + ',' + (c - v * k).toFixed(1) + '"/>');
    });
    if (Math.abs(d) < R) {
      var half = Math.sqrt(R * R - d * d) * k;
      o.push('<path class="ch-chord" d="M' + (c - half).toFixed(1) + ',' + y.toFixed(1) + ' ' + (c + half).toFixed(1) + ',' + y.toFixed(1) + '"/>');
    } else {
      o.push('<path class="ch-miss" d="M8,' + y.toFixed(1) + ' ' + (S - 8) + ',' + y.toFixed(1) + '"/>');
    }
    return o.join('') + '</svg>';
  }
  function curveSvg(ev, s) {
    var inside = Math.abs(s.d) <= ev.el.R, dur = inside ? s.dur : ev.dur_max_s, sig = ev.sigma_s || 0;
    var W = 240, H = 130, x0 = 24, x1 = W - 8, span = Math.max(dur * 2.2, dur + 4 * sig, 4);
    var xs = function (t) { return x0 + (t / span + 0.5) * (x1 - x0); }, yTop = 22, yBot = H - 26, o = [];
    o.push('<svg class="curve" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="How the brightness drops">');
    o.push('<path class="cv-axis" d="M' + x0 + ',' + yTop + ' ' + x0 + ',' + yBot + ' ' + x1 + ',' + yBot + '"/>');
    o.push('<rect class="cv-sig" x="' + xs(-dur / 2 - sig).toFixed(1) + '" y="' + yTop + '" width="' + Math.max(1, (xs(-dur / 2 + sig) - xs(-dur / 2 - sig))).toFixed(1) + '" height="' + (yBot - yTop) + '"/>');
    o.push('<rect class="cv-sig" x="' + xs(dur / 2 - sig).toFixed(1) + '" y="' + yTop + '" width="' + Math.max(1, (xs(dur / 2 + sig) - xs(dur / 2 - sig))).toFixed(1) + '" height="' + (yBot - yTop) + '"/>');
    var a = xs(-dur / 2), b = xs(dur / 2);
    o.push('<path class="cv-line' + (inside ? '' : ' centre') + '" d="M' + x0.toFixed(1) + ',' + yTop + ' ' + a.toFixed(1) + ',' + yTop
           + ' ' + a.toFixed(1) + ',' + yBot + ' ' + b.toFixed(1) + ',' + yBot + ' ' + b.toFixed(1) + ',' + yTop + ' ' + x1.toFixed(1) + ',' + yTop + '"/>');
    o.push('<text class="st-lbl" x="2" y="' + (yTop + 3) + '">' + ev.combined_mag.toFixed(1) + '</text>');
    o.push('<text class="st-lbl" x="2" y="' + (yBot + 3) + '">' + ev.asteroid.mag.toFixed(1) + '</text>');
    o.push('<text class="st-lbl" x="' + ((a + b) / 2).toFixed(1) + '" y="' + (yBot + 14) + '" text-anchor="middle">' + r1(dur) + ' s</text>');
    return o.join('') + '</svg>';
  }
  function worldTrack(el, n) {
    var AE = 6378.137, F = 1 / 298.257223563, k = el.k, n1 = Math.hypot(-k[1], k[0]);
    var e1 = [-k[1] / n1, k[0] / n1, 0], e2 = [k[1] * e1[2] - k[2] * e1[1], k[2] * e1[0] - k[0] * e1[2], k[0] * e1[1] - k[1] * e1[0]], out = [];
    for (var i = 0; i <= n; i++) {
      var tau = -el.W + 2 * el.W * i / n, u = tau / el.W, th = WE * tau, ct = Math.cos(th), st = Math.sin(th);
      var x = poly(el.x, u), y = poly(el.y, u), R0 = el.R0;
      var toItrs = function (v) {
        var p = [R0[0] * v[0] + R0[1] * v[1] + R0[2] * v[2], R0[3] * v[0] + R0[4] * v[1] + R0[5] * v[2], R0[6] * v[0] + R0[7] * v[1] + R0[8] * v[2]];
        return [ct * p[0] + st * p[1], -st * p[0] + ct * p[1], p[2]];      // Rz(-theta) R0: GCRS -> ITRS at t0 + tau
      };
      var b = toItrs([x * e1[0] + y * e2[0], x * e1[1] + y * e2[1], x * e1[2] + y * e2[2]]), ki = toItrs(k), sc = 1 / (1 - F);
      var a2 = [b[0], b[1], b[2] * sc], k2 = [ki[0], ki[1], ki[2] * sc];
      var Q = k2[0] * k2[0] + k2[1] * k2[1] + k2[2] * k2[2];
      var B2 = a2[0] * k2[0] + a2[1] * k2[1] + a2[2] * k2[2], C2 = a2[0] * a2[0] + a2[1] * a2[1] + a2[2] * a2[2] - AE * AE;
      var disc = B2 * B2 - Q * C2;
      if (disc < 0) { out.push(null); continue; }
      var lam = (-B2 + Math.sqrt(disc)) / Q, g = [b[0] + lam * ki[0], b[1] + lam * ki[1], b[2] + lam * ki[2]];
      out.push([Math.atan2(g[2], (1 - F) * (1 - F) * Math.hypot(g[0], g[1])) / RAD, Math.atan2(g[1], g[0]) / RAD]);
    }
    return out;
  }
  function worldSvg(ev) {
    var o = ['<svg class="world" viewBox="0 0 360 180" role="img" aria-label="The whole path across the Earth">'];
    (WORLD || []).forEach(function (r) {
      o.push('<path class="wd-land" d="M' + r.map(function (q) { return (q[1] + 180).toFixed(1) + ',' + (90 - q[0]).toFixed(1); }).join(' ') + 'Z"/>');
    });
    var seg = [];
    worldTrack(ev.el, 400).forEach(function (p) {      // dense enough that the racing ends near the limb stay on the map
      if (!p) { if (seg.length > 1) o.push('<path class="wd-path" d="M' + seg.join(' ') + '"/>'); seg = []; return; }
      if (seg.length) {                                   // break the line where it wraps round the map
        var prev = +seg[seg.length - 1].split(',')[0] - 180;
        if (Math.abs(p[1] - prev) > 180) { if (seg.length > 1) o.push('<path class="wd-path" d="M' + seg.join(' ') + '"/>'); seg = []; }
      }
      seg.push((p[1] + 180).toFixed(1) + ',' + (90 - p[0]).toFixed(1));
    });
    if (seg.length > 1) o.push('<path class="wd-path" d="M' + seg.join(' ') + '"/>');
    var B2 = META.bbox;
    o.push('<rect class="wd-frame" x="' + (B2[0] + 180) + '" y="' + (90 - B2[3]) + '" width="' + (B2[2] - B2[0]) + '" height="' + (B2[3] - B2[1]) + '"/>');
    var me = [(LOC.lon + 180).toFixed(1), (90 - LOC.lat).toFixed(1)];
    o.push('<circle class="ast-pin" cx="' + me[0] + '" cy="' + me[1] + '" r="3" stroke-width="1.2"/>');
    return o.join('') + '</svg>';
  }
  var WORLD = null;
  function withWorld(done) {
    if (WORLD) return done();
    fetch(META.world).then(function (r) { return r.json(); }).then(function (w) { WORLD = w; done(); }).catch(function () { WORLD = []; done(); });
  }
  function fillWorld(det, ev) {      // the outline is one small file, fetched the first time a panel opens
    withWorld(function () { var slot = det.querySelector('.world-pane .world'); if (slot) slot.outerHTML = worldSvg(ev); });
  }
  function detailHtml(ev, tz, s) {
    var R = ev.el.R, inside = Math.abs(s.d) <= R, ground = toCentre(ev.el, LOC.lat, LOC.lon)[0];
    var chordCap = inside ? ('Your chord: ' + r0(2 * Math.sqrt(R * R - s.d * s.d)) + ' km of the ' + r0(2 * R) + ' km disc · ' + r1(s.dur) + ' s')
                          : ('Your line misses the ' + r0(2 * R) + ' km disc by ' + r0(Math.abs(s.d) - R) + ' km; the dashed lines are where 1σ would put it');
    return '<div class="ast-panes">' + finderSvg(ev, tz) + bigMap(ev, tz) + '</div>'
      + '<div class="ast-panes2">'
      + '<div>' + chordSvg(ev, s) + '<p class="pane-cap">' + chordCap + '</p>' + stripSvg(ev, s)
      + '<p class="pane-cap">' + r0(ground) + ' km from the centre line across a path ' + r0(2 * R) + ' km wide, ± ' + r0(ev.sigma_km || 0) + ' km</p></div>'
      + '<div>' + curveSvg(ev, s) + '<p class="pane-cap">' + (inside ? 'What you would record' : 'On the centre line — you are outside the path')
      + ': ' + r1(ev.drop) + ' mag for ' + r1(inside ? s.dur : ev.dur_max_s) + ' s, timing ± ' + r1(ev.sigma_s || 0) + ' s</p></div>'
      + '<div class="world-pane"><svg class="world" viewBox="0 0 360 180" aria-hidden="true"></svg><p class="pane-cap">The whole path on Earth; the box is this map</p></div>'
      + '</div>'
      + '<div class="ast-dl"><button class="btn" data-dl="kml">Download path (KML)</button>'
      + '<button class="btn" data-dl="gpx">GPX</button></div>'
      + '<p class="ast-note">Marks across the path are whole minutes; the dot is you. On the chart the dashed line is the asteroid\'s'
      + ' track through the field, ticked every three hours, ending on the star.</p>';
  }

  var data = null, LOC = null, FILTER = 'all';
  try { var sl = JSON.parse(localStorage.getItem('occult-loc')); if (sl && isFinite(sl.lat)) LOC = sl; } catch (e) {}
  if (!LOC) LOC = { lat: META.defaultPlace[1], lon: META.defaultPlace[2], label: META.defaultPlace[0] };
  try { var sf = localStorage.getItem('occult-ast-filter'); if (sf === 'near') FILTER = sf; } catch (e) {}
  function tzOf(loc) { var c = META.cities[loc.label]; return (c && c[2]) || (loc.label === META.defaultPlace[0] ? META.defaultPlace[3] : Intl.DateTimeFormat().resolvedOptions().timeZone); }
  var countLine = document.getElementById('count-line'), nightsEl = document.getElementById('ast-nights'), calEl = document.getElementById('ast-cal');
  var cards = {}; document.querySelectorAll('article.ast').forEach(function (a) { cards[a.dataset.id] = a; });
  document.querySelectorAll('#ast-filter input').forEach(function (r) { r.checked = r.value === FILTER;
    r.addEventListener('change', function () { FILTER = r.value; try { localStorage.setItem('occult-ast-filter', FILTER); } catch (e) {} render(); }); });
  function render() {
    if (!data) return;
    var tz = tzOf(LOC), groups = {}, order = [], mine = 0;
    data.events.forEach(function (ev) {
      var s = solve(ev.el, LOC.lat, LOC.lon), tc = toCentre(ev.el, LOC.lat, LOC.lon), y = you(ev, s, tc), a = cards[ev.id];
      if (!a) return;
      byId[ev.id] = ev;
      a.className = 'ast v-' + y[0];
      a.querySelector('.ast-time').textContent = fT(Date.parse(ev.el.t0) + s.tau * 1000, tz);
      a.querySelector('.ast-you').textContent = y[1];
      a.querySelector('.ast-look').textContent = y[2];
      var p = xy(LOC.lat, LOC.lon), pin = a.querySelector('.ast-pin'); pin.setAttribute('cx', p[0].toFixed(1)); pin.setAttribute('cy', p[1].toFixed(1));
      var det = a.querySelector('.ast-detail');     // an open panel follows the place; a closed one is rebuilt on opening
      if (det && !det.hidden) { det.innerHTML = detailHtml(ev, tz, s); det.dataset.built = '1'; fillWorld(det, ev); } else if (det) det.dataset.built = '';
      var near = y[0] === 'in' || y[0] === 'near'; if (near) mine++;
      a.hidden = FILTER === 'near' && !near;
      var k = dateKey(Date.parse(ev.t_geo) - 432e5, tz);
      if (!groups[k]) { groups[k] = { list: [], mine: 0 }; order.push(k); }
      groups[k].list.push(a); if (near) groups[k].mine++;
    });
    order.sort();
    var frag = document.createDocumentFragment();
    order.forEach(function (k) {
      var g = groups[k], shown = g.list.filter(function (a) { return !a.hidden; });
      var sec = document.createElement('section'); sec.className = 'night'; sec.id = 'night-' + k; sec.hidden = !shown.length;
      sec.innerHTML = '<header class="night-head"><h3>Night of ' + keyLabel(k) + '</h3><span class="hint">' + g.list.length + (g.list.length === 1 ? ' event' : ' events') + (g.mine ? ' · ' + g.mine + ' near you' : '') + '</span></header>';
      g.list.forEach(function (a) { sec.appendChild(a); });
      frag.appendChild(sec);
    });
    nightsEl.innerHTML = ''; nightsEl.appendChild(frag);
    var YM = META.t0.slice(0, 7).split('-'), y = +YM[0], mo = +YM[1], ndays = new Date(Date.UTC(y, mo, 0)).getUTCDate(), first = (new Date(Date.UTC(y, mo - 1, 1)).getUTCDay() + 6) % 7, html = '';
    ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].forEach(function (w) { html += '<div class="cal-wd">' + w + '</div>'; });
    for (var e = 0; e < first; e++) html += '<div class="cal-cell empty"></div>';
    for (var d = 1; d <= ndays; d++) {
      var ck = y + '-' + String(mo).padStart(2, '0') + '-' + String(d).padStart(2, '0'), g = groups[ck];
      var n = g ? (FILTER === 'near' ? g.mine : g.list.length) : 0, inner = '<span class="cal-d">' + d + '</span><span class="cal-n">' + (n || '') + '</span>';
      html += n ? '<a class="cal-cell has' + (g.mine ? ' mine' : '') + '" href="#night-' + ck + '">' + inner + '</a>' : '<div class="cal-cell">' + inner + '</div>';
    }
    calEl.innerHTML = html;
    document.getElementById('tz-label').textContent = tzLabel(tz);
    document.getElementById('chip-name').textContent = LOC.label;
    countLine.textContent = data.events.length + ' asteroid occultations cross India at night this month · ' + mine + ' pass over ' + LOC.label + ' (inside the path or within its 1σ margin)';
  }
  nightsEl.addEventListener('click', function (e) {
    var dl = e.target.closest('[data-dl]');
    if (dl) {
      var evd = byId[dl.closest('article.ast').dataset.id];
      if (evd) save(evd.id + '.' + dl.dataset.dl, dl.dataset.dl === 'kml' ? kml(evd) : gpx(evd),
                    dl.dataset.dl === 'kml' ? 'application/vnd.google-earth.kml+xml' : 'application/gpx+xml');
      return;
    }
    var b = e.target.closest('.ast-more');
    if (!b) return;
    var a = b.closest('article.ast'), ev = byId[a.dataset.id], det = a.querySelector('.ast-detail');
    if (!ev) return;
    if (!det) { det = document.createElement('div'); det.className = 'ast-detail'; det.hidden = true; a.appendChild(det); }
    var open = det.hidden;
    if (open && det.dataset.built !== '1') {
      det.innerHTML = detailHtml(ev, tzOf(LOC), solve(ev.el, LOC.lat, LOC.lon));
      det.dataset.built = '1';
      fillWorld(det, ev);
    }
    det.hidden = !open;
    b.setAttribute('aria-expanded', open ? 'true' : 'false');
    b.textContent = open ? 'Hide chart & map' : 'Chart & map';
  });
  var sheet = document.getElementById('loc-sheet'), latI = document.getElementById('loc-lat'), lonI = document.getElementById('loc-lon'), sel = document.getElementById('loc-city');
  function setLoc(lat, lon, label) { lat = +lat; lon = +lon; if (!isFinite(lat) || !isFinite(lon)) return;
    LOC = { lat: lat, lon: lon, label: label || (lat.toFixed(2) + ', ' + lon.toFixed(2)) };
    try { localStorage.setItem('occult-loc', JSON.stringify(LOC)); } catch (e) {}
    render(); }
  document.getElementById('loc-chip').addEventListener('click', function () { latI.value = LOC.lat.toFixed(4); lonI.value = LOC.lon.toFixed(4); sheet.showModal(); });
  sheet.addEventListener('click', function (e) { if (e.target === sheet) sheet.close(); });
  document.getElementById('loc-go').addEventListener('click', function () { setLoc(latI.value, lonI.value); sheet.close(); });
  sel.addEventListener('change', function () { var c = META.cities[sel.value]; if (c) { setLoc(c[0], c[1], sel.value); sheet.close(); } });
  var geo = document.getElementById('loc-geo'); if (!navigator.geolocation) geo.hidden = true;
  geo.addEventListener('click', function () { geo.disabled = true; geo.textContent = 'Locating…';
    navigator.geolocation.getCurrentPosition(function (p) { geo.disabled = false; geo.textContent = 'Use my location'; setLoc(p.coords.latitude, p.coords.longitude); sheet.close(); },
      function () { geo.disabled = false; geo.textContent = 'Location unavailable'; }); });
  fetch(META.src).then(function (r) { return r.json(); }).then(function (d) { data = d; render(); });
})();
"""

TEMPLATE = """
<nav class="subnav">
  <div class="subnav-row">
    <div class="subnav-links">__PREV__<a href="/#asteroids">All months</a>__NEXT__</div>
    <button class="chip" id="loc-chip" type="button" aria-haspopup="dialog"><span class="chip-pin">📍</span><span id="chip-name">__PLACE__</span></button>
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
<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs><symbol id="ast-land" viewBox="0 0 __MW__ __MH__">__LAND__</symbol></defs></svg>
<main class="wrap">
  <h1>__TITLE__</h1>
  <p class="sub">Stars hidden by asteroids, on paths across India</p>
  <p class="lead">An asteroid too small to see passes in front of a star, and its shadow — exactly as wide as the asteroid —
  races across the Earth. Inside that band the star blinks out for a few seconds; a few kilometres outside it, nothing
  happens. Each card maps the path and says how close it comes to you.</p>
  <div class="filters" id="ast-filter"><label class="chipbox"><input type="radio" name="f" value="all" checked> All over India</label>
    <label class="chipbox"><input type="radio" name="f" value="near"> Only paths over me</label></div>
  <p class="hint" id="count-line">__COUNT__</p>
  <div class="cal" id="ast-cal" aria-label="The month at a glance">__CAL__</div>
  <p class="hint">Times in <span id="tz-label">__TZL__</span>, for the moment the shadow passes closest to you. A night runs from
  noon to noon. On each map the shaded band is the path, the dashed lines its 1σ uncertainty and the dot is you.</p>
  <div id="ast-nights">__NIGHTS__</div>
  <h2>Reading the list</h2>
  <p class="method">A card turns <b style="color:var(--c-visible)">green</b> when you are inside the predicted path and
  <b style="color:var(--c-limit)">amber</b> when you are outside it but within its 1σ uncertainty — a miss is still likely
  then, but a chord from the edge is the most valuable observation of all. The <em>drop</em> is how much fainter the star
  and asteroid together get while the star is hidden; under half a magnitude needs a camera. <em>Up to</em> is the longest
  the star can vanish, on the centre line.</p>
  <table class="rules"><tbody>__RULES__</tbody></table>
  <p class="method">Orbits are JPL's (__ORBITS__), carried to the date with the DE431 ephemeris, the four largest asteroids
  and the Sun's relativistic pull; stars are Gaia DR3 to G 12.5, carried to the date with their proper motion and parallax.
  The asteroid is treated as a sphere of its catalogue diameter: a real, lumpy asteroid casts a shadow that can be
  narrower or wider, which is exactly what observations along the path measure. The 1σ lines combine the star's Gaia
  uncertainty with the orbit's: the largest of JPL's formal uncertainty, the gap between JPL's and the Minor Planet Center's
  orbits for that event (divided by √2), and 10 mas — about how far independent orbit solutions for these asteroids
  disagree. A <span class="badge">RUWE</span> badge marks a star Gaia finds hard to fit — often a close
  double, whose fade may come in steps.</p>
  <script type="application/json" id="ast-meta">__META__</script>
</main>
__FOOTER__
<script>
__JS__
</script>
</body>
</html>
"""


def month_page(ym, d, cities, nav):
    from asteroid_occultations import local, to_centre
    y, mo = (int(x) for x in ym.split("-"))
    label = f"{MONTHS[mo - 1]} {y}"
    slug = f"asteroids-{ym}"
    title = f"Asteroid occultations — {label}"
    seed = json.loads((ROOT / "seed.json").read_text())
    aud = seed["audiences"][d["audience"]]
    geo = json.loads((ROOT / "geo" / f"{d['audience']}.json").read_text())
    proj = Proj(geo["bbox"], aud["lat0"], MAP_W)
    land = land_svg(proj, geo)
    # the location sheet offers the audience's own cities: these paths only cross India
    cities = {c["name"]: [round(c["lat"], 3), round(c["lon"], 3), c.get("tz") or aud["tz"]]
              for c in json.loads((ROOT / aud["cities"]).read_text())}
    name, lat, lon, tzname = DEFAULT_PLACE
    tz = zoneinfo.ZoneInfo(tzname)
    groups, mine = {}, 0
    for ev in d["events"]:
        s = local(ev["el"], lat, lon)
        tc = to_centre(ev["el"], lat, lon)
        cls = you_html(ev, s, tc)[0]
        mine += cls in ("in", "near")
        html = card_html(ev, proj, s, tc, tz)
        x, yy = proj.xy(lat, lon)
        html = html.replace('cx="-20" cy="-20"', f'cx="{x:.1f}" cy="{yy:.1f}"')
        g = groups.setdefault(night_key(ev, tz), {"cards": [], "mine": 0})
        g["cards"].append(html)
        g["mine"] += cls in ("in", "near")
    nights = []
    for key in sorted(groups):
        g = groups[key]
        n = len(g["cards"])
        count = f'{n} {"event" if n == 1 else "events"}' + (f' · {g["mine"]} near you' if g["mine"] else "")
        nights.append(f'<section class="night" id="night-{key.isoformat()}"><header class="night-head"><h3>Night of {key.strftime("%a %-d %b")}</h3>'
                      f'<span class="hint">{count}</span></header>{"".join(g["cards"])}</section>')
    import calendar
    first_wd, ndays = calendar.monthrange(y, mo)
    cells = [f'<div class="cal-wd">{w}</div>' for w in WEEKDAYS] + ['<div class="cal-cell empty"></div>'] * first_wd
    for day in range(1, ndays + 1):
        key = datetime(y, mo, day).date()
        g = groups.get(key)
        inner = f'<span class="cal-d">{day}</span><span class="cal-n">{len(g["cards"]) if g else ""}</span>'
        cells.append(f'<a class="cal-cell has{" mine" if g["mine"] else ""}" href="#night-{key.isoformat()}">{inner}</a>' if g
                     else f'<div class="cal-cell">{inner}</div>')
    rules = d["engine"]["rules"]
    rules_html = "".join(f"<tr><td>{a}</td><td>{b}</td></tr>" for a, b in (
        ("Asteroids", f"the {d['engine']['asteroids']:,} with a diameter of {d['engine']['d_min_km']:g} km or more"),
        ("Stars", "Gaia DR3, magnitude G 12.5 and brighter"),
        ("Listed when", f"the path passes within {rules['city_km']:g} km of one of the site's Indian cities with the star at least "
                        f"{rules['star_alt_min']:g}° up and the Sun at least {-rules['sun_alt_max']:g}° below the horizon; the path is at "
                        f"least as wide as its 1σ uncertainty; and the star fades by {rules['drop_min']:g} mag or more "
                        f"({rules['drop_min_long']:g} for events over {rules['long_s']:g} s) for at least {rules['dur_min_s']:g} s"),
        ("This month", f"{d['engine']['shadows_on_earth']:,} shadows touch the Earth somewhere; {len(d['events'])} are listed")))
    data_json = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
    meta = {"src": f"/data/{slug}.json?v={_hash(data_json)}", "t0": f"{ym}-01T00:00:00Z", "defaultPlace": list(DEFAULT_PLACE),
            "cities": cities, "bbox": geo["bbox"], "lat0": aud["lat0"], "mapW": MAP_W, "world": world_url()}
    prev_link = f'<a href="/{nav["prev"]}">‹ {nav["prev_label"]}</a>' if nav.get("prev") else "<span></span>"
    next_link = f'<a href="/{nav["next"]}">{nav["next_label"]} ›</a>' if nav.get("next") else "<span></span>"
    desc = (f"Asteroid occultations crossing India in {label}: {len(d['events'])} stars hidden by asteroids, each with a map of "
            f"its path and, for your location, how close it passes, when, and how long the star vanishes.")
    page = head(f"{title} · {SITE_NAME}", desc, f"/{slug}", extra=f"<style>{AST_CSS}</style>", og="ast")
    body = TEMPLATE
    for k, v in {"__PREV__": prev_link, "__NEXT__": next_link, "__PLACE__": esc(name), "__TITLE__": esc(title),
                 "__CITY_OPTS__": "".join(f'<option value="{esc(n)}">{esc(n)}</option>' for n in cities),
                 "__MW__": f"{proj.W:.0f}", "__MH__": f"{proj.H:.0f}", "__LAND__": land, "__TZL__": "IST",
                 "__COUNT__": f"{len(d['events'])} asteroid occultations cross India at night this month · {mine} pass over {esc(name)} (inside the path or within its 1σ margin)",
                 "__CAL__": "".join(cells), "__NIGHTS__": "".join(nights) or '<p class="hint">No asteroid shadows cross India at night this month.</p>',
                 "__RULES__": rules_html, "__ORBITS__": esc(d["engine"]["orbits"]),
                 "__META__": json.dumps(meta, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"),
                 "__FOOTER__": FOOTER, "__JS__": SOLVER_JS}.items():
        body = body.replace(k, v)
    (OUT / f"{slug}.html").write_text(page + body)
    (OUT / "data").mkdir(exist_ok=True)
    (OUT / "data" / f"{slug}.json").write_text(data_json)
    print(f"wrote site/{slug}.html: {len(d['events'])} events, {mine} over {name}")
    nxt = d["events"][0] if d["events"] else None
    return {"slug": slug, "label": label, "year": y, "month": mo, "n": len(d["events"]), "mine": mine, "planet": "asteroids",
            "nights": len(groups), "first": nxt["asteroid"]["name"] if nxt else None}


def build_all(cities, only=None):
    files = sorted((ROOT / "data").glob("asteroids-*.json"))
    yms = [f.stem[len("asteroids-"):] for f in files]
    if only:
        yms = [ym for ym in yms if ym in only]
    built = []
    for i, ym in enumerate(yms):
        nav = {}
        if i > 0:
            nav["prev"], nav["prev_label"] = f"asteroids-{yms[i - 1]}", MONTHS[int(yms[i - 1][5:]) - 1][:3]
        if i < len(yms) - 1:
            nav["next"], nav["next_label"] = f"asteroids-{yms[i + 1]}", MONTHS[int(yms[i + 1][5:]) - 1][:3]
        built.append(month_page(ym, json.loads((ROOT / "data" / f"asteroids-{ym}.json").read_text()), cities, nav))
    return built


if __name__ == "__main__":
    import build_feeds
    seed = json.loads((ROOT / "seed.json").read_text())
    build_all(build_feeds.collect_cities(seed), only=sys.argv[1:] or None)
