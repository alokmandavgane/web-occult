"""
The Moon's relief as one small image, for the pages' Moon renderer — from LRO LOLA LDEM_16.

Output: site/img/moon-relief-<W>.png, 8-bit grayscale, equirectangular: column 0 = longitude 0 (east-positive,
increasing to the right), row 0 = latitude +90. Pixel value = height above the 1737.4 km sphere, linearly from
HMIN_KM (0) to HMAX_KM (255). The browser takes slopes from it and lights them with the real Sun direction, so
craters and basins shade correctly for any phase; low ground is tinted darker as a stand-in for the maria.

Usage: .venv/bin/python engine/moon_texture.py [720|360] [--preview out.png]
"""

import os
import struct
import sys
import zlib

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ephem_paths import EPHEM_DIR, REPO  # noqa: E402

HMIN_KM, HMAX_KM = -9.0, 11.0


def write_png_gray(path, img):
    h, w = img.shape
    best = None
    for ftype in (1, 2, 4):
        rows = []
        prev = np.zeros(w, dtype=np.int16)
        for i in range(h):
            row = img[i].astype(np.int16)
            if ftype == 1:
                left = np.concatenate([[0], row[:-1]])
                f = (row - left) % 256
            elif ftype == 2:
                f = (row - prev) % 256
            else:
                left = np.concatenate([[0], row[:-1]])
                upleft = np.concatenate([[0], prev[:-1]])
                p = left + prev - upleft
                pa, pb, pc = np.abs(p - left), np.abs(p - prev), np.abs(p - upleft)
                pred = np.where((pa <= pb) & (pa <= pc), left, np.where(pb <= pc, prev, upleft))
                f = (row - pred) % 256
            rows.append(bytes([ftype]) + f.astype(np.uint8).tobytes())
            prev = row
        data = zlib.compress(b"".join(rows), 9)
        if best is None or len(data) < len(best):
            best = data

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)) + chunk(b"IDAT", best) + chunk(b"IEND", b"")
    open(path, "wb").write(png)
    return len(png)


def relief(width):
    res = 16
    dn = np.memmap(os.path.join(EPHEM_DIR, "lola", "ldem_16.img"), dtype="<i2", mode="r", shape=(180 * res, 360 * res))
    f = (360 * res) // width
    h = dn.reshape(180 * res // f, f, 360 * res // f, f).astype(np.float32).mean(axis=(1, 3)) * 0.5 / 1000.0
    return h


def main():
    width = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 720
    h = relief(width)
    img = np.clip(np.round((h - HMIN_KM) / (HMAX_KM - HMIN_KM) * 255), 0, 255).astype(np.uint8)
    os.makedirs(os.path.join(REPO, "site", "img"), exist_ok=True)
    out = os.path.join(REPO, "site", "img", f"moon-relief-{width}.png")
    n = write_png_gray(out, img)
    print(f"{width}x{width//2}: heights {h.min():+.1f}..{h.max():+.1f} km -> {os.path.relpath(out, REPO)} ({n/1024:.1f} KB)")
    if "--preview" in sys.argv:
        # orthographic nearside, Sun from the lunar east (right), relief x6: orientation + legibility check
        prev = sys.argv[sys.argv.index("--preview") + 1]
        N = 360
        y, x = np.mgrid[-1:1:N * 1j, -1:1:N * 1j]
        r2 = x * x + y * y
        inside = r2 < 1
        z = np.sqrt(np.clip(1 - r2, 0, 1))
        lat = np.degrees(np.arcsin(np.clip(-y, -1, 1)))
        lon = np.degrees(np.arctan2(x, z)) % 360
        H, W = h.shape
        gy, gx = np.gradient(h)                       # km per pixel (rows = -lat, cols = +lon)
        kmpp = 2 * np.pi * 1737.4 / W
        ii = np.clip(((90 - lat) / 180 * H).astype(int), 0, H - 1)
        jj = np.clip((lon / 360 * W).astype(int), 0, W - 1)
        coslat = np.cos(np.radians(lat))
        dhdE = gx[ii, jj] / (kmpp * np.maximum(coslat, 0.05)) * 6
        dhdN = -gy[ii, jj] / kmpp * 6
        # surface frame in view coordinates (x right = lunar east, y up = north, z toward viewer)
        lo, la = np.radians(lon), np.radians(lat)
        up = np.stack([np.cos(la) * np.sin(lo), np.sin(la), np.cos(la) * np.cos(lo)])
        east = np.stack([np.cos(lo), np.zeros_like(lo), -np.sin(lo)])
        north = np.stack([-np.sin(la) * np.sin(lo), np.cos(la), -np.sin(la) * np.cos(lo)])
        n = up - dhdE * east - dhdN * north
        n = n / np.linalg.norm(n, axis=0)
        sun = np.array([0.94, 0.15, 0.3]); sun /= np.linalg.norm(sun)
        lam = np.clip(np.tensordot(sun, n, 1), 0, 1)
        tint = 0.55 + 0.45 * np.clip((h[ii, jj] + 3) / 5, 0, 1)
        v = np.where(inside, lam * tint, 0)
        write_png_gray(prev, (np.clip(v, 0, 1) * 255).astype(np.uint8))
        print("preview:", prev)


if __name__ == "__main__":
    main()
