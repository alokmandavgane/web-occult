"""Where the inputs that are not in git live. None of them are copied into this repo.

  DE431      JPL planetary ephemeris de431t.bsp, 3.4 GB   https://ssd.jpl.nasa.gov/ftp/eph/planets/bsp/de431t.bsp
             Set OCCULT_DE431 to its path; the default is a kaalshodh checkout beside this repo (api/de431t.bsp).
  ephemeris/ this repo, gitignored:
               jup365.bsp   JPL Jupiter satellites, 1.1 GB   naif.jpl.nasa.gov/pub/naif/generic_kernels/spk/satellites/
               sat441.bsp   JPL Saturn satellites, 630 MB    (same place)
               lola/        LRO LOLA LDEM_64 + LDEM_16 (PDS) and the NAIF lunar-orientation kernels
                            moon_pa_de421_1900-2050.bpc, pck00010.tpc, moon_080317.tf
  MAP_DIR    the eclipse app's map files. Set OCCULT_MAP_DIR; the default is an eclipse checkout beside this repo.
               land_50m.geojson, world_land.geojson   Natural Earth land, 50m and 110m       scripts/build_geo.py
               borders.geojson                        international borders, India-compliant  scripts/build_geo.py
               cities.csv                             GeoNames extract by population          "world" city lists
                                                      (name,lat,lng,cc,tz,pop,utcoff,country)
             Nothing else reads them: geo/ is committed and the other audiences' cities are in cities/.
"""

import os

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
EPHEM_DIR = os.path.join(REPO, "ephemeris")
DE431 = os.environ.get("OCCULT_DE431") or os.path.abspath(os.path.join(REPO, "..", "kaalshodh", "api", "de431t.bsp"))
MAP_DIR = os.environ.get("OCCULT_MAP_DIR") or os.path.abspath(
    os.path.join(REPO, "..", "eclipse", "composemap", "src", "commonMain", "composeResources", "files"))


def require_de431():
    if not os.path.exists(DE431):
        raise SystemExit(f"DE431 not found at {DE431}. Set OCCULT_DE431 to the path of de431t.bsp "
                         f"(3.4 GB, https://ssd.jpl.nasa.gov/ftp/eph/planets/bsp/de431t.bsp).")


def require_map_file(name):
    path = os.path.join(MAP_DIR, name)
    if not os.path.exists(path):
        raise SystemExit(f"{name} not found in {MAP_DIR}. Set OCCULT_MAP_DIR to the folder holding land_50m.geojson, "
                         f"world_land.geojson, borders.geojson and cities.csv (see engine/ephem_paths.py).")
    return path
