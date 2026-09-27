#!/usr/bin/env python3
"""Jupiter's and Saturn's moons: one page per month from data/<planet>-moons-<year>.json
(engine/satellite_events.py, DE431 + JPL jup365 / sat441).

Events are geocentric — one UTC instant for the whole Earth — so a location only decides whether the planet is up
and the sky dark (from the RA/Dec stored with each event and sidereal time; no ephemeris in the browser).

The page: the moons' configuration diagram, a month calendar, and one card per observing night (noon to noon).
Each event is ONE row — start → end at the moment the moon's centre crosses the planet's or the shadow's edge,
the convention published tables use — with a type icon. The row HTML exists twice, `item_li` here and `li()` in
RENDER_JS, and must stay identical (same rounding: floor(x + 0.5)); the page prerenders New Delhi for crawlers.
DIAGRAM_JS and RENDER_JS are one shared file for both planets (site/js/moons.js) and the city list another
(site/js/cities.js); a month page carries only its own events and diagram data.
"""

import calendar as _calendar
import json
import math
import zoneinfo
from datetime import datetime, timedelta, timezone

from build_pages import FOOTER, OUT, ROOT, SITE, SITE_NAME, asset, cities_js, esc, head, site_js_url

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
# the diagram's full screen runs noon to noon in the reader's zone, so each month carries positions and events this far
# either side of it: the night before the 1st and the morning after the last, anywhere from UTC−12 to UTC+14
PAD_S = 26 * 3600
FULL_ON = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2 6V2h4M10 2h4v4M14 10v4h-4M6 14H2v-4"/></svg>'
SHARE = ('<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="12" cy="3.5" r="2"/><circle cx="4" cy="8" r="2"/>'
         '<circle cx="12" cy="12.5" r="2"/><path d="M5.8 7l4.4-2.5M5.8 9l4.4 2.5"/></svg>')

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

