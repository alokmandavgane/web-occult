#!/usr/bin/env python3
"""site/method.html — "How this is computed": the inputs, how each kind of page is made, what it was checked against,
and what is approximate. Counts come from the data at build time; the checks are the ones the tests pin or the commit
history records — add a row only for a comparison that was actually made.

    .venv/bin/python scripts/build_method.py      (also run by build_pages.py, after the feeds)
"""

import glob
import json
from datetime import datetime

from build_pages import FOOTER, OUT, ROOT, SITE_NAME, esc, head

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]

HOW_CSS = """
    .how .table-wrap { margin: 0.6rem 0 0.4rem; }
    .how th, .how td { white-space: normal; line-height: 1.4; }
    .how td:first-child { font-weight: 600; min-width: 9rem; }
    .how ul { padding-left: 1.2rem; margin: 0.5rem 0 0.8rem; }
    .how li { margin: 0.35rem 0; }
    .how h3 { font-family: var(--serif); font-size: 1.15rem; margin: 1.3rem 0 0.2rem; }
    .how .toc { display: flex; flex-wrap: wrap; gap: 0.3rem 1rem; font-size: 0.9rem; margin: 0.8rem 0 0; }
"""


def _ym(ym):
    y, m = ym.split("-")
    return f"{MONTHS[int(m) - 1]} {y}"


def facts():
    seed = json.loads((ROOT / "seed.json").read_text())
    evs = seed["events"]
    now = datetime.utcnow().strftime("%Y-%m-%d")
    nxt = next((e for e in evs if e["date"] >= now), evs[-1])
    dt_s = json.loads((ROOT / "data" / f"{nxt['slug']}.json").read_text())["engine"]["delta_t_s"]
    ms = sorted(p.split("moon-stars-")[1][:7] for p in glob.glob(str(ROOT / "data" / "moon-stars-*.json")))
    sat = {}
    for p in ("jupiter", "saturn"):
        fs = sorted(glob.glob(str(ROOT / "data" / f"{p}-moons-*.json")))
        sat[p] = (sum(len(json.loads(open(f).read())["events"]) for f in fs), fs[0][-9:-5] if fs else "", fs[-1][-9:-5] if fs else "")
    grs = json.loads((ROOT / "catalog" / "grs.json").read_text())
    ast = sorted(p.split("asteroids-")[1][:7] for p in glob.glob(str(ROOT / "data" / "asteroids-*.json")))
    return {
        "ast_from": _ym(ast[0]) if ast else "", "ast_to": _ym(ast[-1]) if ast else "",
        "ast_events": sum(len(json.loads((ROOT / "data" / f"asteroids-{ym}.json").read_text())["events"]) for ym in ast),
        "n_asteroids": sum(1 for _ in open(ROOT / "catalog" / "asteroids.csv")) - 1,
        "n_events": len(evs), "first": evs[0]["date"][:4], "last": evs[-1]["date"][:4], "delta_t": dt_s, "dt_year": nxt["date"][:4],
        "n_stars": sum(1 for _ in open(ROOT / "catalog" / "moonband.csv")) - 1,
        "ms_from": _ym(ms[0]) if ms else "", "ms_to": _ym(ms[-1]) if ms else "",
        "sat": sat, "grs": grs, "n_feeds": len(list((OUT / "ics").glob("*.ics"))),
    }


