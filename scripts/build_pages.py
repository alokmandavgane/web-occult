#!/usr/bin/env python3
"""Build site/ — the whole static site — from seed + data + geo.

    data/<slug>.json    (engine/occultation_event.py, DE431)
  + geo/<audience>.json (scripts/build_geo.py)
  + seed.json
  -> site/index.html, site/<slug>.html, site/data/<slug>.json, site/sitemap.xml,
     site/404.html, site/robots.txt, site/_headers

Static by construction: the maps are inline SVG, the city table is in the HTML,
nothing is fetched. A crawler sees the whole page; a reader costs nothing to
serve. Re-run after regenerating the data or editing the seed.

Usage:  python3 scripts/build_pages.py
"""

import html
import json
import math
import sys
import zoneinfo
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site"
SITE = "https://occult.alokm.com"
SITE_NAME = "Occult"
GA_ID = "G-GD7LT48Y79"   # the alokm.com GA4 property, shared with eclipse/zsd/inc
TAGLINE = "lunar occultations, computed"


def esc(s):
    return html.escape(str(s), quote=True)


def parse(iso):
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


# ── projection + SVG ───────────────────────────────────────────────────────

class Proj:
    """Equirectangular with the audience's standard parallel — a plain lat/lon
    grid stretched so distances near lat0 read true."""

    def __init__(self, bbox, lat0, width):
        self.lon0, self.lat0, self.lon1, self.lat1 = bbox
        self.k = math.cos(math.radians(lat0))
        self.s = width / ((self.lon1 - self.lon0) * self.k)
        self.W = width
        self.H = (self.lat1 - self.lat0) * self.s

    def xy(self, lat, lon):
        return ((lon - self.lon0) * self.k * self.s, (self.lat1 - lat) * self.s)

    def path(self, rings, close=True):
        parts = []
        for ring in rings:
            pts = [self.xy(lat, lon) for lat, lon in ring]
            d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
            parts.append(d + ("Z" if close else ""))
        return " ".join(parts)

    def path_lonlat(self, rings, close=True):
        return self.path([[(lat, lon) for lon, lat in r] for r in rings], close)


def svg_map(data, geo, aud, cities, featured, width=800, inset=False):
    m = data["maps"][data["audience"] if not inset else "world"]
    bbox = geo["bbox"]
    p = Proj(bbox, aud["lat0"], width)
    W, H = p.W, p.H
    out = [f'<svg viewBox="0 0 {W:.0f} {H:.0f}" xmlns="http://www.w3.org/2000/svg" role="img" '
           f'aria-label="Map of where the occultation is visible" class="occ-svg{" occ-inset" if inset else ""}">']
    out.append(f'<rect width="{W:.0f}" height="{H:.0f}" class="sea"/>')
    if not inset:
        out[0] = out[0].replace('class="occ-svg', 'id="main-map" class="occ-svg')
    out.append(f'<path class="land" d="{p.path_lonlat(geo["land"])}"/>')
    if geo.get("borders"):
        out.append(f'<path class="border" d="{p.path_lonlat(geo["borders"], close=False)}"/>')
    out.append(f'<path class="region" fill-rule="evenodd" d="{p.path(m["region"])}"/>')
    if m["region_night"]:
        out.append(f'<path class="night" fill-rule="evenodd" d="{p.path(m["region_night"])}"/>')
    exact = m.get("limits_exact") or []
    for lim in m["limits"]:
        cls = "limit-grid" if exact and lim["kind"] in ("north", "south") else f"limit-{lim['kind']}"
        out.append(f'<path class="limit {cls}" d="{p.path([lim["points"]], close=False)}"/>')
    for lim in exact:
        out.append(f'<path class="limit limit-{lim["kind"]} limit-exact" d="{p.path([lim["points"]], close=False)}"/>')
    if inset:
        # the audience frame on the world inset
        ab = data["maps"][data["audience"]]["bbox"]
        x0, y0 = p.xy(ab[3], ab[0])
        x1, y1 = p.xy(ab[1], ab[2])
        out.append(f'<rect class="frame" x="{x0:.1f}" y="{y0:.1f}" width="{x1-x0:.1f}" height="{y1-y0:.1f}"/>')
    else:
        r = width / 200
        for c in cities:
            x, y = p.xy(c["lat"], c["lon"])
            if not (0 <= x <= W and 0 <= y <= H):
                continue
            out.append(f'<circle class="city city-{c["verdict"]}" data-city="{esc(c["name"])}" cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}">'
                       f'<title>{esc(c["name"])}: {esc(verdict_text(c, data))}</title></circle>')
        for c in cities:
            if c["name"] not in featured:
                continue
            x, y = p.xy(c["lat"], c["lon"])
            if not (0 <= x <= W and 0 <= y <= H):
                continue
            out.append(f'<text class="city-label" x="{x + r*1.6:.1f}" y="{y + r*0.9:.1f}">{esc(c["name"])}</text>')
    if not inset:
        out.append('<g id="pin" hidden><circle r="9" class="pin-ring"/><circle r="2.5" class="pin-dot"/></g>')
    out.append("</svg>")
    return "\n".join(out)


# ── text helpers ───────────────────────────────────────────────────────────

def t_local(iso, tz, fmt="%H:%M:%S"):
    return parse(iso).astimezone(tz).strftime(fmt)


def compass(az):
    return ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"][int((az + 11.25) // 22.5) % 16]


def look_text(c):
    """Where the Moon is at that moment, in words: '41° up in the WSW · daylight'."""
    alt, az = c.get("moon_alt", 0), c.get("moon_az")
    if alt <= 0:
        return "Moon below the horizon"
    height = "low" if alt < 15 else "high" if alt > 60 else ""
    where = f"{alt:.0f}° up{' (' + height + ')' if height else ''}" + (f" in the {compass(az)}" if az is not None else "")
    return f"{where} · {sky_text(c['sun_alt'])}"


def sky_text(sun_alt):
    if sun_alt > 0:
        return f"daylight, Sun {sun_alt:+.0f}°"
    if sun_alt > -6:
        return "sunset twilight"
    if sun_alt > -12:
        return "dusk"
    return "dark sky"


def verdict_text(c, data):
    tname = data["target"]["names"]["common"]
    if c["verdict"] == "visible":
        hid = c.get("hidden_min")
        return (f"hidden {hid:.0f} min, " if hid else "") + sky_text(c["sun_alt"])
    if c["verdict"] == "miss":
        gap = c["sep_arcmin"] - c["moon_sd_arcmin"]
        return f"misses — {tname} passes {gap:.1f}′ from the limb"
    return "Moon below the horizon"


def city_row(c, data, tz):
    con = c.get("contacts", {})
    tname = data["target"]["names"]["common"]
    name = esc(c["name"])
    if c["verdict"] == "visible" and con:
        d = f'{t_local(con["D2"], tz)}' if "D2" in con else "—"
        d1 = f'<small>from {t_local(con["D1"], tz, "%H:%M:%S")}</small>' if "D1" in con and "D2" in con else ""
        r = f'{t_local(con["R1"], tz)}' if "R1" in con else "—"
        r2 = f'<small>to {t_local(con["R2"], tz, "%H:%M:%S")}</small>' if "R2" in con and "R1" in con else ""
        hid = f'{c["hidden_min"]:.0f} min' if c.get("hidden_min") else "—"
        return (f'<tr class="v-visible" data-lat="{c["lat"]}" data-lon="{c["lon"]}"><td>{name}</td>'
                f'<td>{d}{d1}</td><td>{r}{r2}</td><td>{hid}</td><td>{esc(look_text(c))}</td></tr>')
    if c["verdict"] == "miss":
        gap = c["sep_arcmin"] - c["moon_sd_arcmin"]
        when = t_local(c["closest"], tz, "%H:%M") if c.get("closest") else ""
        return (f'<tr class="v-miss" data-lat="{c["lat"]}" data-lon="{c["lon"]}"><td>{name}</td>'
                f'<td colspan="3">misses — {esc(tname)} passes {gap:.1f}′ from the limb at {when}</td>'
                f'<td>{esc(look_text(c))}</td></tr>')
    return (f'<tr class="v-down" data-lat="{c["lat"]}" data-lon="{c["lon"]}"><td>{name}</td>'
            f'<td colspan="4">Moon below the horizon</td></tr>')


# ── page ───────────────────────────────────────────────────────────────────

