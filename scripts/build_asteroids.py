#!/usr/bin/env python3
"""Asteroid occultations: one page per month listing every asteroid shadow that crosses India at night, with a small
map of its path and — for the reader's own place — how far the path passes, when, and for how long the star vanishes.
Tapping one opens site/asteroid.html, ONE page that draws any event from its id (`/asteroid?e=<event id>`): a slippy
map of the path, the finder chart, the chord you would time, the fade, the whole path on Earth, and the KML to drive by.

  data/asteroids-<YYYY-MM>.json   engine/asteroid_occultations.py (DE431 + JPL orbits + Gaia DR3)
  -> site/asteroids-<YYYY-MM>.html, site/asteroid.html, site/js/asteroid.js, site/data/asteroids-<YYYY-MM>.json

`LIB_JS` (site/js/asteroid.js, shared by both pages) holds the twins: `solve()` / `toCentre()` mirror `local()` /
`to_centre()` in the engine, and `you()` mirrors `you_html()` here, with the same rounding (floor(x + 0.5)) — change
them TOGETHER. The month page prerenders New Delhi; the browser recomputes for the chosen place.

The event page is the site's only third-party request: Leaflet from cdnjs (with integrity hashes) and OpenStreetMap
tiles. Everything else it draws itself, and the month pages stay self-contained.
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
LEAFLET = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4"
LEAFLET_JS_SRI = "sha512-BwHfrr4c9kmRkLw6iXFdzcdWV/PGkVgiIyIWLLlTSXzWQzxuSg4DiQUCpauz/EWjgk5TYQqX/kvn9pG1NpYfqg=="
LEAFLET_CSS_SRI = "sha512-Zcn6bjR/8RZbLEpLIeOwNtzREBAJnUKESxces60Mpoj+2okopSAcSUIUOseddDm0cxnGQzxIR7vJgsLZbdLE3w=="


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
    """A coarse world outline (rings of [lat, lon]) for the world inset: one small file, written once and fetched by the
    event page — too big to sit in every page's HTML."""
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
    # the thumbnail carries the band and its edges only: the 1-sigma lines live on the event page, where they can be read
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
    more = f'<a class="ast-more" href="/asteroid?e={esc(ev["id"])}">Map, finder chart &amp; download →</a>'
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
    .ast-more { display: inline-block; margin-top: 0.4rem; font-size: 0.78rem; color: var(--t-ast); }
    @media (max-width: 560px) { .ast { grid-template-columns: 92px 1fr; gap: 0.6rem; } .ast-map { width: 92px; } .cal-cell { min-height: 44px; } }
    .rules td, .rules th { padding: 0.25rem 0.6rem; font-size: 0.85rem; white-space: normal; }
"""

# the drawings, shared by both pages
CHART_CSS = """
    .chord, .curve, .world, .strip, .finder { width: 100%; height: auto; display: block; }
    .chord, .curve, .world, .finder { background: var(--sea); border-radius: 8px; }
    .pane-cap { font-size: 0.76rem; color: var(--muted); margin-top: 0.25rem; }
    .ch-disc { fill: color-mix(in srgb, var(--t-ast) 22%, transparent); stroke: var(--t-ast); stroke-width: 1.2; }
    .ch-chord { stroke: var(--c-limit); stroke-width: 2.4; stroke-linecap: round; }
    .ch-miss { stroke: var(--muted); stroke-width: 1.6; stroke-dasharray: 5 4; }
    .ch-sig { stroke: var(--t-ast); stroke-width: 1; stroke-dasharray: 4 3; opacity: 0.7; fill: none; }
    .st-band { fill: color-mix(in srgb, var(--t-ast) 30%, transparent); }
    .st-sig { fill: color-mix(in srgb, var(--t-ast) 12%, transparent); }
    .st-sig2 { fill: color-mix(in srgb, var(--t-ast) 6%, transparent); }
    .st-axis { stroke: var(--line); stroke-width: 1; }
    .st-you { fill: var(--c-limit); }
    .st-lbl { font: 500 9px -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif; fill: var(--muted); }
    .cv-line { fill: none; stroke: var(--c-limit); stroke-width: 2; stroke-linejoin: round; }
    .cv-line.centre { stroke: var(--muted); stroke-dasharray: 5 4; stroke-width: 1.6; }
    .cv-axis { stroke: var(--line); stroke-width: 1; }
    .cv-sig { fill: color-mix(in srgb, var(--c-limit) 20%, transparent); }
    .wd-land { fill: var(--land); stroke: var(--land-line); stroke-width: 0.3; }
    .wd-path { fill: none; stroke: var(--t-ast); stroke-width: 1.6; }
    .wd-dim { fill: none; stroke: var(--muted); stroke-width: 1; opacity: 0.55; }
    .wd-frame { fill: none; stroke: var(--c-limit); stroke-width: 0.8; }
    .fd-edge { fill: none; stroke: var(--line); stroke-width: 0.8; }
    .fd-star { fill: var(--text); }
    .fd-target { fill: none; stroke: var(--c-limit); stroke-width: 1.6; }
    .fd-track { fill: none; stroke: var(--t-ast); stroke-width: 1.2; stroke-dasharray: 4 3; }
    .fd-tick { fill: var(--t-ast); }
    .fd-lbl { font: 500 8px -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif; fill: var(--muted); }
    .fd-cap { font: 500 9px -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif; fill: var(--muted); }