def write_page():
    f = facts()
    g = f["grs"]
    grs_until = datetime.fromisoformat(g["valid_until"]).strftime("%-d %B %Y")
    grs_date = datetime.fromisoformat(g["date"]).strftime("%-d %B %Y")
    jn, j0, j1 = f["sat"]["jupiter"]
    sn, s0, s1 = f["sat"]["saturn"]

    inputs = [
        ("The Moon, the Sun and the planets", "NASA JPL's <b>DE431</b> planetary ephemeris, read with the Skyfield library"),
        ("Jupiter's and Saturn's moons", "JPL's satellite ephemerides <b>jup365</b> and <b>sat441</b>"),
        ("The Moon's mountains and valleys", "Topography from NASA's Lunar Reconnaissance Orbiter laser altimeter (<b>LRO LOLA</b>), "
                                             "LDEM_64: a height every 1/64° of lunar longitude, about 470 m"),
        ("Which way the Moon faces (libration)", "NAIF's lunar orientation kernels (the DE421 principal-axes frame)"),
        ("Stars", f"ESA <b>Gaia DR3</b> to magnitude G 9.5 in the band the Moon crosses, <b>Hipparcos-2</b> for the brightest stars and "
                  f"those Gaia cannot solve, names from the <b>Yale Bright Star Catalogue</b> — {f['n_stars']:,} stars, each carried "
                  f"to the date with its proper motion, parallax and radial velocity; for asteroid occultations, Gaia DR3 over "
                  f"the whole sky to G 12.5, about five million stars, and a 15′ field around each target to G 14 for the "
                  f"finder charts"),
        ("Asteroids", f"NASA JPL's <b>Small-Body Database</b>: the orbits and diameters of the {f['n_asteroids']:,} asteroids of "
                      f"15 km and more, and each orbit's uncertainty"),
        ("Planets' poles and rotation", "The IAU Working Group on Cartographic Coordinates and Rotational Elements"),
        ("Earth's rotation (ΔT)", f"Skyfield's tables and their projection forward: ΔT ≈ {f['delta_t']:.0f} s in {f['dt_year']}"),
        ("The Great Red Spot's longitude", f"An observation, not an ephemeris: {g['lon_II']:g}° (System II) on {grs_date}, drifting "
                                           f"{g['drift_deg_per_month']:g}° a month — {esc(g['source'])}"),
        ("Crater names and sizes", "The IAU Gazetteer of Planetary Nomenclature (USGS), for the outlines on the Moon diagrams"),
        ("Maps and cities", "Natural Earth outlines with India's official borders; city positions from GeoNames and a curated list of Indian cities"),
    ]
    checks = [
        ("The Moon hides Aldebaran, 9 January 2017: disappearance at Jaipur, New Delhi and Silchar",
         "in-the-sky.org's published times", "Within 5 s at each city; through the Moon-and-stars pipeline +0.5, −1.4 and +1.2 s. <i>Automated test.</i>"),
        (f"Which planets the Moon hides, {f['first']}–{f['last']}", "Fred Espenak's <i>Sky Event Almanac</i>",
         "Every occultation it lists is found; the scan's few extras are within about 12° of the Sun, where no one can see them."),
        ("Jupiter's moons, 1–3 October 2026", "Project Pluto's 2026 tables", "Every Io, Europa and Ganymede event to the minute."),
        ("Jupiter's moons eclipsing and hiding each other", "IMCCE and BAA mutual-event predictions",
         "Io occults Europa 23 September 2026 04:29 UT; Io eclipses Ganymede 18 January 2027 04:56 UT."),
        ("Saturn's moons, 12 September 2026", "Astronomy.com's listing",
         "Dione's shadow on Saturn, Dione crossing the north pole and Tethys entering eclipse, at the listed times."),
        ("The Moon's libration and the tilt of its pole", "JPL Horizons", "0.02° and 0.3°. <i>Automated test.</i>"),
        ("Jupiter's central meridian, for the Great Red Spot", "JPL Horizons", "0.01°. <i>Automated test.</i>"),
        ("The star-occultation solver your browser runs", "Direct Skyfield searches at random places", "Within 0.5 s. <i>Automated test.</i>"),
        ("The any-location solver on each event page", "The engine's own contact search for every listed city",
         "The compact description sits on the Moon's edge to within 0.05″ at every contact; the build refuses to publish otherwise."),
        ("Asteroid occultation paths, September–October 2026: 45 events", "Occult4, as published by IOTA-India",
         "Path widths within 0.5 km; star positions within about 2 mas; the shadow reaching and leaving the Earth within a minute "
         "of the published times. The centre lines differ by a rigid sideways shift — a median 12 km, 0.4 of Occult's own 1σ, with the "
         "Minor Planet Center's orbits that Occult uses, and 0.7σ with JPL's, the size by which the two orbit solutions differ. "
         "<i>Automated test</i> for five of them."),
        ("The any-location solver on each asteroid page", "The engine's full model", "Within 0.02 km and 0.1 s. <i>Automated test.</i>"),
    ]
    rows = lambda items: "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in items)

    body = f"""
<main class="wrap how">
  <h1>How this is computed</h1>
  <p class="sub">Where every number on this site comes from, what it was checked against, and what is approximate.</p>
  <nav class="toc" aria-label="On this page"><a href="#inputs">The inputs</a><a href="#pages">Each page</a><a href="#checks">Checked against</a>
    <a href="#limits">What is approximate</a><a href="#about">About</a></nav>

  <p class="lead">Nothing here is copied from another prediction service. The positions of the Moon, the Sun and the planets come
  from NASA JPL's DE431 ephemeris; from them the site works out where on Earth each event can be seen and when, city by city,
  and your browser repeats the calculation for any place you choose. Other people's predictions are used to check the results,
  never as input.</p>

  <h2 id="inputs">The inputs</h2>
  <div class="table-wrap"><table><thead><tr><th>What</th><th>Source</th></tr></thead><tbody>{rows(inputs)}</tbody></table></div>

  <h2 id="pages">How each page is made</h2>
  <h3>Lunar occultations</h3>
  <p>The {f['n_events']} events from {f['first']} to {f['last']} are chosen by hand from a scan of DE431 for every time the Moon covers a
  planet or a bright star. For each one the engine maps the part of Earth that sees it and traces the northern and southern graze
  limits. For every listed city it finds the moments of contact, then refines them against the real, uneven edge of the Moon —
  LOLA terrain turned to that city's view — which moves them by up to a few seconds. Each page also carries a compact description
  of the event, about 2 KB, from which your browser solves any latitude and longitude, including light-time and aberration.</p>
  <p>When the Moon rises or sets during an occultation, a place sees only half of it; the page says which half.</p>
  <h3>The Moon and the stars</h3>
  <p>Each month from {f['ms_from']} to {f['ms_to']} is one file: the Moon and the Sun as smooth day-by-day curves, and the few thousand stars the
  Moon can cover somewhere that month. Your browser finds every occultation for your location. Whether you'll see one follows a
  stated rule of thumb for each instrument — how faint a star can be at the dark and at the bright edge of the Moon, less in
  moonglare and twilight, with the Moon at least 5° up. The rule is printed on each page.</p>
  <h3>Asteroid occultations</h3>
  <p>Each month from {f['ast_from']} to {f['ast_to']}, every one of the {f['n_asteroids']:,} orbits is carried through the month by the
  site's own integrator — the planets and the Moon from DE431, the pulls of Ceres, Pallas, Vesta and Hygiea, and the Sun's
  relativistic term — and every Gaia star within reach of each asteroid's shadow is tested. For each shadow that touches the
  Earth the engine traces the centre line and the two edges, a band exactly as wide as the asteroid, and the lines one standard
  deviation beyond them. That deviation combines the star's Gaia uncertainty with the orbit's, taken as the largest of JPL's
  formal covariance, the gap between JPL's and the Minor Planet Center's orbits for that very event (divided by √2), and 10 mas —
  independent orbit solutions for these asteroids disagree by about that much, and JPL's formal figures are far smaller. A path
  is listed when it passes within 100 km of one of the site's Indian cities with the star at least 10° up in a sky at least 6°
  past sunset, it is at least as wide as its uncertainty, and the star fades enough to notice — {f['ast_events']:,} so far.
  Each event also carries a finder chart — the Gaia stars within 15′ of the target down to G 14, with the asteroid's track
  through the field hour by hour — and the path as KML or GPX to take to a station. As on the other pages, a compact description of each event lets your browser work out how close the
  path comes to you, when, and for how long the star vanishes.</p>
  <h3>Jupiter's and Saturn's moons</h3>
  <p>Eclipses, occultations, transits and shadow transits of Jupiter's four large moons and seven of Saturn's are searched in JPL's
  satellite ephemerides, with the planet as a flattened globe and its shadow as a cone — {jn:,} events for Jupiter and {sn:,} for
  Saturn from {min(j0, s0)} to {max(j1, s1)}. These happen at one instant for the whole Earth, so the page only works out whether the planet is
  up and the sky dark where you are.</p>
  <h3>The Great Red Spot</h3>
  <p>A storm, not a body with an orbit. The site computes when Jupiter's central meridian, in the System II longitude system, reaches
  the spot's longitude, using DE431 and the IAU pole. The longitude itself is measured by observers and drifts, so the site carries
  it forward only until {grs_until} and shows no transits after that until it is updated.</p>
  <h3>Calendar feeds</h3>
  <p>The same calculations for each of {f['n_feeds']} cities: the chosen lunar occultations the city can see, the star occultations
  visible there in binoculars over the next twelve months, and the asteroid shadows whose path crosses the city or comes within
  its margin of error — with the star up in a dark sky, and each entry saying how far the centre line passes.</p>

  <h2 id="checks">Checked against</h2>
  <p>Comparisons with independent predictions, and the checks that tie the browser's calculations to the engine's. Those marked
  <i>automated test</i> run again whenever the data is rebuilt.</p>
  <div class="table-wrap"><table><thead><tr><th>What</th><th>Compared with</th><th>Agreement</th></tr></thead><tbody>{rows(checks)}</tbody></table></div>

  <h2 id="limits">What is approximate</h2>
  <ul>
    <li><b>The Moon's edge.</b> City tables and the solid graze lines use the real lunar terrain. Times for “your location”, the
    shaded map and the world map treat the Moon as a smooth sphere, which is good to about 2 seconds.</li>
    <li><b>The horizon.</b> Altitudes are geometric, for sea level, without atmospheric refraction or hills and buildings. Near the
    horizon the Moon looks about half a degree higher than the number given, and what you can see depends on your skyline.</li>
    <li><b>Earth's rotation.</b> ΔT for future dates is a projection, a small and slowly growing uncertainty — well under the
    few seconds that matter here through {f['last']}.</li>
    <li><b>Grazes.</b> Near a graze limit a few hundred metres north or south changes what you see. The graze profile on each event
    page shows how sensitive your spot is.</li>
    <li><b>Seeing a star.</b> Visibility is a rule of thumb. Haze, light pollution, your instrument and your eyes decide.</li>
    <li><b>Jupiter's and Saturn's moons.</b> The brightness drop in a mutual event assumes evenly lit discs. Saturn's rings are not
    modelled, so “behind Saturn” means behind the globe. The configuration diagrams are pictures, good to about a tenth of a
    planet's radius; the times come from JPL.</li>
    <li><b>The Great Red Spot.</b> Its times are only as good as its assumed longitude: each degree off moves them by 1.65 minutes.</li>
    <li><b>An asteroid's shape.</b> Each asteroid is a sphere of its catalogue diameter. Real ones are lumpy and tumbling, so the
    true shadow can be narrower or wider than the band drawn — which is what timing an occultation from several places measures.</li>
    <li><b>An asteroid path's position.</b> Orbits and star positions are uncertain by a few milliarcseconds, which moves a path
    sideways by kilometres to tens of kilometres; the dashed 1σ lines show by how much. Observers near an edge should expect
    either outcome. A star Gaia flags as hard to fit (high RUWE) is often double, and may fade in steps or not at all.</li>
    <li><b>The list.</b> The lunar occultations are a hand-picked selection, not every one that happens. The asteroid list keeps
    only paths near Indian cities at night that are at least as wide as their uncertainty, for asteroids of 15 km and more and
    stars to G 12.5.</li>
  </ul>

  <h2 id="about">About</h2>
  <p>{SITE_NAME} is a static site built by <a href="https://alokm.com/">Alok Mandavgane</a>: no accounts and nothing to sign in to,
  with basic page analytics only. Prediction services such as IOTA's Occult and in-the-sky.org are used to check the results here
  and are never pasted in — their output is their own work, and a copied time couldn't be recomputed for your location anyway.
  Corrections are welcome through <a href="https://alokm.com/">alokm.com</a>.</p>
</main>
{FOOTER}
</body>
</html>
"""
    desc = ("Where every number on Occult comes from: JPL ephemerides, lunar terrain and star catalogues, how each page is computed, "
            "the independent predictions it was checked against, and what is approximate.")
    (OUT / "method.html").write_text(head(f"How this is computed · {SITE_NAME}", desc, "/method", extra=f"<style>{HOW_CSS}</style>") + body)
    print("wrote site/method.html")


if __name__ == "__main__":
    write_page()
