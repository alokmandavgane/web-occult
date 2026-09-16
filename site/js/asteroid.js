
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
             sun_alt: Math.asin(clamp(dot(el.sun, ug))) / RAD, q: [-s[0], -s[1]], v: [s[2], s[3]] };
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
  function shapeChord(ev, s) {
    // The place's track across DAMIT's outline: the line through q along the shadow's motion v, clipped by the (convex)
    // hull, all in the fundamental plane's e1/e2 km — no rotation, so no way to mirror it. null when there is no shape.
    var h = ev.shape && ev.shape.hull;
    if (!h) return null;
    var n = Math.hypot(s.v[0], s.v[1]), ux = s.v[0] / n, uy = s.v[1] / n, wx = -uy, wy = ux;
    var w0 = s.q[0] * wx + s.q[1] * wy, lo = Infinity, hi = -Infinity, wlo = Infinity, whi = -Infinity;
    for (var i = 0; i < h.length; i++) {
      var hw = h[i][0] * wx + h[i][1] * wy;
      wlo = Math.min(wlo, hw); whi = Math.max(whi, hw);
      var a = h[i], b = h[(i + 1) % h.length], aw = a[0] * wx + a[1] * wy - w0, bw = b[0] * wx + b[1] * wy - w0;
      if ((aw <= 0) === (bw <= 0)) continue;
      var au = a[0] * ux + a[1] * uy, bu = b[0] * ux + b[1] * uy, u = au + (bu - au) * aw / (aw - bw);
      lo = Math.min(lo, u); hi = Math.max(hi, u);
    }
    var km = hi > lo ? hi - lo : 0;
    return { km: km, s: km / s.speed, u: [lo, hi], frame: [ux, uy, wx, wy], across: whi - wlo };
  }
  function you(ev, s, tc) {   // twin of you_html()
    var R = ev.el.R, sig = ev.sigma_km || 0, d = Math.abs(s.d), ground = tc[0], brg = tc[1];
    var look = 'Star ' + r0(s.star_alt) + '° up in the ' + compass(s.star_az) + ' · ' + sky(s.sun_alt);
    if (s.star_alt < 0) return ['below', 'The star is below your horizon then', 'Star ' + r0(-s.star_alt) + '° below the horizon'];
    var edge = d > 0 ? ground * (d - R) / d : 0;
    if (d <= R) return ['in', 'You are inside the path, ' + r0(ground) + ' km from its centre line: the star vanishes for up to ' + r1(s.dur) + ' s', look];
    if (d <= R + sig) return ['near', 'The predicted edge passes ' + r0(edge) + ' km to the ' + compass(brg) + ' — within its 1σ uncertainty of ' + r0(sig) + ' km, worth watching', look];
    if (d <= R + 2 * sig) return ['chance', 'The predicted edge passes ' + r0(edge) + ' km to the ' + compass(brg) + ' — beyond its 1σ uncertainty of ' + r0(sig) + ' km but within 2σ, a long shot', look];
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
    var R = ev.el.R, sig = ev.sigma_km || 0, d = s.d, S = 210, c = S / 2, sc = shapeChord(ev, s), h = sc && ev.shape.hull;
    var ext = h ? Math.max.apply(null, h.map(function (p) { return Math.hypot(p[0], p[1]); })) : 0;
    var k = (c - 18) / Math.max(R, Math.abs(d), ext, 1), y = c - d * k, o = [];
    o.push('<svg class="chord" viewBox="0 0 ' + S + ' ' + S + '" role="img" aria-label="Your chord across the asteroid">');
    if (h) {
      // across = along the motion (u), up = left of it (w): the same frame d is measured in, so your line sits at w = d
      var f = sc.frame;
      o.push('<circle class="ch-sphere" cx="' + c + '" cy="' + c + '" r="' + (R * k).toFixed(1) + '"/>');
      o.push('<path class="ch-disc" d="M' + h.map(function (p) {
        return (c + (p[0] * f[0] + p[1] * f[1]) * k).toFixed(1) + ',' + (c - (p[0] * f[2] + p[1] * f[3]) * k).toFixed(1);
      }).join(' ') + 'Z"/>');
    } else {
      o.push('<circle class="ch-disc" cx="' + c + '" cy="' + c + '" r="' + (R * k).toFixed(1) + '"/>');
    }
    [d - sig, d + sig].forEach(function (v) {
      o.push('<path class="ch-sig" d="M8,' + (c - v * k).toFixed(1) + ' ' + (S - 8) + ',' + (c - v * k).toFixed(1) + '"/>');
    });
    if (sc && sc.km > 0) {
      o.push('<path class="ch-chord" d="M' + (c + sc.u[0] * k).toFixed(1) + ',' + y.toFixed(1) + ' ' + (c + sc.u[1] * k).toFixed(1) + ',' + y.toFixed(1) + '"/>');
    } else if (!sc && Math.abs(d) < R) {
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
                             chordSvg: chordSvg, curveSvg: curveSvg, pathLines: pathLines, shapeChord: shapeChord,
                             fmt: { t: fT, hm: fHM, date: fDate, compass: compass, r0: r0, r1: r1, sky: sky } };
})();
