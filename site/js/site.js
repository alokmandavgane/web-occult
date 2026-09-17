/* occult.alokm.com — shared by every page with a location sheet. */
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