BASE_CSS = """
    :root { color-scheme: light dark;
            --bg: #fbfbfa; --card: #ffffff; --card-2: #f3f4f2; --border: #e6e7e3; --line: #d5d7d2;
            --text: #16181d; --muted: #6b7280; --accent: #0e7490;
            --sea: #eef2f5; --land: #dfe3e8; --land-line: #c8ced6;
            --c-visible: #15803d; --c-miss: #dc2626; --c-down: #9ca3af; --c-limit: #d97706; --c-night: #7c3aed;
            --region: rgba(14,116,144,0.22); --region-line: rgba(14,116,144,0.6); --night: rgba(124,58,237,0.22); }
    @media (prefers-color-scheme: dark) { :root {
            --bg: #0f1115; --card: #171a21; --card-2: #1f232c; --border: #262a33; --line: #343945;
            --text: #e8eaee; --muted: #9aa3b2; --accent: #67c9e6;
            --sea: #0b0e14; --land: #232833; --land-line: #3a4150;
            --c-visible: #4ade80; --c-miss: #f87171; --c-down: #6b7280; --c-limit: #fbbf24; --c-night: #c4b5fd;
            --region: rgba(103,201,230,0.22); --region-line: rgba(103,201,230,0.6); --night: rgba(196,181,253,0.25); } }
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    html { -webkit-text-size-adjust: 100%; }
    body { background: var(--bg); color: var(--text); line-height: 1.55; padding-bottom: 4rem;
           font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, "Helvetica Neue", Arial, sans-serif;
           font-feature-settings: "tnum"; }
    a { color: var(--accent); text-decoration: none; }
    a:hover { text-decoration: underline; }
    header.site { padding: 1.1rem 1rem; }
    .site-row { display: flex; align-items: baseline; justify-content: space-between; gap: 1rem; flex-wrap: wrap; max-width: 860px; margin: 0 auto; }
    .brand { font-weight: 700; font-size: 1.1rem; color: var(--text); letter-spacing: -0.01em; display: inline-flex; align-items: center; gap: 0.45rem; }
    .brand:hover { text-decoration: none; }
    .brand svg { width: 1.1em; height: 1.1em; }
    .tagline { color: var(--muted); font-size: 0.85rem; }
    .wrap { max-width: 860px; margin: 0 auto; padding: 0 1rem; }
    h1 { font-size: clamp(1.6rem, 4vw, 2.2rem); font-weight: 700; line-height: 1.15; letter-spacing: -0.02em; margin: 1.6rem 0 0.35rem; }
    .sub { color: var(--muted); }
    h2 { font-size: 0.8rem; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); margin: 2rem 0 0.7rem; }
    p { margin: 0.55rem 0; }
    .lead { font-size: 1.1rem; margin-top: 1rem; }
    .facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 0.6rem; margin: 1.2rem 0; }
    .fact { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 0.75rem 0.9rem; }
    .facts-main { grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); margin-top: 1.1rem; }
    .facts-main .fact { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 8%, var(--card)); }
    .facts-main .fact-value { font-size: 1.45rem; white-space: nowrap; }
    .meta { color: var(--muted); font-size: 0.88rem; }
    .fact-label { font-size: 0.72rem; color: var(--muted); letter-spacing: 0.06em; text-transform: uppercase; }
    .fact-value { font-size: 1.3rem; font-weight: 700; margin-top: 0.15rem; letter-spacing: -0.01em; }
    .fact-sub { font-size: 0.8rem; color: var(--muted); margin-top: 0.15rem; }
    .map-card { background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 0.6rem; }
    .occ-svg { width: 100%; height: auto; display: block; border-radius: 8px; }
    .occ-inset { max-width: 420px; margin: 0.6rem auto 0; }
    .sea { fill: var(--sea); }
    .land { fill: var(--land); stroke: var(--land-line); stroke-width: 0.8; }
    .border { fill: none; stroke: var(--land-line); stroke-width: 0.7; }
    .region { fill: var(--region); stroke: var(--region-line); stroke-width: 1; }
    .night { fill: var(--night); stroke: none; }
    .limit { fill: none; stroke-width: 2.6; stroke-linecap: round; stroke-linejoin: round; }
    .limit-north, .limit-south { stroke: var(--c-limit); }
    .limit-horizon { stroke: var(--muted); stroke-width: 1.2; stroke-dasharray: 5 4; }
    .limit-grid { stroke: var(--c-limit); stroke-width: 1; opacity: 0.35; stroke-dasharray: 3 3; }
    .frame { fill: none; stroke: var(--c-limit); stroke-width: 1.2; }
    .city { stroke: var(--card); stroke-width: 1; }
    .city-visible { fill: var(--c-visible); }
    .city-miss { fill: var(--c-miss); }
    .city-moon_down { fill: var(--c-down); }
    .city-label { font: 500 11px -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif; fill: var(--text); paint-order: stroke; stroke: var(--card); stroke-width: 3px; stroke-linejoin: round; }
    .legend { display: flex; flex-wrap: wrap; gap: 0.4rem 1.1rem; font-size: 0.82rem; color: var(--muted); margin: 0.7rem 0.2rem 0.1rem; }
    .legend span::before { content: ''; display: inline-block; width: 0.8em; height: 0.8em; border-radius: 50%; margin-right: 0.4em; vertical-align: -0.05em; }
    .lg-region::before { background: var(--region-line); border-radius: 2px !important; }
    .lg-night::before { background: var(--c-night); opacity: 0.6; border-radius: 2px !important; }
    .lg-limit::before { background: var(--c-limit); height: 0.25em !important; vertical-align: 0.25em !important; }
    .lg-visible::before { background: var(--c-visible); }
    .lg-miss::before { background: var(--c-miss); }
    .table-wrap { overflow-x: auto; background: var(--card); border: 1px solid var(--border); border-radius: 14px; }
    table { border-collapse: collapse; width: 100%; font-size: 0.9rem; }
    th, td { text-align: left; padding: 0.55rem 0.75rem; border-bottom: 1px solid var(--border); white-space: nowrap; vertical-align: top; }
    tbody tr:last-child td { border-bottom: 0; }
    th { color: var(--muted); font-weight: 600; font-size: 0.72rem; letter-spacing: 0.06em; text-transform: uppercase; }
    th small { font-weight: 400; text-transform: none; letter-spacing: 0; }
    td small { display: block; color: var(--muted); font-size: 0.75rem; }
    tr.v-miss td { color: var(--muted); }
    tr.v-miss td:first-child { color: var(--c-miss); }
    tr.v-visible td:first-child { color: var(--c-visible); font-weight: 600; }
    tr.v-down td { color: var(--c-down); }
    tr.nearest td { background: rgba(217,119,6,0.12); }
    details { border-top: 1px solid var(--border); }
    summary { cursor: pointer; color: var(--accent); font-size: 0.9rem; padding: 0.6rem 0.75rem; }
    .btn { background: var(--card); color: var(--text); border: 1px solid var(--line); border-radius: 999px; padding: 0.45rem 0.95rem; font: inherit; font-size: 0.85rem; cursor: pointer; }
    .btn:hover { border-color: var(--accent); color: var(--accent); }
    .method { font-size: 0.85rem; color: var(--muted); }
    .limb-card { background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 0.8rem; max-width: 480px; margin: 0.6rem auto; }
    .limb-controls { display: flex; justify-content: space-between; align-items: center; gap: 0.6rem; flex-wrap: wrap; font-size: 0.9rem; }
    .limb-controls select { font: inherit; padding: 0.3rem 0.5rem; border-radius: 8px; border: 1px solid var(--line); background: var(--card); color: var(--text); max-width: 60vw; }
    .limb-readout { color: var(--muted); font-size: 0.85rem; font-variant-numeric: tabular-nums; }
    .limb-svg { width: 100%; height: auto; display: block; margin: 0.5rem 0; }
    .limb-svg .disc-dark { fill: #2a2f3a; }
    .limb-svg .disc-bright { fill: #f2e9c9; }
    .limb-svg .disc-edge { fill: none; stroke: var(--line); stroke-width: 1; }
    .limb-svg .crater { fill: none; stroke-width: 0.8; stroke-linejoin: round; }
    .limb-svg .crater-night { stroke: #aab3c5; opacity: 0.16; }
    .limb-svg .crater-day { stroke: #7d6e4c; opacity: 0.4; }
    .limb-svg .track { fill: none; stroke: var(--accent); stroke-width: 1.5; stroke-dasharray: 4 3; }
    .limb-svg .track-hidden { fill: none; stroke: var(--accent); stroke-width: 1.5; opacity: 0.35; }
    .limb-svg .contact { fill: var(--c-limit); }
    .limb-svg .target { fill: #fff; stroke: var(--accent); stroke-width: 1.2; }
    .limb-svg .lbl { font: 500 10px -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif; fill: var(--muted); }
    .limb-svg .miss-note { font: 500 11px -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif; fill: var(--c-miss); }
    input[type=range] { width: 100%; accent-color: var(--accent); }
    details.advanced { border: 1px dashed var(--line); border-radius: 12px; padding: 0 0.8rem; margin: 1.2rem 0 0; }
    details.advanced summary { color: var(--muted); font-size: 0.85rem; padding: 0.55rem 0; }
    details.advanced[open] summary { color: var(--accent); }
    details.advanced .graze-card { margin-bottom: 0.8rem; }
    .graze-card { background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 0.8rem; }
    .graze-svg { width: 100%; height: auto; display: block; }
    .gz-sky { fill: var(--sea); }
    .gz-terrain { fill: #6b7280; opacity: 0.85; }
    .gz-mean { stroke: var(--muted); stroke-width: 0.8; stroke-dasharray: 3 3; }
    .gz-star { fill: none; stroke: var(--c-limit); stroke-width: 2; }
    .gz-disc { fill: var(--c-limit); opacity: 0.2; }
    .gz-ev { stroke: var(--accent); stroke-width: 1; stroke-dasharray: 2 2; }
    .gz-lbl { font: 500 10px -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif; fill: var(--muted); }
    .gz-cap { font: 600 11px -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif; fill: var(--text); }
    .subnav { position: sticky; top: 0; z-index: 20; background: color-mix(in srgb, var(--bg) 88%, transparent); backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px); border-bottom: 1px solid var(--border); }
    .subnav-row { max-width: 860px; margin: 0 auto; padding: 0.45rem 1rem; display: flex; align-items: center; justify-content: space-between; gap: 0.6rem; }
    .subnav-links { display: flex; gap: 0.2rem; overflow-x: auto; scrollbar-width: none; }
    .subnav-links::-webkit-scrollbar { display: none; }
    .subnav-links a { color: var(--muted); font-size: 0.85rem; padding: 0.3rem 0.55rem; border-radius: 999px; white-space: nowrap; }
    .subnav-links a:hover { text-decoration: none; color: var(--text); }
    .subnav-links a.active { color: var(--text); background: var(--card-2); }
    .chip { display: inline-flex; align-items: center; gap: 0.4rem; max-width: 55vw; background: var(--card); border: 1px solid var(--line); border-radius: 999px; padding: 0.3rem 0.7rem 0.3rem 0.5rem; font: inherit; font-size: 0.85rem; color: var(--text); cursor: pointer; white-space: nowrap; overflow: hidden; }
    .chip:hover { border-color: var(--accent); }
    .chip-pin { font-size: 0.9em; }
    .chip-sub { color: var(--muted); font-size: 0.78rem; overflow: hidden; text-overflow: ellipsis; }
    .chip-sub:empty { display: none; }
    .sheet { border: 1px solid var(--border); border-radius: 16px; background: var(--card); color: var(--text); padding: 0; max-width: 420px; width: calc(100% - 2rem); }
    .sheet::backdrop { background: rgba(0,0,0,0.45); }
    .sheet-body { padding: 1rem 1.1rem 1.1rem; display: grid; gap: 0.7rem; }
    .sheet-title { font-weight: 700; font-size: 1.05rem; }
    .sheet-hint { color: var(--muted); font-size: 0.82rem; margin: 0; }
    .sheet label { display: flex; align-items: center; gap: 0.4rem; font-size: 0.9rem; }
    .sheet select { flex: 1; }
    .btn-primary { background: var(--accent); color: var(--bg); border-color: var(--accent); }
    @media (max-width: 600px) { .sheet { margin: auto 0 0; width: 100%; max-width: none; border-radius: 16px 16px 0 0; } }
    .hint { color: var(--muted); font-size: 0.85rem; }
    tr.yours td { background: color-mix(in srgb, var(--c-limit) 14%, transparent); }
    tr.yours td:first-child { color: var(--c-limit); font-weight: 600; }
    .loc-row { display: flex; flex-wrap: wrap; gap: 0.5rem 0.8rem; align-items: center; font-size: 0.9rem; }
    .loc-row input { font: inherit; width: 7.5rem; padding: 0.35rem 0.5rem; border-radius: 8px; border: 1px solid var(--line); background: var(--card); color: var(--text); }
    .loc-row select { font: inherit; padding: 0.35rem 0.5rem; border-radius: 8px; border: 1px solid var(--line); background: var(--card); color: var(--text); max-width: 45vw; }
    .loc-result { margin: 0.4rem 0 0.6rem; display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 0.5rem; }
    .loc-result .fact-value { font-size: 1.15rem; }
    .loc-result .verdict { grid-column: 1 / -1; font-weight: 600; }
    .loc-result .verdict.miss { color: var(--c-miss); } .loc-result .verdict.visible { color: var(--c-visible); } .loc-result .verdict.moon_down { color: var(--c-down); }
    #main-map { cursor: crosshair; }
    .pin-ring { fill: none; stroke: var(--c-limit); stroke-width: 2; } .pin-dot { fill: var(--c-limit); }
    .event-list { list-style: none; display: grid; gap: 0.7rem; margin: 0.6rem 0; }
    .event-card { display: block; background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 1rem 1.1rem; color: var(--text); }
    .event-card:hover { border-color: var(--accent); text-decoration: none; }
    .event-card .when { color: var(--muted); font-size: 0.85rem; }
    .event-card .what { font-size: 1.2rem; font-weight: 700; letter-spacing: -0.01em; margin: 0.15rem 0; }
    .event-card .note { color: var(--muted); font-size: 0.92rem; }
    .event-list-months { grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); }
    .event-list-months .event-card .what { font-size: 1rem; }
    footer { max-width: 860px; margin: 3rem auto 0; padding: 1.2rem 1rem 0; font-size: 0.82rem; color: var(--muted); border-top: 1px solid var(--border); }
"""


def head(title, desc, path, extra=""):
    url = f"{SITE}{path}"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <!-- Google tag (gtag.js) — shared property with alokm.com, eclipse/zsd/inc. Plain multi-page
       site, so the automatic page_view is right here (the Compose apps disable it and publish their own). -->
  <script async src="https://www.googletagmanager.com/gtag/js?id={GA_ID}"></script>
  <script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}gtag('js',new Date());gtag('config','{GA_ID}');</script>
  <title>{esc(title)}</title>
  <meta name="description" content="{esc(desc)}">
  <link rel="canonical" href="{url}">
  <meta property="og:title" content="{esc(title)}">
  <meta property="og:description" content="{esc(desc)}">
  <meta property="og:type" content="article">
  <meta property="og:url" content="{url}">
  <meta property="og:site_name" content="{SITE_NAME}">
  <meta name="theme-color" content="#fbfbfa" media="(prefers-color-scheme: light)">
  <meta name="theme-color" content="#0f1115" media="(prefers-color-scheme: dark)">
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Ccircle cx='16' cy='16' r='13' fill='%23111'/%3E%3Ccircle cx='21' cy='14' r='11' fill='%23fbfbfa'/%3E%3C/svg%3E">
  <style>{BASE_CSS}</style>
  {extra}
