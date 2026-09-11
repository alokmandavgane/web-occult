#!/usr/bin/env python3
"""Derive the compact map outlines the occultation pages inline as SVG.

Sources are the Natural Earth files bundled with the eclipse app's map module
(the India-compliant borders live there too) — read at build time, never
copied into this repo. The output per audience is a few tens of KB of clipped,
simplified rings, checked in under geo/, so the page builder needs
no geodata and a new audience is one entry in seed.json plus a re-run.

Usage:  python3 scripts/build_geo.py
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "seed.json"
OUT = ROOT / "geo"
SRC = Path("/Users/alokm/dev/eclipse/composemap/src/commonMain/composeResources/files")
LAND_FINE, LAND_COARSE, BORDERS = "land_50m.geojson", "world_land.geojson", "borders.geojson"

# per-audience source + simplification tolerance (deg); world uses the coarse land and no borders
DETAIL = {"india": (LAND_FINE, 0.03, True), "world": (LAND_COARSE, 0.5, False)}
BORDER_TOL = 0.06   # borders are context, not the subject: coarser than the coastline


def clip_ring(ring, bbox):
    """Sutherland–Hodgman polygon clip against an axis-aligned box."""
    x0, y0, x1, y1 = bbox

    def clip_edge(pts, inside, intersect):
        out = []
        if not pts:
            return out
        prev = pts[-1]
        for cur in pts:
            if inside(cur):
                if not inside(prev):
                    out.append(intersect(prev, cur))
                out.append(cur)
            elif inside(prev):
                out.append(intersect(prev, cur))
            prev = cur
        return out

    def ix(a, b, x):  # intersection with vertical line x
        t = (x - a[0]) / (b[0] - a[0])
        return (x, a[1] + t * (b[1] - a[1]))

    def iy(a, b, y):
        t = (y - a[1]) / (b[1] - a[1])
        return (a[0] + t * (b[0] - a[0]), y)

    pts = [tuple(p) for p in ring]
    pts = clip_edge(pts, lambda p: p[0] >= x0, lambda a, b: ix(a, b, x0))
    pts = clip_edge(pts, lambda p: p[0] <= x1, lambda a, b: ix(a, b, x1))
    pts = clip_edge(pts, lambda p: p[1] >= y0, lambda a, b: iy(a, b, y0))
    pts = clip_edge(pts, lambda p: p[1] <= y1, lambda a, b: iy(a, b, y1))
    return pts


def clip_line(line, bbox):
    """Split a polyline into the pieces inside the box (Liang–Barsky per segment)."""
    x0, y0, x1, y1 = bbox
    pieces, cur = [], []
    for a, b in zip(line, line[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        t0, t1 = 0.0, 1.0
        ok = True
        for p, q in ((-dx, a[0] - x0), (dx, x1 - a[0]), (-dy, a[1] - y0), (dy, y1 - a[1])):
            if p == 0:
                if q < 0:
                    ok = False
                    break
                continue
            r = q / p
            if p < 0:
                t0 = max(t0, r)
            else:
                t1 = min(t1, r)
            if t0 > t1:
                ok = False
                break
        if not ok:
            if cur:
                pieces.append(cur)
                cur = []
            continue
        pa = (a[0] + t0 * dx, a[1] + t0 * dy)
        pb = (a[0] + t1 * dx, a[1] + t1 * dy)
        if not cur or cur[-1] != pa:
            if cur:
                pieces.append(cur)
            cur = [pa]
        cur.append(pb)
    if cur:
        pieces.append(cur)
    return pieces


def simplify(pts, tol):
    """Douglas–Peucker, iterative."""
    if len(pts) < 3:
        return list(pts)
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = pts[a]
        bx, by = pts[b]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        best, bi = 0.0, -1
        for i in range(a + 1, b):
            px, py = pts[i]
            if L2 == 0:
                d = ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
            else:
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
                d = ((px - (ax + t * dx)) ** 2 + (py - (ay + t * dy)) ** 2) ** 0.5
            if d > best:
                best, bi = d, i
        if best > tol:
            keep[bi] = True
            stack.append((a, bi))
            stack.append((bi, b))
    return [p for p, k in zip(pts, keep) if k]


def rings_of(geom):
    if geom["type"] == "Polygon":
        return geom["coordinates"]
    if geom["type"] == "MultiPolygon":
        return [r for poly in geom["coordinates"] for r in poly]
    return []


def lines_of(geom):
    if geom["type"] == "LineString":
        return [geom["coordinates"]]
    if geom["type"] == "MultiLineString":
        return geom["coordinates"]
    return []


def rnd(pts):
    out = []
    for x, y in pts:
        p = [round(x, 2), round(y, 2)]
        if not out or out[-1] != p:
            out.append(p)
    return out


def main():
    seed = json.loads(SEED.read_text())
    OUT.mkdir(exist_ok=True)
    for name, cfg in seed["audiences"].items():
        land_file, tol, want_borders = DETAIL.get(name, (LAND_COARSE, 0.25, False))
        bbox = cfg["bbox"]
        land = json.loads((SRC / land_file).read_text())
        rings = []
        for feat in land["features"]:
            for ring in rings_of(feat["geometry"]):
                c = clip_ring(ring, bbox)
                if len(c) >= 3:
                    s = rnd(simplify(c, tol))
                    if len(s) >= 3:
                        rings.append(s)
        out = {"bbox": bbox, "land": rings}
        if want_borders:
            borders = json.loads((SRC / BORDERS).read_text())
            geoms = borders["geometries"] if borders["type"] == "GeometryCollection" else [f["geometry"] for f in borders["features"]]
            blines = []
            for g in geoms:
                for line in lines_of(g):
                    for piece in clip_line(line, bbox):
                        s = rnd(simplify(piece, BORDER_TOL))
                        if len(s) >= 2:
                            blines.append(s)
            out["borders"] = blines
        path = OUT / f"{name}.json"
        path.write_text(json.dumps(out, separators=(",", ":")))
        print(f"{name}: {len(rings)} land rings, {len(out.get('borders', []))} border pieces -> {path.name} ({path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
