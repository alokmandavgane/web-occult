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
        "n_shapes": sum(1 for ym in ast for e in json.loads((ROOT / "data" / f"asteroids-{ym}.json").read_text())["events"] if e.get("shape")),
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
        ("Stars", f"ESA <b>Gaia DR3</b> to G 9.5 along the Moon's path, <b>Hipparcos-2</b> for the brightest and those Gaia "
                  f"cannot solve, names from the <b>Yale Bright Star Catalogue</b>: {f['n_stars']:,} stars, each moved to the "
                  f"event date. For asteroids: Gaia DR3 to G 12.5 over the whole sky (about five million stars), and to G 14 "
                  f"for the finder charts"),
        ("Asteroids", f"NASA JPL's <b>Small-Body Database</b>: the orbits and diameters of the {f['n_asteroids']:,} asteroids of "
                      f"15 km and more, and each orbit's uncertainty"),
        ("Asteroid shapes", "<b>DAMIT</b>, the Database of Asteroid Models from Inversion Techniques (Astronomical Institute of "
                            "Charles University; Ďurech, Sidorin &amp; Kaasalainen 2010), CC BY 4.0: asteroid shapes, spin axes and "
                            "periods from light curves"),
        ("Planets' poles and rotation", "The IAU Working Group on Cartographic Coordinates and Rotational Elements"),
        ("Earth's rotation (ΔT)", f"Skyfield's tables and their projection forward: ΔT ≈ {f['delta_t']:.0f} s in {f['dt_year']}"),
        ("The Great Red Spot's longitude", f"Measured, not predicted: {g['lon_II']:g}° (System II) on {grs_date}, drifting "
                                           f"{g['drift_deg_per_month']:g}° a month. Source: {esc(g['source'])}"),
        ("Crater names and sizes", "The IAU Gazetteer of Planetary Nomenclature (USGS), for the outlines on the Moon diagrams"),
        ("Maps and cities", "Natural Earth outlines with India's official borders; city positions from GeoNames and a curated list of Indian cities"),
    ]
    checks = [
        ("The Moon hides Aldebaran, 9 January 2017: disappearance at Jaipur, New Delhi and Silchar",
         "in-the-sky.org's published times", "Within 5 s at each city; through the Moon-and-stars pipeline +0.5, −1.4 and +1.2 s. <i>Automated test.</i>"),
        (f"Which planets the Moon hides, {f['first']}–{f['last']}", "Fred Espenak's <i>Sky Event Almanac</i>",
         "Every occultation it lists is found. The scan's few extras are within 12° of the Sun, where no one can see them."),
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
         "of the published times. The centre lines are offset sideways as a whole: a median 12 km (0.4σ) with the Minor Planet "
         "Center's orbits that Occult uses, 0.7σ with JPL's. That is how much the two orbits differ. "
         "<i>Automated test</i> for five of them."),
        ("Where the asteroids are, 2026–2027", "JPL Horizons",
         "From JPL's own starting state, the integration stays within 0.12 km of Horizons over the 448 days the pages "
         "cover. From the Small-Body Database's published elements, which the pages use, it differs by a few km. That is "
         "under 4 mas, well within each path's error. <i>Automated test.</i>"),
        ("The search that decides which asteroid and star pairs are worth solving", "A plain two-minute search of the same sky",
         "Over two test days, the fast search kept every pair the full search found. <i>Automated test.</i>"),
        ("The any-location solver on each asteroid page", "The engine's full model", "Within 0.02 km and 0.1 s. <i>Automated test.</i>"),
        ("The formula that turns a DAMIT shape to the way it faces at an event", "DAMIT's own light curves",
         "Rebuilt from the shape alone: 54 light curves of Pallas to 1.6% and 34 of the dog-bone Kleopatra to 3.4%. A reversed "
         "spin fits 2–3 times worse and a quarter-turn phase error 3–11 times worse, so the check can tell. <i>Automated test.</i>"),
        ("Where that shape then sits on the sky", "Textbook spherical astronomy",
         "A test shape with a spike points where the textbook formulas say, in all four quarters of the sky. A mirrored "
         "outline or a wrong obliquity sign fails it. <i>Automated test.</i>"),
        ("The path drawn on each asteroid page's map and world inset", "The engine's own centre line and edges",
         "The browser's track matches the engine's to 0.1 km, for the centre line and both edges. <i>Automated test.</i>"),
    ]
    rows = lambda items: "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in items)

    body = f"""
<main class="wrap how">
  <h1>How this is computed</h1>
  <p class="sub">Where every number on this site comes from, what it was checked against, and what is approximate.</p>
  <nav class="toc" aria-label="On this page"><a href="#inputs">The inputs</a><a href="#pages">Each page</a><a href="#checks">Checked against</a>
    <a href="#limits">What is approximate</a><a href="#about">About</a></nav>

  <p class="lead">Nothing here is copied from another prediction service. Moon, Sun and planet positions come from NASA JPL's
  DE431. The site works out where and when each event is visible, city by city. Your browser does the same for any place you
  pick. Other predictions are used only to check the results.</p>

  <h2 id="inputs">The inputs</h2>
  <div class="table-wrap"><table><thead><tr><th>What</th><th>Source</th></tr></thead><tbody>{rows(inputs)}</tbody></table></div>

  <h2 id="pages">How each page is made</h2>
  <h3>Lunar occultations</h3>
  <p>The {f['n_events']} events for {f['first']}–{f['last']} were picked by hand from a DE431 scan of every time the Moon covers a
  planet or bright star. For each, the engine maps where on Earth it is seen and traces the graze limits. For each city it finds
  the contact times, then corrects them for the Moon's uneven edge. That moves them by a few seconds at most. Each page carries a
  2 KB description of the event, from which your browser solves any place, light time and aberration included.</p>
  <p>When the Moon rises or sets during an occultation, a place sees only half of it; the page says which half.</p>
  <h3>The Moon and the stars</h3>
  <p>Each month, {f['ms_from']} to {f['ms_to']}, is one file: the Moon and Sun as daily curves, and the stars the Moon can cover.
  Your browser finds every occultation for your location. Each instrument has a rule of thumb for how faint a star can be at the
  Moon's dark and bright edges. Moonglare and twilight lower it, and the Moon must be 5° up. Each page prints the rule.</p>
  <h3>Asteroid occultations</h3>
  <p>Each month, {f['ast_from']} to {f['ast_to']}, the site's own integrator moves all {f['n_asteroids']:,} asteroid orbits forward
  and tests every Gaia star in reach. It includes the planets and Moon from DE431, Ceres, Pallas, Vesta and Hygiea, and the Sun's
  relativistic term. For each shadow, the engine draws the centre line, both edges and the 1σ lines.</p>
  <p>The 1σ combines the star's error with the orbit's. The orbit error is the largest of three: JPL's formal error, the gap
  between JPL's and the Minor Planet Center's orbits ÷ √2, and 10 mas. Independent orbits differ by about 10 mas, far more than
  JPL's formal error.</p>
  <p>A path is listed if it passes within 100 km of an Indian city at night, with the star 10° up. It must be at least as wide as
  its error, with a fade you can notice. {f['ast_events']:,} so far.</p>
  <p>Each event has a finder chart (Gaia stars to G 14 within 15′, with the asteroid's hourly track), your chord, a fade sketch,
  a world map, and the path as KML or GPX. It opens on its own page, with the path on a street map. Drop a pin to see what any
  spot gets, then share it. Or let the page suggest five stations across the path; spread-out timings reveal the asteroid's
  shape. The full track around the world is drawn too, bright where the star is up after dark. Press Play to watch the shadow
  cross. As elsewhere, your browser works out how close the path comes to you, when, and for how long.</p>
  <h3>Jupiter's and Saturn's moons</h3>
  <p>Eclipses, occultations, transits and shadow transits of Jupiter's four big moons and seven of Saturn's come from JPL's
  satellite ephemerides. The planet is a flattened globe casting a cone of shadow. That gives {jn:,} events for Jupiter and
  {sn:,} for Saturn, {min(j0, s0)}–{max(j1, s1)}. Each one happens at the same instant everywhere. The page only checks whether the planet is
  up and the sky dark where you are.</p>
  <h3>The Great Red Spot</h3>
  <p>A storm, not a body with an orbit. The site computes when the spot's longitude reaches the middle of Jupiter's disc (System II),
  using DE431 and the IAU pole. The spot drifts, so its longitude is carried forward only to {grs_until}. After that, no transits
  are shown until it is updated.</p>
  <h3>Calendar feeds</h3>
  <p>Each of {f['n_feeds']} cities gets a feed with the lunar occultations it can see, binocular star occultations for twelve
  months, and asteroid shadows passing over or near it.</p>

  <h2 id="checks">Checked against</h2>
  <p>Comparisons with independent predictions, and the checks that tie the browser's calculations to the engine's. Those marked
  <i>automated test</i> run again whenever the data is rebuilt.</p>
  <div class="table-wrap"><table><thead><tr><th>What</th><th>Compared with</th><th>Agreement</th></tr></thead><tbody>{rows(checks)}</tbody></table></div>

  <h2 id="limits">What is approximate</h2>
  <ul>
    <li><b>The Moon's edge.</b> City tables and the solid graze lines use the real lunar terrain. Times for “your location”, the
    shaded map and the world map treat the Moon as a smooth sphere, good to about 2 seconds.</li>
    <li><b>The horizon.</b> Altitudes are geometric, for sea level, without atmospheric refraction or hills and buildings. Near the
    horizon the Moon looks about half a degree higher than shown. Your skyline decides the rest.</li>
    <li><b>Earth's rotation.</b> ΔT for future dates is an estimate, good to well under a few seconds through {f['last']}.</li>
    <li><b>Grazes.</b> Near a graze limit a few hundred metres north or south changes what you see. The graze profile on each event
    page shows how sensitive your spot is.</li>
    <li><b>Seeing a star.</b> Visibility is a rule of thumb. Haze, light pollution, your instrument and your eyes decide. The
    aperture presets on the asteroid pages are estimates too. Each is about a magnitude brighter than what the aperture can
    detect, since a star at the limit is too faint to see fade. A camera reaches 2–3 magnitudes deeper.</li>
    <li><b>Jupiter's and Saturn's moons.</b> The brightness drop in a mutual event assumes evenly lit discs. Saturn's rings are not
    modelled, so “behind Saturn” means behind the globe. The moon diagrams are illustrations, good to a tenth of the planet's
    radius. Shadows and eclipses are drawn from the listed times, which come from JPL.</li>
    <li><b>The Great Red Spot.</b> Its times are only as good as its assumed longitude: each degree off moves them by 1.65 minutes.</li>
    <li><b>An asteroid's shape.</b> Every path, time and duration is worked out for a sphere of the asteroid's catalogue
    diameter. Real asteroids are lumpy, so the shadow may be narrower or wider. Timings from several places measure this. Where
    DAMIT has a reliable model (rated 2 or better of 5, with a settled pole), the event page draws the asteroid's real shape with
    your chord across it: {f['n_shapes']} of {f['ast_events']:,} events. These shapes are convex and scaled to the catalogue size.
    Their rotation is projected from light curves, often over decades. They are shown, not used.</li>
    <li><b>An asteroid path's position.</b> Errors of a few milliarcseconds shift a path sideways by kilometres to tens of
    kilometres. The red dashed 1σ lines show how much. Each place gets a percentage chance, assuming the real path may be off by
    a normal 1σ error, which is how occultation software reads a prediction. The chance is only as good as the 1σ. Occult and
    OccultWatcher use their own orbits, so their numbers may differ. Near an edge, expect either outcome. A star Gaia flags as
    hard to fit (high RUWE) is often double, and may fade in steps or not at all.</li>
    <li><b>The list.</b> The lunar occultations are a hand-picked selection, not every one that happens. The asteroid list covers
    asteroids 15 km and up and stars to G 12.5, on paths near Indian cities at night at least as wide as their error.</li>
  </ul>

  <h2 id="about">About</h2>
  <p>{SITE_NAME} is a static site built by <a href="https://alokm.com/">Alok Mandavgane</a>: no accounts and nothing to sign in to,
  with basic page analytics only. Results are checked against IOTA's Occult and in-the-sky.org, never copied. A copied time
  couldn't be recalculated for your location anyway.
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
