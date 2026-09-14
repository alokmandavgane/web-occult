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


def _hash(content):
    import hashlib
    return hashlib.sha1(content if isinstance(content, bytes) else content.encode()).hexdigest()[:10]


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


WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
TEXTURE = "/img/moon-relief-360.png"


def short_label(label):
    """Gaia-only stars have 19-digit ids: show the tail, keep the full id in the tooltip."""
    return "Gaia …" + label[-7:] if label.startswith("Gaia DR3 ") else label


def li_html(n, ev, vis, t0, tz):
    keys = [k for k in ("D", "R") if k in vis]
    verb = {"D": "Disappears", "R": "Reappears"}
    c0 = vis[keys[0]]
    t = (t0 + timedelta(minutes=c0["m"])).astimezone(tz)
    what = f"{verb[keys[0]]} at the {c0['limb']} limb"
    if len(keys) == 2:
        c1 = vis[keys[1]]
        t1 = (t0 + timedelta(minutes=c1["m"])).astimezone(tz)
        what += f" · {verb[keys[1]].lower()} {t1.strftime('%H:%M:%S')} at the {c1['limb']} limb"
    graze = ' <span class="badge">graze</span>' if ev["graze"] else ""
    return (f'<li class="ev lim-{c0["limb"]}"><span class="ev-n">{n}</span><div class="ev-main">'
            f'<div class="ev-top"><span class="ev-time">{t.strftime("%H:%M:%S")}</span> <b class="ev-star" title="{esc(ev["label"])}">{esc(short_label(ev["label"]))}</b> '
            f'<small>V {ev["vmag"]:.1f}</small>{graze}</div>'
            f'<div class="ev-what">{what}</div>'
            f'<div class="ev-meta">{c0["moon_alt"]:.0f}° up in the {compass(c0["moon_az"])} · {sky_text(c0["sun_alt"])} · '
            f'PA {c0["pa"]:.0f}° · cusp {c0["cusp"]:.0f}°</div></div></li>')


def group_nights(items, t0, tz):
    """items: (first visible minute, ev, vis) sorted. Night of date D = local times from D 12:00 to D+1 12:00."""
    groups = {}
    for m, ev, vis in items:
        key = ((t0 + timedelta(minutes=m)).astimezone(tz) - timedelta(hours=12)).date()
        groups.setdefault(key, []).append((m, ev, vis))
    return groups


def nights_html(groups, t0, tz):
    out = []
    for key in sorted(groups):
        rows = "".join(li_html(i + 1, ev, vis, t0, tz) for i, (_, ev, vis) in enumerate(groups[key]))
        out.append(f'<section class="night" id="night-{key.isoformat()}"><header class="night-head"><h3>Night of {key.strftime("%a %-d %b")}</h3>'
                   f'<span class="night-sub"></span></header><div class="night-body">'
                   f'<canvas class="night-moon" width="120" height="120" aria-hidden="true"></canvas>'
                   f'<ol class="night-events">{rows}</ol></div></section>')
    return "".join(out)


def calendar_html(y, mo, groups):
    import calendar
    first_wd, ndays = calendar.monthrange(y, mo)
    cells = [f'<div class="cal-wd">{w}</div>' for w in WEEKDAYS] + ['<div class="cal-cell empty"></div>'] * first_wd
    for d in range(1, ndays + 1):
        key = datetime(y, mo, d).date()
        n = len(groups.get(key, []))
        inner = f'<span class="cal-d">{d}</span><canvas class="cal-moon" width="26" height="26" aria-hidden="true"></canvas><span class="cal-n">{n or ""}</span>'
        cells.append(f'<a class="cal-cell has" href="#night-{key.isoformat()}" data-day="{d}">{inner}</a>' if n
                     else f'<div class="cal-cell" data-day="{d}">{inner}</div>')
    return "".join(cells)


