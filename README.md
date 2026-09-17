# occult.alokm.com

Lunar occultations of planets and bright stars — where on Earth they can be seen, and when,
city by city — and asteroid shadows crossing India. Every number is computed from the JPL DE431 ephemeris; the pages are static.

```
seed.json          the curated event list: (target, date, audience, note) — nothing else.
                   Planet events = those Fred Espenak's Sky Event Almanac flags 'Occn.'; our DE431
                   scan finds the same set (+ a few within ~12° of the Sun, unobservable, left out).
                   Bright-star events: included when India sees them in a dark sky.
engine/            the computation (Python, Skyfield):
  occultation_event.py   seed entry -> data/<slug>.json + data/<slug>-limb.json
  satellite_events.py    Jupiter / Saturn moon phenomena -> data/<planet>-moons-<year>.json
  lunar_limb.py          the Moon's real limb from the LRO LOLA DEM
  star_occultations.py   catalogue merge + one month of star occultations -> data/moon-stars-<YYYY-MM>.json
  moon_texture.py        LOLA relief image for the Moon renderer -> site/img/moon-relief-360.png (40 KB)
  moon_craters.py        IAU crater rims (USGS gazetteer) for the event diagram -> catalog/moon-craters.json
  grs_transits.py        Great Red Spot central-meridian transits (catalog/grs.json longitude) -> data/jupiter-grs.json
  asteroid_occultations.py  every asteroid >= 15 km through the month against Gaia DR3 to G 12.5 -> data/asteroids-<YYYY-MM>.json
  ephem_paths.py         where the inputs that are not in git live (below)
tests/             pins contact times against an independent published prediction
cities/india.json  the India audience's city list
catalog/moonband.csv  30k stars the Moon can cover: Gaia DR3 to G 9.5 in |ecliptic lat| < 7°, Hipparcos-2 for the
                   brightest and for stars Gaia can't solve, Bayer/Flamsteed names from the Yale Bright Star
                   Catalogue (committed; rebuilt by `engine/star_occultations.py catalog` from ephemeris/catalog/)
catalog/asteroids.csv  JPL Small-Body Database orbits and diameters of the ~4,500 asteroids >= 15 km (committed;
                   `engine/asteroid_occultations.py orbits`); catalog/asteroid-cov.json and asteroid-mpc.json cache
                   JPL's orbit covariances and the Minor Planet Center's orbits for the asteroids that make a listed
                   path — together they set each path's 1-sigma lines (fetched as needed, committed)
ephemeris/         gitignored binary inputs: jup365.bsp, sat441.bsp, lola/ (see engine/ephem_paths.py)
geo/<audience>.json map outlines (Natural Earth + India-compliant borders), committed: scripts/build_geo.py
scripts/build_pages.py   data + geo + seed  ->  site/   (also runs build_jupiter.py, build_moonstars.py and build_asteroids.py: one page per month, and build_feeds.py: a calendar feed per city)
site/              what Cloudflare Pages serves (committed): pages, plus css/, js/ and img/ files they share, linked by content hash
```

## Setup

Python 3.11 or newer (numpy 2.4 needs it):

