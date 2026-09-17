(function () {
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
    return '<tr class="yours"><td>' + label + '</td><td colspan="3">' + (r.verdict === 'miss' ? 'misses — ' + D.target + ' passes ' + gap.toFixed(1) + '′ from the limb at ' + localTime(r.closest.m, false) : 'Moon below the horizon') +
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
      if (r.verdict === 'visible' && c.D2 === undefined) h = h.replace('Occultation visible from here', 'Only part of ' + D.target + "'s disc is covered from here — a grazing partial");
    } else {
      var gap = r.closest.sep - r.closest.sdm;
      h += fact('closest approach', localTime(r.closest.m, false), (gap * 60).toFixed(1) + '′ outside the limb');
      h += fact('Where to look', r.closest.altm > 0 ? r.closest.altm.toFixed(0) + '° up in the ' + compass(r.closest.azm) : 'below the horizon', r.closest.altm > 0 ? skyText(r.closest.alts) : '');
      h += '<div class="verdict ' + r.verdict + '">' + (r.verdict === 'miss' ? D.target + ' passes ' + (gap * 60).toFixed(1) + '′ from the limb — a near miss from here.' : 'The Moon is below the horizon here.') + '</div>';
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
