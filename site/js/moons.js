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
