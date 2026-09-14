#!/usr/bin/env python3
"""Jupiter's and Saturn's moons: one page per month from data/<planet>-moons-<year>.json
(engine/satellite_events.py, DE431 + JPL jup365 / sat441).

Events are geocentric — one UTC instant for the whole Earth — so a location only decides whether the planet is up
and the sky dark (from the RA/Dec stored with each event and sidereal time; no ephemeris in the browser).

The page: the moons' configuration diagram, a month calendar, and one card per observing night (noon to noon).
Each event is ONE row — start → end at the moment the moon's centre crosses the planet's or the shadow's edge,
the convention published tables use — with a type icon. The row HTML exists twice, `item_li` here and `li()` in
RENDER_JS, and must stay identical (same rounding: floor(x + 0.5)); the page prerenders New Delhi for crawlers.
"""

import calendar as _calendar
import json
import math
import zoneinfo
from datetime import datetime, timedelta, timezone

from build_pages import FOOTER, OUT, ROOT, SITE, SITE_NAME, esc, head

MOON_NAME = {"io": "Io", "europa": "Europa", "ganymede": "Ganymede", "callisto": "Callisto",
             "mimas": "Mimas", "enceladus": "Enceladus", "tethys": "Tethys", "dione": "Dione",
             "rhea": "Rhea", "titan": "Titan", "iapetus": "Iapetus", "grs": "Great Red Spot"}
GRS_COLOR = "#d9603b"
GRS_HALF_VIEW = 3000   # s: the spot sits well on the disc for ~50 min either side of the central meridian
PLANETS = {
    "jupiter": dict(name="Jupiter", moons=["io", "europa", "ganymede", "callisto"], oblate=0.935,
                    colors={"io": "#f59e0b", "europa": "#60a5fa", "ganymede": "#a78bfa", "callisto": "#34d399", "grs": GRS_COLOR},
                    radii_rp={"io": 0.0255, "europa": 0.0218, "ganymede": 0.0368, "callisto": 0.0337},
                    pole=[268.056595, -0.006499, 64.495303, 0.002413], rings=None, zooms=[30, 8],
                    intro="Jupiter's four big moons put on a show every night: they slip behind the planet and into its "
                          "shadow, cross its face, and drag their shadows across the cloud tops. Any telescope shows it."),
    "saturn": dict(name="Saturn", moons=["mimas", "enceladus", "tethys", "dione", "rhea", "titan", "iapetus"], oblate=0.902,
                   colors={"mimas": "#94a3b8", "enceladus": "#e2e8f0", "tethys": "#fcd34d", "dione": "#60a5fa",
                           "rhea": "#a78bfa", "titan": "#f97316", "iapetus": "#34d399"},
                   radii_rp={"mimas": 0.0033, "enceladus": 0.0042, "tethys": 0.0088, "dione": 0.0093,
                             "rhea": 0.0127, "titan": 0.0427, "iapetus": 0.0122},
                   pole=[40.589, -0.036, 83.537, -0.004], rings=[2.27, 1.24], zooms=[65, 25, 8],
                   intro="Saturn's moons hide behind the globe, cross its face and fall into its shadow only in the years "
                         "around a ring-plane crossing, when their orbits turn edge-on to us — as they are now, after the "
                         "2025 equinox. Titan is easy in any telescope; Rhea, Dione and Tethys need a little more aperture."),
}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DEFAULT_PLACE = ("New Delhi", 28.6139, 77.2090, "Asia/Kolkata")

# title template, word for the start, word for the end
TYPES = {
    "eclipse": ["{m} in {p}'s shadow", "disappears", "reappears"],
    "occultation": ["{m} behind {p}", "disappears", "reappears"],
    "transit": ["{m} crosses {p}", "enters", "leaves"],
    "shadow": ["{m}'s shadow crosses {p}", "enters", "leaves"],
}
ICONS = {
    "occultation": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="18.5" cy="12" r="3" fill="currentColor" opacity=".45"/>'
                   '<circle cx="10.5" cy="12" r="8" fill="currentColor"/></svg>',
    "eclipse": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="7" cy="12" r="6" fill="currentColor"/>'
               '<path d="M7 6 L23 8 L23 16 L7 18 Z" fill="currentColor" opacity=".22"/>'
               '<circle cx="17.5" cy="12" r="2.4" fill="none" stroke="currentColor" stroke-width="1.3"/></svg>',
    "transit": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.5" fill="currentColor" opacity=".22"/>'
               '<circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="1.4"/>'
               '<circle cx="15" cy="10" r="2.5" fill="currentColor"/></svg>',
    "shadow": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.5" fill="currentColor"/>'
              '<circle cx="14.5" cy="11" r="2.6" fill="var(--card)"/></svg>',
    "mutual": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="9" cy="12" r="5" fill="currentColor" opacity=".45"/>'
              '<circle cx="15" cy="12" r="5" fill="currentColor"/></svg>',
    "grs": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.5" fill="currentColor" opacity=".22"/>'
           '<circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="1.4"/>'
           '<path d="M12 3.5 V20.5" stroke="currentColor" stroke-width="1" stroke-dasharray="1.6 1.4"/>'
           f'<ellipse cx="12" cy="14.6" rx="3.4" ry="2.1" fill="{GRS_COLOR}"/></svg>',
}
LEGEND = [("occultation", "behind the planet"), ("eclipse", "in its shadow"), ("transit", "crossing its face"),
          ("shadow", "shadow on the planet"), ("mutual", "moons eclipse or hide each other"), ("grs", "Great Red Spot mid-disc")]


# ---------------------------------------------------------------------------------------------- data

