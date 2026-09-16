
/* occult.alokm.com — the site kept for the field. Someone who drives out to a path is in the one place with no signal,
   so once a page has been opened it opens again without one: the HTML, the shared JS, the month's data, Leaflet, and
   whatever map tiles were already looked at. Pages and data go to the network first, so an online reader always gets
   the current build and the cache is only the fallback; the pinned Leaflet files and the tiles never change, so they
   come from the cache first. Analytics is left alone. To switch all this off for good, ship an sw.js whose install
   handler is self.registration.unregister(). */
var ASSETS = 'occult-d63fac66fb', TILES = 'occult-tiles', TILE_MAX = 600, CORE = ["/", "/asteroid", "/js/asteroid.js?v=9ae69ae30d", "/data/world-coarse.json?v=48d12d25ba"];

self.addEventListener('install', function (e) {
  // one by one, and a failure is allowed: a single missing file must not leave a reader with no offline site at all
  e.waitUntil(caches.open(ASSETS).then(function (c) {
    return Promise.all(CORE.map(function (u) { return c.add(u).catch(function () {}); }));
  }).then(function () { return self.skipWaiting(); }));
});
self.addEventListener('activate', function (e) {
  e.waitUntil(caches.keys().then(function (ks) {
    return Promise.all(ks.map(function (k) { return k === ASSETS || k === TILES ? null : caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});
function keep(name, req, res, cap) {
  if (!res || (!res.ok && res.type !== 'opaque')) return res;      // a tile comes back opaque: no status to read, still worth keeping
  var copy = res.clone();
  caches.open(name).then(function (c) {
    c.put(req, copy);
    if (cap) c.keys().then(function (ks) { for (var i = 0; i < ks.length - cap; i++) c.delete(ks[i]); });
  });
  return res;
}
function page(r, u) {
  var bare = new Request(u.origin + u.pathname);                   // one entry per page, not one per event or pinned spot
  return fetch(r).then(function (res) { return keep(ASSETS, bare, res); })
    .catch(function () { return caches.match(bare).then(function (c) { return c || caches.match('/'); }); });
}
function fresh(r) {                                                // cache first, then catch up behind
  return caches.match(r).then(function (c) {
    var net = fetch(r).then(function (res) { return keep(ASSETS, r, res); }).catch(function () { return c; });
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
  if (u.hostname === 'cdnjs.cloudflare.com') return e.respondWith(fixed(r, ASSETS));
  if (u.origin !== location.origin) return;
  e.respondWith(r.mode === 'navigate' ? page(r, u) : fresh(r));
});