</head>
<body>
<header class="site">
  <div class="site-row">
    <a class="brand" href="/"><svg viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="16" r="13" fill="currentColor"/><circle cx="21" cy="14" r="11" fill="var(--bg)"/></svg>{SITE_NAME}</a>
    <span class="tagline">{TAGLINE}</span>
  </div>
</header>
"""


FOOTER = f"""
<footer>
  <p>Computed from the JPL DE431 ephemeris, for the Moon's mean limb. Static pages; no tracking beyond
  basic analytics. <a href="/calendar">Calendar feeds</a> · <a href="https://alokm.com/">Alok Mandavgane</a>.</p>
</footer>
"""


def write_geo_files(slug, data, tz, tzl):
    """KML (Google Earth / Maps) and GPX (phone GPS apps) with the graze limit lines and nothing else —
    the line a graze chaser picks a station along. Real lunar limb where traced, mean sphere otherwise.
    City times live on the page, and the browser solves any spot exactly."""
    m = data["maps"][data["audience"]]
    tname = data["target"]["names"]["common"]
    title = f"The Moon occults {tname} — {data['geocentric']['t_min'][:10]}"
    exact = m.get("limits_exact") or []
    lines = exact or [l for l in m["limits"] if l["kind"] in ("north", "south")]
    basis = "real lunar limb (LRO LOLA)" if exact else "mean lunar sphere"

    def coords(points):   # KML wants lon,lat
        return " ".join(f"{lon},{lat},0" for lat, lon in points)

    k = [f'<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>{esc(title)}</name>',
         f'<description>Graze limits from {SITE}/{slug}, traced against the {basis}.</description>',
         '<Style id="graze"><LineStyle><color>ff06b6d9</color><width>4</width></LineStyle></Style>']
    for lim in lines:
        k.append(f'<Placemark><name>{lim["kind"]} graze limit</name><styleUrl>#graze</styleUrl>'
                 f'<LineString><tessellate>1</tessellate><coordinates>{coords(lim["points"])}</coordinates></LineString></Placemark>')
    k.append('</Document></kml>\n')
    (OUT / "kml").mkdir(exist_ok=True)
    (OUT / "kml" / f"{slug}.kml").write_text("\n".join(k))

    g = ['<?xml version="1.0" encoding="UTF-8"?>', f'<gpx version="1.1" creator="{SITE}" xmlns="http://www.topografix.com/GPX/1/1">',
         f'<metadata><name>{esc(title)} — graze limits</name></metadata>']
    for lim in lines:
        g.append(f'<trk><name>{lim["kind"]} graze limit</name><trkseg>' +
                 "".join(f'<trkpt lat="{lat}" lon="{lon}"/>' for lat, lon in lim["points"]) + '</trkseg></trk>')
    g.append('</gpx>\n')
    (OUT / "kml" / f"{slug}.gpx").write_text("\n".join(g))


def build(seed, slug):
    entry = next(e for e in seed["events"] if e["slug"] == slug)
    data = json.loads((ROOT / "data" / f"{slug}.json").read_text())
    aud = seed["audiences"][data["audience"]]
    geo = json.loads((ROOT / "geo" / f"{data['audience']}.json").read_text())
    geo_world = json.loads((ROOT / "geo" / "world.json").read_text())
    tz = zoneinfo.ZoneInfo(aud["tz"])
    tzl = aud["tz_label"]
    tgt = data["target"]["names"]
    g = data["geocentric"]
    tname = tgt["common"]

    cities = data["cities"]
    if aud["cities"] == "world":   # 400 big cities worldwide: only the ones with the Moon up are worth a row
        cities = [c for c in cities if c["verdict"] != "moon_down"]
    featured = [n for n in aud["featured"] if any(c["name"] == n for c in cities)]
    if not featured:   # world audience: the biggest cities that see it, then the biggest near misses
        featured = [c["name"] for c in cities if c["verdict"] == "visible"][:14] + [c["name"] for c in cities if c["verdict"] == "miss"][:4]
    vis = [c for c in cities if c["verdict"] == "visible" and c.get("contacts")]
    misses = [c for c in cities if c["verdict"] == "miss"]
    by_name = {c["name"]: c for c in cities}
    feat_rows = sorted((by_name[n] for n in featured),
                       key=lambda c: (c["verdict"] != "visible", c.get("contacts", {}).get("D2", "z"), c["name"]))
    rest_rows = sorted((c for c in cities if c["name"] not in featured),
                       key=lambda c: c["name"])

    t_min_local = parse(g["t_min"]).astimezone(tz)
    day = t_min_local.strftime("%A %-d %B %Y")
    first_d = min(parse(c["contacts"]["D1" if "D1" in c["contacts"] else "D2"]) for c in vis) if vis else None
    last_r = max(parse(c["contacts"]["R2" if "R2" in c["contacts"] else "R1"]) for c in vis) if vis else None
    max_hidden = max((c.get("hidden_min", 0) for c in vis), default=0)
    longest = max(vis, key=lambda c: c.get("hidden_min", 0)) if vis else None
    near_miss = min(misses, key=lambda c: c["sep_arcmin"] - c["moon_sd_arcmin"]) if misses else None

    title = f"The Moon occults {tname} — {t_min_local.strftime('%-d %B %Y')}"
    n_day = sum(1 for c in vis if c["sun_alt"] > -6)
    if vis:
        sky = ("in daylight" if n_day == len(vis) else "in a dark sky" if n_day == 0 else "in daylight for some, after sunset for others")
        auto_note = (f"The Moon hides {tname} for up to {max_hidden:.0f} minutes, {sky}. "
                     + (f"{len(vis)} of the {len(cities)} listed Indian cities see it" if aud["cities"] != "world" else
                      f"{len(vis)} of the world's big cities see it")
                     + (f"; {esc(near_miss['name'])} misses by {near_miss['sep_arcmin'] - near_miss['moon_sd_arcmin']:.1f}′." if near_miss else "."))
    else:
        auto_note = f"The Moon hides {tname}, but from no large city — the map shows where." 
    kind = "planet" if data["target"]["kind"] == "graha" else "star"
    h1 = f"Lunar occultation of the {kind} {tname}"
    desc = (f"Where and when the Moon hides {tname} on {t_min_local.strftime('%-d %B %Y')}: "
            f"city-by-city times for {aud['label']}, the graze-limit map, and how to watch. "
            f"Computed from the JPL DE431 ephemeris.")
    url = f"{SITE}/{slug}"

    tips = ""
    if data["target"]["key"] == "venus" and vis and max(c["sun_alt"] for c in vis) > 0:
        ip = g.get("target_illum_pct") or 50
        shape = ("thin crescent" if ip < 25 else "fat crescent" if ip < 45 else
                 "half-lit disc" if ip < 55 else "gibbous disc" if ip < 95 else "nearly full disc")
        shape += f" ({2 * g['target_sd_arcsec']:.0f}″ across, {ip}% lit)"
        tips = f"""
      <p>This one happens in <strong>daylight</strong>. Venus is bright enough to see against a blue sky
      if you know exactly where to look — and today the Moon is the finder: a thin crescent,
      three days old, about 40° east of the Sun. Find the crescent first (shade the Sun with a
      building), then look for a hard white point beside its <em>dark</em> edge. Binoculars make it
      easy; a telescope shows Venus as a {shape} sliding behind the mountains of the
      unlit limb, then popping back out at the bright crescent an hour later.</p>
      <p>Because the limb it disappears behind is unlit, the disappearance is the harder half to
      catch — you are watching a bright point vanish into what looks like empty sky. The
      reappearance at the sunlit crescent is the easy, spectacular half. Never sweep near the Sun
      with binoculars.</p>"""

    limit_para = ""
    if near_miss:
        gap = near_miss["sep_arcmin"] - near_miss["moon_sd_arcmin"]
        exact_note = ""
        ex = data["maps"][data["audience"]].get("limits_exact")
        if ex:
            sh = ex[0].get("shift_km") or {}
            exact_note = (f" The solid line is traced against the real lunar limb — LRO LOLA terrain, the mountains and valleys "
                          f"that are on the edge for this libration — and sits {sh.get('min', 0):+.1f} to {sh.get('max', 0):+.1f} km from the "
                          f"mean-sphere line (dotted).")
        limit_para = (f"<p>The gold line is the <strong>north limit</strong>: along it {tname} grazes the Moon's "
                      f"northern edge. North of the line it is a near miss — from {esc(near_miss['name'])} {tname} "
                      f"passes just {gap:.1f}′ outside the limb — and a graze seen from right on the line, {tname} "
                      f"blinking in and out behind lunar mountains, is the finest view of all.{exact_note}</p>")
    night_para = ""
    if data["maps"][data["audience"]]["region_night"]:
        night_para = ("<p>The violet shading is where the Sun has set by the time of the event, so the "
                      "reappearance happens in a darkening sky.</p>")

    ld = {
        "@context": "https://schema.org", "@type": "Event",
        "name": title, "description": desc, "url": url,
        "startDate": first_d.astimezone(tz).isoformat() if first_d else t_min_local.isoformat(),
        "endDate": last_r.astimezone(tz).isoformat() if last_r else t_min_local.isoformat(),
        "eventStatus": "https://schema.org/EventScheduled",
        "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        "location": {"@type": "Place", "name": aud["label"]},
        "organizer": {"@type": "Organization", "name": SITE_NAME, "url": SITE},
        "isAccessibleForFree": True,
    }

    p_main = Proj(geo["bbox"], aud["lat0"], 800)
    graze_block = ""
    if (ROOT / "data" / f"{slug}-limb.json").exists():
        graze_block = f"""  <details class="advanced" id="graze">
    <summary>Advanced · graze profile against the real lunar limb</summary>
    <p class="hint">For graze chasers. The lunar limb as it really is for your libration — LRO LOLA terrain, in km above and
    below the mean sphere — with {esc(tname)}'s track drawn across it six minutes either side of each contact. Where the
    track dips below the terrain, {esc(tname)} is hidden; near a graze it blinks behind peaks.</p>
    <div class="graze-card" id="graze-card">
      <button class="btn" id="graze-load" type="button" data-src="/data/{slug}-limb.json">Load the limb profile (120 KB)</button>
      <svg id="graze-svg" viewBox="0 0 800 230" class="graze-svg" role="img" aria-label="The target's track against the lunar limb profile" hidden></svg>
      <p class="hint" id="graze-out"></p>
    </div>
  </details>

"""

    craters = json.loads((ROOT / "catalog" / "moon-craters.json").read_text())["craters"]
    limb = {
        "tz": aud["tz"], "tzl": tzl, "target": tname, "kind": kind, "lib": data.get("lib"), "craters": craters,
        "illum": g["illum_pct"] / 100, "bright_pa": g["bright_limb_pa"],
        "elements": data["elements"],
        "proj": {"lon0": p_main.lon0, "lat1": p_main.lat1, "k": p_main.k, "s": p_main.s, "W": p_main.W, "H": p_main.H},
        "cities": {c["name"]: [c["lat"], c["lon"]] for c in cities},
    }
    limb_order = [c["name"] for c in feat_rows] + [c["name"] for c in rest_rows]
    limb_options = "".join(f'<option value="{esc(n)}">{esc(n)}</option>' for n in limb_order)

    def fact(label, value, sub=""):
        return (f'<div class="fact"><div class="fact-label">{label}</div><div class="fact-value">{value}</div>'
                f'{f"<div class=fact-sub>{sub}</div>" if sub else ""}</div>')

    facts_main = "".join([
        fact(f"Watch from ({tzl})", f"{first_d.astimezone(tz).strftime('%H:%M')} – {last_r.astimezone(tz).strftime('%H:%M')}" if first_d else "—",
             f"{len(vis)} of {len(cities)} listed cities see it" if cities else "no large city sees it"),
        fact(f"{tname} hidden for", f"up to {max_hidden:.0f} min", f"{esc(longest['name'])}, {longest['hidden_min']:.0f} min" if longest else ""),
    ])
    facts_meta = (f"Closest approach {t_min_local.strftime('%H:%M')} {tzl} (geocentric, {g['min_sep_deg']:.2f}° centre to centre) · "
                  f"Moon {g['moon_age_days']:.1f} days old, {g['illum_pct']:.0f}% lit, {g['elongation_deg']:.0f}° from the Sun")

    thead = (f'<tr><th>City</th><th>{tname} disappears <small>({tzl})</small></th>'
             f'<th>reappears <small>({tzl})</small></th><th>hidden</th>'
             f'<th title="How high the Moon stands above the horizon when {esc(tname)} disappears (0° = horizon, 90° = overhead), the compass direction to look, and whether the sky is light or dark">Where to look at disappearance</th></tr>')

    page = head(f"{title} · {SITE_NAME}", desc, f"/{slug}",
                f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>') + f"""
