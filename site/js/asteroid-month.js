(function () {
  var A = window.OccultAsteroids, META = JSON.parse(document.getElementById('ast-meta').textContent);
  META.cities = window.OccultCities || {};      // js/cities-<audience>.js, loaded just before this file
  var RAD = Math.PI / 180, F = A.fmt;
  function tzLabel(tz) { try { return new Intl.DateTimeFormat('en-GB', { timeZone: tz, timeZoneName: 'short' }).formatToParts(new Date(Date.parse(META.t0) + 864e6)).filter(function (p) { return p.type === 'timeZoneName'; })[0].value; } catch (e) { return tz; } }
  function dateKey(ms, tz) { try { return new Intl.DateTimeFormat('en-CA', { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(ms)); } catch (e) { return new Date(ms).toISOString().slice(0, 10); } }
  function keyLabel(k) { var p = k.split('-'); return new Date(Date.UTC(+p[0], +p[1] - 1, +p[2], 12)).toLocaleDateString('en-GB', { timeZone: 'UTC', weekday: 'short', day: 'numeric', month: 'short' }).replace(',', ''); }
  var B = META.bbox, K = Math.cos(META.lat0 * RAD), SC = META.mapW / ((B[2] - B[0]) * K);
  function xy(lat, lon) { return [(lon - B[0]) * K * SC, (B[3] - lat) * SC]; }

  var data = null, LOC = null, FILTER = 'all', SORT = 'time', INST = 'any', LIM = {};
  META.instruments.forEach(function (i) { LIM[i[0]] = i[2]; });
  try { var sl = JSON.parse(localStorage.getItem('occult-loc')); if (sl && isFinite(sl.lat)) LOC = sl; } catch (e) {}
  if (!LOC) LOC = { lat: META.defaultPlace[1], lon: META.defaultPlace[2], label: META.defaultPlace[0] };
  function keep(k, v, ok) { try { var s = localStorage.getItem(k); return ok(s) ? s : v; } catch (e) { return v; } }
  FILTER = keep('occult-ast-filter', FILTER, function (s) { return s === 'near'; });
  SORT = keep('occult-ast-sort', SORT, function (s) { return s === 'travel' || s === 'mag'; });
  INST = keep('occult-ast-inst', INST, function (s) { return s && LIM[s] !== undefined; });
  function travelTile(y) {   // twin of travel_tile()
    if (y[4] < 0) return ['—', 'star is down'];
    if (y[4] === 0) return ['inside', 'the path'];
    return [y[4].toLocaleString('en-GB') + ' km', 'to the path'];
  }
  function dayLabel(ms, tz) { try { return new Date(ms).toLocaleDateString('en-GB', { timeZone: tz, weekday: 'short', day: 'numeric', month: 'short' }).replace(',', ''); } catch (e) { return ''; } }
  function tzOf(loc) { var c = META.cities[loc.label]; return (c && c[2]) || (loc.label === META.defaultPlace[0] ? META.defaultPlace[3] : Intl.DateTimeFormat().resolvedOptions().timeZone); }
  var countLine = document.getElementById('count-line'), nightsEl = document.getElementById('ast-nights'), calEl = document.getElementById('ast-cal');
  var cards = {}; document.querySelectorAll('article.ast').forEach(function (a) { cards[a.dataset.id] = a; });
  // The scope switch. Off is the whole month across India; on keeps the paths that reach you. The stored value stays
  // 'all' / 'near', so a reader who set it while it was a pair of radio chips keeps their choice.
  var nearBox = document.getElementById('ast-near');
  nearBox.checked = FILTER === 'near';
  nearBox.addEventListener('change', function () { FILTER = nearBox.checked ? 'near' : 'all'; store('occult-ast-filter', FILTER); render(); });
  function store(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  // a select away from its first option is a filter in force, and says so (CSS reads data-default)
  function mark(sel) { if (sel.value === sel.options[0].value) sel.setAttribute('data-default', ''); else sel.removeAttribute('data-default'); }
  function wire(id, key, val, set) {
    var sel = document.getElementById(id);
    sel.value = val; mark(sel);
    sel.addEventListener('change', function () { set(sel.value); mark(sel); store(key, sel.value); render(); });
  }
  wire('ast-sort', 'occult-ast-sort', SORT, function (v) { SORT = v; });
  wire('ast-inst', 'occult-ast-inst', INST, function (v) { INST = v; });
  function render() {
    if (!data) return;
    var tz = tzOf(LOC), groups = {}, order = [], mine = 0, lim = LIM[INST], rows = [];
    data.events.forEach(function (ev) {
      var s = A.solve(ev.el, LOC.lat, LOC.lon), tc = A.toCentre(ev.el, LOC.lat, LOC.lon), y = A.you(ev, s, tc), a = cards[ev.id];
      if (!a) return;
      var t = Date.parse(ev.el.t0) + s.tau * 1000, tv = travelTile(y), tb = a.querySelector('.st-travel');
      a.className = 'ast v-' + y[0];
      a.querySelector('.ast-time').textContent = F.t(t, tz);
      a.querySelector('.ast-day').textContent = dayLabel(t, tz);
      a.querySelector('.ast-p').textContent = y[3] ? y[3] + ' chance' : '';
      a.querySelector('.ast-say').textContent = y[1];
      a.querySelector('.ast-look').textContent = y[2];
      tb.querySelector('b').textContent = tv[0]; tb.querySelector('.k').textContent = tv[1];
      var p = xy(LOC.lat, LOC.lon), pin = a.querySelector('.ast-pin'); pin.setAttribute('cx', p[0].toFixed(1)); pin.setAttribute('cy', p[1].toFixed(1));
      var near = y[0] === 'in' || y[0] === 'near'; if (near) mine++;
      var show = (FILTER !== 'near' || near) && ev.combined_mag <= lim;
      a.hidden = !show;
      var k = dateKey(Date.parse(ev.t_geo) - 432e5, tz);
      if (!groups[k]) { groups[k] = { list: [], mine: 0, shown: 0 }; order.push(k); }
      groups[k].list.push(a); if (near) groups[k].mine++;
      if (show) { groups[k].shown++; rows.push({ a: a, k: k, t: t, travel: y[4] < 0 ? Infinity : y[4], mag: ev.combined_mag }); }
    });
    order.sort();
    var frag = document.createDocumentFragment();
    nightsEl.className = SORT === 'time' ? '' : 'flat';
    if (SORT === 'time') {
      order.forEach(function (k) {
        var g = groups[k];
        var sec = document.createElement('section'); sec.className = 'night'; sec.id = 'night-' + k; sec.hidden = !g.shown;
        var cnt = g.shown < g.list.length ? g.shown + ' of ' + g.list.length + ' events'      // a filter is hiding some of the night
                                          : g.list.length + (g.list.length === 1 ? ' event' : ' events');
        sec.innerHTML = '<header class="night-head"><h3>Night of ' + keyLabel(k) + '</h3><span class="hint">' + cnt + (g.mine ? ' · ' + g.mine + ' near you' : '') + '</span></header>';
        g.list.forEach(function (a) { sec.appendChild(a); });
        frag.appendChild(sec);
      });
    } else {
      // out of date order the night sections mean nothing, so the list runs flat and every card carries its own date.
      // The calendar still links into it: an empty anchor marks where each night's first card has landed.
      rows.sort(SORT === 'travel' ? function (a, b) { return a.travel - b.travel || a.t - b.t; }
                                  : function (a, b) { return a.mag - b.mag || a.t - b.t; });
      var sec = document.createElement('section'); sec.className = 'night'; sec.hidden = !rows.length;
      sec.innerHTML = '<header class="night-head"><h3>' + (SORT === 'travel' ? 'Nearest to you first' : 'Brightest first')
        + '</h3><span class="hint">' + rows.length + (rows.length === 1 ? ' event' : ' events') + '</span></header>';
      var seen = {};
      rows.forEach(function (r) {
        if (!seen[r.k]) { seen[r.k] = 1; var an = document.createElement('span'); an.className = 'night-anchor'; an.id = 'night-' + r.k; sec.appendChild(an); }
        sec.appendChild(r.a);
      });
      frag.appendChild(sec);
    }
    if (!rows.length) {                    // every event filtered away: say which setting did it, or the page just goes blank
      var none = document.createElement('p'); none.className = 'hint';
      none.textContent = INST !== 'any' && FILTER === 'near' ? 'Nothing this month is both over you and bright enough for that aperture.'
        : INST !== 'any' ? 'No event this month is bright enough for that aperture — a camera, or a larger one, would reach these.'
        : 'No path crosses your place this month. Turn off “Only paths over me” to see every path across India.';
      frag.appendChild(none);
    }
    nightsEl.innerHTML = ''; nightsEl.appendChild(frag);
    var YM = META.t0.slice(0, 7).split('-'), y = +YM[0], mo = +YM[1], ndays = new Date(Date.UTC(y, mo, 0)).getUTCDate(), first = (new Date(Date.UTC(y, mo - 1, 1)).getUTCDay() + 6) % 7, html = '';
    ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].forEach(function (w) { html += '<div class="cal-wd">' + w + '</div>'; });
    for (var e = 0; e < first; e++) html += '<div class="cal-cell empty"></div>';
    for (var d = 1; d <= ndays; d++) {
      var ck = y + '-' + String(mo).padStart(2, '0') + '-' + String(d).padStart(2, '0'), g = groups[ck];
      var n = g ? g.shown : 0, inner = '<span class="cal-d">' + d + '</span><span class="cal-n">' + (n || '') + '</span>';
      html += n ? '<a class="cal-cell has' + (g.mine ? ' mine' : '') + '" href="#night-' + ck + '">' + inner + '</a>' : '<div class="cal-cell">' + inner + '</div>';
    }
    calEl.innerHTML = html;
    document.getElementById('tz-label').textContent = tzLabel(tz);
    document.getElementById('chip-name').textContent = LOC.label;
    countLine.textContent = data.events.length + ' asteroid occultations cross India at night this month · ' + mine + ' pass over ' + LOC.label
      + ' (inside the path or within its 1σ margin)' + (rows.length < data.events.length ? ' · showing ' + rows.length : '');
  }
  var sheet = document.getElementById('loc-sheet'), latI = document.getElementById('loc-lat'), lonI = document.getElementById('loc-lon'), sel = document.getElementById('loc-city');
  Object.keys(META.cities).forEach(function (n) { sel.add(new Option(n, n)); });
  function setLoc(lat, lon, label) { lat = +lat; lon = +lon; if (!isFinite(lat) || !isFinite(lon)) return;
    LOC = { lat: lat, lon: lon, label: label || placeName(lat, lon, META.cities) };
    try { localStorage.setItem('occult-loc', JSON.stringify(LOC)); } catch (e) {}
    placeAsked();
    render(); }
  document.getElementById('loc-chip').addEventListener('click', function () { latI.value = LOC.lat.toFixed(4); lonI.value = LOC.lon.toFixed(4); sheet.showModal(); });
  sheet.addEventListener('click', function (e) { if (e.target === sheet) sheet.close(); });
  document.getElementById('loc-go').addEventListener('click', function () { setLoc(latI.value, lonI.value); sheet.close(); });
  sel.addEventListener('change', function () { var c = META.cities[sel.value]; if (c) { setLoc(c[0], c[1], sel.value); sheet.close(); } });
  var geo = document.getElementById('loc-geo'); if (!navigator.geolocation) geo.hidden = true;
  geo.addEventListener('click', function () { geo.disabled = true; geo.textContent = 'Locating…';
    navigator.geolocation.getCurrentPosition(function (p) { geo.disabled = false; geo.textContent = 'Use my location'; setLoc(p.coords.latitude, p.coords.longitude); sheet.close(); },
      function () { geo.disabled = false; geo.textContent = 'Location unavailable'; }); });
  fetch(META.src).then(function (r) { return r.json(); }).then(function (d) { data = d; render(); });
  askPlace(LOC.label, function (lat, lon) { setLoc(lat, lon); });
})();
