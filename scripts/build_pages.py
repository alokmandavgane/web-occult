#!/usr/bin/env python3
"""Build site/ — the whole static site — from seed + data + geo.

    data/<slug>.json    (engine/occultation_event.py, DE431)
  + geo/<audience>.json (scripts/build_geo.py)
  + seed.json
  -> site/index.html, site/<slug>.html, site/data/<slug>.json, site/sitemap.xml,
     site/404.html, site/robots.txt, site/_headers, site/sw.js

Static by construction: the city table is in the HTML and the maps are SVG, so a
crawler sees the whole page and a reader costs nothing to serve. What every page
of a kind shares — the stylesheet, the solvers, the city lists, the map outlines —
is written once under site/css, site/js and site/img and linked with a content
hash (`asset()`), so a reader downloads it once. Re-run after regenerating the
data or editing the seed.

Usage:  python3 scripts/build_pages.py
"""

import hashlib
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
TAGLINE = "occultations for your city"


def esc(s):
    return html.escape(str(s), quote=True)


def asset(rel, text):
    """Write a file every page of a kind shares (site/<rel>) and return its URL with a content hash. /css, /js and /img
    are cached for 30 days (_headers), so a page must never link one without the ?v= of the content it expects."""
    f = OUT / rel
    if not f.exists() or f.read_text() != text:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    return f"/{rel}?v={hashlib.sha1(text.encode()).hexdigest()[:10]}"


def cities_js(name, cities):
    """A location sheet's city list, {name: [lat, lon, tz]}, as site/js/<name>.js setting window.OccultCities: the same
    few KB on every month page, so a script the browser caches rather than JSON inline in each. The page loads it
    before its own script and builds the dropdown from it."""
    return asset(f"js/{name}.js", "window.OccultCities=" + json.dumps(cities, ensure_ascii=False, separators=(",", ":")) + ";\n")


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


def outline(name, geo, p):
    """The land and borders of a map, which are the same on every page drawn in that projection, as one shared SVG file
    (site/img/map-<name>.svg) and the <use> elements that draw it. The paths carry no style of their own: fill and
    stroke come from the class on each <use> and inherit into the copy, so the page's colours (and dark mode) apply."""
    land = p.path_lonlat(geo["land"])
    border = p.path_lonlat(geo["borders"], close=False) if geo.get("borders") else ""
    svg = f'<svg xmlns="http://www.w3.org/2000/svg"><path id="land" d="{land}"/>' + (f'<path id="border" d="{border}"/>' if border else "") + "</svg>\n"
    url = asset(f"img/map-{name}.svg", svg)
    return f'<use href="{url}#land" class="land"/>' + (f'<use href="{url}#border" class="border"/>' if border else "")


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
    out.append(outline(f"{'world' if inset else data['audience']}-{width}", geo, p))
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


def horizon_split(data, c):
    """Which half of a 'visible' occultation a city really sees. The generator calls a city visible when the Moon is
    up at ANY contact, so when the Moon rises or sets mid-event only one half is above the horizon (67 of 768 rows).
    -> (seen, at): seen is 'both', 'rises' (only the reappearance) or 'sets' (only the disappearance); at maps each
    contact to (Moon altitude, Moon azimuth, Sun altitude) from the event's elements. Twin of the JS in solve()."""
    con = c.get("contacts") or {}
    if c.get("verdict") != "visible" or not con:
        return "both", {}
    eng = str(ROOT / "engine")
    if eng not in sys.path:
        sys.path.insert(0, eng)
    from occultation_event import _parse_t0, element_geometry
    el = data["elements"]
    geom, t0 = element_geometry(el, c["lat"], c["lon"]), _parse_t0(el)
    at = {}
    for k, v in con.items():
        g = geom((parse(v) - t0).total_seconds() / 60.0)
        at[k] = (float(g["alt_m"]), float(g["az_m"]), float(g["alt_s"]))
    dk, rk = ("D2" if "D2" in con else "D1"), ("R1" if "R1" in con else "R2")
    up_d, up_r = dk in at and at[dk][0] > 0, rk in at and at[rk][0] > 0
    return ("both" if up_d == up_r else "rises" if up_r else "sets"), at


def verdict_text(c, data):
    tname = data["target"]["names"]["common"]
    if c["verdict"] == "visible":
        seen, _ = horizon_split(data, c)
        if seen != "both":
            return ("reappearance only (the Moon rises during it)" if seen == "rises" else "disappearance only (the Moon sets first)")
        hid = c.get("hidden_min")
        return (f"hidden {hid:.0f} min, " if hid else "") + sky_text(c["sun_alt"])
    if c["verdict"] == "miss":
        gap = c["sep_arcmin"] - c["moon_sd_arcmin"]
        return f"misses by {gap:.1f}′"
    return "Moon below the horizon"


def city_row(c, data, tz):
    con = c.get("contacts", {})
    tname = data["target"]["names"]["common"]
    name = esc(c["name"])
    if c["verdict"] == "visible" and con:
        seen, at = horizon_split(data, c)
        d = f'{t_local(con["D2"], tz)}' if "D2" in con else "—"
        d1 = f'<small>from {t_local(con["D1"], tz, "%H:%M:%S")}</small>' if "D1" in con and "D2" in con else ""
        r = f'{t_local(con["R1"], tz)}' if "R1" in con else "—"
        r2 = f'<small>to {t_local(con["R2"], tz, "%H:%M:%S")}</small>' if "R2" in con and "R1" in con else ""
        hid = f'{c["hidden_min"]:.0f} min' if c.get("hidden_min") else "—"
        look = look_text(c)
        if seen == "rises":
            d1 = "<small>Moon not yet up</small>"
            alt, az, sun = at["R1" if "R1" in con else "R2"]
            look = look_text({"moon_alt": alt, "moon_az": az, "sun_alt": sun}) + " · at reappearance"
        elif seen == "sets":
            r2 = "<small>Moon has set</small>"
        return (f'<tr class="v-visible" data-lat="{c["lat"]}" data-lon="{c["lon"]}"><td>{name}</td>'
                f'<td>{d}{d1}</td><td>{r}{r2}</td><td>{hid}</td><td>{esc(look)}</td></tr>')
    if c["verdict"] == "miss":
        gap = c["sep_arcmin"] - c["moon_sd_arcmin"]
        when = t_local(c["closest"], tz, "%H:%M") if c.get("closest") else ""
        return (f'<tr class="v-miss" data-lat="{c["lat"]}" data-lon="{c["lon"]}"><td>{name}</td>'
                f'<td colspan="3">misses by {gap:.1f}′ (closest at {when})</td>'
                f'<td>{esc(look_text(c))}</td></tr>')
    return (f'<tr class="v-down" data-lat="{c["lat"]}" data-lon="{c["lon"]}"><td>{name}</td>'
            f'<td colspan="4">Moon below the horizon</td></tr>')


# ── page ───────────────────────────────────────────────────────────────────

BASE_CSS = """
    /* Almanac paper by day, night sky by night; lapis / moonlight accent. System fonts only: no web fonts, no font requests. */
    :root { color-scheme: light dark;
            --bg: #f6f3ec; --card: #fffdf8; --card-2: #f0ebe0; --border: #e5dfd2; --line: #d5cdbb;
            --text: #1c1a16; --muted: #6f685b; --accent: #2f5597;
            --sea: #eaeef0; --land: #e3ddcf; --land-line: #c8bfad;
            --c-visible: #2f7a3e; --c-miss: #b83a2e; --c-down: #a39e92; --c-limit: #c26a0a; --c-night: #6a4bb0;
            --region: rgba(47,85,151,0.18); --region-line: rgba(47,85,151,0.55); --night: rgba(106,75,176,0.18);
            --display: "Avenir Next", "Segoe UI Variable Display", "Segoe UI", system-ui, Roboto, "Helvetica Neue", sans-serif;
            --t-occ: #a4600c; --t-ms: #1b6f86; --t-ast: #a8324e; --t-jup: #6a44a8; --t-sat: #2f7a55;
            --shadow: 0 1px 2px rgba(70,55,25,0.05), 0 12px 28px -20px rgba(70,55,25,0.4);
            --sky-top: rgba(47,85,151,0.06); --stars: @STARS_DAY@; }
    @media (prefers-color-scheme: dark) { :root {
            --bg: #0c0f17; --card: #131826; --card-2: #1a2030; --border: #222a3b; --line: #313a50;
            --text: #ece8dd; --muted: #9aa0ae; --accent: #a9c1f0;
            --sea: #090c13; --land: #1c2230; --land-line: #343d52;
            --c-visible: #6fd394; --c-miss: #f08a7e; --c-down: #6b7180; --c-limit: #f2b54a; --c-night: #c3b4f5;
            --region: rgba(169,193,240,0.18); --region-line: rgba(169,193,240,0.55); --night: rgba(195,180,245,0.2);
            --shadow: inset 0 1px 0 rgba(255,255,255,0.04), 0 16px 34px -22px #000;
            --sky-top: rgba(74,104,196,0.17); --stars: @STARS_NIGHT@;
            --t-occ: #f2b54a; --t-ms: #6cc7e0; --t-ast: #f08aa3; --t-jup: #c3b1f5; --t-sat: #6fd394; } }
    /* .sky: a plate of the night, whatever the page's theme. The home page's hero and the icons' eyepieces wear it. */
    .sky, .config-svg, .limb-svg { color-scheme: dark; --bg: #0c0f17; --card: #131826; --card-2: #1a2030; --border: #222a3b; --line: #313a50; --sea: #090c13;
           --text: #ece8dd; --muted: #a3a9b8; --accent: #a9c1f0; --c-limit: #f2b54a; --c-miss: #f08a7e; --stars: @STARS_NIGHT@; color: var(--text);
           --t-occ: #f2b54a; --t-ms: #6cc7e0; --t-ast: #f08aa3; --t-jup: #c3b1f5; --t-sat: #6fd394; }
    /* a page wears its kind's colour (head() puts the class on <html>): --tc on the page, --tn at night, inside an eyepiece */
    .t-occ { --tc: var(--t-occ); --tn: #f2b54a; } .t-ms { --tc: var(--t-ms); --tn: #6cc7e0; } .t-ast { --tc: var(--t-ast); --tn: #f08aa3; }
    .t-jup { --tc: var(--t-jup); --tn: #c3b1f5; } .t-sat { --tc: var(--t-sat); --tn: #6fd394; }
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    html { -webkit-text-size-adjust: 100%; }
    body { background: var(--bg); position: relative; color: var(--text); line-height: 1.55; padding-bottom: 4rem;
           font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, "Helvetica Neue", Arial, sans-serif;
           font-feature-settings: "tnum"; }
    /* the top of every page is sky: stars (ink dots on paper by day), the Moon's glow from the corner, fading out before the reading starts */
    body::before { content: ""; position: absolute; z-index: -1; inset: 0 0 auto; height: 640px; pointer-events: none;
                   background: var(--stars) 50% 0 / 640px 640px,
                               radial-gradient(ellipse 900px 420px at 88% -180px, color-mix(in srgb, var(--accent) 15%, transparent), transparent 72%) no-repeat,
                               linear-gradient(var(--sky-top), transparent 75%);
                   -webkit-mask-image: linear-gradient(#000 30%, transparent); mask-image: linear-gradient(#000 30%, transparent); }
    a { color: var(--accent); text-decoration: none; text-underline-offset: 0.18em; text-decoration-thickness: 1px; }
    a:hover { text-decoration: underline; }
    header.site { padding: 1.1rem 1rem; }
    .site-row { display: flex; align-items: baseline; justify-content: space-between; gap: 1rem; flex-wrap: wrap; max-width: 860px; margin: 0 auto; }
    .brand { font-weight: 700; font-size: 1.1rem; color: var(--text); letter-spacing: -0.01em; display: inline-flex; align-items: center; gap: 0.45rem; }
    .brand:hover { text-decoration: none; }
    .brand svg { width: 1.1em; height: 1.1em; }
    .tagline { color: var(--muted); font-size: 0.85rem; }
    .wrap { max-width: 860px; margin: 0 auto; padding: 0 1rem; }
    h1 { font-family: var(--display); font-size: clamp(1.75rem, 4.6vw, 2.6rem); font-weight: 500; line-height: 1.08; letter-spacing: -0.026em; margin: 1.6rem 0 0.4rem; text-wrap: balance; }
    .sub { color: var(--muted); }
    h2 { font-size: 0.8rem; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); margin: 2rem 0 0.7rem; overflow: hidden; }
    h2::after { content: ""; display: inline-block; width: 100%; height: 1px; margin: 0 -100% 0 0.9rem; vertical-align: middle; background: linear-gradient(90deg, var(--line), transparent 90%); }
    p { margin: 0.55rem 0; }
    b, strong { font-weight: 600; }   /* one step down from bold: a headline, not a shout */
    .lead { font-size: 1.1rem; margin-top: 1rem; }
    .facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 0.6rem; margin: 1.2rem 0; }
    .fact { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 0.75rem 0.9rem; }
    .facts-main { grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); margin-top: 1.1rem; }
    .facts-main .fact { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 8%, var(--card)); }
    .facts-main .fact-value { font-size: 1.45rem; white-space: nowrap; }
    .meta { color: var(--muted); font-size: 0.88rem; }
    .fact-label { font-size: 0.72rem; color: var(--muted); letter-spacing: 0.06em; text-transform: uppercase; }
    .fact-value { font-family: var(--display); font-size: 1.3rem; font-weight: 600; margin-top: 0.15rem; letter-spacing: -0.015em; }
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
    .btn { background: var(--card); color: var(--text); border: 1px solid var(--line); border-radius: 999px; padding: 0.45rem 0.95rem; font: inherit; font-size: 0.85rem; cursor: pointer;
           transition: border-color 0.15s, color 0.15s, box-shadow 0.15s, transform 0.1s; }
    .btn:hover { border-color: var(--accent); color: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 14%, transparent); }
    .btn:active { transform: translateY(1px); }
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
    .subnav { position: sticky; top: 0; z-index: 20; background: color-mix(in srgb, var(--bg) 72%, transparent); backdrop-filter: blur(14px) saturate(1.4); -webkit-backdrop-filter: blur(14px) saturate(1.4); border-bottom: 1px solid var(--border); }
    .subnav-row { max-width: 860px; margin: 0 auto; padding: 0.45rem 1rem; display: flex; align-items: center; justify-content: space-between; gap: 0.6rem; }
    .subnav-links { display: flex; gap: 0.2rem; overflow-x: auto; scrollbar-width: none; }
    .subnav-links::-webkit-scrollbar { display: none; }
    .subnav-links a { color: var(--muted); font-size: 0.85rem; padding: 0.3rem 0.55rem; border-radius: 999px; white-space: nowrap; }
    .subnav-links a:hover { text-decoration: none; color: var(--text); }
    .subnav-links a.active { color: var(--text); background: var(--card-2); }
    .chip { display: inline-flex; align-items: center; gap: 0.4rem; max-width: 55vw; background: var(--card); border: 1px solid var(--line); border-radius: 999px; padding: 0.3rem 0.7rem 0.3rem 0.5rem; font: inherit; font-size: 0.85rem; color: var(--text); cursor: pointer; white-space: nowrap; overflow: hidden; }
    .chip { transition: border-color 0.15s, box-shadow 0.15s; }
    .chip:hover { border-color: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 14%, transparent); }
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
    .btn-primary, .btn-primary:hover { background: linear-gradient(color-mix(in srgb, var(--accent) 84%, #fff), var(--accent)); color: var(--bg); border-color: var(--accent); }
    .btn-primary { box-shadow: 0 8px 18px -10px var(--accent); }
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
    .event-card { transition: border-color 0.15s, transform 0.15s; }
    .event-card:hover { border-color: var(--accent); text-decoration: none; transform: translateY(-1px); }
    .event-card .when { color: var(--muted); font-size: 0.85rem; }
    .event-card .what { font-size: 1.2rem; font-weight: 700; letter-spacing: -0.01em; margin: 0.15rem 0; }
    .event-card .note { color: var(--muted); font-size: 0.92rem; }
    .event-list-months { grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); }
    .event-list-months .event-card .what { font-size: 1rem; }
    footer { max-width: 860px; margin: 3rem auto 0; padding: 1.2rem 1rem 0; font-size: 0.82rem; color: var(--muted); border-top: 1px solid var(--border); }
    /* character: display lines in a modern sans each system already has (no font file), the mark's star in the limit colour, quiet focus and selection */
    .brand, .night-head h3, .feed-city, .sheet-title, .event-card .what { font-family: var(--display); font-weight: 600; letter-spacing: -0.012em; }
    .brand { font-size: 1.2rem; }
    .brand .mark-star { fill: var(--c-limit); }
    h2 { letter-spacing: 0.12em; }
    ::selection { background: color-mix(in srgb, var(--accent) 26%, transparent); }
    :focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 4px; }
    footer { border-top-style: dotted; position: relative; }
    footer::before { content: ""; position: absolute; top: -4px; left: 1rem; width: 7px; height: 7px; transform: rotate(45deg); background: var(--c-limit); box-shadow: 0 0 0 4px var(--bg); }
    /* surfaces lift off the page: one shadow for every card, whichever builder made it */
    .fact, .map-card, .table-wrap, .limb-card, .graze-card, .event-card, .night, .config-card, .ast, .feed-card, .sheet { box-shadow: var(--shadow); }
    /* and carries a faint wash of the page's kind colour from its top-left corner, as the home page's tiles do */
    html :is(.fact, .map-card, .limb-card, .graze-card, .event-card, section.night, .config-card, .ast, .feed-card) { border-radius: 16px;
      background: radial-gradient(120% 90% at 0 0, color-mix(in srgb, var(--tc, var(--accent)) 8%, transparent), transparent 58%), var(--card); }
    html .facts-main .fact { border-color: color-mix(in srgb, var(--tc, var(--accent)) 70%, var(--border));
      background: radial-gradient(120% 120% at 0 0, color-mix(in srgb, var(--tc, var(--accent)) 16%, transparent), transparent 70%), var(--card); }
    /* the drawings of the sky are plates of night in both themes: the moons' diagram and the Moon's disc sit among stars */
    html .limb-svg .lbl { fill: #dfe4f0; paint-order: stroke; stroke: #0b0e17; stroke-width: 3px; stroke-linejoin: round; }
    html .config-svg, html .limb-svg { border-radius: 12px; background: var(--stars) 0 0 / 640px 640px, radial-gradient(90% 150% at 50% 50%, #161f3a, #0b0e17 78%); }
    /* moving between pages is a short cross-fade, and the mark's star twinkles; neither for readers who asked for less motion */
    @view-transition { navigation: auto; }
    ::view-transition-old(root), ::view-transition-new(root) { animation-duration: 0.16s; }
    @keyframes twinkle { 50% { opacity: 0.35; transform: scale(0.8); } }
    .brand .mark-star { transform-box: fill-box; transform-origin: center; animation: twinkle 4.5s ease-in-out infinite; }
    @media (prefers-reduced-motion: reduce) {
      @view-transition { navigation: none; }
      *, *::before, *::after { animation: none !important; transition: none !important; }
    }
    /* phones: what a finger presses is at least 44 px tall, and the navigation bar fits a 375 px screen */
    @media (pointer: coarse) {
      .btn, .chip, .chipbox { min-height: 44px; }
      .btn { display: inline-flex; align-items: center; justify-content: center; }
      .subnav-links a { padding: 0.7rem 0.55rem; }
      .sheet select, .sheet input, select, input[type=range] { min-height: 44px; }
      .brand { padding: 0.45rem 0; }
      .typenav a { min-height: 44px; }
    }
    @media (max-width: 480px) { .chip-sub { display: none; } .chip { max-width: 46vw; } #chip-name { overflow: hidden; text-overflow: ellipsis; } }
    .place-ask { max-width: 860px; margin: 0.7rem auto 0; padding: 0 1rem; }
    .place-ask-msg { margin: 0 0 0.4rem; }
    .place-ask-do { display: flex; flex-wrap: wrap; gap: 0.4rem; margin: 0; }
    .acts { display: flex; flex-wrap: wrap; gap: 0.4rem; margin: 0.6rem 0 0; }
    button[hidden], a[hidden], .acts[hidden] { display: none !important; }   /* a display rule must never beat the hidden attribute */
    /* the event map zooms under two fingers: --z is the zoom, and dots, labels and lines keep their size on screen */
    .map-card { position: relative; }
    #main-map { --z: 1; touch-action: pan-y; }
    #main-map .land { stroke-width: calc(0.8px / var(--z)); } #main-map .border { stroke-width: calc(0.7px / var(--z)); }
    #main-map .region { stroke-width: calc(1px / var(--z)); } #main-map .limit { stroke-width: calc(2.6px / var(--z)); }
    #main-map .limit-horizon { stroke-width: calc(1.2px / var(--z)); } #main-map .limit-grid { stroke-width: calc(1px / var(--z)); }
    #main-map .city { stroke-width: calc(1px / var(--z)); }
    #main-map .city-label { font-size: calc(11px / var(--z)); stroke-width: calc(3px / var(--z)); }
    .map-reset { position: absolute; top: 1rem; right: 1rem; font-size: 0.8rem; box-shadow: 0 1px 4px rgba(0,0,0,0.25); }
"""


