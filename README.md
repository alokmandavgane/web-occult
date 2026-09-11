# occult.alokm.com

Lunar occultations of planets and bright stars — where on Earth they can be seen, and when,
city by city. Every number is computed from the JPL DE431 ephemeris; the pages are static.

```
seed.json          the curated event list: (target, date, audience, note) — nothing else
data/<slug>.json   generated per event by the kaalshodh repo:
                     cd ~/dev/kaalshodh/api && python lookup/generate/occultation_event.py <slug>
geo/<audience>.json map outlines (Natural Earth + India-compliant borders): scripts/build_geo.py
scripts/build_pages.py   data + geo + seed  ->  site/
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