MS_CSS = """
    .filters { display: flex; flex-wrap: wrap; gap: 0.4rem; margin: 1rem 0 0.3rem; }
    .chipbox { display: inline-flex; align-items: center; gap: 0.35rem; border: 1px solid var(--line); border-radius: 999px; padding: 0.2rem 0.7rem; font-size: 0.85rem; cursor: pointer; }
    .chipbox input { accent-color: var(--accent); }
    .chipbox:has(input:checked) { border-color: var(--accent); color: var(--accent); }
    .cal { display: grid; grid-template-columns: repeat(7, 1fr); gap: 4px; margin: 0.9rem 0 1.2rem; }
    .cal-wd { font-size: 0.68rem; color: var(--muted); text-align: center; text-transform: uppercase; letter-spacing: 0.06em; padding-bottom: 2px; }
    .cal-cell { display: flex; flex-direction: column; align-items: center; gap: 1px; padding: 5px 0 4px; border-radius: 10px;
                background: var(--card); border: 1px solid var(--border); color: var(--muted); min-height: 60px; }
    .cal-cell.empty { background: none; border: 0; }
    .cal-cell.has { color: var(--text); border-color: color-mix(in srgb, var(--accent) 55%, var(--border)); }
    a.cal-cell:hover { text-decoration: none; border-color: var(--accent); background: color-mix(in srgb, var(--accent) 8%, var(--card)); }
    .cal-d { font-size: 0.78rem; font-weight: 600; line-height: 1; }
    .cal-moon { width: 26px; height: 26px; }
    .cal-n { font-size: 0.72rem; font-weight: 700; color: var(--accent); min-height: 0.9rem; line-height: 0.9rem; }
    .night { background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 0.75rem 0.95rem; margin: 0.7rem 0; scroll-margin-top: 72px; }
    .night-head { display: flex; align-items: baseline; justify-content: space-between; gap: 0.3rem 0.8rem; flex-wrap: wrap; }
    .night-head h3 { font-size: 1.05rem; margin: 0; letter-spacing: -0.01em; }
    .night-sub { color: var(--muted); font-size: 0.8rem; }
    .night-body { display: grid; grid-template-columns: 124px 1fr; gap: 0.9rem; align-items: start; margin-top: 0.55rem; }
    .night-moon { width: 120px; height: 120px; }
    .night-events { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.6rem; }
    .ev { display: grid; grid-template-columns: 1.45rem 1fr; gap: 0.35rem; }
    .ev-n { font-size: 0.7rem; font-weight: 700; color: #0b0e14; background: var(--muted); border-radius: 999px; width: 1.25rem; height: 1.25rem;
            display: inline-flex; align-items: center; justify-content: center; margin-top: 0.15rem; }
    .ev.lim-dark .ev-n { background: #67c9e6; }
    .ev.lim-bright .ev-n { background: #fbbf24; }
    .ev-time { font-weight: 700; font-size: 1.05rem; font-variant-numeric: tabular-nums; }
    .ev-top small { color: var(--muted); white-space: nowrap; }
    .ev-what { font-size: 0.9rem; }
    .ev-meta { font-size: 0.78rem; color: var(--muted); }
    @media (max-width: 560px) { .night-body { grid-template-columns: 92px 1fr; gap: 0.6rem; } .night-moon { width: 88px; height: 88px; } .cal-cell { min-height: 54px; } }
    @media (max-width: 360px) { .night-body { grid-template-columns: 1fr; } .night-moon { justify-self: center; } }
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
  Model.prototype.face = function (m) {   // geocentric: libration, pole PA and Sun direction for the renderer
    if (!this.d.lib) return null;
    var L = this.d.lib, x = (m - (this.seg0 + 720)) / 1440, k0 = Math.max(0, Math.min(L.length - 2, Math.floor(x))), f = Math.max(0, Math.min(1, x - k0));
    function lerp(a, b, wrap) { var dd = b - a; if (wrap) dd = ((dd + 540) % 360) - 180; return a + dd * f; }
    var A = L[k0], B = L[k0 + 1];
    var k = Math.max(0, Math.min(this.n - 1, Math.floor((m - this.seg0) / 1440))), tau = (m - (this.seg0 + 1440 * k)) / 720 - 1;
    var mc = this.moon[k], sc = this.sun[k], P = [pv(mc[0], tau), pv(mc[1], tau), pv(mc[2], tau)], S = [pv(sc[0], tau), pv(sc[1], tau), pv(sc[2], tau)];
    var mh = unit(P), sm = unit([S[0] - P[0], S[1] - P[1], S[2] - P[2]]), east = unit([-mh[1], mh[0], 0]);
    var north = [mh[1] * east[2] - mh[2] * east[1], mh[2] * east[0] - mh[0] * east[2], mh[0] * east[1] - mh[1] * east[0]];
    return { lat0: lerp(A[0], B[0]), lon0: lerp(A[1], B[1], true), pa: lerp(A[2], B[2], true),
             sun: [dot(sm, east), dot(sm, north), -dot(sm, mh)], illum: (1 - dot(unit(S), mh)) / 2 };
  };
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
  function dateKey(ms, tz) { try { return new Intl.DateTimeFormat('en-CA', { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(ms)); } catch (e) { return new Date(ms).toISOString().slice(0, 10); } }
  function keyLabel(k) { var p = k.split('-'); return new Date(Date.UTC(+p[0], +p[1] - 1, +p[2], 12)).toLocaleDateString('en-GB', { timeZone: 'UTC', weekday: 'short', day: 'numeric', month: 'short' }).replace(',', ''); }
  function shortLabel(l) { return l.indexOf('Gaia DR3 ') === 0 ? 'Gaia …' + l.slice(-7) : l; }
  function li(n, ev, vis, tz) {
    var keys = ['D', 'R'].filter(function (k) { return vis[k]; }), verb = { D: 'Disappears', R: 'Reappears' }, c0 = vis[keys[0]];
    var what = verb[keys[0]] + ' at the ' + c0.limb + ' limb';
    if (keys.length === 2) { var c1 = vis[keys[1]]; what += ' · ' + verb[keys[1]].toLowerCase() + ' ' + fT(T0 + c1.m * 60000, tz) + ' at the ' + c1.limb + ' limb'; }
    return '<li class="ev lim-' + c0.limb + '"><span class="ev-n">' + n + '</span><div class="ev-main">'
      + '<div class="ev-top"><span class="ev-time">' + fT(T0 + c0.m * 60000, tz) + '</span> <b class="ev-star" title="' + esc(ev.label) + '">' + esc(shortLabel(ev.label)) + '</b> <small>V ' + ev.vmag.toFixed(1) + '</small>' + (ev.graze ? ' <span class="badge">graze</span>' : '') + '</div>'
      + '<div class="ev-what">' + what + '</div>'
      + '<div class="ev-meta">' + c0.moon_alt.toFixed(0) + '° up in the ' + compass(c0.moon_az) + ' · ' + sky(c0.sun_alt) + ' · PA ' + c0.pa.toFixed(0) + '° · cusp ' + c0.cusp.toFixed(0) + '°</div></div></li>';
  }
  function moonUp(mFirst, tz) {   // rise / set of the Moon around the night's first event, for the header
    var prev = null, rise = null, set = null, upAtStart = null;
    for (var m = mFirst - 480; m <= mFirst + 480; m += 10) {
      var g = model.geom(m), alt = Math.asin(clamp(dot(g.um, g.up))) / RAD;
      if (prev === null) upAtStart = alt > 0;
      else if ((alt > 0) !== (prev > 0)) { if (alt > 0 && rise === null) rise = m; if (alt <= 0 && set === null) set = m; }
      prev = alt;
    }
    var parts = [];
    if (rise !== null) parts.push('Moon rises ' + fT(T0 + rise * 60000, tz).slice(0, 5));
    if (set !== null) parts.push((parts.length ? 'sets ' : 'Moon sets ') + fT(T0 + set * 60000, tz).slice(0, 5));
    if (!parts.length) parts.push(upAtStart ? 'Moon up all night' : 'Moon down');
    return parts.join(', ');
  }
  var model = null, stars = null, cache = {}, INST = META.defaultInstrument, LOC = null;
  var countLine = document.getElementById('count-line');
  try { var si = localStorage.getItem('occult-instrument'); if (si && META.instruments[si]) INST = si; } catch (e) {}
  try { var sl = JSON.parse(localStorage.getItem('occult-loc')); if (sl && isFinite(sl.lat)) LOC = sl; } catch (e) {}
  if (!LOC) LOC = { lat: META.defaultPlace[1], lon: META.defaultPlace[2], label: META.defaultPlace[0] };
  function tzOf(loc) { var c = META.cities[loc.label]; return (c && c[2]) || (loc.label === META.defaultPlace[0] ? META.defaultPlace[3] : Intl.DateTimeFormat().resolvedOptions().timeZone); }
  document.querySelectorAll('#inst-chips input').forEach(function (r) { r.checked = r.value === INST; r.addEventListener('change', function () { INST = r.value; try { localStorage.setItem('occult-instrument', INST); } catch (e) {} render(); }); });
  var calEl = document.getElementById('ms-cal'), nightsEl = document.getElementById('ms-nights'), YM = META.t0.slice(0, 7).split('-');
  function render() {
    if (!model) return;
    var key = LOC.lat.toFixed(4) + ',' + LOC.lon.toFixed(4);
    if (!cache[key]) cache[key] = model.events(stars, LOC.lat, LOC.lon); else model.observer(LOC.lat, LOC.lon);
    var evs = cache[key], tz = tzOf(LOC), occ = 0, list = [];
    evs.forEach(function (ev) { if (ev.contacts.D || ev.contacts.R) occ++; var v = visible(ev, INST);
      if (v.D || v.R) list.push([Math.min.apply(null, Object.keys(v).map(function (k) { return v[k].m; })), ev, v]); });
    list.sort(function (a, b) { return a[0] - b[0]; });
    var groups = {}, order = [];
    list.forEach(function (x) { var k = dateKey(T0 + x[0] * 60000 - 432e5, tz); if (!groups[k]) { groups[k] = []; order.push(k); } groups[k].push(x); });
    order.sort();
    nightsEl.innerHTML = order.map(function (k) {
      return '<section class="night" id="night-' + k + '"><header class="night-head"><h3>Night of ' + keyLabel(k) + '</h3><span class="night-sub"></span></header>'
        + '<div class="night-body"><canvas class="night-moon" width="120" height="120" aria-hidden="true"></canvas><ol class="night-events">'
        + groups[k].map(function (x, i) { return li(i + 1, x[1], x[2], tz); }).join('') + '</ol></div></section>';
    }).join('') || '<p class="hint">Nothing your instrument can show from here this month — try a larger one.</p>';
    var y = +YM[0], mo = +YM[1], ndays = new Date(Date.UTC(y, mo, 0)).getUTCDate(), first = (new Date(Date.UTC(y, mo - 1, 1)).getUTCDay() + 6) % 7, html = '';
    ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].forEach(function (w) { html += '<div class="cal-wd">' + w + '</div>'; });
    for (var e = 0; e < first; e++) html += '<div class="cal-cell empty"></div>';
    for (var d = 1; d <= ndays; d++) {
      var ck = y + '-' + String(mo).padStart(2, '0') + '-' + String(d).padStart(2, '0'), n = (groups[ck] || []).length;
      var inner = '<span class="cal-d">' + d + '</span><canvas class="cal-moon" width="26" height="26" aria-hidden="true"></canvas><span class="cal-n">' + (n || '') + '</span>';
      html += n ? '<a class="cal-cell has" href="#night-' + ck + '" data-day="' + d + '">' + inner + '</a>' : '<div class="cal-cell" data-day="' + d + '">' + inner + '</div>';
    }
    calEl.innerHTML = html;
    document.querySelectorAll('.night').forEach(function (sec, i) {
      var g = groups[order[i]], sub = sec.querySelector('.night-sub');
      var fc = model.face(g[0][0]);
      sub.textContent = moonUp(g[0][0], tz) + (fc ? ' · ' + (fc.illum * 100).toFixed(0) + '% lit' : '');
    });
    document.getElementById('tz-label').textContent = tzLabel(tz);
    document.getElementById('chip-name').textContent = LOC.label;
    countLine.textContent = list.length + ' occultations you can see from ' + LOC.label + ' with ' + META.instruments[INST][0].toLowerCase() + ' this month, on ' + order.length + ' nights · ' + occ + ' in all from there';
    if (window.MoonRender && model.d.lib) MoonRender.load(META.texture).then(function () {
      calEl.querySelectorAll('.cal-moon').forEach(function (cv) {
        var day = +cv.parentNode.getAttribute('data-day'), ms = Date.UTC(y, mo - 1, day) + (21 - LOC.lon / 15) * 36e5;
        MoonRender.draw(cv, model.face((ms - T0) / 60000));
      });
      document.querySelectorAll('.night').forEach(function (sec, i) {
        var g = groups[order[i]], marks = [];
        g.forEach(function (x, j) { Object.keys(x[2]).forEach(function (k) { var c = x[2][k]; marks.push({ pa: c.pa, n: j + 1, kind: k, limb: c.limb }); }); });
        MoonRender.draw(sec.querySelector('.night-moon'), model.face(g[0][0]), marks);
      });
    });
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
  <div class="cal" id="ms-cal" aria-label="The month at a glance">__CAL__</div>
  <p class="hint">Times in <span id="tz-label">__TZL__</span>. A night runs from noon to noon, so an event at 01:30 stays with the evening before.
  On each Moon, the numbered marks show where on the limb each star disappears or reappears.</p>
  <div id="ms-nights">__NIGHTS__</div>
  <h2>Reading the list</h2>
  <p class="method">The Moons are drawn from LRO LOLA topography (a 40 KB relief map), lit by the Sun as it is at that
  moment and turned to the Moon's real libration: north up, east to the left. A <em>dark-limb</em> event — the star vanishing into, or popping out of, the unlit edge of the Moon — is
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
<script src="/js/moon.js?v=__MOONJS_V__"></script>
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
    groups = group_nights(shown, t0, tz)
    inst_label = INSTRUMENTS[DEFAULT_INSTRUMENT][0]
    chips = "".join(f'<label class="chipbox"><input type="radio" name="inst" value="{k}"{" checked" if k == DEFAULT_INSTRUMENT else ""}> {esc(v[0])}</label>'
                    for k, v in INSTRUMENTS.items())
    rules = "".join(f"<tr><td>{esc(v[0])}</td><td>V ≤ {v[1]:.1f}</td><td>V ≤ {v[2]:.1f}</td></tr>" for v in INSTRUMENTS.values())
    data_json = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
    meta = {"src": f"/data/{slug}.json?v={_hash(data_json)}", "texture": f"{TEXTURE}?v={_hash((OUT / TEXTURE.lstrip('/')).read_bytes())}", "t0": d["t0"], "defaultPlace": list(DEFAULT_PLACE), "defaultInstrument": DEFAULT_INSTRUMENT,
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
                 "__COUNT__": f"{len(shown)} occultations you can see from {esc(name)} with {esc(inst_label.lower())} this month, on {len(groups)} nights · {occ} in all from there",
                 "__CAL__": calendar_html(y, mo, groups), "__NIGHTS__": nights_html(groups, t0, tz), "__RULES__": rules,
                 "__META__": json.dumps(meta, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"),
                 "__FOOTER__": FOOTER, "__JS__": SOLVER_JS, "__MOONJS_V__": _hash(MOON_JS)}.items():
        body = body.replace(k, v)
    (OUT / f"{slug}.html").write_text(page + body)
    (OUT / "data").mkdir(exist_ok=True)
    (OUT / "data" / f"{slug}.json").write_text(data_json)
    print(f"wrote site/{slug}.html: {len(shown)} rows for {name} ({inst_label}), {occ} occultations there")
    return {"slug": slug, "label": label, "year": y, "month": mo, "n": len(shown), "nights": len(groups), "planet": "moon-stars"}


MOON_JS = r"""/* Moon renderer for occult.alokm.com: shades the LRO LOLA relief map (img/moon-relief-360.png, 8-bit heights
   -9..+11 km, equirectangular, east-positive) for a libration, lunar-pole position angle and Sun direction.
   Sky view: north up, east to the left. f = {lat0, lon0, pa, sun:[e, n, toward-observer]}. */
