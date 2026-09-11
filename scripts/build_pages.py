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
            out.append(f'<circle class="city city-{c["verdict"]}" cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}">'
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
    :root { --bg: #0b1220; --card: #141c2e; --card-2: #1b2438; --border: rgba(255,255,255,0.08);
            --text: #eef2f7; --muted: #8b97ab; --accent: #7dd3fc;
            --c-visible: #4ade80; --c-miss: #f87171; --c-down: #64748b; --c-limit: #fbbf24; --c-night: #c084fc; }
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body { background: var(--bg); color: var(--text); font-family: 'Outfit', system-ui, sans-serif; line-height: 1.5; padding-bottom: 4rem; }
    a { color: var(--accent); }
    header.site { border-bottom: 1px solid var(--border); padding: 0.9rem 1rem; }
    .wrap { max-width: 860px; margin: 0 auto; padding: 0 1rem; }
    .site-row { display: flex; align-items: baseline; justify-content: space-between; gap: 1rem; flex-wrap: wrap; max-width: 860px; margin: 0 auto; }
    .brand { font-weight: 600; font-size: 1.05rem; color: var(--text); text-decoration: none; letter-spacing: 0.02em; }
    .brand span { color: var(--accent); }
    .tagline { color: var(--muted); font-size: 0.85rem; }
    h1 { font-size: 1.6rem; font-weight: 600; line-height: 1.2; margin: 1.4rem 0 0.2rem; }
    h1 + .sub { color: var(--muted); }
    h2 { font-size: 1.05rem; font-weight: 600; margin: 1.6rem 0 0.6rem; color: var(--accent); }
    p { margin: 0.5rem 0; }
    .lead { font-size: 1.05rem; }
    .facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 0.6rem; margin: 1rem 0; }
    .fact { background: var(--card); border-radius: 10px; padding: 0.7rem 0.85rem; }
    .fact-label { font-size: 0.75rem; color: var(--muted); letter-spacing: 0.04em; text-transform: uppercase; }
    .fact-value { font-size: 1.25rem; font-weight: 600; margin-top: 0.15rem; }
    .fact-sub { font-size: 0.8rem; color: var(--muted); margin-top: 0.15rem; }
    .map-card { background: var(--card); border-radius: 12px; padding: 0.6rem; }
    .occ-svg { width: 100%; height: auto; display: block; border-radius: 8px; }
    .occ-inset { max-width: 420px; margin: 0.6rem auto 0; }
    .sea { fill: #070d1a; }
    .land { fill: #232f45; stroke: rgba(255,255,255,0.18); stroke-width: 0.8; }
    .border { fill: none; stroke: rgba(255,255,255,0.22); stroke-width: 0.7; }
    .region { fill: rgba(125,211,252,0.28); stroke: rgba(125,211,252,0.7); stroke-width: 1; }
    .night { fill: rgba(192,132,252,0.32); stroke: none; }
    .limit { fill: none; stroke-width: 2.6; stroke-linecap: round; stroke-linejoin: round; }
    .limit-north, .limit-south { stroke: var(--c-limit); }
    .limit-horizon { stroke: var(--muted); stroke-width: 1.2; stroke-dasharray: 5 4; }
    .frame { fill: none; stroke: var(--c-limit); stroke-width: 1.2; }
    .city { stroke: #070d1a; stroke-width: 1; }
    .city-visible { fill: var(--c-visible); }
    .city-miss { fill: var(--c-miss); }
    .city-moon_down { fill: var(--c-down); }
    .city-label { font: 500 11px 'Outfit', system-ui, sans-serif; fill: #eef2f7; paint-order: stroke; stroke: #070d1a; stroke-width: 3px; stroke-linejoin: round; }
    .legend { display: flex; flex-wrap: wrap; gap: 0.4rem 1.1rem; font-size: 0.82rem; color: var(--muted); margin: 0.6rem 0.2rem 0; }
    .legend span::before { content: ''; display: inline-block; width: 0.8em; height: 0.8em; border-radius: 50%; margin-right: 0.4em; vertical-align: -0.05em; }
    .lg-region::before { background: rgba(125,211,252,0.6); border-radius: 2px !important; }
    .lg-night::before { background: rgba(192,132,252,0.7); border-radius: 2px !important; }
    .lg-limit::before { background: var(--c-limit); height: 0.25em !important; vertical-align: 0.25em !important; }
    .lg-visible::before { background: var(--c-visible); }
    .lg-miss::before { background: var(--c-miss); }
    .table-wrap { overflow-x: auto; background: var(--card); border-radius: 12px; }
    table { border-collapse: collapse; width: 100%; font-size: 0.9rem; }
    th, td { text-align: left; padding: 0.5rem 0.7rem; border-bottom: 1px solid var(--border); white-space: nowrap; vertical-align: top; }
    th { color: var(--muted); font-weight: 500; font-size: 0.78rem; letter-spacing: 0.03em; }
    th small { font-weight: 400; }
    td small { display: block; color: var(--muted); font-size: 0.75rem; }
    tr.v-miss td { color: var(--muted); }
    tr.v-miss td:first-child { color: var(--c-miss); }
    tr.v-visible td:first-child { color: var(--c-visible); font-weight: 500; }
    tr.v-down td { color: var(--c-down); }
    tr.nearest td { background: rgba(251,191,36,0.12); }
    details { margin-top: 0.6rem; }
    summary { cursor: pointer; color: var(--accent); font-size: 0.9rem; padding: 0.4rem 0.2rem; }
    .btn { background: var(--card-2); color: var(--text); border: 1px solid var(--border); border-radius: 8px; padding: 0.4rem 0.8rem; font: inherit; font-size: 0.85rem; cursor: pointer; }
    .btn:hover { border-color: var(--accent); }
    .method { font-size: 0.85rem; color: var(--muted); }
    .event-list { list-style: none; display: grid; gap: 0.7rem; margin: 1rem 0; }
    .event-card { display: block; background: var(--card); border-radius: 12px; padding: 0.9rem 1rem; text-decoration: none; color: var(--text); border: 1px solid transparent; }
    .event-card:hover { border-color: var(--accent); }
    .event-card .when { color: var(--muted); font-size: 0.85rem; }
    .event-card .what { font-size: 1.15rem; font-weight: 600; margin: 0.15rem 0; }
    .event-card .note { color: var(--muted); font-size: 0.9rem; }
    footer { max-width: 860px; margin: 2.5rem auto 0; padding: 0 1rem; font-size: 0.85rem; color: var(--muted); }
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
  <meta name="theme-color" content="#0b1220">
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Ccircle cx='16' cy='16' r='13' fill='%23fbbf24'/%3E%3Ccircle cx='21' cy='14' r='11' fill='%230b1220'/%3E%3C/svg%3E">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600&display=swap" rel="stylesheet">
  <style>{BASE_CSS}</style>
  {extra}
</head>
<body>
<header class="site">
  <div class="site-row">
    <a class="brand" href="/">{SITE_NAME} <span>·</span> occult.alokm.com</a>
    <span class="tagline">{TAGLINE}</span>
  </div>
</header>
"""


FOOTER = f"""
<footer>
  <p>Every number on this site is computed from the JPL DE431 ephemeris by the
  <a href="https://kaalshodh.com/">Kaalshodh</a> engine; the pages are static. Predictions are for
  the Moon's mean limb. Built by Alok Mandavgane.</p>
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
    tgt, moon = data["target"]["names"], data["moon"]["names"]
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
    h1 = f"{moon['en-iast']}–{tgt['en-iast']} Samāgama"
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
