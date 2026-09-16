"""Calendar feeds: the star screen never drops what the full solve keeps, and the iCalendar text is well formed.
Data files only — no DE431 needed."""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
sys.path.insert(0, os.path.join(HERE, "..", "engine"))

import build_feeds  # noqa: E402
from star_occultations import INSTRUMENTS, MonthModel, visible  # noqa: E402

MONTHS = ["2026-10", "2027-03"]
PLACES = [(28.6139, 77.2090), (19.0760, 72.8777), (51.5072, -0.1276), (-33.8688, 151.2093)]
UTC = lambda t: t.strftime("%H:%M:%S")


def _asteroid_feed(lat, lon):
    """build_feeds.asteroid_events for one place, over the first asteroid month, with _init's own record shape."""
    import glob

    import build_feeds as bf
    from asteroid_occultations import local
    paths = sorted(glob.glob(os.path.join(HERE, "..", "data", "asteroids-*.json")))
    if not paths:
        pytest.skip("no asteroid month files")
    d = json.load(open(paths[0]))
    recs = []
    for ev in d["events"]:
        t0 = datetime.strptime(ev["el"]["t0"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        recs.append({"ym": d["month"], "bbox": d["bbox"], "gen": t0, "t0": t0, "id": ev["id"], "el": ev["el"],
                     "sigma_km": ev["sigma_km"], "sigma_s": ev["sigma_s"], "ast": ev["asteroid"], "star": ev["star"],
                     "drop": ev["drop"], "dur": ev["dur_max_s"]})
    bf._W.update(asteroids=recs)
    cutoff = datetime(2000, 1, 1, tzinfo=timezone.utc)
    return d, recs, bf.asteroid_events("Test", "test", lat, lon, UTC, lambda t: "UTC", cutoff), local


def test_asteroid_feed_entries_are_the_paths_that_reach_the_place():
    """Every entry is a path over the place (or within its 1σ), and every path over it that is up in a dark sky is an entry."""
    import build_feeds as bf
    d, recs, on_path, local = _asteroid_feed(*PLACES[0])          # New Delhi
    ids = {e["uid"].split("@")[0][len("ast-"):-len("-test")] for e in on_path}
    for r in recs:
        s = local(r["el"], *PLACES[0])
        reach = abs(s["d"]) <= r["el"]["R"] + (r["sigma_km"] or 0)
        want = reach and s["star_alt"] >= bf.AST_ALT_MIN and s["sun_alt"] <= bf.AST_SUN_MAX
        assert (r["id"] in ids) == want, (r["id"], s["d"], r["el"]["R"], r["sigma_km"], s["star_alt"], s["sun_alt"])
    assert on_path, "New Delhi should see some asteroid occultations in a month"
    for e in on_path:
        assert e["alarm"] and e["start"] < e["end"] and e["url"].startswith("https://")
        assert ("inside the path" in e["description"]) != ("just outside the path" in e["summary"])


def test_asteroid_entries_stop_at_the_frame():
    _, _, london, _ = _asteroid_feed(*PLACES[2])                   # far outside the audience's map: no solve, no entries
    assert london == []


def _visible_set(model, stars, lat, lon):
    out = {}
    for ev in model.events(stars, lat, lon):
        vis = visible(ev, build_feeds.INSTRUMENT)
        if "D" in vis or "R" in vis:
            out[ev["label"]] = {k: round(c["m"], 6) for k, c in vis.items()}
    return out


@pytest.mark.parametrize("ym", MONTHS)
def test_screen_keeps_every_visible_event(ym):
    path = os.path.join(HERE, "..", "data", f"moon-stars-{ym}.json")
    if not os.path.exists(path):
        pytest.skip(f"no data for {ym}")
    d = json.load(open(path))
    model = MonthModel(d)
    lim = INSTRUMENTS[build_feeds.INSTRUMENT][1]
    stars = [s for s in MonthModel.star_list(d) if s[1] <= lim]
    for lat, lon in PLACES:
        full = _visible_set(model, stars, lat, lon)
        cands = build_feeds.screen(model, stars, lat, lon, build_feeds.INSTRUMENT)
        assert _visible_set(model, cands, lat, lon) == full, (ym, lat, lon)


def test_ics_is_folded_and_escaped():
    t = datetime(2026, 9, 14, 11, 43, tzinfo=timezone.utc)
    ev = {"uid": "occ-x-mumbai@occult.alokm.com", "stamp": t, "start": t, "end": t + timedelta(hours=1),
          "summary": "The Moon occults Venus; daylight, too", "url": "https://occult.alokm.com/venus-2026-09-14",
          "description": "Venus disappears at 17:13:43 — and reappears at 18:15:14 IST, seen from Mumbai.\n" * 4, "alarm": True}
    text = build_feeds.ics_calendar("Mumbai", "Asia/Kolkata", [ev])
    assert text.endswith("\r\n") and "\n" not in text.replace("\r\n", "")
    for line in text.split("\r\n"):
        assert len(line.encode("utf-8")) <= 75, line
    unfolded = text.replace("\r\n ", "")
    assert "SUMMARY:The Moon occults Venus\\; daylight\\, too" in unfolded
    assert "—" in unfolded                                   # multi-byte characters survive folding intact
    assert unfolded.count("BEGIN:VEVENT") == 1 and "TRIGGER:-PT30M" in unfolded


def _star(key, short, vmag, start_min, end_min):
    t0 = datetime(2026, 11, 13, tzinfo=timezone.utc)
    rec = {"uid": f"star-{short}", "start": t0 + timedelta(minutes=start_min), "end": t0 + timedelta(minutes=end_min),
           "summary": f"The Moon hides {short} · mag {vmag:.1f}", "description": f"{short} disappears.\nMoon up.\nurl"}
    return {"key": key, "vmag": vmag, "short": short, "rec": rec, "line": f"Its companion {short} (magnitude {vmag:.1f})."}


def test_one_calendar_entry_per_double():
    items = [_star("ADS 10417", "36 Oph B", 5.1, 10.2, 70), _star("ADS 10417", "36 Oph A", 5.07, 10, 69),
             _star("ADS 10417", "36 Oph A", 5.07, 27 * 1440, 27 * 1440 + 60),          # next pass: its own entry
             _star("HR 1470", "HR 1470", 7.2, 500, 560)]
    got = sorted(build_feeds.merge_doubles(items), key=lambda r: r["start"])
    assert [r["uid"] for r in got] == ["star-36 Oph A", "star-HR 1470", "star-36 Oph A"]
    first = got[0]
    assert first["summary"] == "The Moon hides 36 Oph A and its companion · mag 5.1"
    assert first["start"] == items[1]["rec"]["start"] and first["end"] == items[0]["rec"]["end"]
    assert first["description"] == "36 Oph A disappears.\nIts companion 36 Oph B (magnitude 5.1).\nMoon up.\nurl"
    assert got[1] == items[3]["rec"]


FEED_CITY = "Adelaide, AU"      # 36 Oph A and B, 1 s apart, on 2027-07-15


def test_feed_lists_each_double_once():
    """A real feed: a double's components make one entry, and no UID repeats."""
    build_feeds._init(datetime(2026, 9, 14, tzinfo=timezone.utc).timestamp())
    seed = json.load(open(os.path.join(HERE, "..", "seed.json")))
    lat, lon, tz = build_feeds.collect_cities(seed)[FEED_CITY]
    _, _, evs = build_feeds._city_events((FEED_CITY, lat, lon, tz, "x", []))
    uids = [e["uid"] for e in evs]
    assert len(uids) == len(set(uids))
    assert sum(" and its companion" in e["summary"] for e in evs) >= 1, "pick a city whose feed has a double"


def test_feed_keeps_only_the_half_above_the_horizon():
    """Mexico City, 6 Oct 2026: the Moon rises while Jupiter is hidden — the entry is the reappearance alone."""
    build_feeds._init(datetime(2026, 9, 14, tzinfo=timezone.utc).timestamp())
    seed = json.load(open(os.path.join(HERE, "..", "seed.json")))
    lat, lon, tz = build_feeds.collect_cities(seed)["Mexico City, MX"]
    _, _, evs = build_feeds._city_events(("Mexico City, MX", lat, lon, tz, "mexico-city-mx", []))
    e = next(x for x in evs if x["uid"].startswith("occ-jupiter-2026-10-06-"))
    assert e["summary"] == "The Moon occults Jupiter (reappearance only)"
    assert e["start"] == datetime(2026, 10, 6, 8, 54, 35, tzinfo=timezone.utc)
    assert "disappears" not in e["description"].split("\n")[0] and "-" not in e["description"].split("\n")[2].split("°")[0]


def test_same_place_is_one_feed():
    cities = {"Delhi": [28.6519, 77.2315, "Asia/Kolkata"], "Delhi, IN": [28.6100, 77.2300, "Asia/Kolkata"],
              "Faridabad, IN": [28.4089, 77.3178, "Asia/Kolkata"], "Kowloon, HK": [22.3167, 114.1833, "Asia/Hong_Kong"],
              "Hong Kong, HK": [22.2783, 114.1747, "Asia/Hong_Kong"]}
    rank = {"Delhi, IN": 0, "Hong Kong, HK": 1, "Kowloon, HK": 2, "Faridabad, IN": 3}
    got = build_feeds.feed_cities(cities, rank)
    assert set(got) == {"Delhi", "Faridabad, IN", "Hong Kong, HK"}
    assert got["Delhi"]["aliases"] == ["Delhi, IN"] and got["Hong Kong, HK"]["aliases"] == ["Kowloon, HK"]


def test_city_slugs_are_unique():
    s = build_feeds.city_slugs(["Mexico City, MX", "Mexico City MX", "Mumbai", "Asunción, PY"])
    assert s == {"Mexico City, MX": "mexico-city-mx", "Mexico City MX": "mexico-city-mx-2", "Mumbai": "mumbai",
                 "Asunción, PY": "asuncion-py"}
