# occult.alokm.com

Lunar occultations of planets and bright stars — where on Earth they can be seen, and when,
city by city. Every number is computed from the JPL DE431 ephemeris; the pages are static.

```
seed.json          the curated event list: (target, date, audience, note) — nothing else.
                   Planet events = those Fred Espenak's Sky Event Almanac flags 'Occn.'; our DE431
                   scan finds the same set (+ a few within ~12° of the Sun, unobservable, left out).
                   Bright-star events: included when India sees them in a dark sky.
data/<slug>.json   generated per event by the kaalshodh repo:
                     cd ~/dev/kaalshodh/api && python lookup/generate/occultation_event.py <slug>
geo/<audience>.json map outlines (Natural Earth + India-compliant borders): scripts/build_geo.py
data/jupiter-moons-<year>.json   Galilean-moon phenomena (kaalshodh: api/lookup/generate/satellite_events.py,
                   DE431 + JPL jup365.bsp): eclipses, occultations, transits, shadows, mutual events
scripts/build_pages.py   data + geo + seed  ->  site/   (also runs scripts/build_jupiter.py: one diary page per month)
site/              what Cloudflare Pages serves (committed; pushed by scripts/deploy.sh)
```

Regenerate after editing the seed:

```bash
(cd ~/dev/kaalshodh/api && python lookup/generate/occultation_event.py)   # all seed entries
python3 scripts/build_pages.py
```

Hosting: Cloudflare Pages Direct Upload project `occult`, custom domain `occult.alokm.com`.
No git integration and no Actions — deploy from this machine:

```bash
./scripts/deploy.sh          # rebuild + upload site/ with Wrangler (npx; `npx wrangler login` once)
```

Cloudflare serves `site/<slug>.html` at `/<slug>` and `404.html` on misses; `_headers` sets cache lifetimes.