def parse(iso):
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _half(c, hidden, a, b):
    if a not in c and b not in c:
        return None
    ta, tb = parse(c.get(a, c.get(b))).timestamp(), parse(c.get(b, c.get(a))).timestamp()
    return {"t": int((ta + tb) // 2), "seen": not (hidden.get(a, False) and hidden.get(b, False))}


def item_of(ev):
    """One row per event, times as integer epoch seconds (the JS uses the same integers)."""
    c = ev["contacts"]
    pl, sun = ev.get("planet") or ev["jupiter"], ev["sun"]
    base = {"kind": ev["type"], "ra": pl["ra_deg"], "dec": pl["dec_deg"], "sra": sun["ra_deg"], "sdec": sun["dec_deg"]}
    if ev["type"] == "mutual":
        t0, t1 = parse(c["D1"]).timestamp(), parse(c["R2"]).timestamp()
        return dict(base, moon=ev["a"], b=ev["b"], verb=ev["kind"], t=int(parse(ev["mid"]).timestamp()),
                    dur=round((t1 - t0) / 60, 3), covered=ev["covered_frac"], drop=ev["mag_drop"])
    hidden = ev.get("hidden", {})
    s, e = _half(c, hidden, "D1", "D2"), _half(c, hidden, "R1", "R2")
    seen = [h for h in (s, e) if h and h["seen"]]
    if not seen:
        return None
    return dict(base, moon=ev["moon"], start=s, end=e, t=seen[0]["t"])


# ------------------------------------------------------------------- twin of RENDER_JS (keep identical)

def r0(x):
    return math.floor(x + 0.5)


def gmst(s):
    d = s / 86400 + 2440587.5 - 2451545
    T = d / 36525
    return (280.46061837 + 360.98564736629 * d + 0.000387933 * T * T) % 360


def alt(s, ra, dec, lat, lon):
    ha = math.radians(gmst(s) + lon - ra)
    return math.degrees(math.asin(math.sin(math.radians(lat)) * math.sin(math.radians(dec))
                                  + math.cos(math.radians(lat)) * math.cos(math.radians(dec)) * math.cos(ha)))


def sky(a):
    return "daylight" if a > 0 else "twilight" if a > -6 else "dusk" if a > -12 else "dark sky"


def good(s, it, lat, lon):
    return alt(s, it["ra"], it["dec"], lat, lon) > 10 and alt(s, it["sra"], it["sdec"], lat, lon) < -6


def item_ok(it, lat, lon):
    if it["kind"] in ("mutual", "grs"):
        return good(it["t"], it, lat, lon)
    return any(h and h["seen"] and good(h["t"], it, lat, lon) for h in (it["start"], it["end"]))


def item_li(it, P, tz, lat, lon):
    hm = lambda s: datetime.fromtimestamp(s, tz).strftime("%H:%M")
    m = MOON_NAME[it["moon"]]
    col = P["colors"].get(it["moon"], "#94a3b8")
    extra = ""
    if it["kind"] == "mutual":
        title = f"{m} {'occults' if it['verb'] == 'occults' else 'eclipses'} {MOON_NAME[it['b']]}"
        times = f"{hm(it['t'])} · {r0(it['dur'] * 10) / 10:.1f} min"
        extra = f"{r0(it['covered'] * 100)}% of {MOON_NAME[it['b']]} covered · ≈{r0(it['drop'] * 10) / 10:.1f} mag fainter"
    elif it["kind"] == "grs":
        title = f"Great Red Spot crosses the middle of {P['name']}"
        times = f"{hm(it['t'])} · on view {hm(it['t'] - GRS_HALF_VIEW)}–{hm(it['t'] + GRS_HALF_VIEW)}"
    else:
        tmpl, w1, w2 = TYPES[it["kind"]]
        title = tmpl.format(m=m, p=P["name"])
        parts = [(f"{hm(h['t'])} {w}" if h["seen"] else f"{w} unseen") for h, w in ((it["start"], w1), (it["end"], w2)) if h]
        times = " → ".join(parts)
        if it["start"] and it["end"]:
            mins = (it["end"]["t"] - it["start"]["t"] + 30) // 60
            times += f" · {mins // 60} h {mins % 60:02d} min" if mins >= 60 else f" · {mins} min"
    a = alt(it["t"], it["ra"], it["dec"], lat, lon)
    sa = alt(it["t"], it["sra"], it["sdec"], lat, lon)
    skytxt = f"{P['name']} {r0(a)}° up · {sky(sa)}" if a > 0 else f"{P['name']} below the horizon"
    meta = (extra + " · " if extra else "") + skytxt
    return (f'<li class="jev k-{it["kind"]}" data-t="{it["t"]}"><span class="jev-ico">{ICONS[it["kind"]]}</span>'
            f'<div class="jev-main"><div class="jev-top"><span class="dot" style="background:{col}"></span><b>{esc(title)}</b></div>'
            f'<div class="jev-times">{times}</div><div class="jev-meta">{esc(meta)}</div></div></li>')


def group_nights(items, tz):
    groups = {}
    for it in sorted(items, key=lambda it: it["t"]):
        key = (datetime.fromtimestamp(it["t"], tz) - timedelta(hours=12)).date()
        groups.setdefault(key, []).append(it)
    return groups


def nights_html(groups, P, tz, lat, lon):
    return "".join(
        f'<section class="night" id="night-{k.isoformat()}"><header class="night-head"><h3>Night of {k.strftime("%a %-d %b")}</h3>'
        f'<span class="night-sub"></span></header><ol class="jevents">'
        + "".join(item_li(it, P, tz, lat, lon) for it in groups[k]) + "</ol></section>" for k in sorted(groups))


def calendar_html(year, month, groups, P):
    first_wd, ndays = _calendar.monthrange(year, month)
    cells = [f'<div class="cal-wd">{w}</div>' for w in WEEKDAYS] + ['<div class="cal-cell empty"></div>'] * first_wd
    for d in range(1, ndays + 1):
        k = datetime(year, month, d).date()
        g = groups.get(k, [])
        moons = list(dict.fromkeys(it["moon"] for it in g))[:4]
        dots = "".join(f'<i style="background:{P["colors"].get(mm, "#94a3b8")}"></i>' for mm in moons)
        inner = f'<span class="cal-d">{d}</span><span class="cal-dots">{dots}</span><span class="cal-n">{len(g) or ""}</span>'
        cells.append(f'<a class="cal-cell has" href="#night-{k.isoformat()}">{inner}</a>' if g else f'<div class="cal-cell">{inner}</div>')
    return "".join(cells)


# ------------------------------------------------------------------------------------------------ JS

DIAGRAM_JS = r"""
(function () {
  // ---- Galilean configuration: Meeus, Astronomical Algorithms ch. 44 (low-accuracy method).
  // Checked against JPL jup365: 0.02 R_J rms along the orbit line, 0.08 across — a picture, not a timing.
  var RAD = Math.PI / 180, sin = Math.sin, cos = Math.cos;
  function galilean(ms) {
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
    for (var i = 0; i < 4; i++) out.push({ x: rr[i] * sin(u[i] * RAD), y: -rr[i] * cos(u[i] * RAD) * sin(DE * RAD), front: cos(u[i] * RAD) > 0 });
    return out;   // x in Jupiter radii, positive WEST; y positive north; front = nearer to Earth than Jupiter
  }
  var DD = JSON.parse(document.getElementById('diary-data').textContent);
  function sampled(ms) {   // linear interpolation of the hourly JPL samples
    var c = DD.config, i = (ms / 1000 - c.t0) / (c.step_min * 60), i0 = Math.floor(i), f = i - i0, out = [];
    c.moons.forEach(function (k) {
      var a = c.xyf[k], n = a.length / 3, j = Math.max(0, Math.min(n - 2, i0)), g = i0 < 0 ? 0 : i0 > n - 2 ? 1 : f;
      out.push({ x: (a[3*j] * (1-g) + a[3*j+3] * g) / 100, y: (a[3*j+1] * (1-g) + a[3*j+4] * g) / 100, front: (g < 0.5 ? a[3*j+2] : a[3*j+5]) === 1 });
    });
    return out;
  }
  var positions = DD.config ? sampled : galilean;
  var NS = 'http://www.w3.org/2000/svg', svg = document.getElementById('config-svg'), sl = document.getElementById('config-slider');
  var out = document.getElementById('config-time'), zoomBtn = document.getElementById('config-zoom'), playBtn = document.getElementById('config-play');
  var T0 = +svg.dataset.t0 * 1000, T1 = +svg.dataset.t1 * 1000, STEP = 5 * 60000;
  var NAMES = DD.names, COL = DD.colors, RAD_RJ = DD.radii, ZOOMS = DD.zooms, zi = 0;
  var half = ZOOMS[0], W = 800, Hh = 170, cx = W / 2, cy = Hh / 2, timer = null;
  // how far the planet's equator is tilted toward us (sub-Earth latitude B): sets the rings' opening
  var Tc = (T0 / 86400000 + 2440587.5 - 2451545) / 36525, PO = DD.pole;
  var pra = (PO[0] + PO[1] * Tc) * RAD, pde = (PO[2] + PO[3] * Tc) * RAD, lra = DD.ra * RAD, lde = DD.dec * RAD;
  var sinB = -(cos(pde) * cos(pra) * cos(lde) * cos(lra) + cos(pde) * sin(pra) * cos(lde) * sin(lra) + sin(pde) * sin(lde));
  function el(n, a) { var e = document.createElementNS(NS, n); for (var k in a) e.setAttribute(k, a[k]); return e; }
  function ringHalf(s, upper) {
    var ro = DD.rings[0] * s, ri = DD.rings[1] * s, eo = Math.max(0.8, Math.abs(sinB) * ro), ei = Math.max(0.5, Math.abs(sinB) * ri), sw = upper ? 1 : 0;
    svg.appendChild(el('path', { class: 'cfg-ring', d: 'M ' + (cx - ro) + ' ' + cy + ' A ' + ro + ' ' + eo + ' 0 0 ' + sw + ' ' + (cx + ro) + ' ' + cy
      + ' L ' + (cx + ri) + ' ' + cy + ' A ' + ri + ' ' + ei + ' 0 0 ' + (1 - sw) + ' ' + (cx - ri) + ' ' + cy + ' Z' }));
  }
  function draw() {
    var ms = T0 + (+sl.value) * STEP, pos = positions(ms), s = (W / 2 - 20) / half, ry = s * DD.oblate;
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    svg.appendChild(el('line', { x1: 0, y1: cy, x2: W, y2: cy, class: 'cfg-line' }));
    function moon(p, i, dim) {
      var g = el('g', { class: 'cfg-moon' + (dim ? ' dim' : '') });
      var r = Math.max(4, RAD_RJ[i] * s);
      g.appendChild(el('circle', { cx: cx + p.x * s, cy: cy - p.y * s, r: r, fill: COL[i], stroke: '#0b0e14', 'stroke-width': 1.2 }));
      var t = el('text', { x: cx + p.x * s, y: cy - p.y * s - r - 6, 'text-anchor': 'middle', class: 'cfg-lbl' });
      t.textContent = NAMES[i].length > 5 ? NAMES[i].slice(0, 2) : NAMES[i][0]; g.appendChild(t);
      svg.appendChild(g);
    }
    var farUpper = sinB > 0;   // seen from the north side, the far half of the rings is the upper half
    if (DD.rings) ringHalf(s, farUpper);
    pos.forEach(function (p, i) { if (!p.front) moon(p, i, Math.abs(p.x) < 1 && Math.abs(p.y) < DD.oblate); });
    if (DD.rings) {
      svg.appendChild(el('ellipse', { cx: cx, cy: cy, rx: s, ry: ry, class: 'cfg-sat' }));
      ringHalf(s, !farUpper);
    } else {
      var clip = el('clipPath', { id: 'jclip' }); clip.appendChild(el('ellipse', { cx: cx, cy: cy, rx: s, ry: ry })); svg.appendChild(clip);
      svg.appendChild(el('ellipse', { cx: cx, cy: cy, rx: s, ry: ry, class: 'cfg-jup' }));
      [[0.3, 0.17], [-0.2, 0.2], [-0.62, 0.1]].forEach(function (b) {
        svg.appendChild(el('rect', { x: cx - s, y: cy - (b[0] + b[1] / 2) * ry, width: 2 * s, height: b[1] * ry, class: 'cfg-band', 'clip-path': 'url(#jclip)' }));
      });
      var G = DD.grs;   // Great Red Spot: its System II longitude against the central meridian (daily DE431 values, interpolated)
      if (G && G.cm.length > 1) {
        var gi = (ms / 1000 - G.t0) / 86400, gk = Math.max(0, Math.min(G.cm.length - 2, Math.floor(gi))), gf = gi - gk;
        if (gi >= 0 && gi <= G.cm.length - 1) {
          var step = ((G.cm[gk + 1] - G.cm[gk] - 870.27) % 360 + 540) % 360 - 180, cmv = G.cm[gk] + (870.27 + step) * gf;
          var lon = G.lon + G.drift * (ms / 1000 - G.ref), dl = (((lon - cmv) % 360) + 540) % 360 - 180;   // + = east of the central meridian
          if (Math.cos(dl * RAD) > 0.05)
            svg.appendChild(el('ellipse', { cx: cx - sin(dl * RAD) * 0.93 * s, cy: cy + 0.36 * ry, rx: Math.max(1, 0.105 * s * cos(dl * RAD)), ry: 0.075 * ry,
              class: 'cfg-grs', 'clip-path': 'url(#jclip)' }));
        }
      }
    }
    pos.forEach(function (p, i) { if (p.front) moon(p, i, false); });
    var e = el('text', { x: 8, y: 14, class: 'cfg-lbl' }); e.textContent = 'E'; svg.appendChild(e);
    var w = el('text', { x: W - 8, y: 14, 'text-anchor': 'end', class: 'cfg-lbl' }); w.textContent = 'W'; svg.appendChild(w);
    var d = new Date(ms);
    out.textContent = d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + ' ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
      + (zi === 0 ? '' : ' · ±' + half + ' radii');
  }
  sl.max = Math.round((T1 - T0) / STEP); sl.value = Math.round(Math.min(Math.max(Date.now(), T0), T1) - T0) / STEP | 0;
  sl.addEventListener('input', draw);
  zoomBtn.addEventListener('click', function () { zi = (zi + 1) % ZOOMS.length; half = ZOOMS[zi]; zoomBtn.textContent = zi === ZOOMS.length - 1 ? 'Zoom out' : 'Zoom in'; draw(); });
  playBtn.addEventListener('click', function () {
    if (timer) { clearInterval(timer); timer = null; playBtn.textContent = 'Play'; return; }
    playBtn.textContent = 'Pause';
    timer = setInterval(function () { var v = +sl.value + 3; if (v > +sl.max) v = 0; sl.value = v; draw(); }, 80);
  });
  window.JDiagram = { at: function (ms) { sl.value = Math.round((ms - T0) / STEP); draw(); } };
  draw();
})();
"""

RENDER_JS = r"""
(function () {
  var M = JSON.parse(document.getElementById('jmeta').textContent), RAD = Math.PI / 180, P = M.planet;
  function r0(x) { return Math.floor(x + 0.5); }
  function gmst(s) { var d = s / 86400 + 2440587.5 - 2451545, T = d / 36525; return ((280.46061837 + 360.98564736629 * d + 0.000387933 * T * T) % 360 + 360) % 360; }
  function alt(s, ra, dec, lat, lon) { var ha = (gmst(s) + lon - ra) * RAD; return Math.asin(Math.sin(lat * RAD) * Math.sin(dec * RAD) + Math.cos(lat * RAD) * Math.cos(dec * RAD) * Math.cos(ha)) / RAD; }
  function sky(a) { return a > 0 ? 'daylight' : a > -6 ? 'twilight' : a > -12 ? 'dusk' : 'dark sky'; }
  function esc(s) { return String(s).replace(/[&<>"']/g, function (ch) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#x27;' }[ch]; }); }
  function fmt(ms, tz, o) { try { return new Date(ms).toLocaleString('en-GB', Object.assign({ timeZone: tz }, o)); } catch (e) { return new Date(ms).toLocaleString('en-GB', o); } }
  function hm(s, tz) { return fmt(s * 1000, tz, { hour: '2-digit', minute: '2-digit', hour12: false }); }
  function dateKey(ms, tz) { try { return new Intl.DateTimeFormat('en-CA', { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(ms)); } catch (e) { return new Date(ms).toISOString().slice(0, 10); } }
  function keyLabel(k) { var p = k.split('-'); return new Date(Date.UTC(+p[0], +p[1] - 1, +p[2], 12)).toLocaleDateString('en-GB', { timeZone: 'UTC', weekday: 'short', day: 'numeric', month: 'short' }).replace(',', ''); }
  function tzLabel(tz) { try { return new Intl.DateTimeFormat('en-GB', { timeZone: tz, timeZoneName: 'short' }).formatToParts(new Date(M.t0 * 1000 + 864e6)).filter(function (x) { return x.type === 'timeZoneName'; })[0].value; } catch (e) { return tz; } }
  var LOC = null;
  function good(s, it) { return alt(s, it.ra, it.dec, LOC.lat, LOC.lon) > 10 && alt(s, it.sra, it.sdec, LOC.lat, LOC.lon) < -6; }
  function itemOk(it) { if (it.kind === 'mutual' || it.kind === 'grs') return good(it.t, it); return [it.start, it.end].some(function (h) { return h && h.seen && good(h.t, it); }); }
  function li(it, tz) {   // twin of item_li()
    var m = M.names[it.moon], col = M.colors[it.moon] || '#94a3b8', title, times, extra = '';
    if (it.kind === 'mutual') {
      title = m + ' ' + (it.verb === 'occults' ? 'occults' : 'eclipses') + ' ' + M.names[it.b];
      times = hm(it.t, tz) + ' · ' + (r0(it.dur * 10) / 10).toFixed(1) + ' min';
      extra = r0(it.covered * 100) + '% of ' + M.names[it.b] + ' covered · ≈' + (r0(it.drop * 10) / 10).toFixed(1) + ' mag fainter';
    } else if (it.kind === 'grs') {
      title = 'Great Red Spot crosses the middle of ' + P.name;
      times = hm(it.t, tz) + ' · on view ' + hm(it.t - M.grsHalf, tz) + '–' + hm(it.t + M.grsHalf, tz);
    } else {
      var T = M.types[it.kind], parts = [];
      title = T[0].replace('{m}', m).replace('{p}', P.name);
      [[it.start, T[1]], [it.end, T[2]]].forEach(function (x) { if (x[0]) parts.push(x[0].seen ? hm(x[0].t, tz) + ' ' + x[1] : x[1] + ' unseen'); });
      times = parts.join(' → ');
      if (it.start && it.end) { var mins = Math.floor((it.end.t - it.start.t + 30) / 60); times += mins >= 60 ? ' · ' + Math.floor(mins / 60) + ' h ' + String(mins % 60).padStart(2, '0') + ' min' : ' · ' + mins + ' min'; }
    }
    var a = alt(it.t, it.ra, it.dec, LOC.lat, LOC.lon), sa = alt(it.t, it.sra, it.sdec, LOC.lat, LOC.lon);
    var meta = (extra ? extra + ' · ' : '') + (a > 0 ? P.name + ' ' + r0(a) + '° up · ' + sky(sa) : P.name + ' below the horizon');
    return '<li class="jev k-' + it.kind + '" data-t="' + it.t + '"><span class="jev-ico">' + M.icons[it.kind] + '</span>'
      + '<div class="jev-main"><div class="jev-top"><span class="dot" style="background:' + col + '"></span><b>' + esc(title) + '</b></div>'
      + '<div class="jev-times">' + times + '</div><div class="jev-meta">' + esc(meta) + '</div></div></li>';
  }
  function windowText(g, tz) {   // when the planet is over 10° up in a dark sky, around the night's events
    var lo = null, hi = null, t0 = g[0].t;
    for (var s = t0 - 36000; s <= t0 + 36000; s += 600) { if (good(s, g[0])) { if (lo === null) lo = s; hi = s; } }
    return lo === null ? '' : P.name + ' well placed ' + hm(lo, tz) + '–' + hm(hi, tz);
  }
  var onlyVis = document.getElementById('only-visible'), chips = [].slice.call(document.querySelectorAll('#moon-chips input'));
  var nightsEl = document.getElementById('j-nights'), calEl = document.getElementById('j-cal'), countLine = document.getElementById('count-line');
  function tzOf(loc) { var c = M.cities[loc.label]; return (c && c[2]) || (loc.label === M.defaultPlace[0] ? M.defaultPlace[3] : Intl.DateTimeFormat().resolvedOptions().timeZone); }
  function render() {
    var tz = tzOf(LOC), want = {}, list = [];
    chips.forEach(function (c) { want[c.value] = c.checked; });
    M.items.forEach(function (it) {
      if (it.kind === 'mutual' ? !want.mutual : !want[it.moon]) return;
      if (onlyVis.checked && !itemOk(it)) return;
      list.push(it);
    });
    list.sort(function (a, b) { return a.t - b.t; });
    var groups = {}, order = [];
    list.forEach(function (it) { var k = dateKey(it.t * 1000 - 432e5, tz); if (!groups[k]) { groups[k] = []; order.push(k); } groups[k].push(it); });
    order.sort();
    nightsEl.innerHTML = order.map(function (k) {
      return '<section class="night" id="night-' + k + '"><header class="night-head"><h3>Night of ' + keyLabel(k) + '</h3><span class="night-sub">'
        + windowText(groups[k], tz) + '</span></header><ol class="jevents">' + groups[k].map(function (it) { return li(it, tz); }).join('') + '</ol></section>';
    }).join('') || '<p class="hint">Nothing matches from here this month — try turning off “Only what I can see”.</p>';
    var y = +M.ym[0], mo = +M.ym[1], ndays = new Date(Date.UTC(y, mo, 0)).getUTCDate(), first = (new Date(Date.UTC(y, mo - 1, 1)).getUTCDay() + 6) % 7, html = '';
    ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].forEach(function (w) { html += '<div class="cal-wd">' + w + '</div>'; });
    for (var e = 0; e < first; e++) html += '<div class="cal-cell empty"></div>';
    for (var d = 1; d <= ndays; d++) {
      var ck = y + '-' + String(mo).padStart(2, '0') + '-' + String(d).padStart(2, '0'), g = groups[ck] || [], seen = {}, dots = '';
      g.forEach(function (it) { if (!seen[it.moon] && Object.keys(seen).length < 4) { seen[it.moon] = 1; dots += '<i style="background:' + (M.colors[it.moon] || '#94a3b8') + '"></i>'; } });
      var inner = '<span class="cal-d">' + d + '</span><span class="cal-dots">' + dots + '</span><span class="cal-n">' + (g.length || '') + '</span>';
      html += g.length ? '<a class="cal-cell has" href="#night-' + ck + '">' + inner + '</a>' : '<div class="cal-cell">' + inner + '</div>';
    }
    calEl.innerHTML = html;
    document.getElementById('tz-label').textContent = tzLabel(tz);
    document.getElementById('chip-name').textContent = LOC.label;
    countLine.textContent = list.length + (onlyVis.checked ? ' events you can see from ' + LOC.label : ' events') + ' this month, on ' + order.length + ' nights';
  }
  nightsEl.addEventListener('click', function (e) {
    var row = e.target.closest && e.target.closest('.jev');
    if (!row || !window.JDiagram) return;
    JDiagram.at(+row.dataset.t * 1000);
    document.getElementById('config').scrollIntoView({ block: 'start', behavior: 'smooth' });
  });
  var sheet = document.getElementById('loc-sheet'), latI = document.getElementById('loc-lat'), lonI = document.getElementById('loc-lon'), sel = document.getElementById('loc-city');
  function setLoc(lat, lon, label) {
    lat = +lat; lon = +lon; if (!isFinite(lat) || !isFinite(lon)) return;
    LOC = { lat: lat, lon: lon, label: label || (lat.toFixed(2) + ', ' + lon.toFixed(2)) };
    try { localStorage.setItem('occult-loc', JSON.stringify(LOC)); } catch (e) {}
    render();
  }
  document.getElementById('loc-chip').addEventListener('click', function () { if (LOC) { latI.value = LOC.lat.toFixed(4); lonI.value = LOC.lon.toFixed(4); } sheet.showModal(); });
  sheet.addEventListener('click', function (e) { if (e.target === sheet) sheet.close(); });
  document.getElementById('loc-go').addEventListener('click', function () { setLoc(latI.value, lonI.value); sheet.close(); });
  sel.addEventListener('change', function () { var c = M.cities[sel.value]; if (c) { setLoc(c[0], c[1], sel.value); sheet.close(); } });
  var geo = document.getElementById('loc-geo'); if (!navigator.geolocation) geo.hidden = true;
  geo.addEventListener('click', function () { geo.disabled = true; geo.textContent = 'Locating…';
    navigator.geolocation.getCurrentPosition(function (p) { geo.disabled = false; geo.textContent = 'Use my location'; setLoc(p.coords.latitude, p.coords.longitude); sheet.close(); },
      function () { geo.disabled = false; geo.textContent = 'Location unavailable'; }); });
  onlyVis.addEventListener('change', render); chips.forEach(function (c) { c.addEventListener('change', render); });
  var saved = null; try { saved = JSON.parse(localStorage.getItem('occult-loc')); } catch (e) {}
  if (saved && isFinite(saved.lat)) setLoc(saved.lat, saved.lon, saved.label);
  else setLoc(M.defaultPlace[1], M.defaultPlace[2], M.defaultPlace[0]);
})();
"""

TEMPLATE = """
<nav class="subnav">
  <div class="subnav-row">
    <div class="subnav-links">__PREV__<a href="/#__PLANET__">All months</a>__NEXT__</div>
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
<main class="wrap">
  <h1>__TITLE__</h1>
  <p class="sub">__SUB__</p>
  <p class="lead">__LEAD__</p>
  <h2 id="config">Where the moons are</h2>
  <div class="config-card">
    <div class="limb-controls"><span class="limb-readout" id="config-time"></span>
      <span><button class="btn" id="config-play" type="button">Play</button> <button class="btn" id="config-zoom" type="button">Zoom in</button></span></div>
    <svg id="config-svg" viewBox="0 0 800 170" class="config-svg" role="img" aria-label="__PNAME__ and its moons" data-t0="__T0__" data-t1="__T1__"></svg>
    <input type="range" id="config-slider" min="0" max="100" value="0" step="1" aria-label="Time">
  </div>
  <p class="hint">__DIAG_HINT__</p>
  <h2 id="events">Events</h2>
  <div class="filters">
    <label class="toggle"><input type="checkbox" id="only-visible" checked> Only what I can see</label>
    <span class="chips" id="moon-chips">__CHIPS__</span>
  </div>
  <p class="hint" id="count-line">__COUNT__</p>
  <div class="cal" id="j-cal" aria-label="The month at a glance">__CAL__</div>
  <div class="legend-icons">__LEGEND__</div>
  <p class="hint">Times in <span id="tz-label">IST</span>, when the moon's centre crosses the edge — as almanacs list them. A night runs
  from noon to noon. Tap an event to see it in the diagram.</p>
  <div id="j-nights">__NIGHTS__</div>
  <h2>Reading the list</h2>
  <p class="method">__METHOD__</p>
  <script type="application/json" id="diary-data">__DIAG_DATA__</script>
  <script type="application/json" id="jmeta">__META__</script>
</main>
__FOOTER__
<script>__DIAGRAM_JS__</script>
<script>__RENDER_JS__</script>
</body>
</html>
"""


def month_page(planet, year, month, items, all_cities, nav, config=None, grs=None):
    P = PLANETS[planet]
    pname = P["name"]
    moon_list = ", ".join(MOON_NAME[m] for m in P["moons"][:-1]) + " and " + MOON_NAME[P["moons"][-1]]
    label = f"{MONTHS[month - 1]} {year}"
    title = f"{pname}'s moons in {label}"
    slug = f"{planet}-moons-{year}-{month:02d}"
    n_mutual = sum(1 for it in items if it["kind"] == "mutual")
    name, lat, lon, tzname = DEFAULT_PLACE
    tz = zoneinfo.ZoneInfo(tzname)
    visible = [it for it in items if item_ok(it, lat, lon)]
    groups = group_nights(visible, tz)
    desc = (f"Every eclipse, occultation, transit and shadow transit of {moon_list} in {label}"
            f"{', with the mutual events' if n_mutual else ''} — a calendar and night-by-night times for your location.")
    t0 = int(datetime(year, month, 1, tzinfo=timezone.utc).timestamp())
    t1 = int(datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=timezone.utc).timestamp())
    first = items[0] if items else {"ra": 0, "dec": 0}
    diag = {"names": [MOON_NAME[m] for m in P["moons"]], "colors": [P["colors"][m] for m in P["moons"]],
            "radii": [P["radii_rp"][m] for m in P["moons"]], "oblate": P["oblate"], "zooms": P["zooms"],
            "config": config, "pole": P["pole"], "rings": P["rings"], "ra": first["ra"], "dec": first["dec"],
            "grs": grs and {k: grs[k] for k in ("t0", "cm", "lon", "ref", "drift")}}
    kinds_present = {it["kind"] for it in items}
    meta = {"items": items, "planet": {"name": pname}, "names": MOON_NAME, "colors": P["colors"], "icons": ICONS, "types": TYPES,
            "cities": all_cities, "defaultPlace": list(DEFAULT_PLACE), "ym": [year, month], "t0": t0, "grsHalf": GRS_HALF_VIEW}
    chips = "".join(f'<label class="chipbox" style="border-color:{P["colors"][m]}"><input type="checkbox" value="{m}" checked> {MOON_NAME[m]}</label>'
                    for m in P["moons"])
    if n_mutual:
        chips += '<label class="chipbox"><input type="checkbox" value="mutual" checked> Mutual</label>'
    else:
        chips += '<input type="checkbox" value="mutual" checked hidden>'
    if "grs" in kinds_present:
        chips += f'<label class="chipbox" style="border-color:{GRS_COLOR}"><input type="checkbox" value="grs" checked> Red Spot</label>'
    legend = "".join(f'<span>{ICONS[k]}{esc(t)}</span>' for k, t in LEGEND if k in kinds_present)
    lead = (P["intro"] + (" This is a mutual-event season — the moons' orbits are edge-on to the Sun and they eclipse and occult "
                          "<em>each other</em>." if n_mutual else "") + " Pick your place: the calendar and the nights keep only what your sky shows.")
    method = (f"Times are for the moment the moon's centre crosses the edge of {pname} or of its shadow, the convention of published "
              f"tables; the moon's own disc takes a few minutes to cross. A start or end marked <em>unseen</em> happens behind {pname} or "
              f"inside its shadow. “Only what I can see” keeps events with {pname} more than 10° up in a dark sky. Positions are from "
              f"JPL DE431 and the {'jup365' if planet == 'jupiter' else 'sat441'} satellite ephemeris, {pname} as an oblate spheroid with "
              f"its shadow cone{'; the rings are not modelled, so a moon behind Saturn means behind the globe' if planet == 'saturn' else ''}. "
              f"Mutual-event brightness drops assume uniform discs and are estimates. Events are geocentric — the same instant everywhere "
              f"on Earth to well under a second."
              + (f" The Great Red Spot is a storm, not ephemeris: its times are when it crosses the middle of the disc (the central "
                 f"meridian, System II from DE431), taking its longitude as {grs['lon']:g}° on {grs['date']} drifting "
                 f"{grs['drift_month']:g}° a month ({esc(grs['source'])}). Each degree that estimate is off moves the time by 1.65 min; "
                 f"the spot is well placed for about 50 minutes either side." if grs else ""))
    diag_hint = (f"{pname}'s equator horizontal, east to the left as in binoculars. Drag through the month, or tap any event below to "
                 f"jump there. Moons behind the planet fade. " + ("Positions ±0.1 Jupiter radii — for the picture; the times come from JPL."
                                                                  if planet == "jupiter" else "Positions are JPL's, sampled hourly; the rings are drawn at their real tilt."))
    prev_link = f'<a href="/{nav["prev"]}">‹ {nav["prev_label"]}</a>' if nav.get("prev") else "<span></span>"
    next_link = f'<a href="/{nav["next"]}">{nav["next_label"]} ›</a>' if nav.get("next") else "<span></span>"
    body = TEMPLATE
    for k, v in {"__PREV__": prev_link, "__NEXT__": next_link, "__PLANET__": planet, "__PLACE__": esc(name),
                 "__CITY_OPTS__": "".join(f'<option value="{esc(n)}">{esc(n)}</option>' for n in all_cities),
                 "__TITLE__": esc(title), "__SUB__": " · ".join(MOON_NAME[m] for m in P["moons"]) + (f" — {n_mutual} mutual events" if n_mutual else ""),
                 "__LEAD__": lead, "__PNAME__": pname, "__T0__": str(t0), "__T1__": str(t1), "__DIAG_HINT__": diag_hint,
                 "__CHIPS__": chips, "__COUNT__": f"{len(visible)} events you can see from {esc(name)} this month, on {len(groups)} nights",
                 "__CAL__": calendar_html(year, month, groups, P), "__LEGEND__": legend,
                 "__NIGHTS__": nights_html(groups, P, tz, lat, lon), "__METHOD__": method,
                 "__DIAG_DATA__": json.dumps(diag, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"),
                 "__META__": json.dumps(meta, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"),
                 "__FOOTER__": FOOTER, "__DIAGRAM_JS__": DIAGRAM_JS, "__RENDER_JS__": RENDER_JS}.items():
        body = body.replace(k, v)
    (OUT / f"{slug}.html").write_text(head(f"{title} · {SITE_NAME}", desc, f"/{slug}", extra=f"<style>{JUPITER_CSS}</style>") + body)
    return {"slug": slug, "label": label, "year": year, "month": month, "n": len(items), "n_mutual": n_mutual, "planet": planet,
            "visible_default": len(visible)}


def build_all(all_cities, planet="jupiter"):
    files = sorted(ROOT.glob(f"data/{planet}-moons-*.json"))
    months, configs, grs_months = {}, {}, {}
    grs_file = ROOT / "data" / f"{planet}-grs.json"
    if grs_file.exists():   # engine/grs_transits.py: only as far ahead as the spot's longitude can be trusted
        gd = json.loads(grs_file.read_text())
        g = gd["grs"]
        ref = datetime.fromisoformat(g["date"]).replace(tzinfo=timezone.utc).timestamp()
        common = {"lon": g["lon_II"], "ref": int(ref), "drift": g["drift_deg_per_month"] / (30.436875 * 86400),
                  "date": datetime.fromisoformat(g["date"]).strftime("%-d %b %Y"), "drift_month": g["drift_deg_per_month"], "source": g["source"]}
        for t, ra, dec, sra, sdec in gd["transits"]:
            u = datetime.fromtimestamp(t, timezone.utc)
            months.setdefault((u.year, u.month), []).append({"kind": "grs", "moon": "grs", "t": t, "ra": ra, "dec": dec, "sra": sra, "sdec": sdec})
            grs_months[(u.year, u.month)] = True
        cmd = gd["cm_daily"]
        for key in grs_months:
            y, m = key
            m0 = int(datetime(y, m, 1, tzinfo=timezone.utc).timestamp())
            m1 = int(datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=timezone.utc).timestamp())
            i0, i1 = max(0, (m0 - cmd["t0"]) // 86400), min(len(cmd["values"]) - 1, (m1 - cmd["t0"]) // 86400)
            grs_months[key] = dict(common, t0=cmd["t0"] + i0 * 86400, cm=cmd["values"][i0:i1 + 1])
    for f in files:
        d = json.loads(f.read_text())
        for ev in d["events"]:
            it = item_of(ev)
            if it:
                t = datetime.fromtimestamp(it["t"], timezone.utc)
                months.setdefault((t.year, t.month), []).append(it)
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
                    cm["xyf"][k].extend(c["xyf"][k][3 * i:3 * i + 3])
    keys = sorted(months)
    built = []
    for i, (y, m) in enumerate(keys):
        items = sorted(months[(y, m)], key=lambda it: it["t"])
        nav = {}
        if i > 0:
            py, pm = keys[i - 1]; nav["prev"] = f"{planet}-moons-{py}-{pm:02d}"; nav["prev_label"] = MONTHS[pm - 1][:3]
        if i < len(keys) - 1:
            ny, nm = keys[i + 1]; nav["next"] = f"{planet}-moons-{ny}-{nm:02d}"; nav["next_label"] = MONTHS[nm - 1][:3]
        built.append(month_page(planet, y, m, items, all_cities, nav, configs.get((y, m)), grs_months.get((y, m))))
        print(f"wrote site/{built[-1]['slug']}.html: {len(items)} events ({built[-1]['n_mutual']} mutual), "
              f"{built[-1]['visible_default']} visible from New Delhi")
    return built


JUPITER_CSS = """
    .config-card { background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 0.6rem 0.8rem; }
    .config-svg { width: 100%; height: auto; display: block; background: var(--sea); border-radius: 8px; margin: 0.4rem 0; }
    .cfg-line { stroke: var(--line); stroke-width: 0.6; }
    .cfg-jup { fill: #d9b98a; stroke: #b08a55; stroke-width: 0.8; }
    .cfg-band { fill: #9c6b3a; opacity: 0.45; }
    .cfg-sat { fill: #e3cf9a; stroke: #b39a60; stroke-width: 0.8; }
    .cfg-grs { fill: #c2502f; stroke: #8f3a22; stroke-width: 0.6; }
    .cfg-ring { fill: #c9b27a; fill-opacity: 0.55; stroke: #a8904f; stroke-width: 0.6; fill-rule: evenodd; }
    .cfg-moon.dim { opacity: 0.25; }
    .cfg-lbl { font: 600 13px -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif; fill: var(--muted); }
    .filters { display: flex; flex-wrap: wrap; gap: 0.6rem 1.2rem; align-items: center; margin: 0.8rem 0 0.3rem; font-size: 0.9rem; }
    .toggle { display: inline-flex; gap: 0.4rem; align-items: center; }
    .chips { display: inline-flex; flex-wrap: wrap; gap: 0.35rem; }
    .chipbox { display: inline-flex; align-items: center; gap: 0.3rem; border: 1px solid var(--line); border-radius: 999px; padding: 0.15rem 0.6rem; font-size: 0.85rem; cursor: pointer; }
    .chipbox input { accent-color: var(--accent); }
    .cal { display: grid; grid-template-columns: repeat(7, 1fr); gap: 4px; margin: 0.9rem 0 0.8rem; }
    .cal-wd { font-size: 0.68rem; color: var(--muted); text-align: center; text-transform: uppercase; letter-spacing: 0.06em; padding-bottom: 2px; }
    .cal-cell { display: flex; flex-direction: column; align-items: center; gap: 3px; padding: 5px 0 4px; border-radius: 10px;
                background: var(--card); border: 1px solid var(--border); color: var(--muted); min-height: 54px; }
    .cal-cell.empty { background: none; border: 0; }
    .cal-cell.has { color: var(--text); border-color: color-mix(in srgb, var(--accent) 55%, var(--border)); }
    a.cal-cell:hover { text-decoration: none; border-color: var(--accent); }
    .cal-d { font-size: 0.78rem; font-weight: 600; line-height: 1; }
    .cal-dots { display: flex; gap: 2px; min-height: 6px; }
    .cal-dots i { display: block; width: 6px; height: 6px; border-radius: 50%; }
    .cal-n { font-size: 0.72rem; font-weight: 700; color: var(--accent); min-height: 0.9rem; line-height: 0.9rem; }
    .legend-icons { display: flex; flex-wrap: wrap; gap: 0.3rem 1.1rem; font-size: 0.8rem; color: var(--muted); margin: 0.2rem 0 0.2rem; }
    .legend-icons svg { width: 18px; height: 18px; vertical-align: -4px; margin-right: 0.3rem; color: var(--muted); }
    .night { background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 0.7rem 0.9rem; margin: 0.7rem 0; scroll-margin-top: 72px; }
    .night-head { display: flex; align-items: baseline; justify-content: space-between; gap: 0.3rem 0.8rem; flex-wrap: wrap; }
    .night-head h3 { font-size: 1.05rem; margin: 0; letter-spacing: -0.01em; }
    .night-sub { color: var(--muted); font-size: 0.8rem; }
    .jevents { list-style: none; margin: 0.45rem 0 0; padding: 0; display: grid; gap: 0.15rem; }
    .jev { display: grid; grid-template-columns: 26px 1fr; gap: 0.55rem; padding: 0.4rem 0.35rem; border-radius: 9px; cursor: pointer; }
    .jev:hover { background: var(--card-2); }
    .jev-ico svg { width: 24px; height: 24px; color: var(--muted); margin-top: 1px; }
    .jev.k-mutual .jev-ico svg { color: var(--accent); }
    .jev-top { font-size: 0.95rem; }
    .jev-top .dot { display: inline-block; width: 0.6em; height: 0.6em; border-radius: 50%; margin-right: 0.45em; vertical-align: 0.05em; }
    .jev-times { font-weight: 700; font-variant-numeric: tabular-nums; }
    .jev-meta { font-size: 0.78rem; color: var(--muted); }
"""