# pack_config() reversed: x and y from their second differences, the in-front flag from its run lengths, back into the flat
# [x, y, front, x, y, front, …] per moon that sampled() reads. Kept apart so the test can run it against pack_config().
UNPACK_JS = r"""
function unpackConfig(c) {
  c.moons.forEach(function (k) {
    var p = c.xyf[k], x = p[0], y = p[1], r = p[2], n = x.length, a = new Array(3 * n), flag = r[0], run = 1, left = r[1];
    for (var i = 0; i < n; i++) {
      a[3 * i] = i === 0 ? x[0] : i === 1 ? a[0] + x[1] : x[i] + 2 * a[3 * i - 3] - a[3 * i - 6];
      a[3 * i + 1] = i === 0 ? y[0] : i === 1 ? a[1] + y[1] : y[i] + 2 * a[3 * i - 2] - a[3 * i - 5];
      while (left === 0) { flag = 1 - flag; left = r[++run]; }
      a[3 * i + 2] = flag; left--;
    }
    c.xyf[k] = a;
  });
}
"""

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
  var DD = JSON.parse(document.getElementById('diary-data').textContent), JM = JSON.parse(document.getElementById('jmeta').textContent);
  if (DD.config) unpackConfig(DD.config);
  function sampled(ms) {   // linear interpolation of the hourly JPL samples
    var c = DD.config, i = (ms / 1000 - c.t0) / (c.step_min * 60), i0 = Math.floor(i), f = i - i0, out = [];
    c.moons.forEach(function (k) {
      var a = c.xyf[k], n = a.length / 3, j = Math.max(0, Math.min(n - 2, i0)), g = i0 < 0 ? 0 : i0 > n - 2 ? 1 : f;
      out.push({ x: (a[3*j] * (1-g) + a[3*j+3] * g) / 100, y: (a[3*j+1] * (1-g) + a[3*j+4] * g) / 100, front: (g < 0.5 ? a[3*j+2] : a[3*j+5]) === 1 });
    });
    return out;
  }
  var positions = DD.config ? sampled : galilean;
  var NS = 'http://www.w3.org/2000/svg', card = document.getElementById('config-card'), svg = document.getElementById('config-svg');
  var sl = document.getElementById('config-slider'), out = document.getElementById('config-time'), scrub = document.getElementById('cfg-scrub');
  var nightSel = document.getElementById('cfg-night'), nativeBtn = document.getElementById('cfg-native'), placeBtn = document.getElementById('cfg-place');
  var T0 = +svg.dataset.t0 * 1000, T1 = +svg.dataset.t1 * 1000, STEP = 5 * 60000;
  var NAMES = DD.names, COL = DD.colors, RAD_RJ = DD.radii, ZOOMS = DD.zooms, zi = 0, half = ZOOMS[0], W = 800, H = 170;
  function acts(a) { return [].slice.call(card.querySelectorAll('[data-act="' + a + '"]')); }
  // the month's events and the neighbouring days' (DD.pad): shadows on the disc, moons in eclipse, the "now" line, the planet's RA/Dec
  var EVS = JM.items.concat(DD.pad || []).sort(function (a, b) { return a.t - b.t; });
  // how far the planet's equator is tilted toward us (sub-Earth latitude B): sets the rings' opening
  var Tc = (T0 / 86400000 + 2440587.5 - 2451545) / 36525, PO = DD.pole;
  var pra = (PO[0] + PO[1] * Tc) * RAD, pde = (PO[2] + PO[3] * Tc) * RAD, lra = DD.ra * RAD, lde = DD.dec * RAD;
  var sinB = -(cos(pde) * cos(pra) * cos(lde) * cos(lra) + cos(pde) * sin(pra) * cos(lde) * sin(lra) + sin(pde) * sin(lde));
  function el(n, a, parent) { var e = document.createElementNS(NS, n); for (var k in a) e.setAttribute(k, a[k]); (parent || svg).appendChild(e); return e; }

  // ---- the reader's clock and sky (the place comes from the event list's location sheet: JDiagram.place)
  var LOC = null, TZ = Intl.DateTimeFormat().resolvedOptions().timeZone;
  function fmt(ms, o) { try { return new Date(ms).toLocaleString('en-GB', Object.assign({ timeZone: TZ }, o)); } catch (e) { return new Date(ms).toLocaleString('en-GB', o); } }
  function hm(ms) { return fmt(ms, { hour: '2-digit', minute: '2-digit', hour12: false }); }
  function tzName(ms) { try { return new Intl.DateTimeFormat('en-GB', { timeZone: TZ, timeZoneName: 'short' }).formatToParts(new Date(ms)).filter(function (x) { return x.type === 'timeZoneName'; })[0].value; } catch (e) { return ''; } }
  function offMin(ms) {   // the zone's offset from UTC at that instant, minutes east
    try {
      var p = {}; new Intl.DateTimeFormat('en-US', { timeZone: TZ, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })
        .formatToParts(new Date(ms)).forEach(function (x) { p[x.type] = x.value; });
      return (Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour % 24, +p.minute, +p.second) - Math.floor(ms / 1000) * 1000) / 60000;
    } catch (e) { return -new Date(ms).getTimezoneOffset(); }
  }
  function dayKey(ms) { var d = new Date(ms + offMin(ms) * 60000); return d.toISOString().slice(0, 10); }
  function addDays(k, n) { var p = k.split('-'); return new Date(Date.UTC(+p[0], +p[1] - 1, +p[2] + n, 12)).toISOString().slice(0, 10); }
  function noon(k) { var p = k.split('-'), g = Date.UTC(+p[0], +p[1] - 1, +p[2], 12), t = g - offMin(g) * 60000; return g - offMin(t) * 60000; }
  function nightOf(ms) { return dayKey(ms - 432e5); }   // a night runs noon to noon, so 01:30 stays with the evening before
  function gmst(s) { var d = s / 86400 + 2440587.5 - 2451545, T = d / 36525; return ((280.46061837 + 360.98564736629 * d + 0.000387933 * T * T) % 360 + 360) % 360; }
  function alt(s, ra, dec) { var ha = (gmst(s) + LOC.lon - ra) * RAD; return Math.asin(sin(LOC.lat * RAD) * sin(dec * RAD) + cos(LOC.lat * RAD) * cos(dec * RAD) * cos(ha)) / RAD; }
  function radec(s) {   // the planet's and the Sun's RA/Dec, interpolated between the events that carry them
    var lo = 0, hi = EVS.length - 1;
    if (hi < 0) return null;
    while (hi - lo > 1) { var mid = (lo + hi) >> 1; if (EVS[mid].t <= s) lo = mid; else hi = mid; }
    var a = EVS[lo], b = EVS[hi], f = b.t === a.t ? 0 : Math.max(0, Math.min(1, (s - a.t) / (b.t - a.t)));
    function mix(x, y, wrap) { var d = y - x; if (wrap) d = ((d + 540) % 360) - 180; return x + d * f; }
    return { ra: mix(a.ra, b.ra, 1), dec: mix(a.dec, b.dec), sra: mix(a.sra, b.sra, 1), sdec: mix(a.sdec, b.sdec) };
  }
  function skyAt(s) { var p = radec(s); return p && LOC ? { a: alt(s, p.ra, p.dec), sa: alt(s, p.sra, p.sdec) } : null; }
  function skyWord(sa) { return sa > 0 ? 'daylight' : sa > -6 ? 'twilight' : sa > -12 ? 'dusk' : 'dark sky'; }

  // ---- the moment shown: one instant, set by the month slider, the full-screen controls or a tapped event
  var ms = Math.min(Math.max(Date.now(), T0), T1), live = false, play = false, last = 0;
  var nights = [], k = nightOf(T0);            // every night that touches the month, the one before the 1st included
  while (noon(k) < T1) { nights.push(k); k = addDays(k, 1); }
  function lo() { return Math.min(T0, noon(nights[0])); }
  function hi() { return Math.max(T1, noon(addDays(nights[nights.length - 1], 1))); }

  function events(s, pos) {
    var sh = [], ecl = {};
    EVS.forEach(function (it) {
      if ((it.kind !== 'shadow' && it.kind !== 'eclipse') || !it.start || !it.end || s < it.start.t || s > it.end.t) return;
      var i = DD.keys.indexOf(it.moon);
      if (i < 0) return;
      if (it.kind === 'eclipse') { ecl[i] = 1; return; }
      // a shadow enters at the east limb (−x) and leaves at the west (+x) at the listed times: carry its offset from the moon
      // between those two edge points, so it keeps pace with its moon and meets the limb when the table says it does
      var a = positions(it.start.t * 1000)[i], b = positions(it.end.t * 1000)[i], f = (s - it.start.t) / (it.end.t - it.start.t);
      function edge(p) { var q = p.y / DD.oblate; return Math.sqrt(Math.max(0, 1 - q * q)); }
      sh.push({ i: i, x: pos[i].x + (-edge(a) - a.x) * (1 - f) + (edge(b) - b.x) * f, y: pos[i].y });
    });
    return { shadows: sh, eclipsed: ecl };
  }
  function ringHalf(s, upper, cx, cy) {
    var ro = DD.rings[0] * s, ri = DD.rings[1] * s, eo = Math.max(0.8, Math.abs(sinB) * ro), ei = Math.max(0.5, Math.abs(sinB) * ri), sw = upper ? 1 : 0;
    el('path', { class: 'cfg-ring', d: 'M ' + (cx - ro) + ' ' + cy + ' A ' + ro + ' ' + eo + ' 0 0 ' + sw + ' ' + (cx + ro) + ' ' + cy
      + ' L ' + (cx + ri) + ' ' + cy + ' A ' + ri + ' ' + ei + ' 0 0 ' + (1 - sw) + ' ' + (cx - ri) + ' ' + cy + ' Z' });
  }
  function draw() {
    var big = isBig(), pos = positions(ms), s = (W / 2 - 20) / half, ry = s * DD.oblate, cx = W / 2, cy = H / 2, st = events(ms / 1000, pos);
    svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    el('line', { x1: 0, y1: cy, x2: W, y2: cy, class: 'cfg-line' });
    var clip = el('clipPath', { id: 'jclip' }); el('ellipse', { cx: cx, cy: cy, rx: s, ry: ry }, clip);
    var labels = [];
    function moon(p, i, dim) {
      var cls = 'cfg-moon' + (dim ? ' dim' : '') + (st.eclipsed[i] ? ' ecl' : ''), g = el('g', { class: cls }), r = Math.max(big ? 5 : 4, RAD_RJ[i] * s);
      el('circle', { cx: cx + p.x * s, cy: cy - p.y * s, r: r, fill: st.eclipsed[i] ? 'none' : COL[i], stroke: st.eclipsed[i] ? COL[i] : '#0b0e14', 'stroke-width': 1.2 }, g);
      labels.push({ x: cx + p.x * s, y: cy - p.y * s, r: r, cls: cls, text: big ? NAMES[i] : NAMES[i].length > 5 ? NAMES[i].slice(0, 2) : NAMES[i][0] });
    }
    var farUpper = sinB > 0;   // seen from the north side, the far half of the rings is the upper half
    if (DD.rings) ringHalf(s, farUpper, cx, cy);
    pos.forEach(function (p, i) { if (!p.front) moon(p, i, Math.abs(p.x) < 1 && Math.abs(p.y) < DD.oblate); });
    if (DD.rings) el('ellipse', { cx: cx, cy: cy, rx: s, ry: ry, class: 'cfg-sat' });
    else {
      el('ellipse', { cx: cx, cy: cy, rx: s, ry: ry, class: 'cfg-jup' });
      [[0.3, 0.17], [-0.2, 0.2], [-0.62, 0.1]].forEach(function (b) {
        el('rect', { x: cx - s, y: cy - (b[0] + b[1] / 2) * ry, width: 2 * s, height: b[1] * ry, class: 'cfg-band', 'clip-path': 'url(#jclip)' });
      });
      var G = DD.grs;   // Great Red Spot: its System II longitude against the central meridian (daily DE431 values, interpolated)
      if (G && G.cm.length > 1) {
        var gi = (ms / 1000 - G.t0) / 86400, gk = Math.max(0, Math.min(G.cm.length - 2, Math.floor(gi))), gf = gi - gk;
        if (gi >= 0 && gi <= G.cm.length - 1) {
          var step = ((G.cm[gk + 1] - G.cm[gk] - 870.27) % 360 + 540) % 360 - 180, cmv = G.cm[gk] + (870.27 + step) * gf;
          var lon = G.lon + G.drift * (ms / 1000 - G.ref), dl = (((lon - cmv) % 360) + 540) % 360 - 180;   // + = east of the central meridian
          if (Math.cos(dl * RAD) > 0.05)
            el('ellipse', { cx: cx - sin(dl * RAD) * 0.93 * s, cy: cy + 0.36 * ry, rx: Math.max(1, 0.105 * s * cos(dl * RAD)), ry: 0.075 * ry,
              class: 'cfg-grs', 'clip-path': 'url(#jclip)' });
        }
      }
    }
    st.shadows.forEach(function (h) {
      var r = Math.max(big ? 5 : 4, RAD_RJ[h.i] * s);   // as big as its moon is drawn
      el('ellipse', { cx: cx + h.x * s, cy: cy - h.y * s, rx: r, ry: r, class: 'cfg-shadow', 'clip-path': 'url(#jclip)' });
    });
    if (DD.rings) ringHalf(s, !farUpper, cx, cy);
    pos.forEach(function (p, i) { if (p.front) moon(p, i, false); });
    // names above the moons, and when two would collide the next goes below, then higher, then lower
    var ends = [-1e9, -1e9, -1e9, -1e9], fs = big ? 14 : 13;
    labels.sort(function (a, b) { return a.x - b.x; }).forEach(function (l) {
      var w = l.text.length * fs * 0.6, left = l.x - w / 2, k = 0;
      while (k < 3 && left < ends[k] + 4) k++;
      ends[k] = Math.max(ends[k], left + w);
      var y = [l.y - l.r - 6, l.y + l.r + fs + 2, l.y - l.r - 8 - fs, l.y + l.r + 2 * fs + 4][k];
      el('text', { x: l.x, y: y, 'text-anchor': 'middle', class: 'cfg-lbl ' + l.cls.replace('cfg-moon', '') }).textContent = l.text;
    });
    var e = el('text', { x: 8, y: 16, class: 'cfg-lbl' }); e.textContent = 'E';
    var w = el('text', { x: W - 8, y: 16, 'text-anchor': 'end', class: 'cfg-lbl' }); w.textContent = 'W';
    var when = fmt(ms, { weekday: 'short', day: 'numeric', month: 'short' }).replace(',', '') + ' · ' + hm(ms) + ' ' + tzName(ms);
    out.textContent = when + (zi === 0 ? '' : ' · ±' + half + ' radii');
    sl.value = Math.round((Math.min(Math.max(ms, T0), T1) - T0) / STEP);
    acts('now').forEach(function (b) { b.classList.toggle('on', live); });
    if (big) readout(when, pos);
  }

  // ---- full screen: the time of night, the sky, what is happening
  function title(it) {
    if (it.kind === 'mutual') return JM.names[it.moon] + ' ' + (it.verb === 'occults' ? 'occults' : 'eclipses') + ' ' + JM.names[it.b];
    if (it.kind === 'grs') return 'Great Red Spot mid-disc';
    return JM.types[it.kind][0].replace('{m}', JM.names[it.moon]).replace('{p}', JM.planet.name);
  }
  function span(it) {   // [from, to] in seconds while an event is under way
    if (it.kind === 'mutual') return [it.t - it.dur * 30, it.t + it.dur * 30];
    if (it.kind === 'grs') return [it.t - JM.grsHalf, it.t + JM.grsHalf];
    return [(it.start || it.end).t, (it.end || it.start).t];
  }
  function contacts() {   // every moment worth jumping to, in order
    var c = [];
    EVS.forEach(function (it) {
      if (it.kind === 'mutual' || it.kind === 'grs') c.push(it.t);
      else [it.start, it.end].forEach(function (h) { if (h && h.seen) c.push(h.t); });
    });
    return c.sort(function (a, b) { return a - b; });
  }
  var CONTACTS = contacts();
  function dur(sec) { var m = Math.round(sec / 60); return m >= 60 ? Math.floor(m / 60) + ' h ' + String(m % 60).padStart(2, '0') + ' min' : m + ' min'; }
  function readout(when, pos) {
    var s = ms / 1000, sk = skyAt(s), now = [], next = null;
    document.getElementById('cfg-when').textContent = when;
    document.getElementById('cfg-sky').textContent = !sk ? '' : sk.a > 0 ? JM.planet.name + ' ' + Math.round(sk.a) + '° up · ' + skyWord(sk.sa) : JM.planet.name + ' below the horizon · ' + skyWord(sk.sa);
    EVS.forEach(function (it) {
      var sp = span(it);
      if (sp[0] <= s && s <= sp[1]) now.push(title(it) + ' · until ' + hm(sp[1] * 1000));
      else if (sp[0] > s && (!next || sp[0] < span(next)[0])) next = it;
    });
    document.getElementById('cfg-happen').textContent = now.length ? now.join(' · ')
      : next ? 'Next: ' + title(next) + ' at ' + hm(span(next)[0] * 1000) + ' (in ' + dur(span(next)[0] - s) + ')' : '';
    if (nightSel.value !== nightOf(ms)) { nightSel.value = nightOf(ms); drawTrack(); }
    var c = scrub.querySelector('.cur'), x = xOf(ms);
    if (c) c.setAttribute('transform', 'translate(' + x + ' 0)');
    scrub.setAttribute('aria-valuetext', when);
  }
  // the time-of-night track: noon to noon, shaded by the Sun, a bar where the planet is well placed, a tick per contact
  var SW = 800, SH = 40;
  function nightRange() { var n = nightOf(ms); return [noon(n), noon(addDays(n, 1))]; }
  function xOf(t) { var r = nightRange(); return 8 + (SW - 16) * (t - r[0]) / (r[1] - r[0]); }
  function drawTrack() {
    if (!isBig() || !LOC) return;
    SW = scrub.clientWidth || 800;
    scrub.setAttribute('viewBox', '0 0 ' + SW + ' ' + SH);
    while (scrub.firstChild) scrub.removeChild(scrub.firstChild);
    var r = nightRange(), n = 144, dx = (SW - 16) / n;
    for (var i = 0; i < n; i++) {
      var t = r[0] + (r[1] - r[0]) * (i + 0.5) / n, sk = skyAt(t / 1000);
      if (!sk) continue;
      el('rect', { x: 8 + i * dx, y: 8, width: dx + 0.6, height: 16, class: 'sk ' + (sk.sa > 0 ? 'sk-day' : sk.sa > -6 ? 'sk-tw' : sk.sa > -12 ? 'sk-dusk' : 'sk-dark') }, scrub);
      if (sk.a > 10 && sk.sa < -6) el('rect', { x: 8 + i * dx, y: 3, width: dx + 0.6, height: 4, class: 'sk-planet' }, scrub);
      else if (sk.a > 0) el('rect', { x: 8 + i * dx, y: 4, width: dx + 0.6, height: 2, class: 'sk-planet low' }, scrub);
    }
    CONTACTS.forEach(function (c) {
      if (c * 1000 < r[0] || c * 1000 > r[1]) return;
      var it = EVS.filter(function (e) { return e.t === c || (e.start && e.start.t === c) || (e.end && e.end.t === c); })[0];
      el('rect', { x: xOf(c * 1000) - 1, y: 10, width: 2, height: 12, fill: (it && JM.colors[it.moon]) || '#94a3b8', class: 'tick' }, scrub);
    });
    for (var h = Math.ceil(r[0] / 36e5) * 36e5; h < r[1]; h += 36e5) {
      var lab = hm(h);
      if (+lab.slice(0, 2) % (SW < 560 ? 3 : 2)) continue;
      el('text', { x: xOf(h), y: 37, 'text-anchor': 'middle', class: 'sk-lbl' }, scrub).textContent = lab;
    }
    var cur = el('g', { class: 'cur', transform: 'translate(' + xOf(ms) + ' 0)' }, scrub);
    el('line', { x1: 0, y1: 2, x2: 0, y2: 26 }, cur);
    el('circle', { cx: 0, cy: 16, r: 6 }, cur);
  }
  function fillNights() {
    nightSel.innerHTML = '';
    nights.forEach(function (n) {
      var p = n.split('-'), lbl = new Date(Date.UTC(+p[0], +p[1] - 1, +p[2], 12)).toLocaleDateString('en-GB', { timeZone: 'UTC', weekday: 'short', day: 'numeric', month: 'short' }).replace(',', '');
      nightSel.add(new Option('Night of ' + lbl, n));
    });
    nightSel.value = nightOf(ms);
  }

  function set(t, how) {
    how = how || {};
    ms = Math.min(Math.max(t, lo()), hi());
    if (!how.live) live = false;
    if (!how.play && play) stopPlay();
    draw();
    if (isBig()) remember();
  }
  var urlTimer = null;
  function remember() {   // the address keeps the moment, so a reload or a shared link opens the same view
    clearTimeout(urlTimer);
    urlTimer = setTimeout(function () { if (isBig()) history.replaceState(history.state, '', location.pathname + '?full&t=' + Math.round(ms / 1000) + location.hash); }, 400);
  }
  function stopPlay() { play = false; acts('play').forEach(function (b) { b.textContent = isBig() ? '▶' : 'Play'; b.setAttribute('aria-label', 'Play'); }); }
  function tick(now) {
    if (!play) return;
    var dt = Math.min(100, now - last); last = now;
    var big = isBig(), t = ms + dt * (big ? 1200 : 11250);   // full screen: 20 minutes a second; the month: 3 hours
    if (big && t >= nightRange()[1]) { set(nightRange()[1]); return; }
    if (!big && t > T1) t = T0;
    set(t, { play: true });
    requestAnimationFrame(tick);
  }
  function togglePlay() {
    if (play) return stopPlay();
    play = true; live = false; last = performance.now();
    acts('play').forEach(function (b) { b.textContent = isBig() ? '❚❚' : 'Pause'; b.setAttribute('aria-label', 'Pause'); });
    requestAnimationFrame(tick);
  }
  function goNow() {
    var t = Date.now(), ym = new Date(t).toISOString().slice(0, 7);
    if (t >= lo() && t <= hi()) return set(t, { live: true });
    if (DD.months.indexOf(ym) >= 0) location.href = '/' + DD.planet + '-moons-' + ym + (isBig() ? '?full' : '') + '#config';
  }
  function stepNight(d) {
    var i = nights.indexOf(nightOf(ms)) + d;
    if (i >= 0 && i < nights.length) return set(ms + d * 864e5);
    var slug = d < 0 ? DD.prev : DD.next;
    if (slug) location.href = '/' + slug + '?full&t=' + Math.round((ms + d * 864e5) / 1000) + '#config';
  }
  function stepEvent(d) {
    var s = ms / 1000, c = d > 0 ? CONTACTS.filter(function (x) { return x > s + 30; })[0] : CONTACTS.filter(function (x) { return x < s - 30; }).pop();
    if (c !== undefined) set(c * 1000);
  }

  // share the moment: a link that opens this month's full screen at this instant, in the recipient's own place and clock
  // (the events are the same instant everywhere); the phone's share sheet where there is one, else the clipboard
  function share(btn) {
    var url = location.origin + location.pathname.replace(/\.html$/, '') + '?full&t=' + Math.round(ms / 1000);
    var title = JM.planet.name + "'s moons · " + fmt(ms, { weekday: 'short', day: 'numeric', month: 'short' }).replace(',', '') + ' ' + hm(ms) + ' ' + tzName(ms);
    if (navigator.share) return navigator.share({ title: title, url: url }).catch(function () {});
    var icon = btn.innerHTML, done = function (ok) {
      btn.textContent = ok ? '✓' : '✕'; btn.title = ok ? 'Link copied' : 'Copy the address bar';
      setTimeout(function () { btn.innerHTML = icon; btn.title = 'Share this moment'; }, 2000);
    };
    if (navigator.clipboard) navigator.clipboard.writeText(url).then(function () { done(true); }, function () { done(false); });
    else done(false);
  }

  function native() { return document.fullscreenElement || document.webkitFullscreenElement; }
  function isBig() { return card.classList.contains('max'); }
  var backOut = function () { if (isBig()) close(); };
  function size() {
    if (isBig()) { W = Math.max(320, svg.clientWidth); H = Math.max(120, svg.clientHeight); }
    else { W = 800; H = 170; }
  }
  function lockLandscape() { try { screen.orientation.lock('landscape').catch(function () {}); } catch (e) {} }
  function goNative() {
    var req = card.requestFullscreen || card.webkitRequestFullscreen, p = req && req.call(card);
    if (p && p.then) p.then(lockLandscape, function () {});
  }
  function open(gesture) {
    if (isBig()) return;
    card.classList.add('max');
    document.documentElement.classList.add('cfg-max-open');
    Overlay.opened(backOut);
    if (gesture) goNative();
    stopPlay(); relayout(); remember();
  }
  function close() {
    if (!isBig()) return;
    if (native()) (document.exitFullscreen || document.webkitExitFullscreen).call(document);
    card.classList.remove('max');
    document.documentElement.classList.remove('cfg-max-open');
    clearTimeout(urlTimer);
    history.replaceState(history.state, '', location.pathname + location.hash);
    Overlay.closed(backOut);
    stopPlay(); relayout();
  }
  function relayout() {
    size();
    nativeBtn.hidden = !isBig() || !!native() || !(card.requestFullscreen || card.webkitRequestFullscreen);
    acts('play').forEach(function (b) { if (!play) b.textContent = isBig() ? '▶' : 'Play'; });
    draw(); drawTrack();
  }
  var wasNative = false;
  function fsChange() { var n = !!native(); if (wasNative && !n) close(); wasNative = n; relayout(); }
  document.addEventListener('fullscreenchange', fsChange);
  document.addEventListener('webkitfullscreenchange', fsChange);
  addEventListener('resize', function () { if (isBig()) relayout(); });

  // ---- wiring
  sl.max = Math.round((T1 - T0) / STEP);
  sl.addEventListener('input', function () { set(T0 + (+sl.value) * STEP); });
  acts('zoom').forEach(function (b) { b.addEventListener('click', function () {
    zi = (zi + 1) % ZOOMS.length; half = ZOOMS[zi];
    acts('zoom').forEach(function (x) { x.textContent = zi === ZOOMS.length - 1 ? 'Zoom out' : 'Zoom in'; });
    draw();
  }); });
  acts('play').forEach(function (b) { b.addEventListener('click', togglePlay); });
  acts('now').forEach(function (b) { b.addEventListener('click', goNow); });
  acts('share').forEach(function (b) { b.addEventListener('click', function () { share(b); }); });
  acts('full').forEach(function (b) { b.addEventListener('click', function () { isBig() ? close() : open(true); }); });
  acts('step').forEach(function (b) { b.addEventListener('click', function () { set(ms + (+b.dataset.m) * 60000); }); });
  acts('event').forEach(function (b) { b.addEventListener('click', function () { stepEvent(+b.dataset.d); }); });
  acts('night').forEach(function (b) { b.addEventListener('click', function () { stepNight(+b.dataset.d); }); });
  nightSel.addEventListener('change', function () { set(ms + (noon(nightSel.value) - noon(nightOf(ms)))); });
  nativeBtn.addEventListener('click', goNative);
  placeBtn.addEventListener('click', function () { document.getElementById('loc-chip').click(); });
  function svgX(ev, el) { var m = el.getScreenCTM(), p = el.createSVGPoint(); p.x = ev.clientX; p.y = ev.clientY; return p.matrixTransform(m.inverse()).x; }
  // the track: tap or drag anywhere on it (getScreenCTM follows the page's rotation on a phone held upright)
  // The night is fixed when the finger goes down and the far end stops a second short of the next noon: at that noon the
  // track would turn to the next night with the cursor at its start, the same finger would then be past ITS end, and the
  // cursor jumped between the two ends a night at a time
  var scrubbing = null;
  function scrubTo(ev) { var r = scrubbing || nightRange(); set(Math.min(r[1] - 1000, r[0] + (r[1] - r[0]) * Math.max(0, Math.min(1, (svgX(ev, scrub) - 8) / (SW - 16))))); }
  // a drag must never start a text selection (it would carry the page's text along and steal the pointer), so the press
  // is taken whole: default prevented, the selection cleared, focus given back by hand for the arrow keys
  function hold(ev, el) { ev.preventDefault(); try { getSelection().removeAllRanges(); } catch (e) {} el.setPointerCapture(ev.pointerId); }
  scrub.addEventListener('pointerdown', function (ev) { hold(ev, scrub); scrub.classList.add('ptr'); scrub.focus({ preventScroll: true }); scrubbing = nightRange(); scrubTo(ev); });
  scrub.addEventListener('keydown', function () { scrub.classList.remove('ptr'); });   // the keys bring the outline back
  scrub.addEventListener('blur', function () { scrub.classList.remove('ptr'); });
  scrub.addEventListener('pointermove', function (ev) { if (scrubbing) scrubTo(ev); });
  scrub.addEventListener('pointerup', function () { scrubbing = null; });
  scrub.addEventListener('pointercancel', function () { scrubbing = null; });
  // full screen, the diagram itself: one finger drags sideways through time (the whole width is four hours), two pinch to
  // zoom; a mouse wheel zooms and a trackpad's sideways swipe moves the time
  var drag = null, pinch = null, pts = {};
  function zoomTo(h) { half = Math.min(ZOOMS[0] * 1.5, Math.max(1.5, h)); draw(); }
  function spread() { var k = Object.keys(pts), a = pts[k[0]], b = pts[k[1]]; return Math.hypot(a.x - b.x, a.y - b.y) || 1; }
  svg.addEventListener('pointerdown', function (ev) {
    if (!isBig()) return;
    hold(ev, svg); pts[ev.pointerId] = { x: ev.clientX, y: ev.clientY };
    if (Object.keys(pts).length === 2) { drag = null; pinch = { d: spread(), half: half }; }
    else if (!pinch) drag = { x: svgX(ev, svg), t: ms };
  });
  svg.addEventListener('pointermove', function (ev) {
    if (!pts[ev.pointerId]) return;
    pts[ev.pointerId] = { x: ev.clientX, y: ev.clientY };
    if (pinch && Object.keys(pts).length === 2) zoomTo(pinch.half * pinch.d / spread());
    else if (drag) set(drag.t + (svgX(ev, svg) - drag.x) / W * 4 * 36e5);
  });
  function lift(ev) { delete pts[ev.pointerId]; drag = null; if (Object.keys(pts).length < 2) pinch = null; }
  svg.addEventListener('pointerup', lift);
  svg.addEventListener('pointercancel', lift);
  svg.addEventListener('wheel', function (ev) {
    if (!isBig()) return;
    ev.preventDefault();
    if (Math.abs(ev.deltaX) > Math.abs(ev.deltaY)) set(ms + ev.deltaX / W * 4 * 36e5);
    else zoomTo(half * Math.exp(ev.deltaY * 0.002));
  }, { passive: false });
  document.addEventListener('keydown', function (e) {
    if (!isBig() || e.target.tagName === 'SELECT' || e.target.tagName === 'INPUT' || document.querySelector('dialog[open]')) return;
    var m = { ArrowLeft: -1, ArrowRight: 1, PageUp: -60, PageDown: 60 }[e.key];
    if (m) { set(ms + m * (e.shiftKey ? 10 : 1) * 60000); e.preventDefault(); }
    else if (e.key === '[' || e.key === ']') stepEvent(e.key === ']' ? 1 : -1);
    else if (e.key === ' ') { togglePlay(); e.preventDefault(); }
    else if (e.key === 'n' || e.key === 'N') goNow();
    else if (e.key === 'Escape' && !native()) close();
  });
  setInterval(function () { if (live) set(Date.now(), { live: true }); }, 20000);

  window.JDiagram = {
    at: function (t) { set(t); },
    place: function (loc, tz) {   // the event list's place: the clock, the sky and the nights follow it
      LOC = loc; TZ = tz;
      placeBtn.querySelector('span').textContent = loc.label;
      nights = []; var n = nightOf(T0); while (noon(n) < T1) { nights.push(n); n = addDays(n, 1); }
      fillNights(); draw(); drawTrack();
    }
  };
  var q = new URLSearchParams(location.search);
  if (q.has('t') && isFinite(+q.get('t'))) ms = Math.min(Math.max(+q.get('t') * 1000, lo()), hi());
  if (!q.has('t') && Date.now() >= T0 && Date.now() <= T1) live = true;   // opened on this month: the diagram follows the clock
  if (q.has('full')) { if (!q.has('t')) { var t = Date.now(); if (t >= lo() && t <= hi()) { ms = t; live = true; } } open(false); }
  fillNights(); draw();
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
    if (window.JDiagram) JDiagram.place(LOC, tz);
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
  M.cities = window.OccultCities || {};      // js/cities.js, loaded just before this file
  Object.keys(M.cities).forEach(function (n) { sel.add(new Option(n, n)); });
  function setLoc(lat, lon, label, quiet) {   // quiet: the page's own starting place, not one the reader chose
    lat = +lat; lon = +lon; if (!isFinite(lat) || !isFinite(lon)) return;
    LOC = { lat: lat, lon: lon, label: label || placeName(lat, lon, M.cities) };
    if (!quiet) { try { localStorage.setItem('occult-loc', JSON.stringify(LOC)); } catch (e) {} placeAsked(); }
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
  if (saved && isFinite(saved.lat)) setLoc(saved.lat, saved.lon, saved.label, true);
  else { setLoc(M.defaultPlace[1], M.defaultPlace[2], M.defaultPlace[0], true); askPlace(M.defaultPlace[0], function (lat, lon) { setLoc(lat, lon); }); }
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
    <label>City <select id="loc-city"><option value="">—</option></select></label>
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
  <div class="config-card" id="config-card">
    <div class="cfg-fs cfg-top">
      <b class="cfg-title">__PNAME__<span class="cfg-month"> · __LABEL__</span></b>
      <span class="cfg-nightnav"><button class="btn" type="button" data-act="night" data-d="-1" aria-label="The night before">‹</button><select id="cfg-night" aria-label="Night"></select><button class="btn" type="button" data-act="night" data-d="1" aria-label="The night after">›</button></span>
      <span class="cfg-right"><button class="btn cfg-place" type="button" id="cfg-place" aria-haspopup="dialog">📍 <span>__PLACE__</span></button><button class="btn" type="button" data-act="zoom">Zoom in</button><button class="btn cfg-share" type="button" data-act="share" aria-label="Share this moment" title="Share this moment">__SHARE__</button><button class="btn" type="button" id="cfg-native" hidden aria-label="Fill the screen" title="Fill the screen">__FULL_ON__</button><button class="btn" type="button" data-act="full" aria-label="Close full screen" title="Close full screen">✕</button></span>
    </div>
    <div class="limb-controls"><span class="limb-readout" id="config-time"></span>
      <span class="cfg-btns"><button class="btn" id="config-now" type="button" data-act="now">Now</button><button class="btn" id="config-play" type="button" data-act="play">Play</button><button class="btn" id="config-zoom" type="button" data-act="zoom">Zoom in</button><button class="btn cfg-share" type="button" data-act="share" aria-label="Share this moment" title="Share this moment">__SHARE__</button><button class="btn cfg-full" id="config-full" type="button" data-act="full" aria-label="Full screen" title="Full screen">__FULL_ON__</button></span></div>
    <svg id="config-svg" viewBox="0 0 800 170" class="config-svg" role="img" aria-label="__PNAME__ and its moons" data-t0="__T0__" data-t1="__T1__"></svg>
    <input type="range" id="config-slider" min="0" max="100" value="0" step="1" aria-label="Time">
    <div class="cfg-fs cfg-read"><b id="cfg-when"></b><span id="cfg-sky"></span><span id="cfg-happen"></span></div>
    <svg class="cfg-fs cfg-scrub" id="cfg-scrub" role="slider" tabindex="0" aria-label="Time of night"></svg>
    <div class="cfg-fs cfg-steps">
      <button class="btn" type="button" data-act="event" data-d="-1" aria-label="Previous event" title="Previous event">⏮</button><button class="btn" type="button" data-act="step" data-m="-60">−1 h</button><button class="btn" type="button" data-act="step" data-m="-10">−10 m</button><button class="btn" type="button" data-act="step" data-m="-1">−1 m</button><button class="btn cfg-now" type="button" data-act="now">Now</button><button class="btn" type="button" data-act="step" data-m="1">+1 m</button><button class="btn" type="button" data-act="step" data-m="10">+10 m</button><button class="btn" type="button" data-act="step" data-m="60">+1 h</button><button class="btn" type="button" data-act="event" data-d="1" aria-label="Next event" title="Next event">⏭</button><button class="btn" type="button" data-act="play" aria-label="Play">▶</button>
    </div>
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
<script src="__SITE_JS__"></script>
<script src="__CITIES_JS__"></script>
<script src="__MOONS_JS__"></script>
</body>
</html>
"""


def pack_config(c):
    """A month of hourly JPL samples as the page carries them: x and y (hundredths of a planet radius) as second
    differences — they change smoothly, so the numbers are small and gzip well — and the in-front flag as run lengths.
    Lossless, and a quarter of the size (Saturn, October 2026: 18.9 KB gzipped as plain numbers, 4.7 KB packed).
    unpackConfig() in UNPACK_JS reverses it."""
    def d2(s):
        return list(s[:1]) + [s[i] - s[i - 1] if i == 1 else s[i] - 2 * s[i - 1] + s[i - 2] for i in range(1, len(s))]

    def runs(f):
        out, cur, n = [f[0]], f[0], 0
        for v in f:
            if v == cur:
                n += 1
            else:
                out.append(n)
                cur, n = v, 1
        return out + [n]

    xyf = {}
    for k, a in c["xyf"].items():
        assert set(a[2::3]) <= {0, 1}, f"{k}: the in-front flag must be 0 or 1"
        xyf[k] = [d2(a[0::3]), d2(a[1::3]), runs(a[2::3])]
    return dict(c, xyf=xyf)


def month_page(planet, year, month, items, all_cities, nav, config=None, grs=None, pad=(), months=()):
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
            "config": config and pack_config(config), "pole": P["pole"], "rings": P["rings"], "ra": first["ra"], "dec": first["dec"],
            "grs": grs and {k: grs[k] for k in ("t0", "cm", "lon", "ref", "drift")},
            "keys": P["moons"], "pad": list(pad), "planet": planet, "prev": nav.get("prev"), "next": nav.get("next"), "months": list(months)}
    kinds_present = {it["kind"] for it in items}
    meta = {"items": items, "planet": {"name": pname}, "names": MOON_NAME, "colors": P["colors"], "icons": ICONS, "types": TYPES,
            "defaultPlace": list(DEFAULT_PLACE), "ym": [year, month], "t0": t0, "grsHalf": GRS_HALF_VIEW}
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
                 f"jump there; full screen (⤢) steps through a single night a minute at a time. Moons behind the planet fade, a moon "
                 f"in {pname}'s shadow is an empty ring, and a shadow on the disc is placed from the listed times. " + ("Positions ±0.1 Jupiter radii — for the picture; the times come from JPL."
                                                                  if planet == "jupiter" else "Positions are JPL's, sampled hourly; the rings are drawn at their real tilt."))
    prev_link = f'<a href="/{nav["prev"]}">‹ {nav["prev_label"]}</a>' if nav.get("prev") else "<span></span>"
    next_link = f'<a href="/{nav["next"]}">{nav["next_label"]} ›</a>' if nav.get("next") else "<span></span>"
    body = TEMPLATE
    for k, v in {"__PREV__": prev_link, "__NEXT__": next_link, "__PLANET__": planet, "__PLACE__": esc(name),
                 "__TITLE__": esc(title), "__SUB__": " · ".join(MOON_NAME[m] for m in P["moons"]) + (f" — {n_mutual} mutual events" if n_mutual else ""),
                 "__LEAD__": lead, "__PNAME__": pname, "__LABEL__": label, "__FULL_ON__": FULL_ON, "__SHARE__": SHARE, "__T0__": str(t0), "__T1__": str(t1), "__DIAG_HINT__": diag_hint,
                 "__CHIPS__": chips, "__COUNT__": f"{len(visible)} events you can see from {esc(name)} this month, on {len(groups)} nights",
                 "__CAL__": calendar_html(year, month, groups, P), "__LEGEND__": legend,
                 "__NIGHTS__": nights_html(groups, P, tz, lat, lon), "__METHOD__": method,
                 "__DIAG_DATA__": json.dumps(diag, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"),
                 "__META__": json.dumps(meta, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"),
                 "__FOOTER__": FOOTER, "__SITE_JS__": site_js_url(), "__CITIES_JS__": cities_js("cities", all_cities),
                 "__MOONS_JS__": asset("js/moons.js", UNPACK_JS.lstrip() + DIAGRAM_JS + RENDER_JS)}.items():
        body = body.replace(k, v)
    (OUT / f"{slug}.html").write_text(head(f"{title} · {SITE_NAME}", desc, f"/{slug}", extra=f"<style>{JUPITER_CSS}</style>", og=planet) + body)
    return {"slug": slug, "label": label, "year": year, "month": month, "n": len(items), "n_mutual": n_mutual, "planet": planet,
            "visible_default": len(visible)}


def build_all(all_cities, planet="jupiter"):
    files = sorted(ROOT.glob(f"data/{planet}-moons-*.json"))
    months, configs, grs_months, samples, moons = {}, {}, {}, {}, None
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
            i0 = max(0, (m0 - PAD_S - cmd["t0"]) // 86400)
            i1 = min(len(cmd["values"]) - 1, (m1 + PAD_S - cmd["t0"]) // 86400 + 1)
            grs_months[key] = dict(common, t0=cmd["t0"] + i0 * 86400, cm=cmd["values"][i0:i1 + 1])
    for f in files:
        d = json.loads(f.read_text())
        for ev in d["events"]:
            it = item_of(ev)
            if it:
                t = datetime.fromtimestamp(it["t"], timezone.utc)
                months.setdefault((t.year, t.month), []).append(it)
        if d.get("config"):
            c = d["config"]; t0 = parse(c["t0"]).timestamp(); step = c["step_min"] * 60
            moons = c["moons"]
            n = len(next(iter(c["xyf"].values()))) // 3
            for i in range(n):
                samples[int(t0 + i * step)] = [c["xyf"][k][3 * i:3 * i + 3] for k in moons]
    if samples:
        # a month's hourly samples, with PAD_S either side, as far as the samples run unbroken
        ts = sorted(samples)
        step = ts[1] - ts[0]
        for (y, m) in months:
            m0 = int(datetime(y, m, 1, tzinfo=timezone.utc).timestamp())
            m1 = int(datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=timezone.utc).timestamp())
            first = next((t for t in ts if t >= m0 - PAD_S), None)
            if first is None or first >= m1:
                continue
            run = [first]
            while run[-1] + step < m1 + PAD_S and run[-1] + step in samples:
                run.append(run[-1] + step)
            configs[(y, m)] = {"t0": first, "step_min": step // 60, "moons": moons,
                               "xyf": {k: [v for t in run for v in samples[t][j]] for j, k in enumerate(moons)}}
    keys = sorted(months)
    every = sorted((it for v in months.values() for it in v), key=lambda it: it["t"])
    yms = [f"{y}-{m:02d}" for y, m in keys]
    built = []
    for i, (y, m) in enumerate(keys):
        items = sorted(months[(y, m)], key=lambda it: it["t"])
        nav = {}
        if i > 0:
            py, pm = keys[i - 1]; nav["prev"] = f"{planet}-moons-{py}-{pm:02d}"; nav["prev_label"] = MONTHS[pm - 1][:3]
        if i < len(keys) - 1:
            ny, nm = keys[i + 1]; nav["next"] = f"{planet}-moons-{ny}-{nm:02d}"; nav["next_label"] = MONTHS[nm - 1][:3]
        m0 = int(datetime(y, m, 1, tzinfo=timezone.utc).timestamp())
        m1 = int(datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=timezone.utc).timestamp())
        pad = [it for it in every if m0 - PAD_S <= it["t"] < m0 or m1 <= it["t"] < m1 + PAD_S]
        built.append(month_page(planet, y, m, items, all_cities, nav, configs.get((y, m)), grs_months.get((y, m)), pad, yms))
        print(f"wrote site/{built[-1]['slug']}.html: {len(items)} events ({built[-1]['n_mutual']} mutual), "
              f"{built[-1]['visible_default']} visible from New Delhi")
    return built


JUPITER_CSS = """
    .config-card { background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 0.6rem 0.8rem; }
    .config-svg, .cfg-scrub, #config-slider, .config-card.max { -webkit-user-select: none; user-select: none; -webkit-touch-callout: none; }
    .config-card.max select { -webkit-user-select: auto; user-select: auto; }
    .config-svg { width: 100%; height: auto; display: block; background: var(--sea); border-radius: 8px; margin: 0.4rem 0; }
    .cfg-line { stroke: var(--line); stroke-width: 0.6; }
    .cfg-jup { fill: #d9b98a; stroke: #b08a55; stroke-width: 0.8; }
    .cfg-band { fill: #9c6b3a; opacity: 0.45; }
    .cfg-sat { fill: #e3cf9a; stroke: #b39a60; stroke-width: 0.8; }
    .cfg-grs { fill: #c2502f; stroke: #8f3a22; stroke-width: 0.6; }
    .cfg-ring { fill: #c9b27a; fill-opacity: 0.55; stroke: #a8904f; stroke-width: 0.6; fill-rule: evenodd; }
    .cfg-moon.dim, .cfg-lbl.dim { opacity: 0.25; }
    .cfg-moon.ecl circle { stroke-dasharray: 2 2; }
    .cfg-lbl.ecl { opacity: 0.5; }
    .cfg-shadow { fill: #07080c; opacity: 0.9; }
    .cfg-btns { display: inline-flex; flex-wrap: wrap; gap: 0.3rem; }
    .cfg-full svg, #cfg-native svg, .cfg-share svg { width: 15px; height: 15px; fill: none; stroke: currentColor; stroke-width: 1.8; vertical-align: -2px; }
    .btn.on { border-color: var(--accent); color: var(--accent); }
    /* Full screen: the card covers the window (and the screen, where the browser allows), always in night colours. A phone
       held upright gets it turned a quarter: the moons lie along a line, and a line wants the long side. */
    .config-card:not(.max) .cfg-fs { display: none; }
    html.cfg-max-open, html.cfg-max-open body { overflow: hidden; }
    .config-card.max { position: fixed; inset: 0 auto auto 0; z-index: 2000; width: 100vw; height: 100vh; height: 100dvh; margin: 0;
      border: 0; border-radius: 0; display: grid; grid-template-rows: auto minmax(0, 1fr) auto auto auto; gap: 0.3rem;
      grid-template-columns: minmax(0, 1fr);
      padding: max(0.4rem, env(safe-area-inset-top)) max(0.6rem, env(safe-area-inset-right)) max(0.4rem, env(safe-area-inset-bottom)) max(0.6rem, env(safe-area-inset-left));
      --bg: #0c0f17; --card: #131826; --card-2: #1a2030; --border: #222a3b; --line: #313a50; --text: #ece8dd; --muted: #9aa0ae;
      --accent: #a9c1f0; --sea: #090c13; color-scheme: dark; background: var(--bg); color: var(--text); }
    @media (orientation: portrait) and (max-width: 600px) and (pointer: coarse) {
      .config-card.max { width: 100vh; width: 100dvh; height: 100vw; height: 100dvw; transform-origin: 0 0; transform: rotate(90deg) translateY(-100%); }
    }
    /* the column is the card's width, never its content's: an auto column grew to fit the one-line "what is happening"
       text, so the track stretched under the finger as that text changed and the time jittered between two values */
    .config-card.max > .limb-controls, .config-card.max > #config-slider { display: none; }
    .config-card.max .config-svg { width: 100%; height: 100%; margin: 0; touch-action: none; cursor: ew-resize; }
    .config-card.max .cfg-lbl { font-size: 14px; }
    .config-card.max .btn { padding: 0.3rem 0.6rem; font-variant-numeric: tabular-nums; white-space: nowrap; }
    .cfg-top { display: flex; align-items: center; gap: 0.4rem 0.8rem; flex-wrap: wrap; }
    .cfg-title { font-family: var(--serif); font-size: 1.05rem; white-space: nowrap; }
    .cfg-nightnav { display: inline-flex; align-items: center; gap: 0.25rem; }
    .cfg-nightnav select { font: inherit; font-size: 0.85rem; padding: 0.3rem 0.4rem; border-radius: 8px; border: 1px solid var(--line); background: var(--card); color: var(--text); }
    .cfg-right { display: inline-flex; gap: 0.3rem; margin-left: auto; }
    .cfg-place { max-width: 11rem; overflow: hidden; text-overflow: ellipsis; }
    .cfg-read { display: flex; flex-wrap: wrap; align-items: baseline; gap: 0.1rem 1rem; font-size: 0.9rem; min-height: 1.3rem; }
    .cfg-read b { font-size: 1.05rem; font-variant-numeric: tabular-nums; }
    #cfg-sky { color: var(--muted); }
    #cfg-happen { color: var(--accent); flex: 1 1 14rem; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .cfg-scrub { display: block; width: 100%; height: 40px; touch-action: none; cursor: pointer; }
    .cfg-scrub:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 4px; }
    .cfg-scrub.ptr:focus-visible { outline: none; }   /* focused by a touch or a click, not a key: nothing to point out */
    .sk-day { fill: #3d5178; } .sk-tw { fill: #2a3657; } .sk-dusk { fill: #1b2340; } .sk-dark { fill: #0e1222; }
    .sk-planet { fill: #e3c486; } .sk-planet.low { opacity: 0.35; }
    .sk-lbl { font: 500 11px -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif; fill: var(--muted); }
    .cur line { stroke: #fff; stroke-width: 2; } .cur circle { fill: #fff; stroke: #0c0f17; stroke-width: 2; }
    .cfg-steps { display: flex; flex-wrap: wrap; justify-content: center; gap: 0.3rem; }
    @media (max-height: 420px), (orientation: portrait) and (max-width: 600px) and (pointer: coarse) {
      .config-card.max { gap: 0.2rem; }
      .cfg-month { display: none; }
      .config-card.max .btn { padding: 0.2rem 0.5rem; font-size: 0.8rem; }
      .cfg-title { font-size: 0.95rem; }
    }
    .cfg-lbl { font: 600 13px -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif; fill: var(--muted);
               paint-order: stroke; stroke: var(--sea); stroke-width: 3px; stroke-linejoin: round; }
    .filters { display: flex; flex-wrap: wrap; gap: 0.6rem 1.2rem; align-items: center; margin: 0.8rem 0 0.3rem; font-size: 0.9rem; }
    .toggle { display: inline-flex; gap: 0.4rem; align-items: center; }
    @media (pointer: coarse) { .toggle { min-height: 44px; } }
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
