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
  ephem_paths.py         where the binary inputs live (below)
tests/             pins contact times against an independent published prediction
cities/india.json  the India audience's city list
ephemeris/         gitignored binary inputs: jup365.bsp, sat441.bsp, lola/ (see engine/ephem_paths.py)
geo/<audience>.json map outlines (Natural Earth + India-compliant borders): scripts/build_geo.py
scripts/build_pages.py   data + geo + seed  ->  site/   (also runs scripts/build_jupiter.py: one diary page per month)
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

## Regenerate

```bash
.venv/bin/python engine/occultation_event.py                    # every seed entry (~55 s each)
.venv/bin/python engine/occultation_event.py venus-2026-09-14   # one
.venv/bin/python engine/occultation_event.py --scan 2026-09-11 2030-01-01 --seed   # candidates
.venv/bin/python engine/satellite_events.py 2027 --planet saturn --config
.venv/bin/python -m pytest tests
python3 scripts/build_pages.py
```

Hosting: Cloudflare Pages Direct Upload project `occult`, custom domain `occult.alokm.com`.
No git integration and no Actions — deploy from this machine:

```bash
./scripts/deploy.sh          # rebuild + upload site/ with Wrangler (npx; `npx wrangler login` once)
```

Cloudflare serves `site/<slug>.html` at `/<slug>` and `404.html` on misses; `_headers` sets cache lifetimes.