```bash
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

## Inputs that are not in git

`engine/ephem_paths.py` resolves all of them and says what reads each.

- **DE431** — `de431t.bsp`, 3.4 GB, from JPL: https://ssd.jpl.nasa.gov/ftp/eph/planets/bsp/de431t.bsp.
  Set `OCCULT_DE431=/path/to/de431t.bsp`; without it the engine looks in a kaalshodh checkout beside this repo
  (`../kaalshodh/api/de431t.bsp`).
- **`ephemeris/`** (gitignored, inside this repo):
  - `jup365.bsp`, `sat441.bsp` — naif.jpl.nasa.gov/pub/naif/generic_kernels/spk/satellites/
  - `lola/ldem_64.img` (+ `.lbl`), `lola/ldem_16.img` — pds-geosciences.wustl.edu, LRO LOLA GDR cylindrical
  - `lola/moon_pa_de421_1900-2050.bpc`, `lola/pck00010.tpc`, `lola/moon_080317.tf` — naif.jpl.nasa.gov generic_kernels
  - `catalog/gaia_dr3_moonband_g9.5.csv` (ESA Gaia archive query), `catalog/hipparcos2_dec31_hp9.8.csv` (Gaia archive
    `public.hipparcos_newreduction`), `catalog/bsc5_catalog.gz` (CDS V/50) — only needed to rebuild `catalog/moonband.csv`
  - `catalog/gaia_g12.5/` and `catalog/gaia_g12.5.npz` — Gaia DR3 to G 12.5 over the whole sky, ~5 million stars:
    `engine/asteroid_occultations.py stars` fetches it from the ESA Gaia archive in 192 HEALPix pieces (~470 MB) and packs
    it (~340 MB). Only the asteroid months read it.
  - `catalog/fields/<gaia id>.json` — the star field around each asteroid target (Gaia to G 14 within 15′), fetched as
    events are found and baked into the month file for the pages' finder charts.
- **DAMIT** (astro.troja.mff.cuni.cz/projects/damit, CC BY 4.0) — `engine/asteroid_shapes.py` caches its model tables
  and the shapes of the asteroids that have events in `ephemeris/damit/` (a few MB) and bakes each event's outline into
  the month file; `engine/asteroid_shapes.py month <YYYY-MM>...` refreshes outlines without re-running a month, and
  `engine/asteroid_shapes.py check 2:102 216:1826` fetches the light curves the orientation test needs.
- **JPL's Small-Body Database API** (ssd-api.jpl.nasa.gov) — read into the committed `catalog/asteroids.csv` and
  `catalog/asteroid-cov.json`, so an asteroid month rebuilds offline once those exist.
- **Map files** — `OCCULT_MAP_DIR`, default `../eclipse/composemap/src/commonMain/composeResources/files` (the map
  module of the author's eclipse app, which is not published). Only two things read them:
  - `scripts/build_geo.py`: `land_50m.geojson` and `world_land.geojson` (Natural Earth land, 50m and 110m) and
    `borders.geojson` (international borders, India-compliant). Its output, `geo/`, is committed.
  - `engine/occultation_event.py`, for an audience with `"cities": "world"`: `cities.csv`, a GeoNames extract sorted
    by population with columns `name,lat,lng,cc,tz,pop,utcoff,country` (cities of a million or more are used).

  Without them, Natural Earth (naturalearthdata.com) and a GeoNames dump (download.geonames.org/export/dump/) in the
  same shapes will do; the borders then follow whichever source you pick.

## Regenerate

```bash
.venv/bin/python engine/occultation_event.py                    # every seed entry (~55 s each)
.venv/bin/python engine/occultation_event.py venus-2026-09-14   # one
.venv/bin/python engine/occultation_event.py --scan 2026-09-11 2030-01-01 --seed   # candidates
.venv/bin/python engine/satellite_events.py 2027 --planet saturn --config
.venv/bin/python engine/star_occultations.py range 2026-09 2028-12        # ~4 s a month
.venv/bin/python engine/asteroid_occultations.py orbits                   # refresh the JPL orbits (then re-run the months)
.venv/bin/python engine/asteroid_occultations.py range 2026-09 2027-08    # needs the Gaia G 12.5 file (`stars`)
.venv/bin/python -m pytest tests
.venv/bin/python scripts/build_pages.py      # the venv: the Moon-and-stars pages prerender with numpy (~2.5 min)
```

The tests that need DE431 skip without it. `scripts/build_og.py` (run first by `build_pages.py`) draws the
link-preview images and app icons with macOS system fonts (Iowan Old Style, Avenir Next); where those fonts are
missing it skips and the committed PNGs stay.

## Hosting

The Cloudflare Pages project `occult` (custom domain `occult.alokm.com`) is connected to this repo through
Cloudflare's Git integration: a push to `main` publishes `site/`, so build locally and commit `site/` with the data it
came from. There are no GitHub Actions. The manual fallback uploads from a machine instead:

```bash
./scripts/deploy.sh          # rebuild + upload site/ with Wrangler (npx; `npx wrangler login` once)
```

Cloudflare serves `site/<slug>.html` at `/<slug>` and `404.html` on misses; `_headers` sets cache lifetimes.

## License and credits

The code is MIT-licensed (`LICENSE`). The numbers and maps come from these sources — keep their credit if you reuse
`data/`, `catalog/`, `geo/` or `site/`:

- NASA JPL: the DE431 planetary ephemeris, the Jupiter and Saturn satellite ephemerides, the NAIF lunar orientation kernels,
  and the Small-Body Database (asteroid orbits, diameters and covariances)
- NASA LRO LOLA lunar topography (PDS Geosciences Node)
- ESA Gaia DR3 (credit ESA/Gaia/DPAC), Hipparcos-2, and the Yale Bright Star Catalogue (CDS V/50)
- DAMIT asteroid shape models (Ďurech, Sidorin & Kaasalainen 2010, A&A 513, A46; CC BY 4.0), each credited on the page
  that draws it
- The IAU Gazetteer of Planetary Nomenclature (USGS)
- Natural Earth (public domain) and GeoNames (CC BY 4.0)
- The Great Red Spot's longitude: Sky & Telescope / JUPOS observations (`catalog/grs.json` records the source)