def stars_uri(ink, dim=1.0):
    """A 640 px tile of stars as an SVG data URI: three sizes of dot, each one path of zero-length strokes with round
    caps (11 bytes a star). The seed is fixed, so the stylesheet is the same on every build."""
    rnd = __import__("random").Random(1610)
    paths = ""
    for width, opacity, n in ((1.1, 0.55, 54), (1.7, 0.75, 20), (2.5, 0.9, 7)):
        d = "".join(f"M{rnd.randrange(6, 634)} {rnd.randrange(6, 634)}h.01" for _ in range(n))
        paths += f"<path d='{d}' stroke-width='{width}' opacity='{round(opacity * dim, 2)}'/>"
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' width='640' height='640' fill='none' stroke='{ink}' "
           f"stroke-linecap='round'>{paths}</svg>")
    return 'url("data:image/svg+xml,' + svg.replace("#", "%23").replace("<", "%3C").replace(">", "%3E") + '")'


BASE_CSS = BASE_CSS.replace("@STARS_DAY@", stars_uri("#1c1a16", 0.3)).replace("@STARS_NIGHT@", stars_uri("#dfe6f7"))


OG = {   # link-preview image per kind of page: key -> (file in site/og/, alt text). Drawn by scripts/build_og.py.
    "home": ("home.png", "Occult: what passes in front of what, and when you can see it"),
    "occ": ("occultations.png", "Lunar occultations: the Moon passing in front of planets and bright stars"),
    "ms": ("moon-stars.png", "The Moon and the stars: every star the Moon hides, for your location"),
    "ast": ("asteroids.png", "Asteroid occultations: a star blinks out as an asteroid's shadow crosses India"),
    "jupiter": ("jupiter.png", "Jupiter's moons: eclipses, transits, shadows and the Great Red Spot"),
    "saturn": ("saturn.png", "Saturn's moons: eclipses, transits and shadows"),
    "calendar": ("calendar.png", "Occultations in your calendar: one feed per city"),
}
_OG_V = {}


SW_JS = r"""
/* occult.alokm.com — the site kept for the field. Someone who drives out to a path is in the one place with no signal,
   so once a page has been opened it opens again without one: the HTML, the stylesheet and scripts it links, the month's
   data, Leaflet, and whatever map tiles were already looked at. Pages go to the network first, so an online reader always
   gets the current build and the cache is only the fallback; files come from the cache and are refreshed behind; the
   pinned Leaflet files and the tiles never change, so they come from the cache alone. Everything is kept under ONE fixed
   name, the oldest dropped past a cap: a deploy never throws away what a reader saved, and a page cached before it still
   finds the ?v= files it links. Analytics is left alone. To switch all this off for good, ship an sw.js whose install
   handler is self.registration.unregister(). */
var SITE = 'occult-site', TILES = 'occult-tiles', SITE_MAX = 500, TILE_MAX = 600, CORE = __CORE__;

self.addEventListener('install', function (e) {
  // one by one, and a failure is allowed: a single missing file must not leave a reader with no offline site at all
  e.waitUntil(caches.open(SITE).then(function (c) {
    return Promise.all(CORE.map(function (u) { return c.add(u).catch(function () {}); }));
  }).then(function () { return self.skipWaiting(); }));
});
self.addEventListener('activate', function (e) {
  // earlier workers kept a cache named for each build: whatever is not one of these two is theirs
  e.waitUntil(caches.keys().then(function (ks) {
    return Promise.all(ks.map(function (k) { return k === SITE || k === TILES ? null : caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});
function keep(name, req, res, cap) {
  if (!res || (!res.ok && res.type !== 'opaque')) return res;      // a tile comes back opaque: no status to read, still worth keeping
  var copy = res.clone();
  caches.open(name).then(function (c) {
    return c.put(req, copy).then(function () {                    // a put moves the entry to the end: the front is the least recently fetched
      return c.keys().then(function (ks) { for (var i = 0; i < ks.length - cap; i++) c.delete(ks[i]); });
    });
  });
  return res;
}
function page(r, u) {
  var bare = new Request(u.origin + u.pathname);                   // one entry per page, not one per event or pinned spot
  return fetch(r).then(function (res) { return keep(SITE, bare, res, SITE_MAX); })
    .catch(function () { return caches.match(bare).then(function (c) { return c || caches.match('/'); }); });
}
function fresh(r) {                                                // cache first, then catch up behind
  return caches.match(r).then(function (c) {
    var net = fetch(r).then(function (res) { return keep(SITE, r, res, SITE_MAX); }).catch(function () { return c; });
    return c || net;
  });
}
function fixed(r, name, cap) {
  return caches.match(r).then(function (c) { return c || fetch(r).then(function (res) { return keep(name, r, res, cap); }); });
}
self.addEventListener('fetch', function (e) {
  var r = e.request, u = new URL(r.url);
  if (r.method !== 'GET' || u.protocol.slice(0, 4) !== 'http' || u.hostname.indexOf('google') >= 0) return;
  if (u.hostname === 'tile.openstreetmap.org') return e.respondWith(fixed(r, TILES, TILE_MAX));
  if (u.hostname === 'cdnjs.cloudflare.com') return e.respondWith(fixed(r, SITE, SITE_MAX));
  if (u.origin !== location.origin) return;
  e.respondWith(r.mode === 'navigate' ? page(r, u) : fresh(r));
});
"""


# What the pages with a location sheet share (site/js/site.js, loaded before the page's own script): going back closes what is
# open over the page, a name for a spot, the first-visit question, and one event into a calendar.
SITE_JS = r"""/* occult.alokm.com — shared by every page with a location sheet. */
(function () {
  // ---- Back — the button, or Android's back gesture — closes what is open over the page (a <dialog>, a full-screen map)
  // instead of leaving the page. An open overlay owns a history entry; closed any other way, it takes that entry back off
  // and keeps whatever address the page set while it was open.
  var stack = [], skip = 0;
  function opened(close) { history.pushState(history.state, ''); stack.push(close); }
  function closed(close) {
    var i = stack.indexOf(close);
    if (i < 0) return;
    stack.splice(i, 1);
    var keep = location.href;
    skip++;
    addEventListener('popstate', function once() { removeEventListener('popstate', once); history.replaceState(history.state, '', keep); });
    history.back();
  }
  addEventListener('popstate', function () {
    if (skip) { skip--; return; }
    var close = stack.pop();
    if (close) close();
  });
  window.Overlay = { opened: opened, closed: closed };
  new MutationObserver(function (ms) {
    ms.forEach(function (m) {
      var d = m.target;
      if (d.tagName !== 'DIALOG') return;
      if (d.open && !d._back) { d._back = function () { d._back = null; d.close(); }; opened(d._back); }
      else if (!d.open && d._back) { var f = d._back; d._back = null; closed(f); }
    });
  }).observe(document.documentElement, { subtree: true, attributes: true, attributeFilter: ['open'] });

  // ---- A name for a spot: the listed city itself within a kilometre, "Spot near <city>" within 60 km, else its coordinates
  window.placeName = function (lat, lon, cities) {
    var best = '', bd = 60, k = Math.cos(lat * Math.PI / 180);
    Object.keys(cities || {}).forEach(function (n) {
      var c = cities[n], dd = Math.hypot((c[0] - lat) * 111.2, ((c[1] - lon + 540) % 360 - 180) * 111.2 * k);
      if (dd < bd) { bd = dd; best = n; }
    });
    return !best ? lat.toFixed(2) + ', ' + lon.toFixed(2) : bd < 1 ? best : 'Spot near ' + best;
  };

  // ---- First visit: say which place the page is showing and offer to change it. Asked once: gone for good when the reader
  // sets a place (the page calls placeAsked) or keeps this one.
  window.askPlace = function (name, set) {
    try { if (localStorage.getItem('occult-loc') || localStorage.getItem('occult-asked')) return; } catch (e) { return; }
    var nav = document.querySelector('.subnav'), b = document.createElement('div');
    if (!nav) return;
    b.className = 'place-ask';
    b.innerHTML = '<p class="place-ask-msg">Showing <b></b>. Where are you watching from?</p><p class="place-ask-do">'
      + (navigator.geolocation ? '<button class="btn btn-primary" type="button" data-a="geo">Use my location</button>' : '')
      + '<button class="btn" type="button" data-a="pick">Choose a place</button><button class="btn" type="button" data-a="keep">Keep this</button></p>';
    b.querySelector('b').textContent = name;
    nav.parentNode.insertBefore(b, nav.nextSibling);
    b.addEventListener('click', function (e) {
      var a = e.target.closest('[data-a]'), msg = b.querySelector('.place-ask-msg');
      if (!a) return;
      if (a.dataset.a === 'keep') { try { localStorage.setItem('occult-asked', '1'); } catch (x) {} b.remove(); }
      else if (a.dataset.a === 'pick') document.getElementById('loc-chip').click();
      else {
        a.disabled = true; a.textContent = 'Locating…';
        navigator.geolocation.getCurrentPosition(function (p) { set(p.coords.latitude, p.coords.longitude); },
          function () { a.remove(); msg.textContent = 'Your location is not available here. Choose a place instead.'; });
      }
    });
  };
  window.placeAsked = function () { var b = document.querySelector('.place-ask'); if (b) b.remove(); };

  // ---- One event into a calendar: a Google Calendar link, or an .ics file for any other calendar app.
  // e = {title, start, end (ms), details, url, uid, file, where?, alarm? (minutes before)}
  function stamp(ms) { return new Date(ms).toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, ''); }
  function text(s) { return String(s).replace(/\\/g, '\\\\').replace(/\n/g, '\\n').replace(/([,;])/g, '\\$1'); }
  function fold(l) { var o = ''; while (l.length > 73) { o += l.slice(0, 73) + '\r\n '; l = l.slice(73); } return o + l; }
  window.Cal = {
    android: /Android/i.test(navigator.userAgent),
    google: function (e) {
      return 'https://calendar.google.com/calendar/render?action=TEMPLATE&text=' + encodeURIComponent(e.title) + '&dates=' + stamp(e.start) + '/'
        + stamp(e.end) + '&details=' + encodeURIComponent(e.details + '\n\n' + e.url) + (e.where ? '&location=' + encodeURIComponent(e.where) : '');
    },
    ics: function (e) {
      var l = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//occult.alokm.com//EN', 'BEGIN:VEVENT', 'UID:' + e.uid + '@occult.alokm.com',
               'DTSTAMP:' + stamp(Date.now()), 'DTSTART:' + stamp(e.start), 'DTEND:' + stamp(e.end), 'SUMMARY:' + text(e.title),
               'DESCRIPTION:' + text(e.details + '\n\n' + e.url), 'URL:' + e.url];
      if (e.where) l.push('LOCATION:' + text(e.where));
      if (e.alarm) l.push('BEGIN:VALARM', 'ACTION:DISPLAY', 'DESCRIPTION:' + text(e.title), 'TRIGGER:-PT' + e.alarm + 'M', 'END:VALARM');
      l.push('END:VEVENT', 'END:VCALENDAR');
      var a = document.createElement('a'), u = URL.createObjectURL(new Blob([l.map(fold).join('\r\n') + '\r\n'], { type: 'text/calendar' }));
      a.href = u; a.download = e.file + '.ics'; document.body.appendChild(a); a.click(); a.remove();
      setTimeout(function () { URL.revokeObjectURL(u); }, 10000);
    },
    // Share a link: the phone's share sheet where there is one, else the clipboard. Tells the button what happened.
    share: function (btn, title, url) {
      if (navigator.share) return navigator.share({ title: title, url: url }).catch(function () {});
      var said = btn.textContent, done = function (t) { btn.textContent = t; setTimeout(function () { btn.textContent = said; }, 2000); };
      if (navigator.clipboard) navigator.clipboard.writeText(url).then(function () { done('Link copied'); }, function () { done('Copy failed'); });
      else done('Copy the address bar');
    }
  };
})();
"""