"""

EVENT_CSS = """
    .ev-head { margin: 1.2rem 0 0.2rem; }
    .ev-head h1 { margin: 0.2rem 0; font-size: clamp(1.4rem, 3.6vw, 2rem); }
    .ev-verdict { font-size: 1.05rem; font-weight: 600; margin: 0.5rem 0 0; }
    .ev-verdict.v-in { color: var(--c-visible); } .ev-verdict.v-near { color: var(--c-limit); } .ev-verdict.v-below { color: var(--c-down); }
    #map { height: min(62vh, 520px); width: 100%; border-radius: 14px; border: 1px solid var(--border); margin: 0.8rem 0 0.3rem; background: var(--sea); z-index: 0; }
    .leaflet-container { font: inherit; font-size: 0.8rem; background: var(--sea); }
    .leaflet-popup-content-wrapper, .leaflet-popup-tip { background: var(--card); color: var(--text); }
    .map-note { font-size: 0.78rem; color: var(--muted); }
    .ev-panes { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 1rem; margin: 1.2rem 0 0; align-items: start; }
    .ev-facts { width: 100%; font-size: 0.9rem; }
    .ev-facts th { width: 42%; color: var(--muted); font-weight: 500; text-transform: none; letter-spacing: 0; font-size: 0.85rem; }
    .ev-facts td, .ev-facts th { padding: 0.3rem 0.6rem; white-space: normal; }
    .ast-dl { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.8rem; }
    .ast-dl .btn { font-size: 0.82rem; }
    .ev-miss { color: var(--muted); }
    .spot { display: flex; flex-wrap: wrap; align-items: center; gap: 0.4rem 0.6rem; margin: 0.6rem 0 0; }
    .spot .btn { font-size: 0.82rem; }
    .spot-coords { font-variant-numeric: tabular-nums; font-weight: 600; }
    .spot-url { flex: 1 1 15rem; min-width: 0; font: inherit; font-size: 0.78rem; padding: 0.3rem 0.5rem; border-radius: 8px;
                border: 1px solid var(--line); background: var(--card); color: var(--muted); }
    .pin-dot { width: 16px; height: 16px; border-radius: 50%; background: var(--c-limit); border: 3px solid var(--card);
               box-shadow: 0 0 0 1px var(--c-limit); cursor: grab; }
    .tick-label { font: 600 11px -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif; color: var(--text);
                  background: color-mix(in srgb, var(--card) 86%, transparent); border: 1px solid var(--border); border-radius: 6px;
                  padding: 0 4px; white-space: nowrap; width: auto !important; height: auto !important; }
    .tick-dot { background: var(--t-ast); border-radius: 50%; width: 6px; height: 6px; margin: -3px 0 0 -3px; }
    .stn-dot { width: 20px; height: 20px; border-radius: 50%; background: var(--c-visible); color: #fff; border: 2px solid var(--card);
               font: 600 11px/16px -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif; text-align: center; cursor: pointer; }
    .stn-panel { margin: 0.6rem 0 0; }
    .stn-list { display: grid; gap: 0.3rem; }
    .stn-list button { font: inherit; font-size: 0.85rem; text-align: left; color: inherit; background: var(--card);
                       border: 1px solid var(--line); border-radius: 10px; padding: 0.35rem 0.6rem; cursor: pointer; }
    .stn-list button:hover { border-color: var(--c-visible); }
    .stn-list b { font-variant-numeric: tabular-nums; }
    .now-label { background: var(--c-limit); border-color: var(--c-limit); color: #fff; font-variant-numeric: tabular-nums; }
"""

# ---------------------------------------------------------------------------------------------- site/js/asteroid.js

LIB_JS = r"""
/* occult.alokm.com — asteroid occultations: the solver both pages run, and the drawings they show.
   solve() / toCentre() / you() are twins of local() / to_centre() / you_html() in the engine and its builder;
   tests/test_asteroid_pages.py runs them against each other. Keep the rounding (floor(x + 0.5)) identical. */
(function () {
  var C = 299792.458, AE = 6378.137, FE = 1 / 298.257223563, RAD = Math.PI / 180, WE = 360.98564736629 * RAD / 86400;
  var COMPASS = ['N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSW','SW','WSW','W','WNW','NW','NNW'];
  function dot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
  function clamp(x) { return Math.max(-1, Math.min(1, x)); }
  function poly(c, u) { var v = 0; for (var i = c.length - 1; i >= 0; i--) v = v * u + c[i]; return v; }
  function dpoly(c, u) { var v = 0; for (var i = c.length - 1; i > 0; i--) v = v * u + i * c[i]; return v; }
  function compass(az) { return COMPASS[Math.floor((az + 11.25) / 22.5) % 16]; }
  function r0(x) { return Math.floor(x + 0.5); }
  function r1(x) { return (Math.floor(x * 10 + 0.5) / 10).toFixed(1); }
  function sky(a) { return a > 0 ? 'daylight' : a > -6 ? 'twilight' : a > -12 ? 'dusk' : 'dark sky'; }
  function fmt(ms, tz, opts) { try { return new Date(ms).toLocaleString('en-GB', Object.assign({ timeZone: tz }, opts)); } catch (e) { return new Date(ms).toLocaleString('en-GB', opts); } }
  function fT(ms, tz) { return fmt(ms, tz, { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }); }
  function fHM(ms, tz) { return fT(ms, tz).slice(0, 5); }
  function fDate(ms, tz) { return fmt(ms, tz, { weekday: 'short', day: 'numeric', month: 'long', year: 'numeric' }).replace(',', ''); }

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
  function dest(lat, lon, brg, km) {        // step km along a bearing, on a sphere
    var Re = 6371, d = km / Re, bb = brg * RAD, la = lat * RAD, lo = lon * RAD;
    var la2 = Math.asin(Math.sin(la) * Math.cos(d) + Math.cos(la) * Math.sin(d) * Math.cos(bb));
    var lo2 = lo + Math.atan2(Math.sin(bb) * Math.sin(d) * Math.cos(la), Math.cos(d) - Math.sin(la) * Math.sin(la2));
    return [la2 / RAD, ((lo2 / RAD + 540) % 360) - 180];
  }
  function toOffset(el, lat, lon, target) {
    // the nearest place the shadow's axis passes `target` km from (0 = the centre line), by Newton steps down the
    // gradient of d. Over a few hundred km d is near enough linear in ground distance that five steps land inside 50 m.
    var la = lat, lo = lon, h = 0.02, i, p;
    for (i = 0; i < 6; i++) {
      var err = target - solve(el, la, lo).d;
      var dn = (solve(el, la + h, lo).d - solve(el, la - h, lo).d) / (2 * h * 111.195);
      var de = (solve(el, la, lo + h).d - solve(el, la, lo - h).d) / (2 * h * 111.195 * Math.cos(la * RAD));
      var g2 = dn * dn + de * de;
      if (!isFinite(g2) || g2 < 1e-12) break;
      var kn = err * dn / g2, ke = err * de / g2, km = Math.hypot(kn, ke);
      if (km < 0.05) break;
      p = dest(la, lo, ((Math.atan2(ke, kn) / RAD) + 360) % 360, km);
      la = p[0]; lo = p[1];
    }
    return [la, lo];
  }
  function you(ev, s, tc) {   // twin of you_html()
    var R = ev.el.R, sig = ev.sigma_km || 0, d = Math.abs(s.d), ground = tc[0], brg = tc[1];
    var look = 'Star ' + r0(s.star_alt) + '° up in the ' + compass(s.star_az) + ' · ' + sky(s.sun_alt);
    if (s.star_alt < 0) return ['below', 'The star is below your horizon then', 'Star ' + r0(-s.star_alt) + '° below the horizon'];
    var edge = d > 0 ? ground * (d - R) / d : 0;
    if (d <= R) return ['in', 'You are inside the path, ' + r0(ground) + ' km from its centre line: the star vanishes for up to ' + r1(s.dur) + ' s', look];
    if (d <= R + sig) return ['near', 'The predicted edge passes ' + r0(edge) + ' km to the ' + compass(brg) + ' — within its 1σ uncertainty of ' + r0(sig) + ' km, worth watching', look];
    return ['out', 'The path passes ' + r0(edge) + ' km to the ' + compass(brg), look];
  }

  // ---------- the drawings ----------
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
  function stripSvg(ev, s) {
    var R = ev.el.R, sig = ev.sigma_km || 0, d = s.d, W = 300, H = 40, c = W / 2;
    var span = Math.max(R + 2 * sig, Math.abs(d)) * 1.2 || 1, k = (W / 2 - 12) / span, o = [];
    o.push('<svg class="strip" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Where you are across the path">');
    o.push('<rect class="st-sig2" x="' + (c - (R + 2 * sig) * k).toFixed(1) + '" y="8" width="' + (2 * (R + 2 * sig) * k).toFixed(1) + '" height="14"/>');
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
  function groundAt(el, tau, off) {
    // where the shadow's axis — moved `off` km across its relative motion — meets the Earth at t0 + tau: [lat, lon],
    // or null when it misses. The twin of the engine's ground(): the light time to the ground point, and the normal
    // taken across the motion RELATIVE to the turning Earth, both settle in three passes. off 0 is the centre line,
    // which tests/test_asteroid_pages.py checks against the engine's own.
    var k = el.k, n1 = Math.hypot(-k[1], k[0]);
    var e1 = [-k[1] / n1, k[0] / n1, 0], e2 = [k[1] * e1[2] - k[2] * e1[1], k[2] * e1[0] - k[0] * e1[2], k[0] * e1[1] - k[1] * e1[0]];
    var u = Math.max(-1, Math.min(1, tau / el.W)), th = WE * tau, ct = Math.cos(th), st = Math.sin(th), R0 = el.R0;
    var x = poly(el.x, u), y = poly(el.y, u), vx = dpoly(el.x, u) / el.W, vy = dpoly(el.y, u) / el.W;
    function toItrs(v) {
      var p = [R0[0] * v[0] + R0[1] * v[1] + R0[2] * v[2], R0[3] * v[0] + R0[4] * v[1] + R0[5] * v[2], R0[6] * v[0] + R0[7] * v[1] + R0[8] * v[2]];
      return [ct * p[0] + st * p[1], -st * p[0] + ct * p[1], p[2]];        // Rz(-theta) R0: GCRS -> ITRS at t0 + tau
    }
    function toGcrs(v) {
      var q = [ct * v[0] - st * v[1], st * v[0] + ct * v[1], v[2]];
      return [R0[0] * q[0] + R0[3] * q[1] + R0[6] * q[2], R0[1] * q[0] + R0[4] * q[1] + R0[7] * q[2], R0[2] * q[0] + R0[5] * q[1] + R0[8] * q[2]];
    }
    var ki = toItrs(k), sc = 1 / (1 - FE), k2 = [ki[0], ki[1], ki[2] * sc], o = off || 0;
    var Q = k2[0] * k2[0] + k2[1] * k2[1] + k2[2] * k2[2], wx = vx, wy = vy, zeta = AE, g = null;
    for (var it = 0; it < 3; it++) {
      var wn = Math.hypot(wx, wy), nx = -wy / wn, ny = wx / wn;            // left of the relative motion
      var px = x + el.vp[0] * zeta / C + o * nx, py = y + el.vp[1] * zeta / C + o * ny;
      var b = toItrs([px * e1[0] + py * e2[0], px * e1[1] + py * e2[1], px * e1[2] + py * e2[2]]);
      var a2 = [b[0], b[1], b[2] * sc];
      var B2 = a2[0] * k2[0] + a2[1] * k2[1] + a2[2] * k2[2], C2 = a2[0] * a2[0] + a2[1] * a2[1] + a2[2] * a2[2] - AE * AE;
      var disc = B2 * B2 - Q * C2;
      if (disc < 0) return null;
      zeta = (-B2 + Math.sqrt(disc)) / Q;
      g = [b[0] + zeta * ki[0], b[1] + zeta * ki[1], b[2] + zeta * ki[2]];
      var vg = toGcrs([-WE * g[1], WE * g[0], 0]);                         // the ground point's own motion
      wx = vx - dot(vg, e1); wy = vy - dot(vg, e2);
    }
    return [Math.atan2(g[2], (1 - FE) * (1 - FE) * Math.hypot(g[0], g[1])) / RAD, Math.atan2(g[1], g[0]) / RAD];
  }
  function skyRuns(el, n) {
    // The shadow crosses half the world, but only part of that stretch is worth standing in: solve() at each ground
    // point gives the star's and the Sun's altitude at the instant the shadow arrives there, on the site's own rule
    // (star at least 10 degrees up, Sun at least 6 degrees down). Runs are cut where the class changes, sharing the
    // point between them so the drawn line has no gap, and `dark` is the stretch that is worth standing in.
    var runs = [], cur = null, dark = null, i;
    for (i = 0; i <= n; i++) {
      var tau = -el.W + 2 * el.W * i / n, g = groundAt(el, tau, 0);
      if (!g) { cur = null; continue; }
      var q = solve(el, g[0], g[1]), cls = q.star_alt < 10 ? 'low' : q.sun_alt > -6 ? 'bright' : 'dark';
      var last = cur && cur.pts[cur.pts.length - 1], wrap = last && Math.abs(g[1] - last[1]) > 90;
      if (!cur || wrap || cur.cls !== cls) {
        cur = { cls: cls, pts: last && !wrap ? [last] : [] };
        runs.push(cur);
      }
      cur.pts.push(g);
      if (cls === 'dark') dark = dark ? [dark[0], tau] : [tau, tau];
    }
    return { runs: runs.filter(function (r) { return r.pts.length > 1; }), dark: dark };
  }
  function worldTrack(el, n) {
    var out = [];
    for (var i = 0; i <= n; i++) out.push(groundAt(el, -el.W + 2 * el.W * i / n));
    return out;
  }
  function bandRuns(el, offs, n) {
    // the lines `offs` km either side of the axis, sampled together and cut into runs where every one of them is on
    // the Earth: what the map fills between, to shade the band by how long the star stays hidden.
    var runs = [], cur = null, i, j;
    for (i = 0; i <= n; i++) {
      var pts = [], ok = true;
      for (j = 0; j < offs.length; j++) {
        var p = groundAt(el, -el.W + 2 * el.W * i / n, offs[j]);
        if (!p || (cur && Math.abs(p[1] - cur[j][cur[j].length - 1][1]) > 90)) { ok = false; break; }
        pts.push(p);
      }
      if (!ok) { cur = null; continue; }
      if (!cur) { cur = offs.map(function () { return []; }); runs.push(cur); }
      for (j = 0; j < offs.length; j++) cur[j].push(pts[j]);
    }
    return runs.filter(function (r) { return r[0].length > 1; });
  }
  function worldSvg(ev, world, bbox, loc) {
    var o = ['<svg class="world" viewBox="0 0 360 180" role="img" aria-label="The whole path across the Earth">'];
    (world || []).forEach(function (r) {
      o.push('<path class="wd-land" d="M' + r.map(function (q) { return (q[1] + 180).toFixed(1) + ',' + (90 - q[0]).toFixed(1); }).join(' ') + 'Z"/>');
    });
    skyRuns(ev.el, 300).runs.forEach(function (r) {    // dense enough that the racing ends near the limb stay on the map
      o.push('<path class="' + (r.cls === 'dark' ? 'wd-path' : 'wd-dim') + '" d="M'
             + r.pts.map(function (q) { return (q[1] + 180).toFixed(1) + ',' + (90 - q[0]).toFixed(1); }).join(' ') + '"/>');
    });
    if (bbox) o.push('<rect class="wd-frame" x="' + (bbox[0] + 180) + '" y="' + (90 - bbox[3]) + '" width="' + (bbox[2] - bbox[0]) + '" height="' + (bbox[3] - bbox[1]) + '"/>');
    if (loc) o.push('<circle class="ast-pin" cx="' + (loc.lon + 180).toFixed(1) + '" cy="' + (90 - loc.lat).toFixed(1) + '" r="3" stroke-width="1.2"/>');
    return o.join('') + '</svg>';
  }

  // ---------- the path, to take with you ----------
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

  window.OccultAsteroids = { solve: solve, toCentre: toCentre, toOffset: toOffset, dest: dest, you: you, kml: kml, gpx: gpx, save: save,
                             groundAt: groundAt, worldTrack: worldTrack, bandRuns: bandRuns, skyRuns: skyRuns, worldSvg: worldSvg, finderSvg: finderSvg, stripSvg: stripSvg,
                             chordSvg: chordSvg, curveSvg: curveSvg, pathLines: pathLines,
                             fmt: { t: fT, hm: fHM, date: fDate, compass: compass, r0: r0, r1: r1, sky: sky } };
})();
"""

# ---------------------------------------------------------------------------------------------- the month page

MONTH_JS = r"""
(function () {
  var A = window.OccultAsteroids, META = JSON.parse(document.getElementById('ast-meta').textContent);
  var RAD = Math.PI / 180, F = A.fmt;
  function tzLabel(tz) { try { return new Intl.DateTimeFormat('en-GB', { timeZone: tz, timeZoneName: 'short' }).formatToParts(new Date(Date.parse(META.t0) + 864e6)).filter(function (p) { return p.type === 'timeZoneName'; })[0].value; } catch (e) { return tz; } }
  function dateKey(ms, tz) { try { return new Intl.DateTimeFormat('en-CA', { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(ms)); } catch (e) { return new Date(ms).toISOString().slice(0, 10); } }
  function keyLabel(k) { var p = k.split('-'); return new Date(Date.UTC(+p[0], +p[1] - 1, +p[2], 12)).toLocaleDateString('en-GB', { timeZone: 'UTC', weekday: 'short', day: 'numeric', month: 'short' }).replace(',', ''); }
  var B = META.bbox, K = Math.cos(META.lat0 * RAD), SC = META.mapW / ((B[2] - B[0]) * K);
  function xy(lat, lon) { return [(lon - B[0]) * K * SC, (B[3] - lat) * SC]; }

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
      var s = A.solve(ev.el, LOC.lat, LOC.lon), tc = A.toCentre(ev.el, LOC.lat, LOC.lon), y = A.you(ev, s, tc), a = cards[ev.id];
      if (!a) return;
      a.className = 'ast v-' + y[0];
      a.querySelector('.ast-time').textContent = F.t(Date.parse(ev.el.t0) + s.tau * 1000, tz);
      a.querySelector('.ast-you').textContent = y[1];
      a.querySelector('.ast-look').textContent = y[2];
      var p = xy(LOC.lat, LOC.lon), pin = a.querySelector('.ast-pin'); pin.setAttribute('cx', p[0].toFixed(1)); pin.setAttribute('cy', p[1].toFixed(1));
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
  happens. Each card maps the path and says how close it comes to you; open one for the map, the finder chart and the path
  to drive to.</p>
  <div class="filters" id="ast-filter"><label class="chipbox"><input type="radio" name="f" value="all" checked> All over India</label>
    <label class="chipbox"><input type="radio" name="f" value="near"> Only paths over me</label></div>
  <p class="hint" id="count-line">__COUNT__</p>
  <div class="cal" id="ast-cal" aria-label="The month at a glance">__CAL__</div>
  <p class="hint">Times in <span id="tz-label">__TZL__</span>, for the moment the shadow passes closest to you. A night runs from
  noon to noon. On each map the shaded band is the path and the dot is you.</p>
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
<script src="/js/asteroid.js?v=__LIBV__"></script>
<script>
__JS__
</script>
</body>
</html>
"""

# ---------------------------------------------------------------------------------------------- the event page

EVENT_JS = r"""
(function () {
  var A = window.OccultAsteroids, META = JSON.parse(document.getElementById('ast-meta').textContent), F = A.fmt;
  var RAD = Math.PI / 180, params = new URLSearchParams(location.search);
  var id = params.get('e') || '', ym = id.slice(0, 7);
  var ev = null, LOC = null, map = null, me = null, ticks = null, arrow = null, world = null, stns = null, SKY = null, play = null;
  var BAND_F = [0, 0.35, 0.62, 0.82, 0.94, 1];       // the ribbons the band is shaded in, as fractions of its half width
  var STATION_F = [-0.8, -0.4, 0, 0.4, 0.8];         // where a line of observers would stand across it
  var stnOn = false, stnPts = [];
  var el = function (x) { return document.getElementById(x); };
  // a shared link carries a spot: it sets this page, but never overwrites the reader's own saved place
  var qlat = parseFloat(params.get('lat')), qlon = parseFloat(params.get('lon'));
  if (isFinite(qlat) && isFinite(qlon)) LOC = { lat: qlat, lon: qlon, label: 'Pinned spot' };
  if (!LOC) { try { var sl = JSON.parse(localStorage.getItem('occult-loc')); if (sl && isFinite(sl.lat)) LOC = sl; } catch (e) {} }
  if (!LOC) LOC = { lat: META.defaultPlace[1], lon: META.defaultPlace[2], label: META.defaultPlace[0] };
  function tzOf(loc) { var c = META.cities[loc.label]; return (c && c[2]) || (loc.label === META.defaultPlace[0] ? META.defaultPlace[3] : Intl.DateTimeFormat().resolvedOptions().timeZone); }
  function css(v) { return getComputedStyle(document.documentElement).getPropertyValue(v).trim() || '#a8324e'; }

  if (!META.months[ym]) return fail();
  fetch(META.months[ym]).then(function (r) { return r.json(); }).then(function (d) {
    ev = (d.events || []).filter(function (x) { return x.id === id; })[0];
    if (!ev) return fail();
    el('back').href = '/asteroids-' + ym;
    el('back').textContent = '‹ ' + META.monthLabels[ym];
    document.title = '(' + ev.asteroid.number + ') ' + ev.asteroid.name + ' hides a star · Occult';
    describe();
    drawMap();
    render();
  }).catch(fail);

  function describe() {
    // one page serves every event, so the crawler needs telling which one this is — and told to ignore the pin in the
    // URL, or every spot anyone ever shared would be a page of its own
    var url = location.origin + location.pathname.replace(/\.html$/, '') + '?e=' + encodeURIComponent(id);   // as the sitemap lists it
    var d = '(' + ev.asteroid.number + ') ' + ev.asteroid.name + ' hides a magnitude ' + F.r1(ev.star.v) + ' star on '
          + ev.el.t0.slice(0, 10) + ': the path across India on a map, how close it passes you, the finder chart, the chord you '
          + 'would time, and the path as KML.';
    [['link[rel="canonical"]', 'href', url], ['meta[name="description"]', 'content', d],
     ['meta[property="og:url"]', 'content', url], ['meta[property="og:title"]', 'content', document.title],
     ['meta[property="og:description"]', 'content', d]].forEach(function (r) {
      var n = document.querySelector(r[0]);
      if (n) n.setAttribute(r[1], r[2]);
    });
  }

  function fail() {
    el('ev-main').innerHTML = '<h1>Event not found</h1><p class="sub">That occultation is not on the site.</p>'
      + '<p><a href="/#asteroids">All asteroid months →</a></p>';
  }

  function drawMap() {
    var L = window.L;
    if (!L) { el('map').innerHTML = '<p class="map-note" style="padding:1rem">The map needs JavaScript from cdnjs; the drawings below work without it.</p>'; return; }
    map = L.map('map', { scrollWheelZoom: false });
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 17, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' }).addTo(map);
    var c = css('--t-ast'), lines = ev.lines, group = [];
    // nothing on the map is clickable but the pin and the stations: a tap anywhere else is a tap on the map, which moves the pin
    function poly(runs, opts) { opts.interactive = false; (runs || []).forEach(function (r) { group.push(L.polyline(r, opts).addTo(map)); }); }
    // the whole track, so zooming out shows where the shadow comes from and where it goes — bright only where the
    // star is up in a dark sky, faint where the Sun is up or the star too low to time
    SKY = A.skyRuns(ev.el, 300);
    SKY.runs.forEach(function (r) {
      L.polyline(r.pts, { color: r.cls === 'dark' ? c : css('--muted'), weight: r.cls === 'dark' ? 1.6 : 1,
                          opacity: r.cls === 'dark' ? 0.55 : r.cls === 'bright' ? 0.3 : 0.18,
                          dashArray: '2 6', interactive: false }).addTo(map);
    });
    if (!shadeBand(c) && lines.left && lines.left.length === 1 && lines.right && lines.right.length === 1) {
      group.push(L.polygon([lines.left[0].concat(lines.right[0].slice().reverse())], { color: c, weight: 0, fillOpacity: 0.22, interactive: false }).addTo(map));
    }
    var sig = ev.sigma_km || 0;
    if (sig) [ev.el.R + 2 * sig, -(ev.el.R + 2 * sig)].forEach(function (o) {   // 2σ: the page draws it from the elements
      A.bandRuns(ev.el, [o], 400).forEach(function (r) {
        L.polyline(r[0], { color: c, weight: 1, opacity: 0.4, dashArray: '2 7', interactive: false }).addTo(map);
      });
    });
    poly(lines.left_1s, { color: c, weight: 1.5, opacity: 0.8, dashArray: '6 5' });
    poly(lines.right_1s, { color: c, weight: 1.5, opacity: 0.8, dashArray: '6 5' });
    poly(lines.left, { color: c, weight: 3 });
    poly(lines.right, { color: c, weight: 3 });
    poly(lines.centre, { color: c, weight: 1.2, opacity: 0.9, dashArray: '3 4' });
    ticks = L.layerGroup().addTo(map);
    arrow = L.layerGroup().addTo(map);
    stns = L.layerGroup().addTo(map);
    me = L.marker([LOC.lat, LOC.lon], { icon: L.divIcon({ className: 'pin-dot', iconSize: [16, 16] }), draggable: true, autoPan: true,
                                        title: 'Drag to move your spot' }).addTo(map);
    me.bindPopup('');
    me.on('dragend', function () { var p = me.getLatLng(); setLoc(p.lat, p.lng, 'Pinned spot'); });
    map.on('click', function (e) { setLoc(e.latlng.lat, e.latlng.lng, 'Pinned spot'); me.openPopup(); });
    map.on('moveend zoomend', timeLabels);
    var bounds = L.featureGroup(group).getBounds();
    map.fitBounds(bounds.isValid() ? bounds : L.latLngBounds([[META.bbox[1], META.bbox[0]], [META.bbox[3], META.bbox[2]]]), { padding: [16, 16] });
  }

  function shadeBand(colour) {
    // The star is hidden longest down the middle of the path and not at all past its edges: the chord through a sphere
    // is 2*sqrt(R^2 - d^2) long. So the band is filled as a set of ribbons either side of the centre line, each as dark
    // as its own chord is long — the middle of the path is where you want to be, and this is how much it is worth.
    var L = window.L, R = ev.el.R, fr = [], i, drew = 0;
    for (i = BAND_F.length - 1; i > 0; i--) fr.push(-BAND_F[i]);
    for (i = 0; i < BAND_F.length; i++) fr.push(BAND_F[i]);
    A.bandRuns(ev.el, fr.map(function (f) { return f * R; }), 240).forEach(function (run) {
      for (var j = 0; j + 1 < fr.length; j++) {
        var mid = Math.abs(fr[j] + fr[j + 1]) / 2, chord = Math.sqrt(Math.max(0, 1 - mid * mid));
        L.polygon([run[j].concat(run[j + 1].slice().reverse())],
                  { color: colour, weight: 0, fillOpacity: 0.05 + 0.28 * chord, interactive: false }).addTo(map);
        drew++;
      }
    });
    return drew;
  }

  function timeLabels() {
    // the time the shadow reaches each place along the centre line, solved here rather than stored: as many labels as
    // the zoom has room for, on round steps of ten seconds to ten minutes
    if (!map || !ticks) return;
    ticks.clearLayers();
    var L = window.L, t0 = Date.parse(ev.el.t0), t0s = Math.round(t0 / 1000), W = ev.el.W, tz = tzOf(LOC), b = map.getBounds();
    var g0 = A.groundAt(ev.el, 0), g1 = A.groundAt(ev.el, 60);
    if (!g0 || !g1) return;
    var pxMin = map.latLngToContainerPoint(g0).distanceTo(map.latLngToContainerPoint(g1)) || 1, step = 60, best = 1e9;
    [10, 20, 30, 60, 120, 300, 600].forEach(function (s) { var d = Math.abs(pxMin * s / 60 - 130); if (d < best) { best = d; step = s; } });
    var first = Math.ceil((t0s - W) / step) * step, last = 0;
    for (var u = first; u <= t0s + W; u += step) {
      var g = A.groundAt(ev.el, u - t0s);
      if (!g || !b.contains([g[0], g[1]])) continue;
      var px = map.latLngToContainerPoint(g);
      if (last && px.distanceTo(last) < 80) continue;
      last = px;
      ticks.addLayer(L.marker(g, { icon: L.divIcon({ className: 'tick-dot', iconSize: [6, 6] }), interactive: false }));
      ticks.addLayer(L.marker(g, { interactive: false, icon: L.divIcon({ className: 'tick-label', iconSize: null,
        html: step < 60 ? F.t(u * 1000, tz) : F.hm(u * 1000, tz) }) }));
    }
  }

  function centrePoint() { return A.toOffset(ev.el, LOC.lat, LOC.lon, 0); }
  function kmApart(a, b) {
    var kx = 111.32 * Math.cos((a[0] + b[0]) / 2 * RAD);
    return Math.hypot((b[0] - a[0]) * 111.32, (((b[1] - a[1] + 180) % 360) - 180) * kx);
  }
  function drawStations() {
    // A line of observers across the path is how a shape gets measured: each one times a different chord through the
    // asteroid, and the chords together outline it. These are spaced across the width at the nearest point of the path.
    if (stns) stns.clearLayers();
    stnPts = [];
    el('stn-panel').hidden = !stnOn;
    if (!stnOn || !ev) return;
    var L = window.L, R = ev.el.R, c = centrePoint(), rows = [];
    STATION_F.forEach(function (f, i) {
      var p = A.toOffset(ev.el, c[0], c[1], f * R), s = A.solve(ev.el, p[0], p[1]), tc = A.toCentre(ev.el, p[0], p[1]);
      var side = (f > 0) === (ev.north_is === 'left') ? 'north' : 'south';
      var where = Math.abs(f) < 1e-9 ? 'on the centre line' : F.r0(tc[0]) + ' km ' + side + ' of it';
      stnPts.push(p);
      rows.push('<button type="button" data-stn="' + i + '"><b>' + (i + 1) + '</b> ' + p[0].toFixed(4) + ', ' + p[1].toFixed(4)
                + ' · ' + where + ' · <b>' + F.r1(s.dur) + ' s</b></button>');
      if (stns) stns.addLayer(L.marker(p, { icon: L.divIcon({ className: 'stn-dot', iconSize: [20, 20], html: String(i + 1) }),
                                            title: 'Station ' + (i + 1) + ' — tap to make it your spot' })
        .bindTooltip(F.r1(s.dur) + ' s', { direction: 'top', offset: [0, -8] })
        .on('click', function () { setLoc(p[0], p[1], 'Station ' + (i + 1)); }));
    });
    el('stn-list').innerHTML = rows.join('');
    el('stn-note').textContent = 'Five spots across the path near you, about ' + F.r0(kmApart(stnPts[0], stnPts[1]))
      + ' km apart. Each records a different chord, and together they measure the asteroid\'s shape — the point of timing one at all. '
      + 'Tap a station to make it your spot, then send whoever takes it the link.';
  }
  function placeMe(s, tc, y) {
    if (!map) return;
    var L = window.L;
    me.setLatLng([LOC.lat, LOC.lon]);
    var t = Date.parse(ev.el.t0) + s.tau * 1000, tz = tzOf(LOC), inside = Math.abs(s.d) <= ev.el.R;
    me.setPopupContent('<b>' + F.t(t, tz) + '</b>' + (inside ? ' · ' + F.r1(s.dur) + ' s' : ' · no fade here') + '<br>'
      + y[1] + '<br><span class="hint">' + y[2] + '</span>');
    arrow.clearLayers();
    if (tc[0] > 1) {
      var target = centrePoint();
      L.polyline([[LOC.lat, LOC.lon], target], { color: css('--c-limit'), weight: 2, dashArray: '5 5', interactive: false })
        .bindTooltip(F.r0(tc[0]) + ' km ' + F.compass(tc[1]) + ' to the centre line', { permanent: true, direction: 'center', className: 'tick-label' })
        .addTo(arrow);
    }
    timeLabels();
    drawStations();
  }

  function stopPlay() {
    if (!play) return;
    cancelAnimationFrame(play.raf);
    play.layer.remove();
    play = null;
    el('spot-play').textContent = '▶ Play the shadow';
  }
  function startPlay() {
    // the bar is the line of places whose mid-event is happening right then — the shadow's own cross-section, edge to
    // edge, sweeping the path at about 70 times life size
    if (!map || !ev) return;
    var L = window.L, W = ev.el.W, t0 = Date.parse(ev.el.t0), tz = tzOf(LOC), R = ev.el.R, span = 9000;
    play = { layer: L.layerGroup().addTo(map), raf: 0, f: 0, last: 0 };
    el('spot-play').textContent = '■ Stop';
    function frame(now) {
      if (!play) return;                                     // a frame already queued when Stop was pressed
      play.f += Math.min(100, now - (play.last || now)) / span;    // by elapsed time, clamped: a hidden tab stops rAF,
      play.last = now;                                             // and on the way back it should pick up, not jump to the end
      if (play.f >= 1) return stopPlay();
      var tau = -W + 2 * W * play.f, bar = [A.groundAt(ev.el, tau, R), A.groundAt(ev.el, tau, 0), A.groundAt(ev.el, tau, -R)].filter(Boolean);
      play.layer.clearLayers();
      if (bar.length > 1) {
        play.layer.addLayer(L.polyline(bar, { color: css('--c-limit'), weight: 5, opacity: 0.85, interactive: false }));
        play.layer.addLayer(L.marker(bar[bar.length >> 1], { interactive: false, zIndexOffset: 500,
          icon: L.divIcon({ className: 'tick-label now-label', iconSize: null, html: F.t(t0 + tau * 1000, tz) }) }));
      }
      play.raf = requestAnimationFrame(frame);
    }
    play.raf = requestAnimationFrame(frame);
  }

  function render() {
    if (!ev) return;
    var tz = tzOf(LOC), s = A.solve(ev.el, LOC.lat, LOC.lon), tc = A.toCentre(ev.el, LOC.lat, LOC.lon), y = A.you(ev, s, tc);
    var t = Date.parse(ev.el.t0) + s.tau * 1000, a = ev.asteroid, st = ev.star, R = ev.el.R, inside = Math.abs(s.d) <= R;
    el('chip-name').textContent = LOC.label;
    el('ev-title').textContent = '(' + a.number + ') ' + a.name + ' hides a magnitude ' + F.r1(st.v) + ' star';
    el('ev-when').textContent = F.date(t, tz) + ' · ' + F.t(t, tz) + ' at ' + LOC.label + (ev.sigma_s ? ' ± ' + F.r1(ev.sigma_s) + ' s' : '');
    var verdict = el('ev-verdict');
    verdict.className = 'ev-verdict v-' + y[0];
    verdict.textContent = y[1];
    el('ev-look').textContent = y[2];
    var rows = [
      ['Asteroid', '(' + a.number + ') ' + a.name + ' · ' + F.r0(a.diameter_km) + ' km across · magnitude ' + F.r1(a.mag) + ' · ' + F.r1(a.dist_au) + ' au away'],
      ['Star', 'Gaia DR3 ' + st.gaia + ' · magnitude ' + F.r1(st.v) + ' (G ' + F.r1(st.g) + ')' + (st.ruwe && st.ruwe > 1.4 ? ' · RUWE ' + st.ruwe + ', may be double' : '')],
      ['The fade', F.r1(ev.drop) + ' magnitudes, to ' + F.r1(ev.combined_mag) + ' · up to ' + F.r1(ev.dur_max_s) + ' s on the centre line'],
      ['From here', inside ? F.r1(s.dur) + ' s, ' + F.r0(tc[0]) + ' km from the centre line' : 'outside the path, ' + F.r0(tc[0]) + ' km from the centre line'],
      ['The path', F.r0(2 * R) + ' km wide, ± ' + F.r0(ev.sigma_km || 0) + ' km (1σ) · shadow at ' + F.r1(ev.speed_kms) + ' km/s'],
      ['The sky here', 'star ' + F.r0(s.star_alt) + '° up in the ' + F.compass(s.star_az) + ' · ' + F.sky(s.sun_alt)
        + ' · Moon ' + F.r0(ev.moon_illum * 100) + '% lit, ' + F.r0(ev.moon_sep) + '° away'],
      ['Geocentric', ev.t_geo.replace('T', ' ').replace('Z', ' UTC') + ' · shadow on the Earth ' + ev.earth[0].slice(11, 19) + '–' + ev.earth[1].slice(11, 19) + ' UTC']
    ];
    el('ev-facts').innerHTML = rows.map(function (r) { return '<tr><th>' + r[0] + '</th><td>' + r[1] + '</td></tr>'; }).join('');
    var chordCap = inside ? ('Your chord: ' + F.r0(2 * Math.sqrt(R * R - s.d * s.d)) + ' km of the ' + F.r0(2 * R) + ' km disc · ' + F.r1(s.dur) + ' s')
                          : ('Your line misses the ' + F.r0(2 * R) + ' km disc by ' + F.r0(Math.abs(s.d) - R) + ' km; the dashed lines are where 1σ would put it');
    el('pane-finder').innerHTML = A.finderSvg(ev, tz) + '<p class="pane-cap">The field 24 hours around the event; the star is ringed.</p>';
    el('pane-chord').innerHTML = A.chordSvg(ev, s) + '<p class="pane-cap">' + chordCap + '</p>' + A.stripSvg(ev, s)
      + '<p class="pane-cap">Across the path: the band is the shadow, the paler edge its 1σ.</p>';
    el('pane-curve').innerHTML = A.curveSvg(ev, s) + '<p class="pane-cap">' + (inside ? 'What you would record' : 'On the centre line — you are outside the path')
      + ': ' + F.r1(ev.drop) + ' mag for ' + F.r1(inside ? s.dur : ev.dur_max_s) + ' s, timing ± ' + F.r1(ev.sigma_s || 0) + ' s</p>';
    var dark = SKY && SKY.dark, t0 = Date.parse(ev.el.t0);
    el('sky-note').textContent = dark
      ? 'Along the track the star is at least 10° up in a sky past twilight between ' + F.t(t0 + dark[0] * 1000, tz) + ' and '
        + F.t(t0 + dark[1] * 1000, tz) + ' — the brighter stretch of the dotted line. Elsewhere the Sun is up or the star too low to time.'
      : '';
    el('pane-world').innerHTML = A.worldSvg(ev, world, META.bbox, LOC) + '<p class="pane-cap">The whole path on Earth; the box is the map above.</p>';
    if (!world) fetch(META.world).then(function (r) { return r.json(); }).then(function (w) {
      world = w; el('pane-world').innerHTML = A.worldSvg(ev, world, META.bbox, LOC) + '<p class="pane-cap">The whole path on Earth; the box is the map above.</p>';
    }).catch(function () { world = []; });
    placeMe(s, tc, y);
    syncUrl();
  }

  function syncUrl() {
    var q = '?e=' + encodeURIComponent(id) + '&lat=' + LOC.lat.toFixed(4) + '&lon=' + LOC.lon.toFixed(4);
    try { history.replaceState(null, '', q); } catch (e) {}
    el('spot-coords').textContent = LOC.lat.toFixed(4) + ', ' + LOC.lon.toFixed(4);
    el('spot-url').value = location.origin + location.pathname + q;
  }
  el('spot-copy').addEventListener('click', function () {
    var b = el('spot-copy'), done = function () { b.textContent = 'Link copied'; setTimeout(function () { b.textContent = 'Copy link to this spot'; }, 2000); };
    if (navigator.clipboard) navigator.clipboard.writeText(el('spot-url').value).then(done, function () { el('spot-url').select(); });
    else { el('spot-url').select(); document.execCommand('copy'); done(); }
  });
  if (navigator.share) {
    el('spot-share').hidden = false;
    el('spot-share').addEventListener('click', function () {
      navigator.share({ title: document.title, text: 'Asteroid occultation — my spot', url: el('spot-url').value }).catch(function () {});
    });
  }
  el('spot-play').addEventListener('click', function () { if (play) stopPlay(); else startPlay(); });
  el('spot-stations').addEventListener('click', function () {
    stnOn = !stnOn;
    el('spot-stations').textContent = stnOn ? 'Hide stations' : 'Suggest stations';
    drawStations();
  });
  el('stn-list').addEventListener('click', function (e) {
    var b = e.target.closest('[data-stn]'), p = b && stnPts[+b.dataset.stn];
    if (!p) return;
    setLoc(p[0], p[1], 'Station ' + (+b.dataset.stn + 1));
    if (map) map.panTo(p);
  });
  el('spot-centre').addEventListener('click', function () {
    if (!ev) return;
    var p = centrePoint();
    setLoc(p[0], p[1], 'On the centre line');
    if (map) map.panTo(p);
  });

  document.getElementById('ast-dl').addEventListener('click', function (e) {
    var b = e.target.closest('[data-dl]');
    if (!b || !ev) return;
    A.save(ev.id + '.' + b.dataset.dl, b.dataset.dl === 'kml' ? A.kml(ev) : A.gpx(ev),
           b.dataset.dl === 'kml' ? 'application/vnd.google-earth.kml+xml' : 'application/gpx+xml');
  });
  var sheet = el('loc-sheet'), latI = el('loc-lat'), lonI = el('loc-lon'), sel = el('loc-city');
  function setLoc(lat, lon, label) { lat = +lat; lon = +lon; if (!isFinite(lat) || !isFinite(lon)) return;
    LOC = { lat: lat, lon: lon, label: label || (lat.toFixed(2) + ', ' + lon.toFixed(2)) };
    try { localStorage.setItem('occult-loc', JSON.stringify(LOC)); } catch (e) {}
    render(); }
  el('loc-chip').addEventListener('click', function () { latI.value = LOC.lat.toFixed(4); lonI.value = LOC.lon.toFixed(4); sheet.showModal(); });
  sheet.addEventListener('click', function (e) { if (e.target === sheet) sheet.close(); });
  el('loc-go').addEventListener('click', function () { setLoc(latI.value, lonI.value); sheet.close(); });
  sel.addEventListener('change', function () { var c = META.cities[sel.value]; if (c) { setLoc(c[0], c[1], sel.value); sheet.close(); } });
  var geo = el('loc-geo'); if (!navigator.geolocation) geo.hidden = true;
  geo.addEventListener('click', function () { geo.disabled = true; geo.textContent = 'Locating…';
    navigator.geolocation.getCurrentPosition(function (p) { geo.disabled = false; geo.textContent = 'Use my location'; setLoc(p.coords.latitude, p.coords.longitude); sheet.close(); },
      function () { geo.disabled = false; geo.textContent = 'Location unavailable'; }); });
})();
"""

EVENT_TEMPLATE = """
<nav class="subnav">
  <div class="subnav-row">
    <div class="subnav-links"><a id="back" href="/#asteroids">‹ All months</a></div>
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
<main class="wrap" id="ev-main">
  <header class="ev-head">
    <p class="sub" id="ev-when">Loading…</p>
    <h1 id="ev-title">Asteroid occultation</h1>
    <p class="ev-verdict" id="ev-verdict"></p>
    <p class="hint" id="ev-look"></p>
  </header>
  <div id="map"></div>
  <p class="map-note">Shaded: the path, as wide as the asteroid, and darkest down the middle where the star stays hidden
  longest — at the edges it barely blinks. Dashed either side: one standard deviation, and beyond it the finer dashes are two.
  The dotted line is the rest of the track around the world. Labels along the centre line are the time the shadow passes there.
  <b>Tap the map, or drag the pin, to put your spot anywhere</b> — everything on this page follows it.</p>
  <p class="map-note" id="sky-note"></p>
  <div class="spot">
    <span class="spot-coords" id="spot-coords"></span>
    <button class="btn" id="spot-centre" type="button">Move to the centre line</button>
    <button class="btn" id="spot-stations" type="button">Suggest stations</button>
    <button class="btn" id="spot-play" type="button">▶ Play the shadow</button>
    <button class="btn" id="spot-copy" type="button">Copy link to this spot</button>
    <button class="btn" id="spot-share" type="button" hidden>Share</button>
    <input class="spot-url" id="spot-url" readonly aria-label="Link to this spot">
  </div>
  <div class="stn-panel" id="stn-panel" hidden>
    <div class="stn-list" id="stn-list"></div>
    <p class="hint" id="stn-note"></p>
  </div>
  <div class="ast-dl" id="ast-dl"><button class="btn" data-dl="kml">Download path (KML)</button><button class="btn" data-dl="gpx">GPX</button></div>
  <div class="ev-panes">
    <div id="pane-finder"></div>
    <div id="pane-chord"></div>
    <div id="pane-curve"></div>
    <div id="pane-world"></div>
  </div>
  <h2>The numbers</h2>
  <div class="table-wrap"><table class="ev-facts"><tbody id="ev-facts"></tbody></table></div>
  <p class="method">Everything here is computed for the place in the chip above: the time is when the shadow passes closest
  to you, and the chord and fade are what you would record there. The asteroid is a sphere of its catalogue diameter, so a
  real, lumpy one casts a slightly different shadow — which is exactly what timing it from several places measures.</p>
  <noscript><p class="method">This page draws itself in the browser. Without JavaScript, the month pages list every event
  with its path and times.</p></noscript>
  <script type="application/json" id="ast-meta">__META__</script>
</main>
__FOOTER__
<link rel="stylesheet" href="__LEAFLET_CSS__" integrity="__LEAFLET_CSS_SRI__" crossorigin="anonymous">
<script src="__LEAFLET_JS__" integrity="__LEAFLET_JS_SRI__" crossorigin="anonymous"></script>
<script src="/js/asteroid.js?v=__LIBV__"></script>
<script>
__JS__
</script>
</body>
</html>
"""


def lib_url():
    (OUT / "js").mkdir(parents=True, exist_ok=True)
    (OUT / "js" / "asteroid.js").write_text(LIB_JS)
    return _hash(LIB_JS)


def event_page(months, cities, aud, geo):
    """site/asteroid.html: one page that draws any event, chosen by `?e=<id>`."""
    desc = ("Everything for one asteroid occultation: the path on a map, how close it passes you, the finder chart, the chord "
            "you would time, how far the star fades, and the path as KML.")
    meta = {"months": {ym: url for ym, url in months.items()}, "monthLabels": {ym: f"{MONTHS[int(ym[5:]) - 1]} {ym[:4]}" for ym in months},
            "cities": cities, "bbox": geo["bbox"], "defaultPlace": list(DEFAULT_PLACE), "world": world_url()}
    page = head(f"Asteroid occultation · {SITE_NAME}", desc, "/asteroid",
                extra=f"<style>{AST_CSS}{CHART_CSS}{EVENT_CSS}</style>", og="ast")
    body = EVENT_TEMPLATE
    for k, v in {"__PLACE__": esc(DEFAULT_PLACE[0]),
                 "__CITY_OPTS__": "".join(f'<option value="{esc(n)}">{esc(n)}</option>' for n in cities),
                 "__META__": json.dumps(meta, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"),
                 "__FOOTER__": FOOTER, "__JS__": EVENT_JS, "__LIBV__": lib_url(),
                 "__LEAFLET_CSS__": f"{LEAFLET}/leaflet.css", "__LEAFLET_CSS_SRI__": LEAFLET_CSS_SRI,
                 "__LEAFLET_JS__": f"{LEAFLET}/leaflet.js", "__LEAFLET_JS_SRI__": LEAFLET_JS_SRI}.items():
        body = body.replace(k, v)
    (OUT / "asteroid.html").write_text(page + body)
    print(f"wrote site/asteroid.html (one page for every event) and site/js/asteroid.js")


def month_page(ym, d, cities_all, nav):
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
    src = f"/data/{slug}.json?v={_hash(data_json)}"
    meta = {"src": src, "t0": f"{ym}-01T00:00:00Z", "defaultPlace": list(DEFAULT_PLACE),
            "cities": cities, "bbox": geo["bbox"], "lat0": aud["lat0"], "mapW": MAP_W}
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
                 "__FOOTER__": FOOTER, "__JS__": MONTH_JS, "__LIBV__": lib_url()}.items():
        body = body.replace(k, v)
    (OUT / f"{slug}.html").write_text(page + body)
    (OUT / "data").mkdir(exist_ok=True)
    (OUT / "data" / f"{slug}.json").write_text(data_json)
    print(f"wrote site/{slug}.html: {len(d['events'])} events, {mine} over {name}")
    nxt = d["events"][0] if d["events"] else None
    return {"slug": slug, "label": label, "year": y, "month": mo, "n": len(d["events"]), "mine": mine, "planet": "asteroids",
            "nights": len(groups), "first": nxt["asteroid"]["name"] if nxt else None, "src": src,
            "ids": [e["id"] for e in d["events"]]}


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
    if built:
        seed = json.loads((ROOT / "seed.json").read_text())
        d0 = json.loads((ROOT / "data" / f"asteroids-{yms[0]}.json").read_text())
        aud = seed["audiences"][d0["audience"]]
        geo = json.loads((ROOT / "geo" / f"{d0['audience']}.json").read_text())
        city_list = {c["name"]: [round(c["lat"], 3), round(c["lon"], 3), c.get("tz") or aud["tz"]]
                     for c in json.loads((ROOT / aud["cities"]).read_text())}
        # every month the event page may be asked for, whichever month it was built with
        all_files = sorted((ROOT / "data").glob("asteroids-*.json"))
        months = {}
        for f in all_files:
            ym = f.stem[len("asteroids-"):]
            months[ym] = f"/data/asteroids-{ym}.json?v={_hash(f.read_text())}"
        event_page(months, city_list, aud, geo)
    return built


if __name__ == "__main__":
    import build_feeds
    seed = json.loads((ROOT / "seed.json").read_text())
    build_all(build_feeds.collect_cities(seed), only=sys.argv[1:] or None)
