#!/usr/bin/env python3
"""Build site/ — the whole static site — from seed + data + geo.

    data/<slug>.json    (kaalshodh: api/lookup/generate/occultation_event.py, DE431)
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
    out.append(f'<path class="land" d="{p.path_lonlat(geo["land"])}"/>')
    if geo.get("borders"):
        out.append(f'<path class="border" d="{p.path_lonlat(geo["borders"], close=False)}"/>')
    out.append(f'<path class="region" fill-rule="evenodd" d="{p.path(m["region"])}"/>')
    if m["region_night"]:
        out.append(f'<path class="night" fill-rule="evenodd" d="{p.path(m["region_night"])}"/>')
    for lim in m["limits"]:
        out.append(f'<path class="limit limit-{lim["kind"]}" d="{p.path([lim["points"]], close=False)}"/>')
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
    out.append("</svg>")
    return "\n".join(out)


# ── text helpers ───────────────────────────────────────────────────────────

def t_local(iso, tz, fmt="%H:%M:%S"):
    return parse(iso).astimezone(tz).strftime(fmt)


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
                f'<td>{d}{d1}</td><td>{r}{r2}</td><td>{hid}</td>'
                f'<td>{c["moon_alt"]:+.0f}°</td><td>{esc(sky_text(c["sun_alt"]))}</td></tr>')
    if c["verdict"] == "miss":
        gap = c["sep_arcmin"] - c["moon_sd_arcmin"]
        when = t_local(c["closest"], tz, "%H:%M") if c.get("closest") else ""
        return (f'<tr class="v-miss" data-lat="{c["lat"]}" data-lon="{c["lon"]}"><td>{name}</td>'
                f'<td colspan="3">misses — {esc(tname)} passes {gap:.1f}′ from the limb at {when}</td>'
                f'<td>{c["moon_alt"]:+.0f}°</td><td>{esc(sky_text(c["sun_alt"]))}</td></tr>')
    return (f'<tr class="v-down" data-lat="{c["lat"]}" data-lon="{c["lon"]}"><td>{name}</td>'
            f'<td colspan="5">Moon below the horizon</td></tr>')


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
    .limb-svg .track { fill: none; stroke: var(--accent); stroke-width: 1.5; stroke-dasharray: 4 3; }
    .limb-svg .track-hidden { fill: none; stroke: var(--accent); stroke-width: 1.5; opacity: 0.35; }
    .limb-svg .contact { fill: var(--c-limit); }
    .limb-svg .target { fill: #fff; stroke: var(--accent); stroke-width: 1.2; }
    .limb-svg .lbl { font: 500 10px -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif; fill: var(--muted); }
    .limb-svg .miss-note { font: 500 11px -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif; fill: var(--c-miss); }
    input[type=range] { width: 100%; accent-color: var(--accent); }
    .event-list { list-style: none; display: grid; gap: 0.7rem; margin: 0.6rem 0; }
    .event-card { display: block; background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 1rem 1.1rem; color: var(--text); }
    .event-card:hover { border-color: var(--accent); text-decoration: none; }
    .event-card .when { color: var(--muted); font-size: 0.85rem; }
    .event-card .what { font-size: 1.2rem; font-weight: 700; letter-spacing: -0.01em; margin: 0.15rem 0; }
    .event-card .note { color: var(--muted); font-size: 0.92rem; }
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
  basic analytics. <a href="https://alokm.com/">Alok Mandavgane</a>.</p>
</footer>
"""


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
    featured = [n for n in aud["featured"] if any(c["name"] == n for c in cities)]
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
        limit_para = (f"<p>The gold line is the <strong>north limit</strong>: along it {tname} grazes the Moon's "
                      f"northern edge. North of the line it is a near miss — from {esc(near_miss['name'])} {tname} "
                      f"passes just {gap:.1f}′ outside the limb — and a graze seen from right on the line, {tname} "
                      f"blinking in and out behind lunar mountains, is the finest view of all.</p>")
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

    limb = {
        "tz": aud["tz"], "tzl": tzl, "target": tname, "kind": kind,
        "target_sd": round(g["target_sd_arcsec"] / 60, 3),
        "illum": g["illum_pct"] / 100, "bright_pa": g["bright_limb_pa"],
        "cities": {c["name"]: {**c["track"], "contacts": c.get("contacts", {}), "verdict": c["verdict"]}
                   for c in cities if c.get("track")},
    }
    limb_order = [c["name"] for c in feat_rows if c.get("track")] + \
                 [c["name"] for c in rest_rows if c.get("track")]
    limb_options = "".join(f'<option value="{esc(n)}">{esc(n)}</option>' for n in limb_order)

    def fact(label, value, sub=""):
        return (f'<div class="fact"><div class="fact-label">{label}</div><div class="fact-value">{value}</div>'
                f'{f"<div class=fact-sub>{sub}</div>" if sub else ""}</div>')

    facts = [
        fact("Closest approach", f"{t_min_local.strftime('%H:%M')} {tzl}", f"geocentric, {g['min_sep_deg']:.2f}° centre to centre"),
        fact("Moon", f"{g['moon_age_days']:.1f} days old", f"{g['illum_pct']:.0f}% lit · {g['elongation_deg']:.0f}° from the Sun"),
        fact(f"{tname} hidden for", f"up to {max_hidden:.0f} min", f"{esc(longest['name'])}, {longest['hidden_min']:.0f} min" if longest else ""),
        fact("Watch from", f"{first_d.astimezone(tz).strftime('%H:%M')}–{last_r.astimezone(tz).strftime('%H:%M')} {tzl}" if first_d else "—",
             f"{len(vis)} of {len(cities)} listed cities see it"),
    ]

    thead = (f'<tr><th>City</th><th>{tname} disappears <small>({tzl})</small></th>'
             f'<th>reappears <small>({tzl})</small></th><th>hidden</th><th>Moon alt.</th><th>Sky</th></tr>')

    page = head(f"{title} · {SITE_NAME}", desc, f"/{slug}",
                f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>') + f"""
<main class="wrap">
  <h1>{esc(title)}</h1>
  <p class="sub">{esc(h1)} · {esc(day)} · {esc(aud['label'])}</p>

  <p class="lead">{esc(entry.get('note', ''))}</p>

  <div class="facts">{''.join(facts)}</div>

  <h2>Where it can be seen</h2>
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

  <h2>At the Moon's edge</h2>
  <p>Pick a city — or tap one on the map — to see {esc(tname)}'s path across the Moon from there, north up
  and east to the left as in binoculars. Drag the slider to move it along its track.</p>
  <div class="limb-card">
    <div class="limb-controls">
      <label>City <select id="limb-city">{limb_options}</select></label>
      <span class="limb-readout" id="limb-readout"></span>
    </div>
    <svg id="limb-svg" viewBox="-190 -190 380 380" class="limb-svg" role="img" aria-label="The Moon's disc with the target's path"></svg>
    <input type="range" id="limb-slider" min="0" max="160" value="80" step="1" aria-label="Time">
  </div>
  <script type="application/json" id="limb-data">{json.dumps(limb, ensure_ascii=False, separators=(",", ":"))}</script>

  <h2>City by city</h2>
  <p>Times are for the Moon's mean limb; the real limb's mountains and valleys shift each contact by up to a
  couple of seconds. <em>Disappears</em> is the moment {esc(tname)} is fully hidden (its disc takes from the
  earlier time to slide in); <em>reappears</em> is when the first sliver returns.</p>
  <p><button class="btn" id="nearest-btn" type="button">Highlight my nearest city</button></p>
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

  <h2>How to watch</h2>{tips}

  <h2>Method &amp; accuracy</h2>
  <p class="method">Positions from the JPL <strong>DE431</strong> ephemeris (Skyfield), ΔT = {data['engine']['delta_t_s']} s,
  the Moon as a sphere of mean radius {data['engine']['moon_radius_km']} km — contact times are therefore
  ±2 s or so against the true, mountainous limb, and the limit line is drawn from a
  {data['maps'][data['audience']]['grid_deg']}° grid (≈10 km). {esc(tname)}'s own disc
  ({2 * g['target_sd_arcsec']:.0f}″ across) is included: partial contacts are the <small>from/to</small> times.
  The numbers behind this page: <a href="/data/{slug}.json">{slug}.json</a>.
  Generated {data['generated'][:10]}.</p>
</main>

{FOOTER}
<script>
(function () {{
  var D = JSON.parse(document.getElementById('limb-data').textContent);
  var svg = document.getElementById('limb-svg'), sel = document.getElementById('limb-city'),
      slider = document.getElementById('limb-slider'), readout = document.getElementById('limb-readout');
  var NS = 'http://www.w3.org/2000/svg', R = 150, cur = null;
  function el(n, a, txt) {{ var e = document.createElementNS(NS, n); for (var k in a) e.setAttribute(k, a[k]); if (txt) e.textContent = txt; return e; }}
  function localTime(ms) {{ return new Date(ms).toLocaleTimeString('en-GB', {{ timeZone: D.tz, hour: '2-digit', minute: '2-digit', second: '2-digit' }}); }}
  function pos(c, minutes) {{  // interpolate the track (east, north in arcmin) at t0 + minutes
    var i = minutes / c.step_min, i0 = Math.max(0, Math.min(c.xy.length / 2 - 2, Math.floor(i))), f = i - i0;
    var e = (c.xy[2*i0] * (1-f) + c.xy[2*i0+2] * f) / 100, n = (c.xy[2*i0+1] * (1-f) + c.xy[2*i0+3] * f) / 100;
    return {{ x: -e / c.sd_arcmin * R, y: -n / c.sd_arcmin * R }};
  }}
  function draw(name) {{
    var c = D.cities[name]; if (!c) return; cur = c;
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    var t0 = Date.parse(c.t0), span = (c.xy.length / 2 - 1) * c.step_min;
    slider.max = span;
    // phase: bright limb toward PA bright_pa; local frame has the bright limb at -y, rotated by -PA
    var k = D.illum, b = R * Math.abs(2 * k - 1), sweep = k > 0.5 ? 1 : 0;
    svg.appendChild(el('circle', {{ class: 'disc-dark', r: R }}));
    svg.appendChild(el('path', {{ class: 'disc-bright', transform: 'rotate(' + (-D.bright_pa) + ')',
      d: 'M ' + (-R) + ' 0 A ' + R + ' ' + R + ' 0 0 1 ' + R + ' 0 A ' + R + ' ' + b + ' 0 0 ' + sweep + ' ' + (-R) + ' 0 Z' }}));
    svg.appendChild(el('circle', {{ class: 'disc-edge', r: R }}));
    svg.appendChild(el('text', {{ class: 'lbl', x: 0, y: -R - 8, 'text-anchor': 'middle' }}, 'N'));
    svg.appendChild(el('text', {{ class: 'lbl', x: -R - 8, y: 4, 'text-anchor': 'end' }}, 'E'));
    // track, with the hidden stretch drawn faint
    var pts = [], m;
    for (m = 0; m <= span; m += 2) pts.push(pos(c, m));
    svg.appendChild(el('polyline', {{ class: 'track', points: pts.map(function (p) {{ return p.x.toFixed(1) + ',' + p.y.toFixed(1); }}).join(' ') }}));
    var marks = [['D1','D'],['D2','D'],['R1','R'],['R2','R']];
    marks.forEach(function (mk) {{
      var iso = c.contacts[mk[0]]; if (!iso) return;
      var p = pos(c, (Date.parse(iso) - t0) / 60000);
      svg.appendChild(el('circle', {{ class: 'contact', cx: p.x, cy: p.y, r: 3 }}));
      if (mk[0] === 'D2' || mk[0] === 'R1' || (mk[0] === 'D1' && !c.contacts.D2) || (mk[0] === 'R2' && !c.contacts.R1))
        svg.appendChild(el('text', {{ class: 'lbl', x: p.x + (mk[1] === 'D' ? 6 : -6), y: p.y - 6, 'text-anchor': mk[1] === 'D' ? 'start' : 'end' }},
          mk[1] + ' ' + localTime(Date.parse(iso))));
    }});
    if (c.verdict !== 'visible') svg.appendChild(el('text', {{ class: 'miss-note', x: 0, y: R + 28, 'text-anchor': 'middle' }},
      c.verdict === 'miss' ? D.target + ' passes outside the limb from here' : 'Moon below the horizon here'));
    svg.appendChild(el('circle', {{ id: 'limb-target', class: 'target', r: Math.max(2.5, D.target_sd / c.sd_arcmin * R) }}));
    if (sel.value !== name) sel.value = name;
    update();
  }}
  function update() {{
    if (!cur) return;
    var m = +slider.value, p = pos(cur, m), t = document.getElementById('limb-target');
    t.setAttribute('cx', p.x); t.setAttribute('cy', p.y);
    var r = Math.hypot(p.x, p.y) / R;
    t.style.opacity = r < 1 - D.target_sd / cur.sd_arcmin ? 0.25 : 1;
    readout.textContent = localTime(Date.parse(cur.t0) + m * 60000) + ' ' + D.tzl;
  }}
  sel.addEventListener('change', function () {{ draw(sel.value); }});
  slider.addEventListener('input', update);
  document.querySelectorAll('circle[data-city]').forEach(function (ci) {{
    ci.style.cursor = 'pointer';
    ci.addEventListener('click', function () {{ draw(ci.dataset.city); document.querySelector('.limb-card').scrollIntoView({{ block: 'nearest', behavior: 'smooth' }}); }});
  }});
  window.limbDraw = draw;
  draw(sel.value);
}})();
(function () {{
  var btn = document.getElementById('nearest-btn');
  if (!btn || !navigator.geolocation) {{ if (btn) btn.hidden = true; return; }}
  btn.addEventListener('click', function () {{
    btn.disabled = true; btn.textContent = 'Locating…';
    navigator.geolocation.getCurrentPosition(function (pos) {{
      var la = pos.coords.latitude, lo = pos.coords.longitude, best = null, bd = 1e9;
      document.querySelectorAll('tr[data-lat]').forEach(function (tr) {{
        var d = Math.hypot(la - +tr.dataset.lat, (lo - +tr.dataset.lon) * Math.cos(la * Math.PI / 180));
        if (d < bd) {{ bd = d; best = tr; }}
        tr.classList.remove('nearest');
      }});
      if (best) {{
        best.classList.add('nearest');
        if (window.limbDraw) window.limbDraw(best.cells[0].textContent);
        var det = best.closest('details'); if (det) det.open = true;
        best.scrollIntoView({{ block: 'center', behavior: 'smooth' }});
        btn.textContent = 'Nearest: ' + best.cells[0].textContent + ' (' + Math.round(bd * 111) + ' km)';
      }}
    }}, function () {{ btn.textContent = 'Location unavailable'; }});
  }});
}})();
</script>
</body>
</html>
"""
    out = OUT / f"{slug}.html"
    out.write_text(page)
    (OUT / "data").mkdir(exist_ok=True)
    (OUT / "data" / f"{slug}.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    print(f"wrote site/{slug}.html ({out.stat().st_size // 1024} KB): {len(vis)} visible / {len(misses)} miss / "
          f"{len(cities) - len(vis) - len(misses)} moon-down cities")
    return {"slug": slug, "title": title, "day": day, "note": entry.get("note", ""),
            "audience": aud["label"], "when": t_min_local, "generated": data["generated"][:10]}


def build_index(seed, built):
    built = sorted(built, key=lambda b: b["when"])
    items = "".join(
        f'<li><a class="event-card" href="/{b["slug"]}"><div class="when">{esc(b["day"])} · {esc(b["audience"])}</div>'
        f'<div class="what">{esc(b["title"])}</div><div class="note">{esc(b["note"])}</div></a></li>'
        for b in built)
    desc = ("Lunar occultations of planets and bright stars: where on Earth each one can be seen, the graze-limit "
            "map, and city-by-city contact times — computed from the JPL DE431 ephemeris.")
    page = head(f"{SITE_NAME} — {TAGLINE}", desc, "/") + f"""
<main class="wrap">
  <h1>When the Moon hides a planet or a star</h1>
  <p class="sub">{TAGLINE}</p>
  <p class="lead">A lunar occultation is the Moon passing in front of a planet or a star. It is visible
  only from a band of the Earth, and the timing changes from city to city. Each page here maps that
  band, draws the graze limit where the object skims the lunar edge, and lists the contact times
  for the cities that see it.</p>
  <h2>Events</h2>
  <ul class="event-list">{items}</ul>
  <h2>How these are made</h2>
  <p class="method">The event list is chosen by hand; every time and line is then computed from the JPL DE431
  ephemeris for the Moon's mean limb (±2 s against the real, mountainous limb). Each page links the JSON
  it was built from. Nothing here is copied from another prediction service.</p>
</main>
{FOOTER}
</body>
</html>
"""
    (OUT / "index.html").write_text(page)
    urls = [("/", "weekly", "1.0")] + [(f"/{b['slug']}", "weekly", "0.8") for b in built]
    sm = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for path, freq, pri in urls:
        sm.append(f"  <url><loc>{SITE}{path}</loc><changefreq>{freq}</changefreq><priority>{pri}</priority></url>")
    sm.append("</urlset>\n")
    (OUT / "sitemap.xml").write_text("\n".join(sm))
    (OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n")
    # Cloudflare Pages: text is unhashed, keep it short-lived; the JSON is immutable per generation date
    (OUT / "_headers").write_text("/*\n  Cache-Control: public, max-age=3600\n/data/*\n  Cache-Control: public, max-age=86400\n")
    (OUT / "404.html").write_text(head(f"Not found · {SITE_NAME}", "No such page.", "/404") + f"""
<main class="wrap"><h1>No such page</h1><p class="sub">Nothing is occulted here.</p>
<p><a href="/">All events</a></p></main>{FOOTER}</body></html>
""")
    print(f"wrote site/index.html, sitemap.xml ({len(urls)} urls), robots.txt, _headers, 404.html")


if __name__ == "__main__":
    seed = json.loads((ROOT / "seed.json").read_text())
    OUT.mkdir(exist_ok=True)
    built = [build(seed, e["slug"]) for e in seed["events"]]
    build_index(seed, built)