def site_js_url():
    return asset("js/site.js", SITE_JS)


def write_sw():
    """site/sw.js. The precache is the home page, the asteroid deep-link target and the files those two always need;
    everything else is kept as the reader goes, which is what makes a month's data and its tiles there in the field.
    The worker's text carries the list, so a build that changes a precached file changes sw.js and the browser installs
    the new one; the cache itself keeps its name, so nothing a reader saved is lost to a deploy."""
    core = ["/", "/asteroid", css_url()]
    try:
        import build_asteroids as ba
        core += [f"/js/asteroid.js?v={ba.lib_url()}", ba.world_url(), ba.cities_url()]
    except Exception as e:                      # no asteroid data built: the rest of the site still caches fine
        print(f"  sw.js: asteroid core skipped ({e})")
    (OUT / "sw.js").write_text(SW_JS.replace("__CORE__", json.dumps(core)))
    return core


def og_url(key):
    """Absolute URL with a content hash, so a redrawn image is a new URL to link-preview caches."""
    if key not in _OG_V:
        import hashlib
        f = OUT / "og" / OG[key][0]
        _OG_V[key] = hashlib.sha1(f.read_bytes()).hexdigest()[:10] if f.exists() else ""
    return f"{SITE}/og/{OG[key][0]}" + (f"?v={_OG_V[key]}" if _OG_V[key] else "")


# the mark: a crescent Moon with a star just off its dark limb, about to be covered
MARK_SVG = ('<svg viewBox="0 0 32 32" aria-hidden="true"><mask id="mark-cut"><rect width="32" height="32" fill="#fff"/>'
            '<circle cx="19.5" cy="13.5" r="9.5" fill="#000"/></mask><circle cx="14.5" cy="17.5" r="10.5" fill="currentColor" '
            'mask="url(#mark-cut)"/><circle class="mark-star" cx="25.5" cy="7.5" r="2.3"/></svg>')
FAVICON = "data:image/svg+xml," + __import__("urllib.parse").parse.quote(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="7" fill="#0c0f17"/>'
    '<mask id="m"><rect width="32" height="32" fill="#fff"/><circle cx="19.5" cy="13.5" r="9.5" fill="#000"/></mask>'
    '<circle cx="14.5" cy="17.5" r="10.5" fill="#ece8dd" mask="url(#m)"/><circle cx="25.5" cy="7.5" r="2.3" fill="#f2b54a"/></svg>')


def css_url():
    """BASE_CSS as site/css/base.css: every page links the same stylesheet, so it is fetched once, not inlined 125 times."""
    return asset("css/base.css", BASE_CSS.strip() + "\n")


def head(title, desc, path, extra="", og="home"):
    url = f"{SITE}{path}"
    kind = {"occ": "t-occ", "ms": "t-ms", "ast": "t-ast", "jupiter": "t-jup", "saturn": "t-sat"}.get(og)
    return f"""<!DOCTYPE html>
<html lang="en"{f' class="{kind}"' if kind else ''}>
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
  <meta property="og:image" content="{og_url(og)}">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta property="og:image:alt" content="{esc(OG[og][1])}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="theme-color" content="#f6f3ec" media="(prefers-color-scheme: light)">
  <meta name="theme-color" content="#0c0f17" media="(prefers-color-scheme: dark)">
  <link rel="icon" href="{FAVICON}">
  <link rel="manifest" href="/manifest.webmanifest">
  <link rel="apple-touch-icon" href="/icons/apple-touch-icon.png">
  <meta name="apple-mobile-web-app-title" content="{SITE_NAME}">
  <script>if('serviceWorker'in navigator)addEventListener('load',function(){{navigator.serviceWorker.register('/sw.js')}});</script>
  <link rel="stylesheet" href="{css_url()}">
  {extra}
</head>
<body>
<header class="site">
  <div class="site-row">
    <a class="brand" href="/">{MARK_SVG}{SITE_NAME}</a>
    <span class="tagline">{TAGLINE}</span>
  </div>
</header>
"""