<nav class="subnav" id="subnav">
  <div class="subnav-row">
    <div class="subnav-links">
      <a href="#map" data-sec="map">Map</a><a href="#moon" data-sec="moon">Moon</a><a href="#cities" data-sec="cities">Cities</a><a href="#watch" data-sec="watch">How to watch</a>
    </div>
    <button class="chip" id="loc-chip" type="button" aria-haspopup="dialog"><span class="chip-pin">📍</span><span id="chip-name">Choose location</span><span class="chip-sub" id="chip-sub"></span></button>
  </div>
</nav>
<dialog id="loc-sheet" class="sheet" aria-label="Location">
  <form method="dialog" class="sheet-body">
    <div class="sheet-title">Location</div>
    <label>City <select id="limb-city"><option value="">—</option>{limb_options}</select></label>
    <div class="loc-row">
      <label>Lat <input id="loc-lat" type="number" step="any" min="-90" max="90" placeholder="19.076"></label>
      <label>Lon <input id="loc-lon" type="number" step="any" min="-180" max="180" placeholder="72.878"></label>
    </div>
    <div class="loc-row">
      <button class="btn btn-primary" id="loc-go" type="button">Compute</button>
      <button class="btn" id="loc-geo" type="button">Use my location</button>
      <button class="btn" value="cancel">Close</button>
    </div>
    <p class="sheet-hint">You can also tap anywhere on the map, or a city dot.</p>
  </form>
</dialog>

<main class="wrap">
  <h1>{esc(title)}</h1>
  <p class="sub">{esc(h1)} · {esc(day)} · {esc(aud['label'])}</p>
  <div class="facts facts-main">{facts_main}</div>
  <p class="lead">{esc(entry.get('note') or auto_note)}</p>
  <p class="meta">{esc(facts_meta)}</p>

  <h2 id="map">Where it can be seen</h2>
  <div class="map-card">
    {svg_map(data, geo, aud, cities, featured)}
    <div class="legend">
      <span class="lg-region">sees the occultation</span>
      {'<span class="lg-night">after sunset</span>' if data["maps"][data["audience"]]["region_night"] else ''}
      <span class="lg-limit">graze limit</span>
      <span class="lg-visible">city sees it</span>
      <span class="lg-miss">near miss</span>
    </div>
    {svg_map(data, geo_world, seed["audiences"]["world"], cities, [], width=360, inset=True)}
  </div>
  {limit_para}
  {night_para}
  <p class="hint">Tap the map to set your location. Take the graze line with you:
  <a href="/kml/{slug}.kml">KML</a> for Google Earth / Maps · <a href="/kml/{slug}.gpx">GPX</a> for a phone GPS app.</p>

  <h2 id="moon">At the Moon's edge</h2>
  <div class="limb-card">
    <div class="limb-controls"><span id="limb-where" class="limb-readout"></span><span class="limb-readout" id="limb-readout"></span></div>
    <div class="loc-result" id="loc-result" hidden></div>
    <svg id="limb-svg" viewBox="-190 -190 380 380" class="limb-svg" role="img" aria-label="The Moon's disc with the target's path"></svg>
    <input type="range" id="limb-slider" min="0" max="160" value="80" step="1" aria-label="Time">
  </div>
  <p class="hint">{esc(tname)}'s path across the Moon from your location — north up, east to the left as in binoculars.
  Times here are computed in your browser from the same ephemeris as the table, to the same ±2 s. Drag the slider to move it along its track.</p>
  <script type="application/json" id="limb-data">{json.dumps(limb, ensure_ascii=False, separators=(",", ":"))}</script>

  {graze_block}

  <h2 id="cities">City by city</h2>
  <p>Times are against the real lunar limb (LRO LOLA terrain at each city's own libration). <em>Disappears</em> is the moment {esc(tname)} is fully hidden (its disc takes from the
  earlier time to slide in); <em>reappears</em> is when the first sliver returns. <em>Where to look</em> is the
  Moon's height above the horizon (0° is the horizon, 90° straight up) and compass direction at that moment,
  and whether the Sun is still up.</p>
  <div class="table-wrap">
    <table id="city-table">
      <thead>{thead}</thead>
      <tbody>{''.join(city_row(c, data, tz) for c in feat_rows)}</tbody>
    </table>
    <details>
      <summary>All {len(rest_rows)} other cities</summary>
      <table>
        <thead>{thead}</thead>
        <tbody>{''.join(city_row(c, data, tz) for c in rest_rows)}</tbody>
      </table>
    </details>
  </div>

  <h2 id="watch">How to watch</h2>{tips}

  <h2>Method &amp; accuracy</h2>
  <p class="method">Positions from the JPL <strong>DE431</strong> ephemeris (Skyfield), ΔT = {data['engine']['delta_t_s']} s.
  The city table's contact times and the solid limit line use the <strong>real lunar limb</strong> — the silhouette of
  LRO LOLA terrain (LDEM_64, ~0.5 km) at each observer's own libration — so they carry the mountains and valleys
  that a mean sphere misses (up to a few seconds at ordinary contacts, tens of seconds near a graze). The
  any-location solver in your browser and the shaded region still use the mean sphere of {data['engine']['moon_radius_km']} km (±2 s). {esc(tname)}'s own disc
  ({2 * g['target_sd_arcsec']:.0f}″ across) is included: partial contacts are the <small>from/to</small> times.
  The numbers behind this page: <a href="/data/{slug}.json">{slug}.json</a>.
  Generated {data['generated'][:10]}.</p>
</main>

{FOOTER}
<script>

