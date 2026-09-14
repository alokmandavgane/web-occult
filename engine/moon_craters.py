"""Crater outlines for the event pages' "At the Moon's edge" diagram.

Reads the IAU Gazetteer of Planetary Nomenclature point file for the Moon (USGS Astrogeology,
MOON_nomenclature_center_pts.dbf from
https://asc-planetarynames-data.s3.us-west-2.amazonaws.com/MOON_nomenclature_center_pts.zip)
and writes catalog/moon-craters.json: adopted craters on the side that can face Earth, as
[lat, lon east-positive -180..180, diameter km]. The page projects each rim circle with the
event's libration and pole angle (`lib`) — a hint of the Moon's face, not a render.

    python engine/moon_craters.py path/to/MOON_nomenclature_center_pts.dbf [--min-km 60]
"""
import argparse
import json
import struct
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "catalog" / "moon-craters.json"
MAX_LON = 100  # libration reaches ~8°, so craters past ±100° never cross the limb


def read_dbf(path):
    with open(path, "rb") as f:
        head = f.read(32)
        n = struct.unpack("<I", head[4:8])[0]
        hlen, rlen = struct.unpack("<HH", head[8:12])
        fields = []
        while True:
            d = f.read(32)
            if d[0] == 0x0D:
                break
            fields.append((d[:11].split(b"\0")[0].decode(), d[16]))
        f.seek(hlen)
        for _ in range(n):
            rec, off = f.read(rlen), 1
            row = {}
            for name, ln in fields:
                row[name] = rec[off:off + ln].decode("utf-8", "replace").strip()
                off += ln
            yield row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dbf")
    ap.add_argument("--min-km", type=float, default=85)  # 85 keeps Tycho; lower reads as texture, not a face
    a = ap.parse_args()
    craters = []
    for r in read_dbf(a.dbf):
        if not r["type"].startswith("Crater") or not r["approval"].startswith("Adopted"):
            continue
        lon = float(r["center_lon"])
        lon = lon - 360 if lon > 180 else lon
        d = float(r["diameter"])
        if abs(lon) <= MAX_LON and d >= a.min_km:
            craters.append([round(float(r["center_lat"]), 2), round(lon, 2), round(d)])
    craters.sort(key=lambda c: -c[2])
    OUT.write_text(json.dumps({
        "source": "IAU Gazetteer of Planetary Nomenclature (USGS Astrogeology), MOON_nomenclature_center_pts",
        "retrieved": date.today().isoformat(),
        "min_diameter_km": a.min_km,
        "fields": ["lat", "lon_east", "diameter_km"],
        "craters": craters,
    }, separators=(",", ":")))
    print(f"wrote {OUT.relative_to(REPO)}: {len(craters)} craters >= {a.min_km:g} km")


if __name__ == "__main__":
    main()
