# occult.alokm.com

Lunar occultations of planets and bright stars — where on Earth they can be seen, and when,
city by city. Every number is computed from the JPL DE431 ephemeris; the pages are static.

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
  ephem_paths.py         where the binary inputs live (below)
tests/             pins contact times against an independent published prediction
cities/india.json  the India audience's city list
catalog/moonband.csv  30k stars the Moon can cover: Gaia DR3 to G 9.5 in |ecliptic lat| < 7°, Hipparcos-2 for the
                   brightest and for stars Gaia can't solve, Bayer/Flamsteed names from the Yale Bright Star
                   Catalogue (committed; rebuilt by `engine/star_occultations.py catalog` from ephemeris/catalog/)
ephemeris/         gitignored binary inputs: jup365.bsp, sat441.bsp, lola/ (see engine/ephem_paths.py)
geo/<audience>.json map outlines (Natural Earth + India-compliant borders): scripts/build_geo.py
scripts/build_pages.py   data + geo + seed  ->  site/   (also runs build_jupiter.py and build_moonstars.py: one page per month)
site/              what Cloudflare Pages serves (committed)
```

## Setup

```bash
/opt/homebrew/bin/python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

The engine needs **DE431** (`de431t.bsp`, 3.4 GB), which is not copied here: it lives in the
kaalshodh checkout. Keep kaalshodh beside this repo (`../kaalshodh/api/de431t.bsp`, the default) or set
`OCCULT_DE431=/path/to/de431t.bsp`. The other inputs go in `ephemeris/`:

- `jup365.bsp`, `sat441.bsp` — naif.jpl.nasa.gov/pub/naif/generic_kernels/spk/satellites/
- `lola/ldem_64.img` (+ `.lbl`), `lola/ldem_16.img` — pds-geosciences.wustl.edu, LRO LOLA GDR cylindrical
- `lola/moon_pa_de421_1900-2050.bpc`, `lola/pck00010.tpc`, `lola/moon_080317.tf` — naif.jpl.nasa.gov generic_kernels
- `catalog/gaia_dr3_moonband_g9.5.csv` (ESA Gaia archive query), `catalog/hipparcos2_dec31_hp9.8.csv` (Gaia archive
  `public.hipparcos_newreduction`), `catalog/bsc5_catalog.gz` (CDS V/50) — only needed to rebuild `catalog/moonband.csv`

## Regenerate

```bash
.venv/bin/python engine/occultation_event.py                    # every seed entry (~55 s each)
.venv/bin/python engine/occultation_event.py venus-2026-09-14   # one
.venv/bin/python engine/occultation_event.py --scan 2026-09-11 2030-01-01 --seed   # candidates
.venv/bin/python engine/satellite_events.py 2027 --planet saturn --config
.venv/bin/python engine/star_occultations.py range 2026-09 2028-12        # ~4 s a month
.venv/bin/python -m pytest tests
.venv/bin/python scripts/build_pages.py      # the venv: the Moon-and-stars pages prerender with numpy (~2.5 min)
```

Hosting: Cloudflare Pages Direct Upload project `occult`, custom domain `occult.alokm.com`.
No git integration and no Actions — deploy from this machine:

```bash
./scripts/deploy.sh          # rebuild + upload site/ with Wrangler (npx; `npx wrangler login` once)
```

Cloudflare serves `site/<slug>.html` at `/<slug>` and `404.html` on misses; `_headers` sets cache lifetimes.