(function () {{
  var D = JSON.parse(document.getElementById('limb-data').textContent), E = D.elements;
  var C = 299792.458, T0 = Date.parse(E.t0), HALF = E.half_hours * 60, R0 = E.R0, VE = E.v_earth_km_s;
  var OMEGA = E.era_rate_deg_per_min * Math.PI / 180 / 60, RAD = Math.PI / 180;
  function poly(c, t) {{ var v = 0; for (var i = c.length - 1; i >= 0; i--) v = v * t + c[i]; return v; }}
  function dpoly(c, t) {{ var v = 0; for (var i = c.length - 1; i >= 1; i--) v = v * t + i * c[i]; return v; }}
  function norm(v) {{ return Math.hypot(v[0], v[1], v[2]); }}
  function dot(a, b) {{ return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]; }}
  function unit(v) {{ var n = norm(v); return [v[0]/n, v[1]/n, v[2]/n]; }}
  // geometry for one observer, as a closure: mirrors element_geometry() in the generator
  function observer(lat, lon) {{
    var a = E.earth_a_km, f = E.earth_f, e2 = f * (2 - f), la = lat * RAD, lo = lon * RAD;
    var N = a / Math.sqrt(1 - e2 * Math.sin(la) * Math.sin(la));
    var r = [N * Math.cos(la) * Math.cos(lo), N * Math.cos(la) * Math.sin(lo), N * (1 - e2) * Math.sin(la)];
    var up = [Math.cos(la) * Math.cos(lo), Math.cos(la) * Math.sin(lo), Math.sin(la)];
    var wxr = [-OMEGA * r[1], OMEGA * r[0], 0];                  // omega x r, ITRS
    return function geom(m) {{
      var tau = m / HALF, th = E.era_rate_deg_per_min * m * RAD, c = Math.cos(th), s = Math.sin(th);
      // R(t) = Rz(th).R0 (GCRS->ITRS); we need its transpose applied to ITRS vectors
      var R = [c*R0[0] + s*R0[3], c*R0[1] + s*R0[4], c*R0[2] + s*R0[5],
               -s*R0[0] + c*R0[3], -s*R0[1] + c*R0[4], -s*R0[2] + c*R0[5], R0[6], R0[7], R0[8]];
      function toG(v) {{ return [R[0]*v[0] + R[3]*v[1] + R[6]*v[2], R[1]*v[0] + R[4]*v[1] + R[7]*v[2], R[2]*v[0] + R[5]*v[1] + R[8]*v[2]]; }}
      var obs = toG(r), upg = toG(up), vrot = toG(wxr);
      var eg = toG([-Math.sin(lo), Math.cos(lo), 0]), ng = toG([-Math.sin(la) * Math.cos(lo), -Math.sin(la) * Math.sin(lo), Math.cos(la)]);
      var vobs = [VE[0] + vrot[0], VE[1] + vrot[1], VE[2] + vrot[2]];
      function topo(coef) {{
        var P = [poly(coef[0], tau), poly(coef[1], tau), poly(coef[2], tau)];
        var v = [dpoly(coef[0], tau) / (HALF * 60) + VE[0], dpoly(coef[1], tau) / (HALF * 60) + VE[1], dpoly(coef[2], tau) / (HALF * 60) + VE[2]];
        var d = [P[0] - obs[0], P[1] - obs[1], P[2] - obs[2]], dist = norm(d), lt = dot(obs, d) / dist / C;
        d = [d[0] + v[0] * lt, d[1] + v[1] * lt, d[2] + v[2] * lt];
        var u = unit(d); u = unit([u[0] + vobs[0] / C, u[1] + vobs[1] / C, u[2] + vobs[2] / C]);
        return {{ u: u, dist: dist }};
      }}
      var M = topo(E.moon), S = topo(E.target), sun = [poly(E.sun[0], tau) - obs[0], poly(E.sun[1], tau) - obs[1], poly(E.sun[2], tau) - obs[2]];
      var sep = Math.acos(Math.max(-1, Math.min(1, dot(M.u, S.u)))) / RAD;
      var sdm = Math.asin(E.moon_radius_km / M.dist) / RAD, sdt = E.target_radius_km ? Math.asin(E.target_radius_km / S.dist) / RAD : 0;
      var ram = Math.atan2(M.u[1], M.u[0]), decm = Math.asin(M.u[2]), ras = Math.atan2(S.u[1], S.u[0]), decs = Math.asin(S.u[2]);
      var dra = ((ras - ram + 3 * Math.PI) % (2 * Math.PI)) - Math.PI;
      var azm = Math.atan2(dot(M.u, eg), dot(M.u, ng)) / RAD; if (azm < 0) azm += 360;
      return {{ sep: sep, sdm: sdm, sdt: sdt, mu: M.u, mdist: M.dist, altm: Math.asin(dot(M.u, upg)) / RAD, azm: azm, alts: Math.asin(dot(unit(sun), upg)) / RAD,
               east: dra * Math.cos(decm) / RAD * 60, north: (decs - decm) / RAD * 60 }};
    }};
  }}
  function state(g) {{ return g.sep < g.sdm - g.sdt ? 2 : (g.sep < g.sdm + g.sdt ? 1 : 0); }}
  function solve(lat, lon) {{
    var geom = observer(lat, lon), contacts = {{}}, prev = state(geom(-HALF)), best = null, m;
    for (m = -HALF + 0.5; m <= HALF; m += 0.5) {{
      var g = geom(m), cur = state(g);
      if (!best || g.sep < best.sep) {{ best = g; best.m = m; }}
      if (cur !== prev) {{
        var lo = m - 0.5, hi = m;
        for (var i = 0; i < 40; i++) {{ var mid = (lo + hi) / 2; if (state(geom(mid)) === prev) lo = mid; else hi = mid; }}
        var mc = (lo + hi) / 2;
        if (prev === 0 && cur >= 1) contacts.D1 = mc;
        if (prev <= 1 && cur === 2) contacts.D2 = mc;
        if (prev === 2 && cur <= 1) contacts.R1 = mc;
        if (prev >= 1 && cur === 0) contacts.R2 = mc;
        prev = cur;
      }}
    }}
    var keys = Object.keys(contacts), verdict;
    if (keys.length) {{ verdict = keys.some(function (k) {{ return geom(contacts[k]).altm > 0; }}) ? 'visible' : 'moon_down'; }}
    else verdict = best.altm > 0 ? 'miss' : 'moon_down';
    var ref = contacts.D2 !== undefined ? contacts.D2 : (contacts.D1 !== undefined ? contacts.D1 : best.m);
    return {{ geom: geom, contacts: contacts, closest: best, verdict: verdict, at: geom(ref), ref: ref,
             hidden: (contacts.D2 !== undefined && contacts.R1 !== undefined) ? contacts.R1 - contacts.D2 : null }};
  }}
  function localTime(m, secs) {{ return new Date(T0 + m * 60000).toLocaleTimeString('en-GB', {{ timeZone: D.tz, hour: '2-digit', minute: '2-digit', second: secs ? '2-digit' : undefined }}); }}
  function compass(az) {{ return ['N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSW','SW','WSW','W','WNW','NW','NNW'][Math.floor(((az + 11.25) % 360) / 22.5) % 16]; }}
  function lookText(g) {{ if (g.altm <= 0) return 'Moon below the horizon'; var h = g.altm < 15 ? ' (low)' : g.altm > 60 ? ' (high)' : ''; return g.altm.toFixed(0) + '° up' + h + ' in the ' + compass(g.azm) + ' · ' + skyText(g.alts); }}
  function skyText(a) {{ return a > 0 ? 'daylight, Sun ' + (a > 0 ? '+' : '') + a.toFixed(0) + '°' : a > -6 ? 'sunset twilight' : a > -12 ? 'dusk' : 'dark sky'; }}

  // ---- UI: one page-level location; chip + sheet, map, moon view and table all follow it ----
  var latI = document.getElementById('loc-lat'), lonI = document.getElementById('loc-lon'), res = document.getElementById('loc-result');
  var sel = document.getElementById('limb-city'), where = document.getElementById('limb-where'), pin = document.getElementById('pin');
  var chip = document.getElementById('loc-chip'), chipName = document.getElementById('chip-name'), chipSub = document.getElementById('chip-sub');
  var sheet = document.getElementById('loc-sheet'), P = D.proj, LOC = null;
  function fact(l, v, s) {{ return '<div class="fact"><div class="fact-label">' + l + '</div><div class="fact-value">' + v + '</div>' + (s ? '<div class="fact-sub">' + s + '</div>' : '') + '</div>'; }}
  function tableRow(r, label) {{
    var c = r.contacts;
    if (r.verdict === 'visible' || (r.verdict === 'moon_down' && Object.keys(c).length)) {{
      return '<tr class="yours"><td>' + label + '</td><td>' + (c.D2 !== undefined ? localTime(c.D2, true) : '—') + (c.D1 !== undefined ? '<small>from ' + localTime(c.D1, true) + '</small>' : '') +
        '</td><td>' + (c.R1 !== undefined ? localTime(c.R1, true) : '—') + (c.R2 !== undefined ? '<small>to ' + localTime(c.R2, true) + '</small>' : '') +
        '</td><td>' + (r.hidden !== null ? r.hidden.toFixed(0) + ' min' : '—') + '</td><td>' + lookText(r.at) + '</td></tr>';
    }}
    var gap = (r.closest.sep - r.closest.sdm) * 60;
    return '<tr class="yours"><td>' + label + '</td><td colspan="3">' + (r.verdict === 'miss' ? 'misses — ' + D.target + ' passes ' + gap.toFixed(1) + '′ from the limb at ' + localTime(r.closest.m, false) : 'Moon below the horizon') +
      '</td><td>' + lookText(r.closest) + '</td></tr>';
  }}
  function show(lat, lon, label, fromUrl) {{
    lat = +lat; lon = +lon; if (!isFinite(lat) || !isFinite(lon)) return;
    LOC = {{ lat: lat, lon: lon, label: label || '' }};
    latI.value = lat.toFixed(4); lonI.value = lon.toFixed(4);
    var r = solve(lat, lon), c = r.contacts, h = '', summary;
    if (r.verdict === 'visible' || (r.verdict === 'moon_down' && Object.keys(c).length)) {{
      h += fact(D.target + ' disappears', c.D2 !== undefined ? localTime(c.D2, true) : '—', c.D1 !== undefined && c.D2 !== undefined ? 'first touch ' + localTime(c.D1, true) : '');
      h += fact('reappears', c.R1 !== undefined ? localTime(c.R1, true) : '—', c.R1 !== undefined && c.R2 !== undefined ? 'fully out ' + localTime(c.R2, true) : '');
      h += fact('hidden', r.hidden !== null ? r.hidden.toFixed(1) + ' min' : '—');
      h += fact('Where to look', r.at.altm > 0 ? r.at.altm.toFixed(0) + '° up in the ' + compass(r.at.azm) : 'below the horizon', r.at.altm > 0 ? skyText(r.at.alts) + ' · at disappearance' : '');
      h += '<div class="verdict ' + r.verdict + '">' + (r.verdict === 'visible' ? 'Occultation visible from here (' + D.tzl + ').' : 'The Moon is below the horizon here during the occultation.') + '</div>';
      summary = r.verdict === 'visible' && c.D2 !== undefined && c.R1 !== undefined ? 'hidden ' + localTime(c.D2, false) + '–' + localTime(c.R1, false) : (r.verdict === 'visible' ? 'grazing partial' : 'Moon below horizon');
      if (r.verdict === 'visible' && c.D2 === undefined) h = h.replace('Occultation visible from here', 'Only part of ' + D.target + "'s disc is covered from here — a grazing partial");
    }} else {{
      var gap = r.closest.sep - r.closest.sdm;
      h += fact('closest approach', localTime(r.closest.m, false), (gap * 60).toFixed(1) + '′ outside the limb');
      h += fact('Where to look', r.closest.altm > 0 ? r.closest.altm.toFixed(0) + '° up in the ' + compass(r.closest.azm) : 'below the horizon', r.closest.altm > 0 ? skyText(r.closest.alts) : '');
      h += '<div class="verdict ' + r.verdict + '">' + (r.verdict === 'miss' ? D.target + ' passes ' + (gap * 60).toFixed(1) + '′ from the limb — a near miss from here.' : 'The Moon is below the horizon here.') + '</div>';
      summary = r.verdict === 'miss' ? 'near miss, ' + (gap * 60).toFixed(1) + '′' : 'Moon below horizon';
    }}
    res.innerHTML = h; res.hidden = false;
    var name = label || (lat.toFixed(3) + ', ' + lon.toFixed(3));
    chipName.textContent = name; chipSub.textContent = summary; where.textContent = name;
    var x = (lon - P.lon0) * P.k * P.s, y = (P.lat1 - lat) * P.s;
    if (x >= 0 && x <= P.W && y >= 0 && y <= P.H) {{ pin.setAttribute('transform', 'translate(' + x.toFixed(1) + ',' + y.toFixed(1) + ')'); pin.hidden = false; }} else pin.hidden = true;
    var old = document.querySelector('tr.yours'); if (old) old.remove();
    var tb = document.querySelector('#city-table tbody'); if (tb) tb.insertAdjacentHTML('afterbegin', tableRow(r, 'Your location · ' + name));
    if (!label) sel.value = '';
    if (!fromUrl) {{ var u = new URL(location.href); u.search = label ? '?city=' + encodeURIComponent(label) : '?lat=' + lat.toFixed(4) + '&lon=' + lon.toFixed(4); history.replaceState(null, '', u); }}
    drawLimb(r);
    if (typeof drawGraze === 'function') drawGraze(r);
  }}
  chip.addEventListener('click', function () {{ sheet.showModal(); }});
  sheet.addEventListener('click', function (e) {{ if (e.target === sheet) sheet.close(); }});
  document.getElementById('loc-go').addEventListener('click', function () {{ show(latI.value, lonI.value); sheet.close(); }});
  [latI, lonI].forEach(function (i) {{ i.addEventListener('keydown', function (e) {{ if (e.key === 'Enter') {{ e.preventDefault(); show(latI.value, lonI.value); sheet.close(); }} }}); }});
  var geoBtn = document.getElementById('loc-geo');
  if (!navigator.geolocation) geoBtn.hidden = true;
  geoBtn.addEventListener('click', function () {{
    geoBtn.disabled = true; geoBtn.textContent = 'Locating…';
    navigator.geolocation.getCurrentPosition(function (p) {{ geoBtn.disabled = false; geoBtn.textContent = 'Use my location'; show(p.coords.latitude, p.coords.longitude); sheet.close(); }},
      function () {{ geoBtn.disabled = false; geoBtn.textContent = 'Location unavailable'; }});
  }});
  sel.addEventListener('change', function () {{ var c = D.cities[sel.value]; if (c) {{ show(c[0], c[1], sel.value); sheet.close(); }} }});
  var map = document.getElementById('main-map');
  map.addEventListener('click', function (ev) {{
    var pt = map.createSVGPoint(); pt.x = ev.clientX; pt.y = ev.clientY;
    var q = pt.matrixTransform(map.getScreenCTM().inverse());
    var t = ev.target.closest && ev.target.closest('circle[data-city]');
    if (t) {{ var c = D.cities[t.dataset.city]; show(c[0], c[1], t.dataset.city); }}
    else show(P.lat1 - q.y / P.s, P.lon0 + q.x / (P.k * P.s));
  }});
  var links = document.querySelectorAll('.subnav-links a'), secs = [].map.call(links, function (a) {{ return document.getElementById(a.dataset.sec); }});
  if ('IntersectionObserver' in window) {{
    var io = new IntersectionObserver(function (es) {{
      es.forEach(function (e) {{ if (e.isIntersecting) links.forEach(function (a) {{ a.classList.toggle('active', a.dataset.sec === e.target.id); }}); }});
    }}, {{ rootMargin: '-40% 0px -55% 0px' }});
    secs.forEach(function (sc) {{ if (sc) io.observe(sc); }});
  }}

  // ---- graze profile: the target's track against the real lunar limb for THIS location ----
  var gzCard = document.getElementById('graze-card'), gzBtn = document.getElementById('graze-load'), gzSvg = document.getElementById('graze-svg'), gzOut = document.getElementById('graze-out');
  var LIMB = null, lastR = null;
  function rotMe(m) {{   // ICRF -> MOON_ME at t0 + m minutes: the Moon spins about its pole
    var th = LIMB.spin_deg_per_min * m * RAD, c = Math.cos(th), s = Math.sin(th), R0 = LIMB.R_me;
    return [c*R0[0] + s*R0[3], c*R0[1] + s*R0[4], c*R0[2] + s*R0[5], -s*R0[0] + c*R0[3], -s*R0[1] + c*R0[4], -s*R0[2] + c*R0[5], R0[6], R0[7], R0[8]];
  }}
  function limbKm(m, g) {{   // real limb radius excess (km) at the target's PA, for the observer's libration
    var R = rotMe(m), u = g.mu, o = [-(R[0]*u[0] + R[1]*u[1] + R[2]*u[2]), -(R[3]*u[0] + R[4]*u[1] + R[5]*u[2]), -(R[6]*u[0] + R[7]*u[1] + R[8]*u[2])];
    var lat = Math.asin(o[2]) / RAD, lon = Math.atan2(o[1], o[0]) / RAD;
    var dlat = lat - LIMB.sub_earth[0], dlon = ((lon - LIMB.sub_earth[1] + 540) % 360) - 180;
    var n = LIMB.nodes, h = (n - 1) / 2, fi = Math.max(0, Math.min(n - 1.0001, dlat / LIMB.node_step + h)), fj = Math.max(0, Math.min(n - 1.0001, dlon / LIMB.node_step + h));
    var i0 = Math.floor(fi), j0 = Math.floor(fj), a = fi - i0, b = fj - j0;
    var pa = ((Math.atan2(g.east, g.north) / RAD) + 360) % 360, k = pa / LIMB.pa_step, k0 = Math.floor(k) % 3600, k1 = (k0 + 1) % 3600, c = k - Math.floor(k);
    function P(i, j) {{ var p = LIMB.profiles[i][j]; return (p[k0] * (1 - c) + p[k1] * c) / 100; }}
    return (P(i0, j0) * (1-a) * (1-b) + P(i0+1, j0) * a * (1-b) + P(i0, j0+1) * (1-a) * b + P(i0+1, j0+1) * a * b);
  }}
  function drawGraze(r) {{
    lastR = r; if (!LIMB) return;
    var geom = r.geom, c = r.contacts, centers = [];
    if (c.D2 !== undefined || c.D1 !== undefined) centers.push({{ m: (c.D1 !== undefined ? c.D1 : c.D2), label: 'disappearance' }});
    if (c.R1 !== undefined || c.R2 !== undefined) centers.push({{ m: (c.R2 !== undefined ? c.R2 : c.R1), label: 'reappearance' }});
    if (!centers.length) centers.push({{ m: r.closest.m, label: 'closest approach' }});
    if (centers.length === 2 && centers[1].m - centers[0].m < 14) centers = [{{ m: (centers[0].m + centers[1].m) / 2, label: 'graze' }}];
    var g0c = geom(centers[0].m), tKm = Math.tan(g0c.sdt * RAD) * g0c.mdist;     // the target's radius, km at the Moon
    var W = 800, H = 230, pad = 34, HALF = 6, KM = Math.max(6, Math.ceil(tKm * 1.6 / 5) * 5), sy = (H - 2 * pad) / (2 * KM), kstep = KM > 10 ? 10 : 2;
    while (gzSvg.firstChild) gzSvg.removeChild(gzSvg.firstChild);
    var panels = centers.length, pw = W / panels, notes = [];
    centers.forEach(function (cen, pi) {{
      var gx = pi * pw, sxp = (pw - 2 * pad) / (2 * HALF);
      var terrain = [], star = [], top = [], bot = [], events = [], prevSt = null;
      function Y(v) {{ return Math.max(pad - 8, Math.min(H - pad + 8, H - pad - (v + KM) * sy)); }}
      for (var dm = -HALF; dm <= HALF; dm += 2 / 60) {{
        var m = cen.m + dm, g = geom(m), km = limbKm(m, g);
        var rt = Math.tan(g.sep * RAD) * g.mdist - 1737.4;          // target centre above the mean sphere, km
        var x = gx + pad + (dm + HALF) * sxp;
        terrain.push(x.toFixed(1) + ',' + Math.max(pad, Math.min(H - pad, H - pad - (km + KM) * sy)).toFixed(1));
        star.push(x.toFixed(1) + ',' + Y(rt).toFixed(1));
        if (tKm > 0.5) {{ top.push(x.toFixed(1) + ',' + Y(rt + tKm).toFixed(1)); bot.unshift(x.toFixed(1) + ',' + Y(rt - tKm).toFixed(1)); }}
        var st = rt + tKm < km ? 2 : (rt - tKm < km ? 1 : 0);        // 2 fully hidden, 1 partly, 0 clear
        if (prevSt !== null && st !== prevSt) events.push({{ m: m, from: prevSt, to: st }});
        prevSt = st;
      }}
      var g0 = el('rect', {{ x: gx + pad, y: pad, width: pw - 2 * pad, height: H - 2 * pad, class: 'gz-sky' }}); gzSvg.appendChild(g0);
      gzSvg.appendChild(el('polygon', {{ class: 'gz-terrain', points: terrain.join(' ') + ' ' + (gx + pw - pad).toFixed(1) + ',' + (H - pad) + ' ' + (gx + pad).toFixed(1) + ',' + (H - pad) }}));
      gzSvg.appendChild(el('line', {{ x1: gx + pad, x2: gx + pw - pad, y1: H - pad - KM * sy, y2: H - pad - KM * sy, class: 'gz-mean' }}));
      if (top.length) gzSvg.appendChild(el('polygon', {{ class: 'gz-disc', points: top.concat(bot).join(' ') }}));
      gzSvg.appendChild(el('polyline', {{ class: 'gz-star', points: star.join(' ') }}));
      for (var k = -KM; k <= KM; k += kstep) {{ var t = el('text', {{ x: gx + pad - 4, y: H - pad - (k + KM) * sy + 3, 'text-anchor': 'end', class: 'gz-lbl' }}); t.textContent = (k > 0 ? '+' : '') + k; gzSvg.appendChild(t); }}
      for (var mm = -HALF; mm <= HALF; mm += 2) {{ var t2 = el('text', {{ x: gx + pad + (mm + HALF) * sxp, y: H - pad + 14, 'text-anchor': 'middle', class: 'gz-lbl' }}); t2.textContent = localTime(cen.m + mm, false); gzSvg.appendChild(t2); }}
      var cap = el('text', {{ x: gx + pw / 2, y: pad - 10, 'text-anchor': 'middle', class: 'gz-cap' }}); cap.textContent = cen.label; gzSvg.appendChild(cap);
      events.forEach(function (e) {{
        var x = gx + pad + (e.m - cen.m + HALF) * sxp;
        gzSvg.appendChild(el('line', {{ x1: x, x2: x, y1: pad, y2: H - pad, class: 'gz-ev' }}));
        var nm = e.to > e.from ? (e.to === 2 ? 'D2' : 'D1') : (e.to === 0 ? 'R2' : 'R1');
        notes.push(nm + ' ' + localTime(e.m, true));
      }});
    }});
    // how much a step north moves the track on this chart
    var probe = solve(LOC.lat + 0.009, LOC.lon), m0 = centers[0].m, g1 = geom(m0), g2 = probe.geom(m0);
    var shift = (Math.tan(g2.sep * RAD) * g2.mdist - Math.tan(g1.sep * RAD) * g1.mdist);
    gzOut.textContent = (notes.length ? notes.join(' · ') + ' (' + D.tzl + ', real limb). ' : 'No contact with the real limb from here. ')
      + 'Moving 1 km north shifts the track by ' + (shift > 0 ? '+' : '') + shift.toFixed(2) + ' km on this chart.';
  }}
  gzBtn.addEventListener('click', function () {{
    gzBtn.disabled = true; gzBtn.textContent = 'Loading limb…';
    fetch(gzBtn.dataset.src).then(function (r) {{ return r.json(); }}).then(function (j) {{ LIMB = j; gzBtn.hidden = true; gzSvg.hidden = false; if (lastR) drawGraze(lastR); }})
      .catch(function () {{ gzBtn.disabled = false; gzBtn.textContent = 'Could not load the limb profile'; }});
  }});

  // ---- limb diagram ----
  var svg = document.getElementById('limb-svg'), slider = document.getElementById('limb-slider'), readout = document.getElementById('limb-readout');
  var NS = 'http://www.w3.org/2000/svg', RM = 150, track = null;
  function el(n, a, txt) {{ var e = document.createElementNS(NS, n); for (var k in a) e.setAttribute(k, a[k]); if (txt) e.textContent = txt; return e; }}
  function xy(g) {{ return {{ x: -g.east / g.sdm / 60 * RM, y: -g.north / g.sdm / 60 * RM }}; }}
  function craterPath(m) {{   // IAU crater rims projected with the event's libration + pole angle; north up, east left
    if (!D.lib || !D.craters) return '';
    var L = D.lib, x = (m - L.t0_offset_min) / L.step_min, n = L.samples.length, DG = Math.PI / 180;
    var k0 = Math.max(0, Math.min(n - 2, Math.floor(x))), f = Math.max(0, Math.min(1, x - k0));
    function lerp(a, b, wrap) {{ var dd = b - a; if (wrap) dd = ((dd + 540) % 360) - 180; return a + dd * f; }}
    var A = L.samples[k0], B = L.samples[k0 + 1];
    var la0 = lerp(A[0], B[0]) * DG, lo0 = lerp(A[1], B[1], true) * DG, P = lerp(A[2], B[2], true) * DG, cP = Math.cos(P), sP = Math.sin(P);
    var E0 = [-Math.sin(lo0), Math.cos(lo0), 0], N0 = [-Math.sin(la0) * Math.cos(lo0), -Math.sin(la0) * Math.sin(lo0), Math.cos(la0)];
    var U0 = [Math.cos(la0) * Math.cos(lo0), Math.cos(la0) * Math.sin(lo0), Math.sin(la0)], d = [];
    D.craters.forEach(function (c) {{
      var la = c[0] * DG, lo = c[1] * DG, a = c[2] / 2 / 1737.4, ca = Math.cos(a), sa = Math.sin(a);
      var C = [Math.cos(la) * Math.cos(lo), Math.cos(la) * Math.sin(lo), Math.sin(la)];
      if (dot(C, U0) < -sa) return;
      var U = [-Math.sin(lo), Math.cos(lo), 0], W = [-Math.sin(la) * Math.cos(lo), -Math.sin(la) * Math.sin(lo), Math.cos(la)], pen = false;
      for (var k = 0; k <= 28; k++) {{
        var t = k / 28 * 2 * Math.PI, ct = Math.cos(t) * sa, st = Math.sin(t) * sa;
        var v = [C[0] * ca + U[0] * ct + W[0] * st, C[1] * ca + U[1] * ct + W[1] * st, C[2] * ca + U[2] * ct + W[2] * st];
        if (dot(v, U0) <= 0) {{ pen = false; continue; }}
        var xi = dot(v, E0), eta = dot(v, N0), no = eta * cP + xi * sP, ea = eta * sP - xi * cP;
        d.push((pen ? 'L' : 'M') + (-ea * RM).toFixed(1) + ' ' + (-no * RM).toFixed(1)); pen = true;
      }}
    }});
    return d.join('');
  }}
  function drawLimb(r) {{
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    var mid = (r.contacts.D2 !== undefined && r.contacts.R1 !== undefined) ? (r.contacts.D2 + r.contacts.R1) / 2 : r.ref;
    track = {{ geom: r.geom, m0: mid - 80, span: 160, r: r }};
    slider.max = track.span; slider.value = 80;
    var k = D.illum, b = RM * Math.abs(2 * k - 1), sweep = k > 0.5 ? 1 : 0, cd = craterPath(mid);
    var litT = 'rotate(' + (-D.bright_pa) + ')', litD = 'M ' + (-RM) + ' 0 A ' + RM + ' ' + RM + ' 0 0 1 ' + RM + ' 0 A ' + RM + ' ' + b + ' 0 0 ' + sweep + ' ' + (-RM) + ' 0 Z';
    svg.appendChild(el('circle', {{ class: 'disc-dark', r: RM }}));
    if (cd) svg.appendChild(el('path', {{ class: 'crater crater-night', d: cd }}));
    svg.appendChild(el('path', {{ class: 'disc-bright', transform: litT, d: litD }}));
    if (cd) {{
      var defs = el('defs', {{}}), clip = el('clipPath', {{ id: 'lit-clip' }});
      clip.appendChild(el('path', {{ transform: litT, d: litD }})); defs.appendChild(clip); svg.appendChild(defs);
      svg.appendChild(el('path', {{ class: 'crater crater-day', d: cd, 'clip-path': 'url(#lit-clip)' }}));
    }}
    svg.appendChild(el('circle', {{ class: 'disc-edge', r: RM }}));
    svg.appendChild(el('text', {{ class: 'lbl', x: 0, y: -RM - 8, 'text-anchor': 'middle' }}, 'N'));
    svg.appendChild(el('text', {{ class: 'lbl', x: -RM - 8, y: 4, 'text-anchor': 'end' }}, 'E'));
    var pts = [];
    for (var m = 0; m <= track.span; m += 2) {{ var p = xy(r.geom(track.m0 + m)); pts.push(p.x.toFixed(1) + ',' + p.y.toFixed(1)); }}
    svg.appendChild(el('polyline', {{ class: 'track', points: pts.join(' ') }}));
    ['D1', 'D2', 'R1', 'R2'].forEach(function (kk) {{
      if (r.contacts[kk] === undefined) return;
      var p = xy(r.geom(r.contacts[kk]));
      svg.appendChild(el('circle', {{ class: 'contact', cx: p.x, cy: p.y, r: 3 }}));
      if (kk === 'D2' || kk === 'R1')
        svg.appendChild(el('text', {{ class: 'lbl', x: p.x + (kk[0] === 'D' ? 6 : -6), y: p.y - 6, 'text-anchor': kk[0] === 'D' ? 'start' : 'end' }}, kk[0] + ' ' + localTime(r.contacts[kk], true)));
    }});
    if (r.verdict !== 'visible') svg.appendChild(el('text', {{ class: 'miss-note', x: 0, y: RM + 28, 'text-anchor': 'middle' }},
      r.verdict === 'miss' ? D.target + ' passes outside the limb from here' : 'Moon below the horizon here'));
    var sdt = r.at.sdt, sdm = r.at.sdm;
    svg.appendChild(el('circle', {{ id: 'limb-target', class: 'target', r: Math.max(2.5, sdt / sdm * RM) }}));
    update();
  }}
  function update() {{
    if (!track) return;
    var m = track.m0 + (+slider.value), g = track.geom(m), p = xy(g), t = document.getElementById('limb-target');
    t.setAttribute('cx', p.x); t.setAttribute('cy', p.y);
    t.style.opacity = g.sep < g.sdm - g.sdt ? 0.25 : 1;
    readout.textContent = localTime(m, true) + ' ' + D.tzl + ' · Moon ' + (g.altm > 0 ? g.altm.toFixed(0) + '° up, ' + compass(g.azm) : 'below horizon');
  }}
  slider.addEventListener('input', update);
  var qs = new URLSearchParams(location.search), qc = qs.get('city');
  if (qc && D.cities[qc]) show(D.cities[qc][0], D.cities[qc][1], qc, true);
  else if (qs.get('lat') && qs.get('lon')) show(qs.get('lat'), qs.get('lon'), '', true);
  else {{ var first = sel.options[1]; if (first) {{ var c0 = D.cities[first.value]; show(c0[0], c0[1], first.value, true); }} }}
}})();