FOOTER = f"""
<footer>
  <p>Computed from the JPL DE431 ephemeris, for the Moon's mean limb. Static pages; no tracking beyond
  basic analytics. <a href="/method">How this is computed</a> · <a href="/calendar">Calendar feeds</a> · <a href="https://alokm.com/">Alok Mandavgane</a>.</p>
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


# The event page's script: the any-location solver (the twin of element_geometry() in the generator), the location sheet,
# the Moon's-edge drawing and the graze profile. Everything it needs is in the page's limb-data JSON, so every event page
# shares this one file (site/js/occultation.js).
OCC_JS = r"""(function () {
  var D = JSON.parse(document.getElementById('limb-data').textContent), E = D.elements;
  var C = 299792.458, T0 = Date.parse(E.t0), HALF = E.half_hours * 60, R0 = E.R0, VE = E.v_earth_km_s;
  var OMEGA = E.era_rate_deg_per_min * Math.PI / 180 / 60, RAD = Math.PI / 180;
  function poly(c, t) { var v = 0; for (var i = c.length - 1; i >= 0; i--) v = v * t + c[i]; return v; }
  function dpoly(c, t) { var v = 0; for (var i = c.length - 1; i >= 1; i--) v = v * t + i * c[i]; return v; }
  function norm(v) { return Math.hypot(v[0], v[1], v[2]); }
  function dot(a, b) { return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]; }
  function unit(v) { var n = norm(v); return [v[0]/n, v[1]/n, v[2]/n]; }
  // geometry for one observer, as a closure: mirrors element_geometry() in the generator
  function observer(lat, lon) {
    var a = E.earth_a_km, f = E.earth_f, e2 = f * (2 - f), la = lat * RAD, lo = lon * RAD;
    var N = a / Math.sqrt(1 - e2 * Math.sin(la) * Math.sin(la));
    var r = [N * Math.cos(la) * Math.cos(lo), N * Math.cos(la) * Math.sin(lo), N * (1 - e2) * Math.sin(la)];
    var up = [Math.cos(la) * Math.cos(lo), Math.cos(la) * Math.sin(lo), Math.sin(la)];
    var wxr = [-OMEGA * r[1], OMEGA * r[0], 0];                  // omega x r, ITRS
    return function geom(m) {
      var tau = m / HALF, th = E.era_rate_deg_per_min * m * RAD, c = Math.cos(th), s = Math.sin(th);
      // R(t) = Rz(th).R0 (GCRS->ITRS); we need its transpose applied to ITRS vectors
      var R = [c*R0[0] + s*R0[3], c*R0[1] + s*R0[4], c*R0[2] + s*R0[5],
               -s*R0[0] + c*R0[3], -s*R0[1] + c*R0[4], -s*R0[2] + c*R0[5], R0[6], R0[7], R0[8]];
      function toG(v) { return [R[0]*v[0] + R[3]*v[1] + R[6]*v[2], R[1]*v[0] + R[4]*v[1] + R[7]*v[2], R[2]*v[0] + R[5]*v[1] + R[8]*v[2]]; }
      var obs = toG(r), upg = toG(up), vrot = toG(wxr);
      var eg = toG([-Math.sin(lo), Math.cos(lo), 0]), ng = toG([-Math.sin(la) * Math.cos(lo), -Math.sin(la) * Math.sin(lo), Math.cos(la)]);
      var vobs = [VE[0] + vrot[0], VE[1] + vrot[1], VE[2] + vrot[2]];
      function topo(coef) {
        var P = [poly(coef[0], tau), poly(coef[1], tau), poly(coef[2], tau)];
        var v = [dpoly(coef[0], tau) / (HALF * 60) + VE[0], dpoly(coef[1], tau) / (HALF * 60) + VE[1], dpoly(coef[2], tau) / (HALF * 60) + VE[2]];
        var d = [P[0] - obs[0], P[1] - obs[1], P[2] - obs[2]], dist = norm(d), lt = dot(obs, d) / dist / C;
        d = [d[0] + v[0] * lt, d[1] + v[1] * lt, d[2] + v[2] * lt];
        var u = unit(d); u = unit([u[0] + vobs[0] / C, u[1] + vobs[1] / C, u[2] + vobs[2] / C]);
        return { u: u, dist: dist };
      }
      var M = topo(E.moon), S = topo(E.target), sun = [poly(E.sun[0], tau) - obs[0], poly(E.sun[1], tau) - obs[1], poly(E.sun[2], tau) - obs[2]];
      var sep = Math.acos(Math.max(-1, Math.min(1, dot(M.u, S.u)))) / RAD;
      var sdm = Math.asin(E.moon_radius_km / M.dist) / RAD, sdt = E.target_radius_km ? Math.asin(E.target_radius_km / S.dist) / RAD : 0;
      var ram = Math.atan2(M.u[1], M.u[0]), decm = Math.asin(M.u[2]), ras = Math.atan2(S.u[1], S.u[0]), decs = Math.asin(S.u[2]);
      var dra = ((ras - ram + 3 * Math.PI) % (2 * Math.PI)) - Math.PI;
      var azm = Math.atan2(dot(M.u, eg), dot(M.u, ng)) / RAD; if (azm < 0) azm += 360;
      return { sep: sep, sdm: sdm, sdt: sdt, mu: M.u, mdist: M.dist, altm: Math.asin(dot(M.u, upg)) / RAD, azm: azm, alts: Math.asin(dot(unit(sun), upg)) / RAD,
               east: dra * Math.cos(decm) / RAD * 60, north: (decs - decm) / RAD * 60 };
    };
  }
  function state(g) { return g.sep < g.sdm - g.sdt ? 2 : (g.sep < g.sdm + g.sdt ? 1 : 0); }
  function solve(lat, lon) {
    var geom = observer(lat, lon), contacts = {}, prev = state(geom(-HALF)), best = null, m;
    for (m = -HALF + 0.5; m <= HALF; m += 0.5) {
      var g = geom(m), cur = state(g);
      if (!best || g.sep < best.sep) { best = g; best.m = m; }
      if (cur !== prev) {
        var lo = m - 0.5, hi = m;
        for (var i = 0; i < 40; i++) { var mid = (lo + hi) / 2; if (state(geom(mid)) === prev) lo = mid; else hi = mid; }
        var mc = (lo + hi) / 2;
        if (prev === 0 && cur >= 1) contacts.D1 = mc;
        if (prev <= 1 && cur === 2) contacts.D2 = mc;
        if (prev === 2 && cur <= 1) contacts.R1 = mc;
        if (prev >= 1 && cur === 0) contacts.R2 = mc;
        prev = cur;
      }
    }
    var keys = Object.keys(contacts), verdict;
    if (keys.length) { verdict = keys.some(function (k) { return geom(contacts[k]).altm > 0; }) ? 'visible' : 'moon_down'; }
    else verdict = best.altm > 0 ? 'miss' : 'moon_down';
    var ref = contacts.D2 !== undefined ? contacts.D2 : (contacts.D1 !== undefined ? contacts.D1 : best.m);
    // twin of horizon_split(): when the Moon rises or sets mid-event only one half is above the horizon
    var dk = contacts.D2 !== undefined ? 'D2' : 'D1', rk = contacts.R1 !== undefined ? 'R1' : 'R2', seen = 'both';
    if (verdict === 'visible') {
      var upD = contacts[dk] !== undefined && geom(contacts[dk]).altm > 0, upR = contacts[rk] !== undefined && geom(contacts[rk]).altm > 0;
      seen = upD === upR ? 'both' : upR ? 'rises' : 'sets';
      if (seen === 'rises') ref = contacts[rk];
    }
    return { geom: geom, contacts: contacts, closest: best, verdict: verdict, at: geom(ref), ref: ref, seen: seen, dk: dk, rk: rk,
             hidden: (contacts.D2 !== undefined && contacts.R1 !== undefined) ? contacts.R1 - contacts.D2 : null };
  }
  function localTime(m, secs) { return new Date(T0 + m * 60000).toLocaleTimeString('en-GB', { timeZone: D.tz, hour: '2-digit', minute: '2-digit', second: secs ? '2-digit' : undefined }); }
  function compass(az) { return ['N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSW','SW','WSW','W','WNW','NW','NNW'][Math.floor(((az + 11.25) % 360) / 22.5) % 16]; }
  function lookText(g) { if (g.altm <= 0) return 'Moon below the horizon'; var h = g.altm < 15 ? ' (low)' : g.altm > 60 ? ' (high)' : ''; return g.altm.toFixed(0) + '° up' + h + ' in the ' + compass(g.azm) + ' · ' + skyText(g.alts); }
  function skyText(a) { return a > 0 ? 'daylight, Sun ' + (a > 0 ? '+' : '') + a.toFixed(0) + '°' : a > -6 ? 'sunset twilight' : a > -12 ? 'dusk' : 'dark sky'; }

  // ---- UI: one page-level location; chip + sheet, map, moon view and table all follow it ----
  var latI = document.getElementById('loc-lat'), lonI = document.getElementById('loc-lon'), res = document.getElementById('loc-result');
  var sel = document.getElementById('limb-city'), where = document.getElementById('limb-where'), pin = document.getElementById('pin');
  var chip = document.getElementById('loc-chip'), chipName = document.getElementById('chip-name'), chipSub = document.getElementById('chip-sub');
  var sheet = document.getElementById('loc-sheet'), P = D.proj, LOC = null, MZ = 1, gestureAt = 0;
  Object.keys(D.cities).forEach(function (n) { sel.add(new Option(n, n)); });
  function fact(l, v, s) { return '<div class="fact"><div class="fact-label">' + l + '</div><div class="fact-value">' + v + '</div>' + (s ? '<div class="fact-sub">' + s + '</div>' : '') + '</div>'; }
  function tableRow(r, label) {
    var c = r.contacts;
    if (r.verdict === 'visible' || (r.verdict === 'moon_down' && Object.keys(c).length)) {
      return '<tr class="yours"><td>' + label + '</td><td>' + (c.D2 !== undefined ? localTime(c.D2, true) : '—') + (r.seen === 'rises' ? '<small>Moon not yet up</small>' : c.D1 !== undefined ? '<small>from ' + localTime(c.D1, true) + '</small>' : '') +
        '</td><td>' + (c.R1 !== undefined ? localTime(c.R1, true) : '—') + (r.seen === 'sets' ? '<small>Moon has set</small>' : c.R2 !== undefined ? '<small>to ' + localTime(c.R2, true) + '</small>' : '') +
        '</td><td>' + (r.hidden !== null ? r.hidden.toFixed(0) + ' min' : '—') + '</td><td>' + lookText(r.at) + (r.seen === 'rises' ? ' · at reappearance' : '') + '</td></tr>';
    }
    var gap = (r.closest.sep - r.closest.sdm) * 60;
    return '<tr class="yours"><td>' + label + '</td><td colspan="3">' + (r.verdict === 'miss' ? 'misses by ' + gap.toFixed(1) + '′ (closest at ' + localTime(r.closest.m, false) + ')' : 'Moon below the horizon') +
      '</td><td>' + lookText(r.closest) + '</td></tr>';
  }
  function show(lat, lon, label, fromUrl) {
    lat = +lat; lon = +lon; if (!isFinite(lat) || !isFinite(lon)) return;
    LOC = { lat: lat, lon: lon, label: label || '' };
    latI.value = lat.toFixed(4); lonI.value = lon.toFixed(4);
    var r = solve(lat, lon), c = r.contacts, h = '', summary;
    if (r.verdict === 'visible' || (r.verdict === 'moon_down' && Object.keys(c).length)) {
      h += fact(D.target + ' disappears', c.D2 !== undefined ? localTime(c.D2, true) : '—', r.seen === 'rises' ? 'the Moon is not up yet' : c.D1 !== undefined && c.D2 !== undefined ? 'first touch ' + localTime(c.D1, true) : '');
      h += fact('reappears', c.R1 !== undefined ? localTime(c.R1, true) : '—', r.seen === 'sets' ? 'the Moon has set' : c.R1 !== undefined && c.R2 !== undefined ? 'fully out ' + localTime(c.R2, true) : '');
      h += fact('hidden', r.hidden !== null ? r.hidden.toFixed(1) + ' min' : '—');
      h += fact('Where to look', r.at.altm > 0 ? r.at.altm.toFixed(0) + '° up in the ' + compass(r.at.azm) : 'below the horizon', r.at.altm > 0 ? skyText(r.at.alts) + (r.seen === 'rises' ? ' · at reappearance' : ' · at disappearance') : '');
      var halfText = r.seen === 'rises' ? 'Only the reappearance is visible from here: the Moon rises during the occultation (' + D.tzl + ').'
        : r.seen === 'sets' ? 'Only the disappearance is visible from here: the Moon sets before ' + D.target + ' comes back (' + D.tzl + ').'
        : 'Occultation visible from here (' + D.tzl + ').';
      h += '<div class="verdict ' + r.verdict + '">' + (r.verdict === 'visible' ? halfText : 'The Moon is below the horizon here during the occultation.') + '</div>';
      summary = r.verdict !== 'visible' ? 'Moon below horizon' : r.seen === 'rises' ? 'reappears ' + localTime(c[r.rk], false) : r.seen === 'sets' ? 'disappears ' + localTime(c[r.dk], false)
        : c.D2 !== undefined && c.R1 !== undefined ? 'hidden ' + localTime(c.D2, false) + '–' + localTime(c.R1, false) : 'grazing partial';
      if (r.verdict === 'visible' && c.D2 === undefined) h = h.replace('Occultation visible from here', 'Only part of ' + D.target + "'s disc is covered from here: a partial graze.");
    } else {
      var gap = r.closest.sep - r.closest.sdm;
      h += fact('closest approach', localTime(r.closest.m, false), (gap * 60).toFixed(1) + '′ outside the limb');
      h += fact('Where to look', r.closest.altm > 0 ? r.closest.altm.toFixed(0) + '° up in the ' + compass(r.closest.azm) : 'below the horizon', r.closest.altm > 0 ? skyText(r.closest.alts) : '');
      h += '<div class="verdict ' + r.verdict + '">' + (r.verdict === 'miss' ? 'From here ' + D.target + ' misses the Moon by ' + (gap * 60).toFixed(1) + '′.' : 'The Moon is below the horizon here.') + '</div>';
      summary = r.verdict === 'miss' ? 'near miss, ' + (gap * 60).toFixed(1) + '′' : 'Moon below horizon';
    }
    res.innerHTML = h; res.hidden = false;
    var name = label || placeName(lat, lon, D.cities);
    LOC.name = name;
    chipName.textContent = name; chipSub.textContent = summary; where.textContent = name;
    var x = (lon - P.lon0) * P.k * P.s, y = (P.lat1 - lat) * P.s;
    pin.dataset.x = x.toFixed(1); pin.dataset.y = y.toFixed(1); placePin();
    if (x >= 0 && x <= P.W && y >= 0 && y <= P.H) pin.hidden = false; else pin.hidden = true;
    var old = document.querySelector('tr.yours'); if (old) old.remove();
    var tb = document.querySelector('#city-table tbody'); if (tb) tb.insertAdjacentHTML('afterbegin', tableRow(r, 'Your location · ' + name));
    if (!label) sel.value = '';
    if (!fromUrl) { var u = new URL(location.href); u.search = label ? '?city=' + encodeURIComponent(label) : '?lat=' + lat.toFixed(4) + '&lon=' + lon.toFixed(4); history.replaceState(null, '', u); }
    drawLimb(r);
    if (typeof drawGraze === 'function') drawGraze(r);
    actions(r, name);
  }
  function placePin() { pin.setAttribute('transform', 'translate(' + pin.dataset.x + ',' + pin.dataset.y + ') scale(' + (1 / MZ).toFixed(3) + ')'); }
  // a place the reader chose themselves (the sheet, their location): shown, and remembered for the site's other pages.
  // A tap on the map or a city dot only explores — it does not replace the place they keep.
  function choose(lat, lon, label) {
    show(lat, lon, label);
    try { localStorage.setItem('occult-loc', JSON.stringify({ lat: +LOC.lat, lon: +LOC.lon, label: LOC.name })); } catch (e) {}
    placeAsked();
  }
  // take it with you: this place's occultation into a calendar, or the page for this place to someone else
  var acts = document.getElementById('ev-acts'), actIcs = document.getElementById('act-ics'), actG = document.getElementById('act-gcal'), CAL = null;
  function actions(r, name) {
    acts.hidden = false;
    var c = r.contacts, keys = ['D1', 'D2', 'R1', 'R2'].filter(function (k) {
      return c[k] !== undefined && !(r.seen === 'rises' && k[0] === 'D') && !(r.seen === 'sets' && k[0] === 'R');
    });
    CAL = null;
    if (r.verdict === 'visible' && keys.length) {
      var ms = keys.map(function (k) { return c[k]; }), first = Math.min.apply(null, ms), last = Math.max.apply(null, ms);
      var half = r.seen === 'rises' ? ' (reappearance only: the Moon rises during it)' : r.seen === 'sets' ? ' (disappearance only: the Moon sets during it)' : '';
      CAL = { title: 'The Moon occults ' + D.target, start: T0 + first * 60000 - 10 * 60000, end: T0 + last * 60000 + 5 * 60000,
              details: 'Seen from ' + name + half + '. '
                + (c.D2 !== undefined && r.seen !== 'rises' ? D.target + ' disappears ' + localTime(c.D2, true) + ' ' + D.tzl + '. ' : '')
                + (c.R1 !== undefined && r.seen !== 'sets' ? 'It reappears ' + localTime(c.R1, true) + ' ' + D.tzl + '. ' : '')
                + 'Look ' + lookText(r.at) + '.',
              url: location.href, uid: 'occ-' + location.pathname.slice(1) + '-' + LOC.lat.toFixed(3) + '-' + LOC.lon.toFixed(3),
              file: location.pathname.slice(1) || 'occultation', where: name, alarm: 30 };
      actG.href = Cal.google(CAL);
    }
    actIcs.hidden = actG.hidden = !CAL;
    if (Cal.android && CAL) acts.insertBefore(actG, actIcs);            // Android's calendar is Google's: offer it first
  }
  actIcs.addEventListener('click', function () { if (CAL) { CAL.url = location.href; Cal.ics(CAL); } });
  document.getElementById('act-share').addEventListener('click', function () { Cal.share(this, document.title, location.href); });
  chip.addEventListener('click', function () { sheet.showModal(); });
  sheet.addEventListener('click', function (e) { if (e.target === sheet) sheet.close(); });
  document.getElementById('loc-go').addEventListener('click', function () { choose(latI.value, lonI.value); sheet.close(); });
  [latI, lonI].forEach(function (i) { i.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); choose(latI.value, lonI.value); sheet.close(); } }); });
  var geoBtn = document.getElementById('loc-geo');
  if (!navigator.geolocation) geoBtn.hidden = true;
  geoBtn.addEventListener('click', function () {
    geoBtn.disabled = true; geoBtn.textContent = 'Locating…';
    navigator.geolocation.getCurrentPosition(function (p) { geoBtn.disabled = false; geoBtn.textContent = 'Use my location'; choose(p.coords.latitude, p.coords.longitude); sheet.close(); },
      function () { geoBtn.disabled = false; geoBtn.textContent = 'Location unavailable'; });
  });
  sel.addEventListener('change', function () { var c = D.cities[sel.value]; if (c) { choose(c[0], c[1], sel.value); sheet.close(); } });
  var map = document.getElementById('main-map');
  map.addEventListener('click', function (ev) {
    if (Date.now() - gestureAt < 400) return;
    var pt = map.createSVGPoint(); pt.x = ev.clientX; pt.y = ev.clientY;
    var q = pt.matrixTransform(map.getScreenCTM().inverse());
    var t = ev.target.closest && ev.target.closest('circle[data-city]');
    if (t) { var c = D.cities[t.dataset.city]; show(c[0], c[1], t.dataset.city); }
    else show(P.lat1 - q.y / P.s, P.lon0 + q.x / (P.k * P.s));
  });
  var links = document.querySelectorAll('.subnav-links a'), secs = [].map.call(links, function (a) { return document.getElementById(a.dataset.sec); });
  if ('IntersectionObserver' in window) {
    var io = new IntersectionObserver(function (es) {
      es.forEach(function (e) { if (e.isIntersecting) links.forEach(function (a) { a.classList.toggle('active', a.dataset.sec === e.target.id); }); });
    }, { rootMargin: '-40% 0px -55% 0px' });
    secs.forEach(function (sc) { if (sc) io.observe(sc); });
  }

  // ---- graze profile: the target's track against the real lunar limb for THIS location ----
  var gzCard = document.getElementById('graze-card'), gzBtn = document.getElementById('graze-load'), gzSvg = document.getElementById('graze-svg'), gzOut = document.getElementById('graze-out');
  var LIMB = null, lastR = null;
  function rotMe(m) {   // ICRF -> MOON_ME at t0 + m minutes: the Moon spins about its pole
    var th = LIMB.spin_deg_per_min * m * RAD, c = Math.cos(th), s = Math.sin(th), R0 = LIMB.R_me;
    return [c*R0[0] + s*R0[3], c*R0[1] + s*R0[4], c*R0[2] + s*R0[5], -s*R0[0] + c*R0[3], -s*R0[1] + c*R0[4], -s*R0[2] + c*R0[5], R0[6], R0[7], R0[8]];
  }
  function limbKm(m, g) {   // real limb radius excess (km) at the target's PA, for the observer's libration
    var R = rotMe(m), u = g.mu, o = [-(R[0]*u[0] + R[1]*u[1] + R[2]*u[2]), -(R[3]*u[0] + R[4]*u[1] + R[5]*u[2]), -(R[6]*u[0] + R[7]*u[1] + R[8]*u[2])];
    var lat = Math.asin(o[2]) / RAD, lon = Math.atan2(o[1], o[0]) / RAD;
    var dlat = lat - LIMB.sub_earth[0], dlon = ((lon - LIMB.sub_earth[1] + 540) % 360) - 180;
    var n = LIMB.nodes, h = (n - 1) / 2, fi = Math.max(0, Math.min(n - 1.0001, dlat / LIMB.node_step + h)), fj = Math.max(0, Math.min(n - 1.0001, dlon / LIMB.node_step + h));
    var i0 = Math.floor(fi), j0 = Math.floor(fj), a = fi - i0, b = fj - j0;
    var pa = ((Math.atan2(g.east, g.north) / RAD) + 360) % 360, k = pa / LIMB.pa_step, k0 = Math.floor(k) % 3600, k1 = (k0 + 1) % 3600, c = k - Math.floor(k);
    function P(i, j) { var p = LIMB.profiles[i][j]; return (p[k0] * (1 - c) + p[k1] * c) / 100; }
    return (P(i0, j0) * (1-a) * (1-b) + P(i0+1, j0) * a * (1-b) + P(i0, j0+1) * (1-a) * b + P(i0+1, j0+1) * a * b);
  }
  function drawGraze(r) {
    lastR = r; if (!LIMB) return;
    var geom = r.geom, c = r.contacts, centers = [];
    if (c.D2 !== undefined || c.D1 !== undefined) centers.push({ m: (c.D1 !== undefined ? c.D1 : c.D2), label: 'disappearance' });
    if (c.R1 !== undefined || c.R2 !== undefined) centers.push({ m: (c.R2 !== undefined ? c.R2 : c.R1), label: 'reappearance' });
    if (!centers.length) centers.push({ m: r.closest.m, label: 'closest approach' });
    if (centers.length === 2 && centers[1].m - centers[0].m < 14) centers = [{ m: (centers[0].m + centers[1].m) / 2, label: 'graze' }];
    var g0c = geom(centers[0].m), tKm = Math.tan(g0c.sdt * RAD) * g0c.mdist;     // the target's radius, km at the Moon
    var W = 800, H = 230, pad = 34, HALF = 6, KM = Math.max(6, Math.ceil(tKm * 1.6 / 5) * 5), sy = (H - 2 * pad) / (2 * KM), kstep = KM > 10 ? 10 : 2;
    while (gzSvg.firstChild) gzSvg.removeChild(gzSvg.firstChild);
    var panels = centers.length, pw = W / panels, notes = [];
    centers.forEach(function (cen, pi) {
      var gx = pi * pw, sxp = (pw - 2 * pad) / (2 * HALF);
      var terrain = [], star = [], top = [], bot = [], events = [], prevSt = null;
      function Y(v) { return Math.max(pad - 8, Math.min(H - pad + 8, H - pad - (v + KM) * sy)); }
      for (var dm = -HALF; dm <= HALF; dm += 2 / 60) {
        var m = cen.m + dm, g = geom(m), km = limbKm(m, g);
        var rt = Math.tan(g.sep * RAD) * g.mdist - 1737.4;          // target centre above the mean sphere, km
        var x = gx + pad + (dm + HALF) * sxp;
        terrain.push(x.toFixed(1) + ',' + Math.max(pad, Math.min(H - pad, H - pad - (km + KM) * sy)).toFixed(1));
        star.push(x.toFixed(1) + ',' + Y(rt).toFixed(1));
        if (tKm > 0.5) { top.push(x.toFixed(1) + ',' + Y(rt + tKm).toFixed(1)); bot.unshift(x.toFixed(1) + ',' + Y(rt - tKm).toFixed(1)); }
        var st = rt + tKm < km ? 2 : (rt - tKm < km ? 1 : 0);        // 2 fully hidden, 1 partly, 0 clear
        if (prevSt !== null && st !== prevSt) events.push({ m: m, from: prevSt, to: st });
        prevSt = st;
      }
      var g0 = el('rect', { x: gx + pad, y: pad, width: pw - 2 * pad, height: H - 2 * pad, class: 'gz-sky' }); gzSvg.appendChild(g0);
      gzSvg.appendChild(el('polygon', { class: 'gz-terrain', points: terrain.join(' ') + ' ' + (gx + pw - pad).toFixed(1) + ',' + (H - pad) + ' ' + (gx + pad).toFixed(1) + ',' + (H - pad) }));
      gzSvg.appendChild(el('line', { x1: gx + pad, x2: gx + pw - pad, y1: H - pad - KM * sy, y2: H - pad - KM * sy, class: 'gz-mean' }));
      if (top.length) gzSvg.appendChild(el('polygon', { class: 'gz-disc', points: top.concat(bot).join(' ') }));
      gzSvg.appendChild(el('polyline', { class: 'gz-star', points: star.join(' ') }));
      for (var k = -KM; k <= KM; k += kstep) { var t = el('text', { x: gx + pad - 4, y: H - pad - (k + KM) * sy + 3, 'text-anchor': 'end', class: 'gz-lbl' }); t.textContent = (k > 0 ? '+' : '') + k; gzSvg.appendChild(t); }
      for (var mm = -HALF; mm <= HALF; mm += 2) { var t2 = el('text', { x: gx + pad + (mm + HALF) * sxp, y: H - pad + 14, 'text-anchor': 'middle', class: 'gz-lbl' }); t2.textContent = localTime(cen.m + mm, false); gzSvg.appendChild(t2); }
      var cap = el('text', { x: gx + pw / 2, y: pad - 10, 'text-anchor': 'middle', class: 'gz-cap' }); cap.textContent = cen.label; gzSvg.appendChild(cap);
      events.forEach(function (e) {
        var x = gx + pad + (e.m - cen.m + HALF) * sxp;
        gzSvg.appendChild(el('line', { x1: x, x2: x, y1: pad, y2: H - pad, class: 'gz-ev' }));
        var nm = e.to > e.from ? (e.to === 2 ? 'D2' : 'D1') : (e.to === 0 ? 'R2' : 'R1');
        notes.push(nm + ' ' + localTime(e.m, true));
      });
    });
    // how much a step north moves the track on this chart
    var probe = solve(LOC.lat + 0.009, LOC.lon), m0 = centers[0].m, g1 = geom(m0), g2 = probe.geom(m0);
    var shift = (Math.tan(g2.sep * RAD) * g2.mdist - Math.tan(g1.sep * RAD) * g1.mdist);
    gzOut.textContent = (notes.length ? notes.join(' · ') + ' (' + D.tzl + ', real limb). ' : 'No contact with the real limb from here. ')
      + 'Moving 1 km north shifts the track by ' + (shift > 0 ? '+' : '') + shift.toFixed(2) + ' km on this chart.';
  }
  gzBtn.addEventListener('click', function () {
    gzBtn.disabled = true; gzBtn.textContent = 'Loading limb…';
    fetch(gzBtn.dataset.src).then(function (r) { return r.json(); }).then(function (j) { LIMB = j; gzBtn.hidden = true; gzSvg.hidden = false; if (lastR) drawGraze(lastR); })
      .catch(function () { gzBtn.disabled = false; gzBtn.textContent = 'Could not load the limb profile'; });
  });

  // ---- limb diagram ----
  var svg = document.getElementById('limb-svg'), slider = document.getElementById('limb-slider'), readout = document.getElementById('limb-readout');
  var NS = 'http://www.w3.org/2000/svg', RM = 150, track = null;
  function el(n, a, txt) { var e = document.createElementNS(NS, n); for (var k in a) e.setAttribute(k, a[k]); if (txt) e.textContent = txt; return e; }
  function xy(g) { return { x: -g.east / g.sdm / 60 * RM, y: -g.north / g.sdm / 60 * RM }; }
  function craterPath(m) {   // IAU crater rims projected with the event's libration + pole angle; north up, east left
    if (!D.lib || !D.craters) return '';
    var L = D.lib, x = (m - L.t0_offset_min) / L.step_min, n = L.samples.length, DG = Math.PI / 180;
    var k0 = Math.max(0, Math.min(n - 2, Math.floor(x))), f = Math.max(0, Math.min(1, x - k0));
    function lerp(a, b, wrap) { var dd = b - a; if (wrap) dd = ((dd + 540) % 360) - 180; return a + dd * f; }
    var A = L.samples[k0], B = L.samples[k0 + 1];
    var la0 = lerp(A[0], B[0]) * DG, lo0 = lerp(A[1], B[1], true) * DG, P = lerp(A[2], B[2], true) * DG, cP = Math.cos(P), sP = Math.sin(P);
    var E0 = [-Math.sin(lo0), Math.cos(lo0), 0], N0 = [-Math.sin(la0) * Math.cos(lo0), -Math.sin(la0) * Math.sin(lo0), Math.cos(la0)];
    var U0 = [Math.cos(la0) * Math.cos(lo0), Math.cos(la0) * Math.sin(lo0), Math.sin(la0)], d = [];
    D.craters.forEach(function (c) {
      var la = c[0] * DG, lo = c[1] * DG, a = c[2] / 2 / 1737.4, ca = Math.cos(a), sa = Math.sin(a);
      var C = [Math.cos(la) * Math.cos(lo), Math.cos(la) * Math.sin(lo), Math.sin(la)];
      if (dot(C, U0) < -sa) return;
      var U = [-Math.sin(lo), Math.cos(lo), 0], W = [-Math.sin(la) * Math.cos(lo), -Math.sin(la) * Math.sin(lo), Math.cos(la)], pen = false;
      for (var k = 0; k <= 28; k++) {
        var t = k / 28 * 2 * Math.PI, ct = Math.cos(t) * sa, st = Math.sin(t) * sa;
        var v = [C[0] * ca + U[0] * ct + W[0] * st, C[1] * ca + U[1] * ct + W[1] * st, C[2] * ca + U[2] * ct + W[2] * st];
        if (dot(v, U0) <= 0) { pen = false; continue; }
        var xi = dot(v, E0), eta = dot(v, N0), no = eta * cP + xi * sP, ea = eta * sP - xi * cP;
        d.push((pen ? 'L' : 'M') + (-ea * RM).toFixed(1) + ' ' + (-no * RM).toFixed(1)); pen = true;
      }
    });
    return d.join('');
  }
  function drawLimb(r) {
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    var mid = (r.contacts.D2 !== undefined && r.contacts.R1 !== undefined) ? (r.contacts.D2 + r.contacts.R1) / 2 : r.ref;
    track = { geom: r.geom, m0: mid - 80, span: 160, r: r };
    slider.max = track.span; slider.value = 80;
    var k = D.illum, b = RM * Math.abs(2 * k - 1), sweep = k > 0.5 ? 1 : 0, cd = craterPath(mid);
    var litT = 'rotate(' + (-D.bright_pa) + ')', litD = 'M ' + (-RM) + ' 0 A ' + RM + ' ' + RM + ' 0 0 1 ' + RM + ' 0 A ' + RM + ' ' + b + ' 0 0 ' + sweep + ' ' + (-RM) + ' 0 Z';
    svg.appendChild(el('circle', { class: 'disc-dark', r: RM }));
    if (cd) svg.appendChild(el('path', { class: 'crater crater-night', d: cd }));
    svg.appendChild(el('path', { class: 'disc-bright', transform: litT, d: litD }));
    if (cd) {
      var defs = el('defs', {}), clip = el('clipPath', { id: 'lit-clip' });
      clip.appendChild(el('path', { transform: litT, d: litD })); defs.appendChild(clip); svg.appendChild(defs);
      svg.appendChild(el('path', { class: 'crater crater-day', d: cd, 'clip-path': 'url(#lit-clip)' }));
    }
    svg.appendChild(el('circle', { class: 'disc-edge', r: RM }));
    svg.appendChild(el('text', { class: 'lbl', x: 0, y: -RM - 8, 'text-anchor': 'middle' }, 'N'));
    svg.appendChild(el('text', { class: 'lbl', x: -RM - 8, y: 4, 'text-anchor': 'end' }, 'E'));
    var pts = [];
    for (var m = 0; m <= track.span; m += 2) { var p = xy(r.geom(track.m0 + m)); pts.push(p.x.toFixed(1) + ',' + p.y.toFixed(1)); }
    svg.appendChild(el('polyline', { class: 'track', points: pts.join(' ') }));
    ['D1', 'D2', 'R1', 'R2'].forEach(function (kk) {
      if (r.contacts[kk] === undefined) return;
      var p = xy(r.geom(r.contacts[kk]));
      svg.appendChild(el('circle', { class: 'contact', cx: p.x, cy: p.y, r: 3 }));
      if (kk === 'D2' || kk === 'R1')
        svg.appendChild(el('text', { class: 'lbl', x: p.x + (kk[0] === 'D' ? 6 : -6), y: p.y - 6, 'text-anchor': kk[0] === 'D' ? 'start' : 'end' }, kk[0] + ' ' + localTime(r.contacts[kk], true)));
    });
    if (r.verdict !== 'visible') svg.appendChild(el('text', { class: 'miss-note', x: 0, y: RM + 28, 'text-anchor': 'middle' },
      r.verdict === 'miss' ? D.target + ' passes outside the limb from here' : 'Moon below the horizon here'));
    var sdt = r.at.sdt, sdm = r.at.sdm;
    svg.appendChild(el('circle', { id: 'limb-target', class: 'target', r: Math.max(2.5, sdt / sdm * RM) }));
    update();
  }
  function update() {
    if (!track) return;
    var m = track.m0 + (+slider.value), g = track.geom(m), p = xy(g), t = document.getElementById('limb-target');
    t.setAttribute('cx', p.x); t.setAttribute('cy', p.y);
    t.style.opacity = g.sep < g.sdm - g.sdt ? 0.25 : 1;
    readout.textContent = localTime(m, true) + ' ' + D.tzl + ' · Moon ' + (g.altm > 0 ? g.altm.toFixed(0) + '° up, ' + compass(g.azm) : 'below horizon');
  }
  slider.addEventListener('input', update);
  // ---- the map under two fingers: pinch to zoom, move them to pan; once zoomed in, one finger moves it too. At full size one
  // finger scrolls the page and a tap sets a place, as before. Only the map zooms, never the page.
  (function () {
    var W0 = P.W, H0 = P.H, vx = 0, vy = 0, vw = W0, pts = {}, g = null, moved = false, reset = document.getElementById('map-reset');
    var circles = [].slice.call(map.querySelectorAll('circle.city')), r0 = circles.length ? +circles[0].getAttribute('r') : 4;
    function view(x, y, w) {
      w = Math.max(W0 / 10, Math.min(W0, w));
      var h = w * H0 / W0;
      vx = Math.max(0, Math.min(W0 - w, x)); vy = Math.max(0, Math.min(H0 - h, y)); vw = w; MZ = W0 / w;
      map.setAttribute('viewBox', vx.toFixed(2) + ' ' + vy.toFixed(2) + ' ' + w.toFixed(2) + ' ' + h.toFixed(2));
      map.style.setProperty('--z', MZ.toFixed(3));
      map.style.touchAction = MZ > 1.01 ? 'none' : 'pan-y';
      circles.forEach(function (c) { c.setAttribute('r', (r0 / MZ).toFixed(2)); });
      if (pin.dataset.x) placePin();
      reset.hidden = MZ <= 1.01;
    }
    function begin() {
      var ids = Object.keys(pts), rect = map.getBoundingClientRect(), k = vw / rect.width;
      if (ids.length >= 2) {
        var a = pts[ids[0]], b = pts[ids[1]], mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2;
        g = { pinch: true, d: Math.hypot(a[0] - b[0], a[1] - b[1]) || 1, w: vw, sx: vx + (mx - rect.left) * k, sy: vy + (my - rect.top) * k };
      } else if (ids.length === 1 && MZ > 1.01) {
        g = { pinch: false, cx: pts[ids[0]][0], cy: pts[ids[0]][1], x: vx, y: vy, k: k };
      } else g = null;
    }
    map.addEventListener('pointerdown', function (e) {
      if (e.pointerType !== 'touch') return;
      pts[e.pointerId] = [e.clientX, e.clientY];
      begin();
    });
    map.addEventListener('pointermove', function (e) {
      if (!pts[e.pointerId] || !g) return;
      pts[e.pointerId] = [e.clientX, e.clientY];
      var ids = Object.keys(pts), rect = map.getBoundingClientRect();
      if (g.pinch && ids.length >= 2) {
        var a = pts[ids[0]], b = pts[ids[1]], w = g.w * g.d / (Math.hypot(a[0] - b[0], a[1] - b[1]) || 1), k = w / rect.width;
        view(g.sx - ((a[0] + b[0]) / 2 - rect.left) * k, g.sy - ((a[1] + b[1]) / 2 - rect.top) * k, w);
        moved = true;
      } else if (!g.pinch) {
        var dx = e.clientX - g.cx, dy = e.clientY - g.cy;
        if (Math.abs(dx) + Math.abs(dy) > 6) { view(g.x - dx * g.k, g.y - dy * g.k, vw); moved = true; }
      }
    });
    function end(e) {   // the click a lifted finger leaves behind is not a tap: time it from the lift, however long they held still
      if (!pts[e.pointerId]) return;
      delete pts[e.pointerId];
      if (moved) gestureAt = Date.now();
      if (!Object.keys(pts).length) moved = false;
      begin();
    }
    map.addEventListener('pointerup', end);
    map.addEventListener('pointercancel', end);
    reset.addEventListener('click', function () { view(0, 0, W0); });
  })();
  var qs = new URLSearchParams(location.search), qc = qs.get('city'), saved = null;
  try { saved = JSON.parse(localStorage.getItem('occult-loc')); } catch (e) {}
  if (qc && D.cities[qc]) show(D.cities[qc][0], D.cities[qc][1], qc, true);
  else if (qs.get('lat') && qs.get('lon')) show(qs.get('lat'), qs.get('lon'), '', true);
  else if (saved && isFinite(saved.lat) && isFinite(saved.lon)) show(saved.lat, saved.lon, D.cities[saved.label] ? saved.label : '', true);
  else {
    var first = sel.options[1];
    if (first) { var c0 = D.cities[first.value]; show(c0[0], c0[1], first.value, true); }
    askPlace(LOC ? LOC.name : '', function (lat, lon) { choose(lat, lon); });
  }
})();
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
    def seen_times(c):   # the contacts with the Moon above the horizon: "watch from" shouldn't start before moonrise
        _, at = horizon_split(data, c)
        return [parse(v) for k, v in c["contacts"].items() if at[k][0] > 0]
    first_d = min(min(seen_times(c)) for c in vis) if vis else None
    last_r = max(max(seen_times(c)) for c in vis) if vis else None
    max_hidden = max((c.get("hidden_min", 0) for c in vis), default=0)
    longest = max(vis, key=lambda c: c.get("hidden_min", 0)) if vis else None
    near_miss = min(misses, key=lambda c: c["sep_arcmin"] - c["moon_sd_arcmin"]) if misses else None

    title = f"The Moon occults {tname} — {t_min_local.strftime('%-d %B %Y')}"
    n_day = sum(1 for c in vis if c["sun_alt"] > -6)
    if vis:
        sky = ("in daylight" if n_day == len(vis) else "in a dark sky" if n_day == 0 else "in daylight for some, after sunset for others")
        auto_note = (f"The Moon hides {tname} for up to {max_hidden:.0f} minutes, {sky}. "
                     + (f"{len(vis)} of the {len(cities)} listed Indian cities {'sees' if len(vis) == 1 else 'see'} it" if aud["cities"] != "world" else
                      f"{len(vis)} of the world's big cities {'sees' if len(vis) == 1 else 'see'} it")
                     + (f"; {esc(near_miss['name'])} misses by {near_miss['sep_arcmin'] - near_miss['moon_sd_arcmin']:.1f}′." if near_miss else "."))
    else:
        auto_note = "No large city sees this one. The map shows where it's visible." 
    kind = "planet" if data["target"]["kind"] == "graha" else "star"
    h1 = f"Lunar occultation of the {kind} {tname}"
    for_whom = "the world's big cities" if aud["cities"] == "world" else aud["label"]
    desc = (f"Where and when the Moon hides {tname} on {t_min_local.strftime('%-d %B %Y')}: "
            f"times for {for_whom}, the graze-limit map, and how to watch. "
            f"Computed from the JPL DE431 ephemeris.")
    url = f"{SITE}/{slug}"

    tips = ""
    if data["target"]["key"] == "venus" and vis and max(c["sun_alt"] for c in vis) > 0:
        ip = g.get("target_illum_pct") or 50
        shape = ("thin crescent" if ip < 25 else "fat crescent" if ip < 45 else
                 "half-lit disc" if ip < 55 else "gibbous disc" if ip < 95 else "nearly full disc")
        shape += f" ({2 * g['target_sd_arcsec']:.0f}″ across, {ip}% lit)"
        tips = f"""
      <p>This one happens in <strong>daylight</strong>. Venus shows in a blue sky if you know where to look,
      and today the thin crescent Moon points the way, 40° east of the Sun. Find the crescent first (shade
      the Sun with a building), then look for a hard white point by its <em>dark</em> edge. Binoculars make
      it easy. A telescope shows Venus as a {shape}, slipping behind the Moon's dark edge and
      reappearing at the bright one an hour later.</p>
      <p>The disappearance is harder to catch: Venus vanishes into the dark edge, which looks like empty sky.
      The reappearance at the sunlit crescent is the easy, striking half. Never sweep near the Sun with
      binoculars.</p>"""

    limit_para = ""
    if near_miss:
        gap = near_miss["sep_arcmin"] - near_miss["moon_sd_arcmin"]
        exact_note = ""
        ex = data["maps"][data["audience"]].get("limits_exact")
        if ex:
            sh = ex[0].get("shift_km") or {}
            exact_note = (f" The solid line uses the Moon's real, mountainous edge. It lies {sh.get('min', 0):+.1f} to "
                          f"{sh.get('max', 0):+.1f} km from the smooth-sphere line (dotted).")
        limit_para = (f"<p>The gold line is the <strong>north limit</strong>: along it {tname} grazes the Moon's "
                      f"northern edge. North of the line, {tname} misses: from {esc(near_miss['name'])} it passes "
                      f"{gap:.1f}′ outside the Moon. Right on the line it grazes, blinking behind lunar mountains.{exact_note}</p>")
    night_para = ""
    if data["maps"][data["audience"]]["region_night"]:
        night_para = "<p>In the violet area the Sun has set, so the reappearance is in a darkening sky.</p>"

    india = aud["cities"] != "world"
    def place(name):   # world cities are named "Shanghai, CN"; India's carry no country
        city, cc = (name, "IN") if india else name.rsplit(", ", 1)
        return {"@type": "Place", "name": city,
                "address": {"@type": "PostalAddress", "addressLocality": city, "addressCountry": cc}}
    vis_names = {c["name"] for c in vis}
    # the headline cities that see it; with none, the whole audience (no address for "World": no city sees it)
    location = ([place(n) for n in featured if n in vis_names]
                or {"@type": "Place", "name": aud["label"],
                    **({"address": {"@type": "PostalAddress", "addressCountry": "IN"}} if india else {})})
    # no "performer": nobody performs an occultation, and Google only recommends the field
    ld = {
        "@context": "https://schema.org", "@type": "Event",
        "name": title, "description": desc, "url": url, "image": [og_url("occ")],
        "startDate": first_d.astimezone(tz).isoformat() if first_d else t_min_local.isoformat(),
        "endDate": last_r.astimezone(tz).isoformat() if last_r else t_min_local.isoformat(),
        "eventStatus": "https://schema.org/EventScheduled",
        "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        "location": location,
        "organizer": {"@type": "Organization", "name": SITE_NAME, "url": SITE},
        "isAccessibleForFree": True,
        "offers": {"@type": "Offer", "price": "0", "priceCurrency": "INR" if india else "USD",
                   "availability": "https://schema.org/InStock", "url": url, "validFrom": data["generated"]},
    }

    p_main = Proj(geo["bbox"], aud["lat0"], 800)
    graze_block = ""
    if (ROOT / "data" / f"{slug}-limb.json").exists():
        graze_block = f"""  <details class="advanced" id="graze">
    <summary>Advanced · graze profile against the real lunar limb</summary>
    <p class="hint">For graze chasers. The Moon's real edge as you see it, from LRO LOLA terrain, with {esc(tname)}'s
    track for six minutes around each contact. Where the track dips below the terrain, {esc(tname)} is hidden; near a
    graze it blinks behind peaks.</p>
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
        # featured cities first, then the rest by name: the page builds its dropdown from this, in this order
        "cities": {c["name"]: [c["lat"], c["lon"]] for c in feat_rows + rest_rows},
    }

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
             f'<th title="Height and direction of the Moon at the contact you can see (0° = horizon, 90° = overhead), and whether the sky is light or dark">Where to look</th></tr>')

    page = head(f"{title} · {SITE_NAME}", desc, f"/{slug}",
                f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>', og="occ") + f"""
