"""The Moon renderer shared by every page that draws the Moon (event pages, Moon-and-stars months).

MOON_JS is written to site/js/moon.js; pages load it as /js/moon.js?v=<hash> and the relief map as
/img/moon-relief-360.png?v=<hash> (engine/moon_texture.py) — /img is cached 30 days, so never drop the hash.
"""

import hashlib

TEXTURE = "/img/moon-relief-360.png"


def version(content):
    return hashlib.sha1(content if isinstance(content, bytes) else content.encode()).hexdigest()[:10]


def write_assets(out):
    """Write site/js/moon.js; return (moon.js URL, texture URL), both versioned."""
    (out / "js").mkdir(exist_ok=True)
    (out / "js" / "moon.js").write_text(MOON_JS)
    tex = (out / TEXTURE.lstrip("/")).read_bytes()
    return f"/js/moon.js?v={version(MOON_JS)}", f"{TEXTURE}?v={version(tex)}"


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
  function draw(cv, f, marks, opts) {
    opts = opts || {};
    var css = cv.clientWidth || +cv.getAttribute('width'), dpr = Math.min(2, window.devicePixelRatio || 1), N = Math.round(css * dpr);
    cv.width = N; cv.height = N;
    var ctx = cv.getContext('2d'), img = ctx.createImageData(N, N), px = img.data;
    var R = N / 2 * (opts.radiusFrac || (1 - (marks && marks.length ? 0.2 : 0.04))), cx = N / 2, cy = N / 2;
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