</script>
</body>
</html>
"""
    out = OUT / f"{slug}.html"
    out.write_text(page)
    write_geo_files(slug, data, tz, tzl)
    (OUT / "data").mkdir(exist_ok=True)
    (OUT / "data" / f"{slug}.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    limb_src = ROOT / "data" / f"{slug}-limb.json"
    if limb_src.exists():
        (OUT / "data" / f"{slug}-limb.json").write_bytes(limb_src.read_bytes())
    print(f"wrote site/{slug}.html ({out.stat().st_size // 1024} KB): {len(vis)} visible / {len(misses)} miss / "
          f"{len(cities) - len(vis) - len(misses)} moon-down cities")
    return {"slug": slug, "title": title, "day": day, "note": entry.get("note") or auto_note,
            "kind": kind, "target": tname, "end_utc": (last_r or parse(g["t_min"])).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "audience": aud["label"], "when": t_min_local, "generated": data["generated"][:10]}


INDEX_CSS = """
    :root { --t-occ: #b45309; --t-ms: #0e7490; --t-jup: #6d28d9; --t-sat: #047857; }
    @media (prefers-color-scheme: dark) { :root { --t-occ: #fbbf24; --t-ms: #67c9e6; --t-jup: #c4b5fd; --t-sat: #34d399; } }
    .t-occ { --tc: var(--t-occ); } .t-ms { --tc: var(--t-ms); } .t-jup { --tc: var(--t-jup); } .t-sat { --tc: var(--t-sat); }
    .home-h1 { margin-bottom: 0.3rem; }
    .typenav { display: flex; flex-wrap: wrap; gap: 0.4rem; margin: 1rem 0 0.2rem; }
    .typenav a { display: inline-flex; align-items: center; gap: 0.4rem; border: 1px solid var(--line); border-radius: 999px;
                 padding: 0.25rem 0.75rem 0.25rem 0.4rem; font-size: 0.85rem; color: var(--text); background: var(--card); }
    .typenav a:hover { border-color: var(--tc); text-decoration: none; }
    .typenav svg { width: 22px; height: 22px; color: var(--tc); flex: none; }
    .upnext { display: grid; grid-template-columns: repeat(auto-fit, minmax(185px, 1fr)); gap: 0.6rem; margin: 0.5rem 0 0.5rem; }
    .tile { display: grid; grid-template-columns: 38px 1fr; gap: 0.1rem 0.7rem; align-items: start; background: var(--card);
            border: 1px solid var(--border); border-top: 3px solid var(--tc); border-radius: 12px; padding: 0.75rem 0.85rem; color: var(--text); }
    .tile:hover { text-decoration: none; border-color: var(--tc); }
    .tile svg { width: 38px; height: 38px; color: var(--tc); grid-row: span 3; }
    .tile-kicker { font-size: 0.68rem; letter-spacing: 0.07em; text-transform: uppercase; color: var(--tc); font-weight: 700; }
    .tile-title { font-weight: 700; font-size: 1.02rem; letter-spacing: -0.01em; line-height: 1.25; }
    .tile-detail { color: var(--muted); font-size: 0.8rem; line-height: 1.35; margin-top: 0.1rem; }
    .kind { margin: 2.4rem 0 0; padding-top: 1.3rem; border-top: 1px solid var(--border); scroll-margin-top: 12px; }
    .kind-head { display: grid; grid-template-columns: 54px 1fr; gap: 0.2rem 0.9rem; align-items: start; }
    .kind-head svg { width: 54px; height: 54px; color: var(--tc); grid-row: span 3; }
    .kind-head h2 { margin: 0; font-size: 1.4rem; letter-spacing: -0.02em; text-transform: none; color: var(--text); }
    .kind-what { margin: 0.15rem 0 0; }
    .kind-facts { display: flex; flex-wrap: wrap; gap: 0.25rem 1.1rem; margin: 0.35rem 0 0; padding: 0; list-style: none; font-size: 0.82rem; color: var(--muted); }
    .kind-facts b { color: var(--tc); font-weight: 600; }
    .evlist { list-style: none; margin: 1rem 0 0; border: 1px solid var(--border); border-left: 3px solid var(--tc); border-radius: 12px; background: var(--card); overflow: hidden; padding: 0; }
    .evlist li + li { border-top: 1px solid var(--border); }
    .evlist .ev a { display: grid; grid-template-columns: 4.2rem 1fr auto; gap: 0.1rem 0.9rem; align-items: center; padding: 0.6rem 0.9rem; color: var(--text); }
    .evlist .ev a:hover { background: var(--card-2); text-decoration: none; }
    .ev-date { display: flex; flex-direction: column; line-height: 1.15; }
    .ev-dmy { font-weight: 700; font-size: 1rem; font-variant-numeric: tabular-nums; }
    .ev-y { font-size: 0.72rem; color: var(--muted); }
    .ev-what { font-weight: 600; display: block; }
    .ev-note { color: var(--muted); font-size: 0.82rem; display: block; margin-top: 0.1rem; }
    .tags { display: flex; flex-direction: column; align-items: flex-end; gap: 0.2rem; }
    .tag { display: inline-block; font-size: 0.66rem; letter-spacing: 0.05em; text-transform: uppercase; border: 1px solid var(--line); border-radius: 999px; padding: 0 0.45rem; color: var(--muted); }
    .tag-planet { border-color: var(--tc); color: var(--tc); }
    .ev.past a { opacity: 0.45; }
    .ev-more { margin: 0.6rem 0 0; }
    @media (max-width: 560px) { .evlist .ev a { grid-template-columns: 3.6rem 1fr; } .tags { grid-column: 2; flex-direction: row; align-items: center; } .ev-note { display: none; } }
    .this-month { margin: 1rem 0 0; font-size: 0.92rem; }
    .this-month a { font-weight: 600; }
    .yrs { margin: 0.8rem 0 0; display: grid; gap: 0.4rem; }
    .yr { display: grid; grid-template-columns: 2.8rem 1fr; align-items: center; gap: 0.5rem; }
    .yr-label { font-size: 0.8rem; color: var(--muted); font-weight: 600; font-variant-numeric: tabular-nums; }
    .mpills { list-style: none; display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 4px; margin: 0; padding: 0; }
    .mpills a, .mpills span { display: block; text-align: center; font-size: 0.78rem; padding: 0.35rem 0; border-radius: 8px; }
    .mpills a { background: var(--card); border: 1px solid var(--border); color: var(--text); }
    .mpills a:hover { border-color: var(--tc); text-decoration: none; }
    .mpills span { color: var(--line); opacity: 0.6; }
    .mo.current a { background: color-mix(in srgb, var(--tc) 20%, var(--card)); border-color: var(--tc); font-weight: 700; }
    .mo.past a { opacity: 0.45; }
    @media (max-width: 560px) { .mpills { grid-template-columns: repeat(6, minmax(0, 1fr)); } }
"""

ICONS = {
    # the Moon with a planet at its edge
    "occ": '<svg viewBox="0 0 40 40" aria-hidden="true"><circle cx="17" cy="21" r="13" fill="currentColor" opacity=".22"/>'
           '<circle cx="17" cy="21" r="13" fill="none" stroke="currentColor" stroke-width="1.6"/><circle cx="30.5" cy="13" r="4" fill="currentColor"/></svg>',
    # a crescent and stars
    "ms": '<svg viewBox="0 0 40 40" aria-hidden="true"><path d="M21 6a14 14 0 1 0 12.2 20.8A11.5 11.5 0 1 1 21 6z" fill="currentColor"/>'
          '<circle cx="31" cy="9" r="1.7" fill="currentColor"/><circle cx="36" cy="17" r="1.2" fill="currentColor"/><circle cx="27" cy="15.5" r="1" fill="currentColor"/></svg>',
    # Jupiter and its four moons
    "jup": '<svg viewBox="0 0 40 40" aria-hidden="true"><circle cx="20" cy="20" r="8.5" fill="currentColor"/>'
           '<path d="M12.2 17.2h15.6M11.6 21.4h16.8" stroke="var(--card)" stroke-width="1.4"/>'
           '<circle cx="3.5" cy="20" r="1.7" fill="currentColor"/><circle cx="8.5" cy="20" r="1.4" fill="currentColor"/>'
           '<circle cx="31.5" cy="20" r="1.5" fill="currentColor"/><circle cx="37" cy="20" r="1.7" fill="currentColor"/></svg>',
    # Saturn, rings nearly edge-on, a moon
    "sat": '<svg viewBox="0 0 40 40" aria-hidden="true"><ellipse cx="20" cy="20" rx="17" ry="4.2" fill="none" stroke="currentColor" stroke-width="1.6"/>'
           '<circle cx="20" cy="20" r="7.5" fill="currentColor"/><path d="M3 20a17 4.2 0 0 0 34 0" fill="none" stroke="currentColor" stroke-width="1.6"/>'
           '<circle cx="34" cy="10" r="1.8" fill="currentColor"/></svg>',
}

KINDS = [
    ("occ", "occultations", "Lunar occultations", "Occultations",
     "The Moon passes in front of a planet or a bright star. Only a band of the Earth sees it, and the times change from city to city.",
     [("You need", "your eyes or binoculars"), ("How often", "a few a year"), ("Each page", "a map of where it's seen and times for 500 cities")]),
    ("ms", "moon-stars", "The Moon and the stars", "Moon & stars",
     "Every night the Moon slides over fainter stars. A star doesn't fade — it switches off at one edge and back on at the other. Computed for your own place.",
     [("You need", "binoculars or a small telescope"), ("How often", "about one a night"), ("Each page", "a month calendar and every event for your location")]),
    ("jup", "jupiter", "Jupiter's moons", "Jupiter",
     "Io, Europa, Ganymede and Callisto slip behind Jupiter, into its shadow and across its face — and the Great Red Spot turns to face us every ten hours.",
     [("You need", "any small telescope"), ("How often", "most nights"), ("Each page", "a month of events and a live diagram of the moons")]),
    ("sat", "saturn", "Saturn's moons", "Saturn",
     "Titan, Rhea, Dione and Tethys cross Saturn's face and fall into its shadow — possible only in the few years around the 2025 ring-plane crossing.",
     [("You need", "a telescope, 100 mm or more"), ("How often", "most nights while the season lasts"), ("Each page", "a month of events and a live diagram")]),
]

INDEX_JS = r"""
(function () {
  var now = Date.now(), ym = new Date().toISOString().slice(0, 7);
  // occultations: upcoming first by the READER's clock, past last and dimmed, first five shown
  var list = document.getElementById('evlist');
  if (list) {
    var items = [].slice.call(list.querySelectorAll('li.ev')), up = [], past = [];
    items.forEach(function (li) { var p = Date.parse(li.dataset.end) < now; li.classList.toggle('past', p); (p ? past : up).push(li); });
    up.concat(past.reverse()).forEach(function (li) { list.appendChild(li); });
    var SHOW = 5, more = document.getElementById('ev-more');
    list.querySelectorAll('li.ev').forEach(function (li, i) { li.hidden = i >= SHOW; });
    if (more) {
      if (items.length <= SHOW) more.hidden = true;
      more.textContent = 'Show all ' + items.length + ' events' + (past.length ? ' (' + past.length + ' past)' : '');
      more.addEventListener('click', function () { list.querySelectorAll('li.ev').forEach(function (li) { li.hidden = false; }); more.hidden = true; });
    }
    var t = document.getElementById('tile-occ');
    if (t && up[0]) {
      t.setAttribute('href', up[0].querySelector('a').getAttribute('href'));
      t.querySelector('.tile-title').textContent = up[0].querySelector('.ev-what').textContent;
      t.querySelector('.tile-detail').textContent = up[0].dataset.detail;
    }
  }
  // month links: this month highlighted, earlier months dimmed; tiles follow this month
  document.querySelectorAll('.mo').forEach(function (li) { if (li.dataset.ym === ym) li.classList.add('current'); else if (li.dataset.ym < ym) li.classList.add('past'); });
  ['ms', 'jup', 'sat'].forEach(function (k) {
    var tile = document.getElementById('tile-' + k), pill = document.querySelector('#kind-' + k + ' .mo[data-ym="' + ym + '"]');
    if (!tile || !pill || tile.dataset.ym === ym) return;
    tile.setAttribute('href', pill.querySelector('a').getAttribute('href'));
    tile.querySelector('.tile-title').textContent = pill.dataset.label;
    tile.querySelector('.tile-detail').textContent = pill.dataset.detail;
    var tm = document.querySelector('#kind-' + k + ' .this-month');
    if (tm) tm.innerHTML = 'This month: <a href="' + pill.querySelector('a').getAttribute('href') + '">' + pill.dataset.label + '</a> — ' + pill.dataset.detail;
  });
})();
"""


def build_index(seed, built, jup=(), ms=()):
    """The front door: a 'coming up' tile for each kind of event, then one section per kind, each saying
    what it is, what you need and how often, with its own colour and icon. Clock-dependent choices (next
    occultation, this month) are prerendered from the build date and corrected by the reader's clock."""
    built = sorted(built, key=lambda b: b["when"])
    now = datetime.now(timezone.utc)
    ym_now = now.strftime("%Y-%m")
    MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    kinds = {k[0]: k for k in KINDS}

    # ---------------- per-kind month entries: (ym, slug, label, detail)
    def monthly(entries, detail):
        return [(f"{e['year']}-{e['month']:02d}", e["slug"], e["label"], detail(e)) for e in entries]
    months = {
        "ms": monthly(ms, lambda e: f"{e['n']} occultations on {e.get('nights', '?')} nights from New Delhi with a small telescope"),
        "jup": monthly([j for j in jup if j.get("planet", "jupiter") == "jupiter"],
                       lambda e: f"{e['n']} events" + (f" · {e['n_mutual']} mutual" if e["n_mutual"] else "")),
        "sat": monthly([j for j in jup if j.get("planet") == "saturn"],
                       lambda e: f"{e['n']} events" + (f" · {e['n_mutual']} mutual" if e["n_mutual"] else "")),
    }

    def current(entries):
        return next((m for m in entries if m[0] >= ym_now), entries[-1] if entries else None)

    def year_rows(entries):
        by_year = {}
        for ymk, slug, label, detail in entries:
            by_year.setdefault(int(ymk[:4]), {})[int(ymk[5:])] = (ymk, slug, label, detail)
        out = []
        for y in sorted(by_year):
            cells = []
            for mo in range(1, 13):
                e = by_year[y].get(mo)
                if e:
                    cells.append(f'<li class="mo" data-ym="{e[0]}" data-label="{esc(e[2])}" data-detail="{esc(e[3])}">'
                                 f'<a href="/{e[1]}" title="{esc(e[2])}: {esc(e[3])}">{MON[mo - 1]}</a></li>')
                else:
                    cells.append(f'<li aria-hidden="true"><span>{MON[mo - 1]}</span></li>')
            out.append(f'<div class="yr"><span class="yr-label">{y}</span><ul class="mpills">{"".join(cells)}</ul></div>')
        return f'<div class="yrs">{"".join(out)}</div>'

    # ---------------- occultation rows
    def row(b, past):
        w = b["when"]
        detail = f"{w.strftime('%a %-d %b %Y')} · {b['audience']}"
        tags = (f'<span class="tags"><span class="tag tag-{b["kind"]}">{b["kind"]}</span>'
                f'<span class="tag">{esc(b["audience"])}</span></span>')
        return (f'<li class="ev{" past" if past else ""}" data-end="{b["end_utc"]}" data-detail="{esc(detail)}">'
                f'<a href="/{b["slug"]}"><span class="ev-date"><span class="ev-dmy">{w.strftime("%-d %b")}</span>'
                f'<span class="ev-y">{w.strftime("%a %Y")}</span></span>'
                f'<span class="ev-body"><span class="ev-what">The Moon occults {esc(b["target"])}</span>'
                f'<span class="ev-note">{esc(b["note"])}</span></span>{tags}</a></li>')

    upcoming = [b for b in built if parse(b["end_utc"]) >= now]
    past = [b for b in built if parse(b["end_utc"]) < now]
    rows = "".join(row(b, False) for b in upcoming) + "".join(row(b, True) for b in reversed(past))
    nxt = upcoming[0] if upcoming else (built[-1] if built else None)

    # ---------------- tiles
    tiles = []
    if nxt:
        tiles.append(f'<a class="tile t-occ" id="tile-occ" href="/{nxt["slug"]}">{ICONS["occ"]}'
                     f'<span class="tile-kicker">Next lunar occultation</span>'
                     f'<span class="tile-title">The Moon occults {esc(nxt["target"])}</span>'
                     f'<span class="tile-detail">{esc(nxt["when"].strftime("%a %-d %b %Y"))} · {esc(nxt["audience"])}</span></a>')
    for k, kicker in (("ms", "Moon & stars · this month"), ("jup", "Jupiter's moons · this month"), ("sat", "Saturn's moons · this month")):
        cur = current(months[k])
        if cur:
            tiles.append(f'<a class="tile t-{k}" id="tile-{k}" href="/{cur[1]}" data-ym="{cur[0]}">{ICONS[k]}'
                         f'<span class="tile-kicker">{kicker}</span><span class="tile-title">{esc(cur[2])}</span>'
                         f'<span class="tile-detail">{esc(cur[3])}</span></a>')

    # ---------------- sections
    def section(k, body):
        _, anchor, name, _, what, facts = kinds[k]
        facts_html = "".join(f"<li><b>{esc(a)}</b> {esc(b)}</li>" for a, b in facts)
        return (f'<section class="kind t-{k}" id="kind-{k}"><a id="{anchor}"></a><header class="kind-head">{ICONS[k]}'
                f'<h2>{esc(name)}</h2><p class="kind-what">{esc(what)}</p><ul class="kind-facts">{facts_html}</ul></header>{body}</section>')

    sections = []
    if built:
        sections.append(section("occ", f'<ul class="evlist" id="evlist">{rows}</ul>'
                                       f'<p class="ev-more"><button class="btn" id="ev-more" type="button">Show all events</button></p>'))
    for k in ("ms", "jup", "sat"):
        if months[k]:
            cur = current(months[k])
            sections.append(section(k, f'<p class="this-month">This month: <a href="/{cur[1]}">{esc(cur[2])}</a> — {esc(cur[3])}</p>'
                                       + year_rows(months[k])))

    nav = "".join(f'<a class="t-{k[0]}" href="#{k[1]}">{ICONS[k[0]]}{esc(k[3])}</a>' for k in KINDS if (k[0] == "occ" and built) or months.get(k[0]))
    desc = ("Lunar occultations of planets and stars, and the eclipses, transits and mutual events of Jupiter's and Saturn's "
            "moons — where on Earth they can be seen and when, computed from JPL ephemerides.")
    page = head(f"{SITE_NAME} — {TAGLINE}", desc, "/", extra=f"<style>{INDEX_CSS}</style>") + f"""
<main class="wrap">
  <h1 class="home-h1">What passes in front of what — and when you can see it</h1>
  <p class="sub">Four kinds of sky events, computed from JPL ephemerides for where you are.</p>
  <nav class="typenav" aria-label="Kinds of event">{nav}</nav>
  <h2>Coming up</h2>
  <div class="upnext">{"".join(tiles)}</div>
  <p style="margin:0.7rem 0 0"><a href="/calendar">Get the occultations your city can see in your calendar →</a></p>
  {"".join(sections)}
  <section class="kind" id="method"><h2>How these are made</h2>
  <p class="method">Every time, line and diagram here is computed, not copied: planets, the Moon and the Sun from the JPL DE431
  ephemeris, Jupiter's and Saturn's moons from JPL's satellite ephemerides, stars from Gaia DR3 and Hipparcos-2, and the
  Moon's mountains from NASA's LRO laser altimeter. The lunar-occultation list is chosen by hand; each page links the data it
  was built from.</p></section>
</main>
{FOOTER}
<script>{INDEX_JS}</script>
</body>
</html>
"""
    (OUT / "index.html").write_text(page)
    urls = [("/", "weekly", "1.0"), ("/calendar", "monthly", "0.7")] + [(f"/{b['slug']}", "weekly", "0.8") for b in built] + [(f"/{j['slug']}", "monthly", "0.6") for j in jup] + [(f"/{m['slug']}", "monthly", "0.6") for m in ms]
    sm = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for path, freq, pri in urls:
        sm.append(f"  <url><loc>{SITE}{path}</loc><changefreq>{freq}</changefreq><priority>{pri}</priority></url>")
    sm.append("</urlset>\n")
    (OUT / "sitemap.xml").write_text("\n".join(sm))
    (OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n")
    # Cloudflare Pages: unhashed text stays short-lived; KML/GPX download; images long-lived (URLs carry ?v= hashes)
    (OUT / "_headers").write_text("/*\n  Cache-Control: public, max-age=3600\n/data/*\n  Cache-Control: public, max-age=86400\n"
                                  "/kml/*\n  Cache-Control: public, max-age=86400\n  Content-Disposition: attachment\n"
                                  "/img/*\n  Cache-Control: public, max-age=2592000\n"
                                  "/ics/*\n  Cache-Control: public, max-age=21600\n  Content-Type: text/calendar; charset=utf-8\n")
    (OUT / "404.html").write_text(head(f"Not found · {SITE_NAME}", "No such page.", "/404") + f"""
<main class="wrap"><h1>No such page</h1><p class="sub">Nothing is occulted here.</p>
<p><a href="/">All events</a></p></main>{FOOTER}</body></html>
""")
    print(f"wrote site/index.html, sitemap.xml ({len(urls)} urls), robots.txt, _headers, 404.html")


if __name__ == "__main__":
    import build_feeds
    import build_jupiter
    import build_moonstars
    seed = json.loads((ROOT / "seed.json").read_text())
    OUT.mkdir(exist_ok=True)
    built = [build(seed, e["slug"]) for e in seed["events"]]
    # every city any event page knows: the diary pages' location sheet and one calendar feed each
    cities_sorted = build_feeds.collect_cities(seed)
    jup = build_jupiter.build_all(cities_sorted, "jupiter") + build_jupiter.build_all(cities_sorted, "saturn")
    ms = build_moonstars.build_all(cities_sorted)
    build_feeds.build_all(seed, cities_sorted)
    build_index(seed, built, jup, ms)