<nav class="subnav" id="subnav">
  <div class="subnav-row">
    <div class="subnav-links">
      <a href="#map" data-sec="map">Map</a><a href="#moon" data-sec="moon">Moon</a><a href="#cities" data-sec="cities">Cities</a><a href="#watch" data-sec="watch">Watch</a>
    </div>
    <button class="chip" id="loc-chip" type="button" aria-haspopup="dialog"><span class="chip-pin">📍</span><span id="chip-name">Choose location</span><span class="chip-sub" id="chip-sub"></span></button>
  </div>
</nav>
<dialog id="loc-sheet" class="sheet" aria-label="Location">
  <form method="dialog" class="sheet-body">
    <div class="sheet-title">Location</div>
    <label>City <select id="limb-city"><option value="">—</option></select></label>
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
    <button class="btn map-reset" id="map-reset" type="button" hidden>Reset zoom</button>
    {svg_map(data, geo, aud, cities, featured)}
    <div class="legend">
      <span class="lg-region">sees the occultation</span>
      {'<span class="lg-night">after sunset</span>' if data["maps"][data["audience"]]["region_night"] else ''}
      <span class="lg-limit">graze limit</span>
      <span class="lg-visible">city sees it</span>
      <span class="lg-miss">near miss</span>
    </div>
    {svg_map(data, geo_world, seed["audiences"]["world"], cities, [], width=360, inset=True) if data["audience"] != "world" else ""}
  </div>
  {limit_para}
  {night_para}
  <p class="hint">Tap the map to set your location; pinch it to zoom in. Take the graze line with you:
  <a href="/kml/{slug}.kml">KML</a> for Google Earth / Maps · <a href="/kml/{slug}.gpx">GPX</a> for a phone GPS app.</p>

  <h2 id="moon">At the Moon's edge</h2>
  <div class="limb-card">
    <div class="limb-controls"><span id="limb-where" class="limb-readout"></span><span class="limb-readout" id="limb-readout"></span></div>
    <div class="loc-result" id="loc-result" hidden></div>
    <div class="acts" id="ev-acts" hidden><button class="btn" id="act-ics" type="button">Add to calendar</button><a class="btn" id="act-gcal" href="#" target="_blank" rel="noopener">Google Calendar</a><button class="btn" id="act-share" type="button">Share</button></div>
    <svg id="limb-svg" viewBox="-190 -190 380 380" class="limb-svg" role="img" aria-label="The Moon's disc with the target's path"></svg>
    <input type="range" id="limb-slider" min="0" max="160" value="80" step="1" aria-label="Time">
  </div>
  <p class="hint">{esc(tname)}'s path across the Moon from your location. North up, east left, as in binoculars.
  Times here are computed in your browser from the same ephemeris as the table, to the same ±2 s. Drag the slider to move it along its track.</p>
  <script type="application/json" id="limb-data">{json.dumps(limb, ensure_ascii=False, separators=(",", ":"))}</script>

  {graze_block}

  <h2 id="cities">City by city</h2>
  <p>Times are against the real lunar limb (LRO LOLA terrain at each city's own libration). <em>Disappears</em>: {esc(tname)} is fully hidden
  (it starts sliding in at the earlier time). <em>Reappears</em>: the first sliver returns. <em>Where to look</em>:
  the Moon's height (0° horizon, 90° overhead), its direction, and whether the Sun is up.</p>
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
  City times and the solid limit line use the <strong>real lunar limb</strong>: LRO LOLA terrain (LDEM_64, ~0.5 km)
  as each observer sees it. That changes times by a few seconds, or tens of seconds near a graze. The
  any-location solver in your browser and the shaded region still use the mean sphere of {data['engine']['moon_radius_km']} km (±2 s). {esc(tname)}'s own disc
  ({2 * g['target_sd_arcsec']:.0f}″ across) is included: partial contacts are the <small>from/to</small> times.
  The numbers behind this page: <a href="/data/{slug}.json">{slug}.json</a>.
  Generated {data['generated'][:10]}.</p>
</main>

{FOOTER}
<script src="{site_js_url()}"></script>
<script src="{asset('js/occultation.js', OCC_JS)}"></script>
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
    .hero h1 { letter-spacing: -0.028em !important; line-height: 1.06; }
    .tile-title, .kind-head h2 { letter-spacing: -0.015em !important; }
    /* The plate: night whatever the theme. Stars drift west behind a waxing Moon, go out at its dark limb and come back at
       the bright one. Only transforms and opacity of whole elements move, so the browser's compositor does all of it. */
    .hero { position: relative; isolation: isolate; overflow: hidden; margin-top: 0.3rem; border: 1px solid #262f45; border-radius: 22px;
            padding: 2.4rem 2rem 2rem; min-height: 330px; display: flex; flex-direction: column; justify-content: center;
            background: var(--stars) 0 0 / 640px 640px, radial-gradient(85% 120% at 80% 48%, #17203a, #0e1322 50%, #080a11);
            box-shadow: 0 30px 60px -36px rgba(8,12,28,0.9); }
    .hero-scene { position: absolute; z-index: -1; inset: 0 0 0 auto; aspect-ratio: 600 / 340; }
    .hero-drift { position: absolute; inset: 0; overflow: hidden;
                  -webkit-mask-image: linear-gradient(90deg, transparent 6%, #000 40%); mask-image: linear-gradient(90deg, transparent 6%, #000 40%); }
    .hero-drift svg { position: absolute; left: -50%; top: 0; width: 150%; height: 100%; animation: drift 30s linear infinite; }
    @keyframes drift { to { transform: translateX(33.3333%); } }
    .hero-moon { position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible; }
    .ping { position: absolute; width: 16px; height: 16px; margin: -8px 0 0 -8px; border-radius: 50%; border: 1.5px solid #f6c768; opacity: 0; animation: ping 30s linear infinite; }
    .ping-r { border-color: #fff6dd; }
    @keyframes ping { 0% { opacity: 0.95; transform: scale(0.3); } 4%, 100% { opacity: 0; transform: scale(2.4); } }
    .hero-text { max-width: min(31rem, 56%); }
    .hero h1 { margin: 0 0 0.6rem; color: #f6f1e4; font-weight: 500; letter-spacing: -0.015em; }
    .hero .sub { font-size: 1.02rem; }
    .typenav { display: flex; flex-wrap: wrap; gap: 0.4rem; margin: 1.1rem 0 0; }
    .typenav a { display: inline-flex; align-items: center; gap: 0.4rem; border: 1px solid rgba(255,255,255,0.16); border-radius: 999px;
                 padding: 0.25rem 0.75rem 0.25rem 0.4rem; font-size: 0.85rem; color: var(--text); background: rgba(255,255,255,0.06);
                 transition: border-color 0.15s, background 0.15s; }
    .typenav a:hover { border-color: var(--tc); background: color-mix(in srgb, var(--tc) 14%, transparent); text-decoration: none; }
    .typenav svg { width: 22px; height: 22px; color: var(--tc); flex: none; }
    @media (max-width: 640px) {
      .hero { display: block; padding: 0 1.2rem 1.4rem; min-height: 0; border-radius: 18px; }
      .hero-scene { position: relative; inset: auto; width: calc(100% + 2.4rem); margin: 0 -1.2rem -1.6rem; }
      .hero-text { max-width: none; }
    }
    /* an icon lives in an eyepiece: a round field of night with a ring in the kind's colour */
    .lens { flex: none; display: grid; place-items: center; width: 54px; aspect-ratio: 1; border-radius: 50%; overflow: hidden; color: var(--tn);
            background: radial-gradient(circle at 36% 30%, #1d2742, #0b0e17 72%);
            box-shadow: inset 0 0 0 1.5px color-mix(in srgb, var(--tn) 60%, transparent), 0 0 0 4px color-mix(in srgb, var(--tn) 13%, transparent); }
    .lens svg { width: 74%; height: 74%; overflow: visible; }
    .upnext { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0.65rem; margin: 0.5rem 0; }
    @media (max-width: 700px) { .upnext { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
    .tile { display: flex; flex-direction: column; gap: 0.1rem; border: 1px solid var(--border); border-radius: 16px; padding: 0.9rem 0.95rem 1rem; color: var(--text);
            background: radial-gradient(130% 90% at 0 0, color-mix(in srgb, var(--tc) 11%, transparent), transparent 62%), var(--card);
            box-shadow: var(--shadow); transition: transform 0.18s, border-color 0.18s, box-shadow 0.18s; }
    .tile:hover { text-decoration: none; border-color: var(--tc); transform: translateY(-2px); box-shadow: 0 0 0 1px var(--tc), 0 18px 34px -22px var(--tc); }
    .tile > .lens { margin: 0 0 0.65rem 4px; }
    .tile-kicker { font-size: 0.68rem; letter-spacing: 0.07em; text-transform: uppercase; color: var(--tc); font-weight: 600; }
    .tile-title { font-family: var(--display); font-weight: 500; font-size: 1.08rem; line-height: 1.25; }
    .tile-detail { color: var(--muted); font-size: 0.8rem; line-height: 1.35; margin-top: 0.1rem; }
    .tile-main { grid-column: 1 / -1; display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: 0.2rem 1.1rem; padding: 1.05rem 1.2rem; }
    .tile-main > .lens { width: 76px; margin: 0 4px; }
    .tile-body { display: flex; flex-direction: column; gap: 0.1rem; min-width: 0; }
    .tile-main .tile-title { font-size: 1.5rem; line-height: 1.15; }
    .tile-in { font-family: var(--display); font-weight: 500; font-size: 1.05rem; color: var(--tc); white-space: nowrap;
               border: 1px solid color-mix(in srgb, var(--tc) 45%, transparent); border-radius: 999px; padding: 0.2rem 0.85rem; }
    .tile-in:empty { display: none; }
    @media (max-width: 520px) { .tile-main { grid-template-columns: auto 1fr; padding: 0.95rem; } .tile-main > .lens { width: 60px; margin: 0 4px 0 4px; }
                                .tile-main .tile-title { font-size: 1.25rem; } .tile-in { grid-column: 2; justify-self: start; font-size: 0.9rem; margin-top: 0.3rem; } }
    /* the icons act out their event, in the tiles only: a star goes behind the Moon, stars twinkle, an asteroid crosses its
       star, Jupiter's moons shuttle, a moon crosses Saturn */
    .tile .i-occ { animation: i-occ 10s linear infinite; }
    @keyframes i-occ { from { transform: translate(10px, -4.5px); } to { transform: translate(-38px, 17px); } }
    .tile .i-tw { animation: twinkle 3.2s ease-in-out infinite; transform-box: fill-box; transform-origin: center; }
    .tile .i-tw.b { animation-delay: -1.1s; } .tile .i-tw.c { animation-delay: -2.2s; }
    .tile .i-rock { animation: i-rock 9s linear infinite; }
    .tile .i-blink { animation: i-blink 9s linear infinite; }
    @keyframes i-rock { 0% { transform: translate(-9px, 5.3px); opacity: 0; } 12%, 88% { opacity: 1; } 100% { transform: translate(23px, -13.5px); opacity: 0; } }
    @keyframes i-blink { 0%, 64% { opacity: 1; } 65%, 82% { opacity: 0.1; } 83%, 100% { opacity: 1; } }
    .tile .i-j { animation: i-shut var(--p) ease-in-out infinite alternate; }
    @keyframes i-shut { from { transform: translateX(calc(0px - var(--d))); } to { transform: translateX(var(--d)); } }
    .tile .i-sat { animation: i-sat 7s ease-in-out infinite alternate; }
    @keyframes i-sat { to { transform: translate(-28px, 20px); } }
    .kind { margin: 2.6rem 0 0; padding-top: 1.4rem; scroll-margin-top: 12px;
            background: linear-gradient(90deg, var(--tc, var(--line)), transparent 70%) 0 0 / 100% 1px no-repeat; }
    .kind-head { display: grid; grid-template-columns: 62px 1fr; gap: 0.2rem 1rem; align-items: start; }
    .kind-head .lens { width: 62px; grid-row: span 3; margin-top: 0.15rem; }
    .kind-head h2 { margin: 0; font-family: var(--display); font-size: 1.6rem; font-weight: 500; letter-spacing: -0.005em; text-transform: none; color: var(--text); overflow: visible; }
    .kind-head h2::after { content: none; }
    .kind-what { margin: 0.15rem 0 0; }
    .kind-facts { display: flex; flex-wrap: wrap; gap: 0.25rem 1.1rem; margin: 0.35rem 0 0; padding: 0; list-style: none; font-size: 0.82rem; color: var(--muted); }
    .kind-facts b { color: var(--tc); font-weight: 600; }
    @media (max-width: 480px) { .kind-head { grid-template-columns: 48px 1fr; gap: 0.2rem 0.8rem; } .kind-head .lens { width: 48px; } }
    .evlist { list-style: none; margin: 1rem 0 0; border: 1px solid var(--border); border-left: 3px solid var(--tc); border-radius: 14px; background: var(--card); overflow: hidden; padding: 0; box-shadow: var(--shadow); }
    .evlist li + li { border-top: 1px solid var(--border); }
    .evlist .ev a { display: grid; grid-template-columns: 4.4rem 1fr auto; gap: 0.1rem 0.9rem; align-items: center; padding: 0.65rem 0.9rem; color: var(--text); transition: background 0.15s; }
    .evlist .ev a:hover { background: color-mix(in srgb, var(--tc) 9%, var(--card)); text-decoration: none; }
    .ev-date { display: flex; flex-direction: column; line-height: 1.15; }
    .ev-dmy { font-family: var(--display); font-weight: 500; font-size: 1.1rem; font-variant-numeric: tabular-nums; }
    .ev-y { font-size: 0.72rem; color: var(--muted); }
    .ev-what { font-weight: 500; display: block; }
    .ev-note { color: var(--muted); font-size: 0.82rem; display: block; margin-top: 0.1rem; }
    .tags { display: flex; flex-direction: column; align-items: flex-end; gap: 0.2rem; }
    .tag { display: inline-block; font-size: 0.66rem; letter-spacing: 0.05em; text-transform: uppercase; border: 1px solid var(--line); border-radius: 999px; padding: 0 0.45rem; color: var(--muted); }
    .tag-planet { border-color: var(--tc); color: var(--tc); }
    .ev.past a { opacity: 0.45; }
    .ev-more { margin: 0.6rem 0 0; }
    @media (max-width: 560px) { .evlist .ev a { grid-template-columns: 3.8rem 1fr; } .tags { grid-column: 2; flex-direction: row; align-items: center; } .ev-note { display: none; } }
    .this-month { margin: 1rem 0 0; font-size: 0.92rem; }
    .this-month a { font-weight: 600; }
    .yrs { margin: 0.8rem 0 0; display: grid; gap: 0.4rem; }
    .yr { display: grid; grid-template-columns: 2.8rem 1fr; align-items: center; gap: 0.5rem; }
    .yr-label { font-family: var(--display); font-size: 0.9rem; color: var(--muted); font-weight: 500; font-variant-numeric: tabular-nums; }
    .mpills { list-style: none; display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 4px; margin: 0; padding: 0; }
    .mpills a, .mpills span { display: block; text-align: center; font-size: 0.78rem; padding: 0.35rem 0; border-radius: 8px; }
    .mpills a { background: var(--card); border: 1px solid var(--border); color: var(--text); transition: border-color 0.15s, background 0.15s; }
    .mpills a:hover { border-color: var(--tc); background: color-mix(in srgb, var(--tc) 10%, var(--card)); text-decoration: none; }
    .mpills span { color: var(--line); opacity: 0.6; }
    .mo.current a { background: color-mix(in srgb, var(--tc) 20%, var(--card)); border-color: var(--tc); font-weight: 600; box-shadow: 0 0 0 3px color-mix(in srgb, var(--tc) 16%, transparent); }
    .mo.past a { opacity: 0.45; }
    @media (max-width: 560px) { .mpills { grid-template-columns: repeat(6, minmax(0, 1fr)); } }
    .cal-cta { margin: 0.9rem 0 0; }
    /* behind the whole page, fixed while it scrolls: faint stars and two soft washes of colour, so the reading slides over a still sky */
    body::after { content: ""; position: fixed; inset: 0; z-index: -1; pointer-events: none; opacity: 0.5;
                  background: radial-gradient(60vw 55vh at 4% 80%, color-mix(in srgb, var(--t-ms) 17%, transparent), transparent 70%),
                              radial-gradient(55vw 50vh at 98% 48%, color-mix(in srgb, var(--t-jup) 17%, transparent), transparent 70%),
                              var(--stars) 30% 40% / 640px 640px; }
"""

# Each icon's moving part carries a class (i-occ, i-tw, i-rock, i-blink, i-j, i-sat) that only a "Coming up" tile animates;
# everywhere else the icon is the still drawing. Discs that hide something are filled with var(--card) first.
ICONS = {
    # the Moon with a planet at its edge (the planet goes behind)
    "occ": '<svg viewBox="0 0 40 40" aria-hidden="true"><circle class="i-occ" cx="30.5" cy="13" r="4" fill="currentColor"/>'
           '<circle cx="17" cy="21" r="13" fill="var(--card)"/><circle cx="17" cy="21" r="13" fill="currentColor" opacity=".22"/>'
           '<circle cx="17" cy="21" r="13" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>',
    # a crescent and stars
    "ms": '<svg viewBox="0 0 40 40" aria-hidden="true"><path d="M21 6a14 14 0 1 0 12.2 20.8A11.5 11.5 0 1 1 21 6z" fill="currentColor"/>'
          '<circle class="i-tw" cx="31" cy="9" r="1.7" fill="currentColor"/><circle class="i-tw b" cx="36" cy="17" r="1.2" fill="currentColor"/>'
          '<circle class="i-tw c" cx="27" cy="15.5" r="1" fill="currentColor"/></svg>',
    # Jupiter and its four moons
    "jup": '<svg viewBox="0 0 40 40" aria-hidden="true"><circle cx="20" cy="20" r="8.5" fill="currentColor"/>'
           '<path d="M12.2 17.2h15.6M11.6 21.4h16.8" stroke="var(--card)" stroke-width="1.4"/>'
           '<circle class="i-j" style="--d:1.2px;--p:7s" cx="3.5" cy="20" r="1.7" fill="currentColor"/>'
           '<circle class="i-j" style="--d:1.6px;--p:2.3s" cx="8.5" cy="20" r="1.4" fill="currentColor"/>'
           '<circle class="i-j" style="--d:-1.8px;--p:3.4s" cx="31.5" cy="20" r="1.5" fill="currentColor"/>'
           '<circle class="i-j" style="--d:-1.2px;--p:5.2s" cx="37" cy="20" r="1.7" fill="currentColor"/></svg>',
    # Saturn, rings nearly edge-on, a moon
    "sat": '<svg viewBox="0 0 40 40" aria-hidden="true"><ellipse cx="20" cy="20" rx="17" ry="4.2" fill="none" stroke="currentColor" stroke-width="1.6"/>'
           '<circle cx="20" cy="20" r="7.5" fill="currentColor"/><path d="M3 20a17 4.2 0 0 0 34 0" fill="none" stroke="currentColor" stroke-width="1.6"/>'
           '<circle class="i-sat" cx="34" cy="10" r="2.1" fill="currentColor" stroke="var(--card)" stroke-width=".9"/></svg>',
    # a lumpy asteroid in front of a star, and the narrow band of its shadow
    "ast": '<svg viewBox="0 0 40 40" aria-hidden="true"><path d="M3 30.5l34-9M5 37l34-9" stroke="currentColor" stroke-width="1.4" opacity=".55"/>'
           '<g class="i-blink"><circle cx="33.5" cy="6.5" r="2.4" fill="currentColor"/><path d="M33.5 1.5v10M28.5 6.5h10" stroke="currentColor" stroke-width="1"/></g>'
           '<path class="i-rock" d="M10.5 12.2c2.4-4.6 8.2-6.3 12.6-4.4 3.9 1.7 5.6 5.9 4.3 9.8-1.2 3.8-5.1 6.4-9.3 6.1-3.2-.2-5.4-1.3-7-3.5-1.5-2.2-1.9-5.4-.6-8z" fill="currentColor"/></svg>',
}


def lens(k):
    """A kind's icon in its eyepiece: always a round field of night, ringed in the kind's colour."""
    return f'<span class="lens sky">{ICONS[k]}</span>'


def hero_scene():
    """The home page's plate, drawn in a 600 x 340 box: a waxing crescent with earthshine (north up, east left, tipped as
    in an evening sky) and a field of stars drifting west behind it. A star reaching the dark limb goes out at once and
    comes back at the bright limb, which is what every page of the site predicts. The field repeats every P units and
    moves SPEED units a second, so the rings that mark the three bright stars' contacts are timed from the geometry."""
    import math
    import random
    R, CX, CY, P, SPEED = 105, 455, 170, 300, 10
    rnd = random.Random(42)
    stars = "".join(f'<circle cx="{rnd.randrange(P)}" cy="{rnd.randrange(8, 332)}" r="{rnd.choice((0.7, 0.7, 0.9, 1.1, 1.4))}" '
                    f'opacity="{rnd.choice((0.5, 0.65, 0.8, 1))}"/>' for _ in range(30))
    bright = [(40, 118), (150, 212), (245, 160)]
    stars += "".join(f'<circle cx="{x}" cy="{y}" r="6.5" fill="#f2b54a" opacity=".16"/><circle cx="{x}" cy="{y}" r="2.3" fill="#f6c768"/>'
                     for x, y in bright)
    pings = ""
    for x, y in bright:
        half = math.sqrt(R * R - (y - CY) ** 2)
        for limb, cls in ((CX - half, "d"), (CX + half, "r")):
            pings += (f'<i class="ping ping-{cls}" style="left:{limb / 6:.2f}%;top:{y / 3.4:.2f}%;'
                      f'animation-delay:{((limb - x) % P) / SPEED:.2f}s"></i>')
    return f"""<div class="hero-scene" aria-hidden="true">
    <div class="hero-drift"><svg viewBox="-{P} 0 {3 * P} 340" fill="#e9eefb"><g id="hs">{stars}</g><use href="#hs" x="-{P}"/><use href="#hs" x="{P}"/></svg></div>
    <svg class="hero-moon" viewBox="0 0 600 340"><defs>
      <radialGradient id="hm-glow" cx="500" cy="{CY}" r="200" gradientUnits="userSpaceOnUse"><stop offset=".4" stop-color="#cdd8f6" stop-opacity=".2"/><stop offset="1" stop-color="#cdd8f6" stop-opacity="0"/></radialGradient>
      <radialGradient id="hm-dark" cx="430" cy="140" r="150" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#262f48"/><stop offset="1" stop-color="#171d2f"/></radialGradient>
      <linearGradient id="hm-lit" x1="{CX + 50}" x2="{CX + R}" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#a9a28c"/><stop offset=".5" stop-color="#ede6d1"/><stop offset="1" stop-color="#fffaf0"/></linearGradient>
      <filter id="hm-soft" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="2.5"/></filter>
      <mask id="hm-cres"><rect x="{CX}" y="{CY - R}" width="{R}" height="{2 * R}" fill="#fff"/><ellipse cx="{CX}" cy="{CY}" rx="56" ry="{R + 1}" fill="#000" filter="url(#hm-soft)"/></mask>
      <clipPath id="hm-disc"><circle cx="{CX}" cy="{CY}" r="{R}"/></clipPath></defs>
      <g transform="rotate(24 {CX} {CY})"><circle cx="500" cy="{CY}" r="200" fill="url(#hm-glow)"/>
      <circle cx="{CX}" cy="{CY}" r="{R}" fill="url(#hm-dark)" stroke="#3b4666" stroke-width=".8"/>
      <g clip-path="url(#hm-disc)"><g fill="#0c1120" opacity=".3" filter="url(#hm-soft)"><ellipse cx="415" cy="128" rx="34" ry="26"/><ellipse cx="388" cy="182" rx="22" ry="34"/>
      <ellipse cx="452" cy="150" rx="26" ry="22"/><ellipse cx="440" cy="222" rx="30" ry="18"/><ellipse cx="482" cy="196" rx="20" ry="24"/></g></g>
      <g mask="url(#hm-cres)"><circle cx="{CX}" cy="{CY}" r="{R}" fill="url(#hm-lit)"/>
      <g fill="#8b846e" opacity=".35"><ellipse cx="528" cy="128" rx="14" ry="20"/><ellipse cx="536" cy="188" rx="12" ry="24"/><circle cx="520" cy="232" r="9"/><circle cx="546" cy="152" r="4"/><circle cx="512" cy="96" r="6"/></g></g></g>
    </svg>{pings}
  </div>"""


KINDS = [
    ("occ", "occultations", "Lunar occultations", "Occultations",
     "The Moon passes in front of a planet or a bright star. Only a band of the Earth sees it, and the times change from city to city.",
     [("You need", "your eyes or binoculars"), ("How often", "a few a year"), ("Each page", "a map of where it's seen and times for 500 cities")]),
    ("ms", "moon-stars", "The Moon and the stars", "Moon & stars",
     "Every night the Moon slides over fainter stars. A star doesn't fade; it switches off at one edge and back on at the other. Computed for your own place.",
     [("You need", "binoculars or a small telescope"), ("How often", "about one a night"), ("Each page", "a month calendar and every event for your location")]),
    ("ast", "asteroids", "Asteroid occultations", "Asteroids",
     "An asteroid passes in front of a star. Its shadow sweeps a narrow path across the Earth: inside it the star blinks out for a few seconds, a few kilometres outside nothing happens.",
     [("You need", "a telescope of 100 mm or more, ideally a camera"), ("How often", "two or three paths over India a night"), ("Each page", "a month of paths across India, each mapped, with how close it passes you")]),
    ("jup", "jupiter", "Jupiter's moons", "Jupiter",
     "Jupiter's four big moons pass behind it, into its shadow and across its face. The Great Red Spot comes round every ten hours.",
     [("You need", "any small telescope"), ("How often", "most nights"), ("Each page", "a month of events and a full-screen diagram of the moons, minute by minute")]),
    ("sat", "saturn", "Saturn's moons", "Saturn",
     "Saturn's big moons cross its face and enter its shadow. This only happens for a few years around the 2025 ring-plane crossing.",
     [("You need", "a telescope, 100 mm or more"), ("How often", "most nights while the season lasts"), ("Each page", "a month of events and a full-screen diagram, minute by minute")]),
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
    var t = document.getElementById('tile-occ'), left = document.getElementById('occ-in');
    if (left) {   // twin of in_text in build_index
      var h = up[0] ? (Date.parse(up[0].dataset.start) - now) / 36e5 : NaN;
      left.textContent = h !== h ? '' : h < 0 ? 'now' : h < 1 ? 'within the hour' : h < 48 ? 'in ' + Math.floor(h + 0.5) + ' hours' : 'in ' + Math.floor(h / 24 + 0.5) + ' days';
    }
    if (t && up[0]) {
      t.setAttribute('href', up[0].querySelector('a').getAttribute('href'));
      t.querySelector('.tile-title').textContent = up[0].querySelector('.ev-what').textContent;
      t.querySelector('.tile-detail').textContent = up[0].dataset.detail;
    }
  }
  // month links: this month highlighted, earlier months dimmed; tiles follow this month
  document.querySelectorAll('.mo').forEach(function (li) { if (li.dataset.ym === ym) li.classList.add('current'); else if (li.dataset.ym < ym) li.classList.add('past'); });
  ['ms', 'ast', 'jup', 'sat'].forEach(function (k) {
    var tile = document.getElementById('tile-' + k), pill = document.querySelector('#kind-' + k + ' .mo[data-ym="' + ym + '"]');
    if (!tile || !pill || tile.dataset.ym === ym) return;
    tile.setAttribute('href', pill.querySelector('a').getAttribute('href'));
    tile.querySelector('.tile-title').textContent = pill.dataset.label;
    tile.querySelector('.tile-detail').textContent = pill.dataset.detail;
    var tm = document.querySelector('#kind-' + k + ' .this-month');
    if (tm) tm.innerHTML = 'This month: <a href="' + pill.querySelector('a').getAttribute('href') + '">' + pill.dataset.label + '</a> · ' + pill.dataset.detail;
  });
})();
"""


def build_index(seed, built, jup=(), ms=(), ast=()):
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
        "ast": monthly(ast, lambda e: f"{e['n']} paths across India at night · {e['mine']} over New Delhi"),
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
        return (f'<li class="ev{" past" if past else ""}" data-start="{w.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}" '
                f'data-end="{b["end_utc"]}" data-detail="{esc(detail)}">'
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
    def in_text(hours):   # twin of inText in INDEX_JS, which redoes it by the reader's clock
        return ("now" if hours < 0 else "within the hour" if hours < 1 else f"in {int(hours + 0.5)} hours" if hours < 48
                else f"in {int(hours / 24 + 0.5)} days")

    if nxt:
        left = in_text((nxt["when"] - now).total_seconds() / 3600) if nxt in upcoming else ""
        tiles.append(f'<a class="tile tile-main t-occ" id="tile-occ" href="/{nxt["slug"]}">{lens("occ")}<span class="tile-body">'
                     f'<span class="tile-kicker">Next lunar occultation</span>'
                     f'<span class="tile-title">The Moon occults {esc(nxt["target"])}</span>'
                     f'<span class="tile-detail">{esc(nxt["when"].strftime("%a %-d %b %Y"))} · {esc(nxt["audience"])}</span></span>'
                     f'<span class="tile-in" id="occ-in">{left}</span></a>')
    for k, kicker in (("ms", "Moon & stars · this month"), ("ast", "Asteroids · this month"), ("jup", "Jupiter's moons · this month"),
                      ("sat", "Saturn's moons · this month")):
        cur = current(months[k])
        if cur:
            tiles.append(f'<a class="tile t-{k}" id="tile-{k}" href="/{cur[1]}" data-ym="{cur[0]}">{lens(k)}'
                         f'<span class="tile-kicker">{kicker}</span><span class="tile-title">{esc(cur[2])}</span>'
                         f'<span class="tile-detail">{esc(cur[3])}</span></a>')

    # ---------------- sections
    def section(k, body):
        _, anchor, name, _, what, facts = kinds[k]
        facts_html = "".join(f"<li><b>{esc(a)}</b> {esc(b)}</li>" for a, b in facts)
        return (f'<section class="kind t-{k}" id="kind-{k}"><a id="{anchor}"></a><header class="kind-head">{lens(k)}'
                f'<h2>{esc(name)}</h2><p class="kind-what">{esc(what)}</p><ul class="kind-facts">{facts_html}</ul></header>{body}</section>')

    sections = []
    if built:
        sections.append(section("occ", f'<ul class="evlist" id="evlist">{rows}</ul>'
                                       f'<p class="ev-more"><button class="btn" id="ev-more" type="button">Show all events</button></p>'))
    for k in ("ms", "ast", "jup", "sat"):
        if months[k]:
            cur = current(months[k])
            sections.append(section(k, f'<p class="this-month">This month: <a href="/{cur[1]}">{esc(cur[2])}</a> · {esc(cur[3])}</p>'
                                       + year_rows(months[k])))

    nav = "".join(f'<a class="t-{k[0]}" href="#{k[1]}">{ICONS[k[0]]}{esc(k[3])}</a>' for k in KINDS if (k[0] == "occ" and built) or months.get(k[0]))
    desc = ("Lunar occultations of planets and stars, asteroid shadows across India, and Jupiter's and Saturn's moons. "
            "Where and when to see them, computed from JPL ephemerides.")
    page = head(f"{SITE_NAME} — {TAGLINE}", desc, "/", extra=f"<style>{INDEX_CSS}</style>") + f"""
<main class="wrap">
  <section class="hero sky">
  {hero_scene()}
  <div class="hero-text">
    <h1 class="home-h1">Occultations you can see, with times for your city</h1>
    <p class="sub">Five kinds of sky events, computed from JPL ephemerides for where you are.</p>
    <nav class="typenav" aria-label="Kinds of event">{nav}</nav>
  </div>
  </section>
  <h2>Coming up</h2>
  <div class="upnext">{"".join(tiles)}</div>
  <p class="cal-cta"><a href="/calendar">Get the occultations your city can see in your calendar →</a></p>
  {"".join(sections)}
  <section class="kind" id="method"><h2>How these are made</h2>
  <p class="method">Everything here is computed, not copied. Sources: JPL (planets, Moon, Sun, the moons, asteroids), Gaia DR3
  and Hipparcos-2 (stars), NASA's LRO laser altimeter (the Moon's mountains). The lunar-occultation list is chosen by hand; each page links the data it
  was built from. <a href="/method">How this is computed, and what it was checked against →</a></p></section>
</main>
{FOOTER}
<script>{INDEX_JS}</script>
</body>
</html>
"""
    (OUT / "index.html").write_text(page)
    urls = [("/", "weekly", "1.0"), ("/calendar", "monthly", "0.7"), ("/method", "monthly", "0.6")] + [(f"/{b['slug']}", "weekly", "0.8") for b in built] + [(f"/{j['slug']}", "monthly", "0.6") for j in jup] + [(f"/{m['slug']}", "monthly", "0.6") for m in ms] + [(f"/{a['slug']}", "monthly", "0.6") for a in ast]
    # every asteroid event is its own page at /asteroid?e=<id> — one file, but a crawler has no way to guess the ids
    urls += [(f"/asteroid?e={i}", "monthly", "0.5") for a in ast for i in a.get("ids", ())]
    sm =['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for path, freq, pri in urls:
        sm.append(f"  <url><loc>{SITE}{path}</loc><changefreq>{freq}</changefreq><priority>{pri}</priority></url>")
    sm.append("</urlset>\n")
    (OUT / "sitemap.xml").write_text("\n".join(sm))
    (OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n")
    # installable: name, colours, icons (scripts/build_og.py draws them) and shortcuts to each kind of event
    icons = [{"src": "/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
             {"src": "/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
             {"src": "/icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}]
    shortcuts = [{"name": name, "short_name": short, "url": url, "icons": [{"src": "/icons/icon-192.png", "sizes": "192x192"}]}
                 for name, short, url in (("Calendar feeds", "Calendar", "/calendar"), ("The Moon and the stars", "Moon & stars", "/#moon-stars"),
                                          ("Asteroid occultations", "Asteroids", "/#asteroids"),
                                          ("Jupiter's moons", "Jupiter", "/#jupiter"), ("Saturn's moons", "Saturn", "/#saturn"))]
    (OUT / "manifest.webmanifest").write_text(json.dumps({
        "id": "/", "name": f"{SITE_NAME} — {TAGLINE}", "short_name": SITE_NAME, "description": desc,
        "start_url": "/", "scope": "/", "display": "standalone", "lang": "en", "dir": "ltr",
        "background_color": "#0c0f17", "theme_color": "#0c0f17", "categories": ["education", "utilities"],
        "icons": icons, "shortcuts": shortcuts}, ensure_ascii=False, indent=1) + "\n")
    write_sw()
    # Cloudflare Pages: unhashed text stays short-lived; KML/GPX download; css, js and images long-lived (URLs carry ?v= hashes)
    (OUT / "_headers").write_text("/*\n  Cache-Control: public, max-age=3600\n/data/*\n  Cache-Control: public, max-age=86400\n"
                                  "/sw.js\n  Cache-Control: no-cache\n"
                                  "/css/*\n  Cache-Control: public, max-age=2592000\n"
                                  "/js/*\n  Cache-Control: public, max-age=2592000\n"
                                  "/kml/*\n  Cache-Control: public, max-age=86400\n  Content-Disposition: attachment\n"
                                  "/img/*\n  Cache-Control: public, max-age=2592000\n"
                                  "/og/*\n  Cache-Control: public, max-age=2592000\n"
                                  "/icons/*\n  Cache-Control: public, max-age=2592000\n"
                                  "/manifest.webmanifest\n  Content-Type: application/manifest+json\n  Cache-Control: public, max-age=86400\n"
                                  "/ics/*\n  Cache-Control: public, max-age=21600\n  Content-Type: text/calendar; charset=utf-8\n")
    (OUT / "404.html").write_text(head(f"Not found · {SITE_NAME}", "No such page.", "/404") + f"""
<main class="wrap"><h1>No such page</h1><p class="sub">Try the <a href="/">home page</a> or the <a href="/calendar">calendar</a>.</p></main>{FOOTER}</body></html>
""")
    print(f"wrote site/index.html, sitemap.xml ({len(urls)} urls), robots.txt, _headers, sw.js, 404.html")


if __name__ == "__main__":
    import build_asteroids
    import build_feeds
    import build_jupiter
    import build_moonstars
    import build_og
    seed = json.loads((ROOT / "seed.json").read_text())
    OUT.mkdir(exist_ok=True)
    build_og.write_all()          # first: every page's head links the images by content hash
    built = [build(seed, e["slug"]) for e in seed["events"]]
    # every city any event page knows: the diary pages' location sheet and one calendar feed each
    cities_sorted = build_feeds.collect_cities(seed)
    jup = build_jupiter.build_all(cities_sorted, "jupiter") + build_jupiter.build_all(cities_sorted, "saturn")
    ms = build_moonstars.build_all(cities_sorted)
    ast = build_asteroids.build_all(cities_sorted)
    build_feeds.build_all(seed, cities_sorted)
    import build_method
    build_method.write_page()      # after the feeds: it counts them
    build_index(seed, built, jup, ms, ast)