window.MoonRender = (function () {
  var RAD = Math.PI / 180, W = 0, HH = 0, H = null, ready = null, HMIN = -9, HMAX = 11, RKM = 1737.4, EXA = 7;
  function load(src) {
    if (!ready) ready = new Promise(function (res, rej) {
      var img = new Image();
      img.onload = function () { var c = document.createElement('canvas'); c.width = img.width; c.height = img.height;
        var x = c.getContext('2d'); x.drawImage(img, 0, 0); var d = x.getImageData(0, 0, img.width, img.height).data;
        W = img.width; HH = img.height; H = new Float32Array(W * HH);
        for (var i = 0; i < W * HH; i++) H[i] = HMIN + d[4 * i] / 255 * (HMAX - HMIN);
        res(); };
      img.onerror = rej; img.src = src;
    });
    return ready;
  }
  function hget(i, j) { if (i < 0) i = 0; if (i > HH - 1) i = HH - 1; j = ((j % W) + W) % W; return H[i * W + j]; }
  function draw(cv, f, marks) {
    var css = cv.clientWidth || +cv.getAttribute('width'), dpr = Math.min(2, window.devicePixelRatio || 1), N = Math.round(css * dpr);
    cv.width = N; cv.height = N;
    var ctx = cv.getContext('2d'), img = ctx.createImageData(N, N), px = img.data;
    var R = N / 2 * (1 - (marks && marks.length ? 0.2 : 0.04)), cx = N / 2, cy = N / 2;
    var la0 = f.lat0 * RAD, lo0 = f.lon0 * RAD, P = f.pa * RAD, cP = Math.cos(P), sP = Math.sin(P);
    var E0 = [-Math.sin(lo0), Math.cos(lo0), 0], N0 = [-Math.sin(la0) * Math.cos(lo0), -Math.sin(la0) * Math.sin(lo0), Math.cos(la0)];
    var U0 = [Math.cos(la0) * Math.cos(lo0), Math.cos(la0) * Math.sin(lo0), Math.sin(la0)];
    var se = f.sun[0], sn = f.sun[1], sz = f.sun[2], sEta = sn * cP + se * sP, sXi = -se * cP + sn * sP;
    var s0 = sXi * E0[0] + sEta * N0[0] + sz * U0[0], s1 = sXi * E0[1] + sEta * N0[1] + sz * U0[1], s2 = sXi * E0[2] + sEta * N0[2] + sz * U0[2];
    var DX = 2 * Math.PI * RKM / W, DY = Math.PI * RKM / HH;
    for (var py = 0; py < N; py++) {
      for (var qx = 0; qx < N; qx++) {
        var e = -(qx + 0.5 - cx) / R, n = (cy - py - 0.5) / R, r2 = e * e + n * n;
        if (r2 >= 1) continue;
        var eta = n * cP + e * sP, xi = -e * cP + n * sP, zeta = Math.sqrt(1 - r2);
        var v0 = xi * E0[0] + eta * N0[0] + zeta * U0[0], v1 = xi * E0[1] + eta * N0[1] + zeta * U0[1], v2 = xi * E0[2] + eta * N0[2] + zeta * U0[2];
        var lat = Math.asin(Math.max(-1, Math.min(1, v2))), lon = Math.atan2(v1, v0);
        var i = Math.round((90 - lat / RAD) / 180 * HH - 0.5), j = Math.round(((lon / RAD + 360) % 360) / 360 * W - 0.5);
        var hc = hget(i, j), cla = Math.cos(lat), sl = Math.sin(lat), so = Math.sin(lon), co = Math.cos(lon);
        var dE = (hget(i, j + 1) - hget(i, j - 1)) / (2 * DX * Math.max(cla, 0.05)) * EXA, dN = (hget(i - 1, j) - hget(i + 1, j)) / (2 * DY) * EXA;
        var nx = v0 + dE * so + dN * sl * co, ny = v1 - dE * co + dN * sl * so, nz = v2 - dN * cla, nl = Math.sqrt(nx * nx + ny * ny + nz * nz);
        var day = v0 * s0 + v1 * s1 + v2 * s2, lam = Math.max(0, (nx * s0 + ny * s1 + nz * s2) / nl);
        var lit = Math.max(0, Math.min(1, (day + 0.02) / 0.04)), tint = 0.5 + 0.5 * Math.max(0, Math.min(1, (hc + 3) / 5));
        var val = (lit * (0.06 + 1.12 * lam) + (1 - lit) * 0.05) * tint, edge = Math.max(0, Math.min(1, (1 - Math.sqrt(r2)) * R));
        var o = 4 * (py * N + qx);
        px[o] = Math.min(255, val * 240); px[o + 1] = Math.min(255, val * 236); px[o + 2] = Math.min(255, val * 226); px[o + 3] = 255 * edge;
      }
    }
    ctx.putImageData(img, 0, 0);
    if (marks && marks.length) {
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.font = '600 ' + Math.round(9 * dpr) + 'px system-ui, -apple-system, sans-serif';
      marks.forEach(function (mk) {
        var t = mk.pa * RAD, sx = Math.sin(t), sy = Math.cos(t), col = mk.limb === 'bright' ? '#fbbf24' : '#67c9e6';
        var x0 = cx - R * sx, y0 = cy - R * sy;
        ctx.fillStyle = col; ctx.strokeStyle = col; ctx.lineWidth = 1.5 * dpr;
        ctx.beginPath(); ctx.arc(x0, y0, 2.8 * dpr, 0, 2 * Math.PI);
        if (mk.kind === 'D') ctx.fill(); else ctx.stroke();
        ctx.fillText(String(mk.n), cx - (R + 9 * dpr) * sx, cy - (R + 9 * dpr) * sy);
      });
    }
  }
  return { load: load, draw: draw };
})();
"""


def build_all(cities, only=None):
    (OUT / "js").mkdir(exist_ok=True)
    (OUT / "js" / "moon.js").write_text(MOON_JS)
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
