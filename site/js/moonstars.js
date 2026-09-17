(function () {
  var META = JSON.parse(document.getElementById('ms-meta').textContent);
  META.cities = window.OccultCities || {};      // js/cities.js, loaded just before this file
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
  Object.keys(META.cities).forEach(function (n) { sel.add(new Option(n, n)); });
  function setLoc(lat, lon, label) { lat = +lat; lon = +lon; if (!isFinite(lat) || !isFinite(lon)) return;
    LOC = { lat: lat, lon: lon, label: label || placeName(lat, lon, META.cities) };
    try { localStorage.setItem('occult-loc', JSON.stringify(LOC)); } catch (e) {}
    placeAsked();
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
  askPlace(LOC.label, function (lat, lon) { setLoc(lat, lon); });
})();
