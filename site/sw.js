
/* occult.alokm.com — the site kept for the field. Someone who drives out to a path is in the one place with no signal,
   so once a page has been opened it opens again without one: the HTML, the stylesheet and scripts it links, the month's
   data, Leaflet, and whatever map tiles were already looked at. Pages go to the network first, so an online reader always
   gets the current build and the cache is only the fallback; files come from the cache and are refreshed behind; the
   pinned Leaflet files and the tiles never change, so they come from the cache alone. Everything is kept under ONE fixed
   name, the oldest dropped past a cap: a deploy never throws away what a reader saved, and a page cached before it still
   finds the ?v= files it links. Analytics is left alone. To switch all this off for good, ship an sw.js whose install
   handler is self.registration.unregister(). */
var SITE = 'occult-site', TILES = 'occult-tiles', SITE_MAX = 500, TILE_MAX = 600, CORE = ["/", "/asteroid", "/css/base.css?v=fe3d30767f", "/js/asteroid.js?v=aa8de3e997", "/data/world-coarse.json?v=48d12d25ba", "/js/cities-india.js?v=5e73770dc4"];

self.addEventListener('install', function (e) {
  // one by one, and a failure is allowed: a single missing file must not leave a reader with no offline site at all
  e.waitUntil(caches.open(SITE).then(function (c) {
    return Promise.all(CORE.map(function (u) { return c.add(u).catch(function () {}); }));
  }).then(function () { return self.skipWaiting(); }));
});
self.addEventListener('activate', function (e) {
  // earlier workers kept a cache named for each build: whatever is not one of these two is theirs
  e.waitUntil(caches.keys().then(function (ks) {
    return Promise.all(ks.map(function (k) { return k === SITE || k === TILES ? null : caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});
function keep(name, req, res, cap) {
  if (!res || (!res.ok && res.type !== 'opaque')) return res;      // a tile comes back opaque: no status to read, still worth keeping
  var copy = res.clone();
  caches.open(name).then(function (c) {
    return c.put(req, copy).then(function () {                    // a put moves the entry to the end: the front is the least recently fetched
      return c.keys().then(function (ks) { for (var i = 0; i < ks.length - cap; i++) c.delete(ks[i]); });
    });
  });
  return res;
}
function page(r, u) {
  var bare = new Request(u.origin + u.pathname);                   // one entry per page, not one per event or pinned spot
  return fetch(r).then(function (res) { return keep(SITE, bare, res, SITE_MAX); })
    .catch(function () { return caches.match(bare).then(function (c) { return c || caches.match('/'); }); });
}
function fresh(r) {                                                // cache first, then catch up behind
  return caches.match(r).then(function (c) {
    var net = fetch(r).then(function (res) { return keep(SITE, r, res, SITE_MAX); }).catch(function () { return c; });
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
  if (u.hostname === 'cdnjs.cloudflare.com') return e.respondWith(fixed(r, SITE, SITE_MAX));
  if (u.origin !== location.origin) return;
  e.respondWith(r.mode === 'navigate' ? page(r, u) : fresh(r));
});
