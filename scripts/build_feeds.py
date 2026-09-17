#!/usr/bin/env python3
"""Calendar feeds: site/ics/<city>.ics for every city the site knows, and site/calendar.html, the page that
subscribes you to one.

A feed holds what is worth an entry in someone's calendar, seen from that city:
  - the hand-picked lunar occultations (planets and bright stars). Where the city is in the event's own list the
    times are that list's (real lunar limb); elsewhere they are solved from the event's elements — the solver the
    page runs, mean limb, ±2 s — for cities in or near the event's visibility region. Kept when the Moon is up.
  - lunar occultations of catalogue stars visible in BINOCULARS (`star_occultations.visible`) over the next
    STAR_MONTHS months: exactly the rows the Moon & stars page lists for that city with binoculars. A cheap screen
    on the solver's 2-minute grid picks the candidates, then `MonthModel.events` solves them exactly
    (tests/test_feeds.py checks the screen never drops an event the full solve keeps).
  - the asteroid shadows that pass over the city: `asteroid_occultations.local` from each event's elements, kept when
    the place is inside the path or within its 1-sigma margin, with the star at least AST_ALT_MIN up and the sky dark.
    About thirty a year for a place in India, half of them inside the path — the entry says which, and links the
    finder chart and the path as KML.
Jupiter's and Saturn's moon events are left out: several a night is not a calendar anyone keeps.

Feeds are static, as fresh as the last deploy: events from PAST_DAYS ago onward. DTSTAMP comes from the data,
not the clock, so a rebuild rewrites a feed only when its events change.

    .venv/bin/python scripts/build_feeds.py      (also run by build_pages.py)
"""

import csv
import hashlib
import json
import math
import os
import re
import sys
import unicodedata
import zoneinfo
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta, timezone

import numpy as np

from build_pages import FOOTER, OUT, ROOT, SITE, SITE_NAME, esc, head

sys.path.insert(0, str(ROOT / "engine"))

FEED_DIR = OUT / "ics"
INSTRUMENT = "binoculars"
STAR_MONTHS = 12
PAST_DAYS = 7
HOST = SITE.split("://", 1)[1]
ALARM_MIN = 30          # a reminder before an event you can watch from where you already are
AST_DRIVE_KMH = 45.0    # a night drive to the path, with a telescope in the back
AST_PACK_MIN = 45.0     # pack it, and at the other end find an 11th-magnitude star and get the clock right
AST_ALARM_MAX = 180     # past three hours a reminder is not a reminder any more
AST_ALT_MIN, AST_SUN_MAX, AST_PAD_DEG = 10.0, -6.0, 3.0    # when an asteroid path is worth a place's calendar


# ------------------------------------------------------------------------------------------ cities

def collect_cities(seed):
    """Every city an event page lists: name -> [lat, lon, tz]."""
    out = {}
    for e in seed["events"]:
        for c in json.loads((ROOT / "data" / f"{e['slug']}.json").read_text())["cities"]:
            out.setdefault(c["name"], [c["lat"], c["lon"], c.get("tz", "")])
    return dict(sorted(out.items()))


def world_rank(seed):
    """The world city list's order (by population) from any world-audience event."""
    for e in seed["events"]:
        d = json.loads((ROOT / "data" / f"{e['slug']}.json").read_text())
        if d["audience"] == "world":
            return {c["name"]: i for i, c in enumerate(d["cities"])}
    return {}


def _km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 12742.0 * math.asin(math.sqrt(min(1.0, h)))


def feed_cities(cities, rank, km=5.0):
    """One feed per place. A city listed twice (the India list's "Delhi", the world list's "Delhi, IN") or a district
    within `km` of a bigger city becomes an alias of the name kept: the India list's, else the more populous."""
    order = sorted(cities, key=lambda n: (rank.get(n, -1), n))
    kept = {}
    for n in order:
        lat, lon, tz = cities[n]
        home = next((k for k, v in kept.items() if _km(lat, lon, v["lat"], v["lon"]) < km), None)
        if home:
            kept[home]["aliases"].append(n)
            kept[home]["tz"] = kept[home]["tz"] or tz
        else:
            kept[n] = {"lat": lat, "lon": lon, "tz": tz, "aliases": []}
    return dict(sorted(kept.items()))


def city_slugs(names):
    out, used = {}, set()
    for n in names:
        ascii_ = unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode()   # Asunción -> Asuncion
        base = re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-") or "city"
        s, k = base, 2
        while s in used:
            s, k = f"{base}-{k}", k + 1
        used.add(s)
        out[n] = s
    return out


# ------------------------------------------------------------------------------------------ iCalendar

def ics_text(s):
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold(line):
    """RFC 5545: lines of at most 75 octets, continued with CRLF + space, never splitting a UTF-8 character."""
    b, parts, limit = line.encode("utf-8"), [], 75
    while len(b) > limit:
        cut = limit
        while (b[cut] & 0xC0) == 0x80:
            cut -= 1
        parts.append(b[:cut])
        b, limit = b[cut:], 74
    parts.append(b)
    return b"\r\n ".join(parts).decode("utf-8")


def stamp(t):
    return t.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ics_calendar(name, tzname, events):
    L = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:-//{HOST}//Occultations//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
         f"X-WR-CALNAME:{ics_text(f'Occultations from {name}')}",
         f"X-WR-CALDESC:{ics_text(f'Occultations you can see from {name}, computed by {HOST}')}",
         "REFRESH-INTERVAL;VALUE=DURATION:PT12H", "X-PUBLISHED-TTL:PT12H"]
    if tzname:
        L.append(f"X-WR-TIMEZONE:{tzname}")
    for ev in events:
        L += ["BEGIN:VEVENT", f"UID:{ev['uid']}", f"DTSTAMP:{stamp(ev['stamp'])}", f"DTSTART:{stamp(ev['start'])}",
              f"DTEND:{stamp(ev['end'])}", f"SUMMARY:{ics_text(ev['summary'])}", f"DESCRIPTION:{ics_text(ev['description'])}",
              f"URL:{ev['url']}", "TRANSP:TRANSPARENT"]
        if ev.get("alarm"):
            lead = ALARM_MIN if ev["alarm"] is True else int(ev["alarm"])    # True = the standard lead, else minutes
            L += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{ics_text(ev['summary'])}",
                  f"TRIGGER:-PT{lead}M", "END:VALARM"]
        L.append("END:VEVENT")
    L.append("END:VCALENDAR")
    return "\r\n".join(fold(x) for x in L) + "\r\n"


# ------------------------------------------------------------------------------------------ the star screen

def screen(model, stars, lat, lon, instrument, step=2.0):
    """Stars that COULD pass `visible` from this place: contacts by linear interpolation on the solver's own grid,
    judged with every threshold eased (0.3 mag, 0.2° of Moon and Sun altitude, either limb near a cusp)."""
    from star_occultations import C_KMS, INSTRUMENTS, R_MOON_KM, visible
    _, dark, bright = INSTRUMENTS[instrument]
    model.observer(lat, lon)
    grid = np.arange(-180, model.d["total_min"] + 180 + 1e-9, step)
    UM, DIST, _, _, VOBS = model.geom_vec(grid)
    SDM = np.degrees(np.arcsin(R_MOON_KM / DIST)) * 3600
    half = int(round(180 / step))
    keep = []
    for star in stars:
        label, vmag, u, tg = star
        c = int(round((tg + 180) / step))
        w = slice(max(0, c - half), min(len(grid), c + half + 1))
        us = u[None, :] + VOBS[w] / C_KMS
        us = us / np.linalg.norm(us, axis=1)[:, None]
        marg = np.degrees(np.arccos(np.clip(np.sum(UM[w] * us, axis=1), -1, 1))) * 3600 - SDM[w]
        if marg.min() > 3.0:
            continue
        g, neg = grid[w], marg < 0
        cons = {}
        for i in np.nonzero(neg[1:] != neg[:-1])[0]:
            m = g[i] + (g[i + 1] - g[i]) * marg[i] / (marg[i] - marg[i + 1])
            cc = dict(model.circumstances(m, u))
            cc["moon_alt"] += 0.2
            cc["sun_alt"] -= 0.2
            if cc["cusp"] < 2:
                cc["limb"] = "bright" if bright >= dark - 2.5 * max(0.0, cc["illum"] - 0.4) else "dark"
            cons["D" if neg[i + 1] else "R"] = cc
        if cons and visible({"vmag": vmag - 0.3, "contacts": cons}, instrument):
            keep.append(star)
    return keep


# ------------------------------------------------------------------------------------------ per-city work (workers)

_W = {}


def _init(now_s):
    from occultation_event import _parse_t0
    from star_occultations import INSTRUMENTS, MonthModel
    now = datetime.fromtimestamp(now_s, timezone.utc)
    seed = json.loads((ROOT / "seed.json").read_text())
    events = []
    for e in seed["events"]:
        d = json.loads((ROOT / "data" / f"{e['slug']}.json").read_text())
        ends = [datetime.strptime(v, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                for c in d["cities"] for v in c.get("contacts", {}).values()]
        if ends and max(ends) < now - timedelta(days=PAST_DAYS):
            continue
        events.append({"slug": e["slug"], "target": d["target"]["names"]["common"], "elements": d["elements"],
                       "generated": datetime.strptime(d["generated"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc),
                       "cities": {c["name"]: c for c in d["cities"]},
                       "rings": [np.asarray(r, dtype=float) for r in d["maps"]["world"]["region"]],
                       "t0": _parse_t0(d["elements"])})
    lim = INSTRUMENTS[INSTRUMENT][1]      # the dark-limb limit: no fainter star can pass `visible` with this instrument
    first = datetime(now.year, now.month, 1) - timedelta(days=PAST_DAYS)
    yms = []
    y, m = first.year, first.month
    for _ in range(STAR_MONTHS + 1):
        yms.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    months = []
    for ym in dict.fromkeys(yms):
        f = ROOT / "data" / f"moon-stars-{ym}.json"
        if f.exists():
            d = json.loads(f.read_text())
            months.append((ym, datetime.strptime(d["t0"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc), MonthModel(d),
                           [s for s in MonthModel.star_list(d) if s[1] <= lim]))
    with open(ROOT / "catalog" / "moonband.csv", newline="") as f:          # labels are unique in the catalogue
        double = {r["label"]: r["double"] for r in csv.DictReader(f) if r["double"]}
    asteroids = []
    for path in sorted((ROOT / "data").glob("asteroids-*.json")):
        d = json.loads(path.read_text())
        gen = datetime.strptime(d["generated"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        for ev in d["events"]:
            t0 = datetime.strptime(ev["el"]["t0"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if t0 < now - timedelta(days=PAST_DAYS):
                continue
            asteroids.append({"ym": d["month"], "bbox": d["bbox"], "gen": gen, "t0": t0, "id": ev["id"], "el": ev["el"],
                              "sigma_km": ev["sigma_km"], "sigma_s": ev["sigma_s"], "ast": ev["asteroid"],
                              "star": ev["star"], "drop": ev["drop"], "dur": ev["dur_max_s"]})
    _W.update(now=now, events=events, months=months, double=double, asteroids=asteroids)


def merge_doubles(items, window=timedelta(hours=1)):
    """One calendar entry per double star. `items` are star records with `key` (the catalogue's BSC double — ADS
    number, else HR — or the label), `vmag`, `short` (display label), `line` (the sentence for a companion) and
    `rec`. Records of one key within `window` of the first become the brightest's entry (its uid), spanning them
    all and naming the others; the same key further apart is a second pass and stays separate."""
    out, cluster = [], []

    def flush():
        best = min(cluster, key=lambda i: (i["vmag"], i["short"]))
        rec = dict(best["rec"])
        others = sorted((i for i in cluster if i is not best), key=lambda i: i["rec"]["start"])
        if others:
            rec["start"] = min(i["rec"]["start"] for i in cluster)
            rec["end"] = max(i["rec"]["end"] for i in cluster)
            rec["summary"] = (f"The Moon hides {best['short']} and its companion{'s' if len(others) > 1 else ''}"
                              f" · mag {best['vmag']:.1f}")
            first, rest = rec["description"].split("\n", 1)
            rec["description"] = "\n".join([first, *(i["line"] for i in others), rest])
        out.append(rec)

    for it in sorted(items, key=lambda i: (i["key"], i["rec"]["start"])):
        if cluster and (it["key"] != cluster[0]["key"] or it["rec"]["start"] - cluster[0]["rec"]["start"] > window):
            flush()
            cluster = []
        cluster.append(it)
    if cluster:
        flush()
    return out


def _near_region(rings, lat, lon, buf=4.0):
    for a in rings:
        dlon = (a[:, 1] - lon + 540) % 360 - 180
        if np.any((np.abs(a[:, 0] - lat) < buf) & (np.abs(dlon) * max(0.2, math.cos(math.radians(lat))) < buf)):
            return True
        x, y = lon + dlon, a[:, 0]
        xj, yj = np.roll(x, 1), np.roll(y, 1)
        cross = ((y > lat) != (yj > lat)) & (lon < (xj - x) * (lat - y) / np.where(yj == y, 1e-12, yj - y) + x)
        if np.count_nonzero(cross) % 2:
            return True
    return False


def _city_events(args):
    from build_moonstars import compass, short_label, sky_text
    from occultation_event import element_geometry, solve_from_elements
    from star_occultations import visible
    from urllib.parse import quote
    name, lat, lon, tzname, slug, aliases = args
    tz = zoneinfo.ZoneInfo(tzname) if tzname else timezone.utc
    now = _W["now"]
    cutoff = now - timedelta(days=PAST_DAYS)
    parse = lambda s: datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    hms = lambda t: t.astimezone(tz).strftime("%H:%M:%S")
    zabbr = lambda t: t.astimezone(tz).strftime("%Z") if tzname else "UTC"
    out = []

    for e in _W["events"]:
        hit = next((n for n in (name, *aliases) if n in e["cities"]), None)
        if hit is not None:
            row = e["cities"][hit]
            if row["verdict"] != "visible" or not row.get("contacts"):
                continue
            con, exact = {k: parse(v) for k, v in row["contacts"].items()}, True
            url = f"{SITE}/{e['slug']}?city={quote(hit)}"
        else:
            if not _near_region(e["rings"], lat, lon):
                continue
            r = solve_from_elements(e["elements"], lat, lon)
            if not r["contacts"]:
                continue
            con, exact = {k: parse(v) for k, v in r["contacts"].items()}, False
            url = f"{SITE}/{e['slug']}?lat={lat:.4f}&lon={lon:.4f}"
        # the Moon at each contact: it can rise or set mid-event, leaving one half below the horizon (as on the page)
        geom = element_geometry(e["elements"], lat, lon)
        at = {k: geom((t - e["t0"]).total_seconds() / 60.0) for k, t in con.items()}
        if not any(float(g["alt_m"]) > 0 for g in at.values()):
            continue
        dk, rk = ("D2" if "D2" in con else "D1"), ("R1" if "R1" in con else "R2")
        up_d, up_r = dk in at and float(at[dk]["alt_m"]) > 0, rk in at and float(at[rk]["alt_m"]) > 0
        seen = "both" if up_d == up_r else "rises" if up_r else "sets"
        keys = [k for k in ("D1", "D2", "R1", "R2") if k in con and (seen == "both" or (seen == "rises") == k.startswith("R"))]
        start, end = con[keys[0]], con[keys[-1]]
        if end < cutoff:
            continue
        g = at[rk if seen == "rises" else dk]
        parts = ([f"disappears at {hms(con[dk])}"] if seen != "rises" and dk in con else []) + \
                ([f"reappears at {hms(con[rk])}"] if seen != "sets" and rk in con else [])
        half = {"both": "", "rises": "The Moon rises during the occultation: only the reappearance is above the horizon.\n",
                "sets": "The Moon sets during the occultation: only the disappearance is above the horizon.\n"}[seen]
        desc = (f"{e['target']} {' and '.join(parts)} {zabbr(start)}, seen from {name}.\n" + half
                + f"The Moon is {float(g['alt_m']):.0f}° up in the {compass(float(g['az_m']))} · {sky_text(float(g['alt_s']))}.\n"
                + ("Times against the real lunar limb.\n" if exact else "Times for the Moon's mean limb, ±2 s.\n")
                + f"Map, timings and the view at the Moon's edge: {url}")
        out.append({"uid": f"occ-{e['slug']}-{slug}@{HOST}", "stamp": e["generated"], "start": start,
                    "end": end if end > start else start + timedelta(minutes=1),
                    "summary": f"The Moon occults {e['target']}" + {"both": "", "rises": " (reappearance only)", "sets": " (disappearance only)"}[seen],
                    "description": desc, "url": url, "alarm": ALARM_MIN})

    verb = {"D": "disappears", "R": "reappears"}
    items = []
    for ym, t0, model, stars in _W["months"]:
        cands = screen(model, stars, lat, lon, INSTRUMENT)
        if not cands:
            continue
        for ev in model.events(cands, lat, lon):
            vis = visible(ev, INSTRUMENT)
            keys = [k for k in ("D", "R") if k in vis]
            if not keys:
                continue
            times = {k: t0 + timedelta(minutes=vis[k]["m"]) for k in keys}
            if max(times.values()) < cutoff:
                continue
            c0 = vis[keys[0]]
            label = short_label(ev["label"])
            what = " and ".join(f"{verb[k]} at {hms(times[k])} at the {vis[k]['limb']} limb" for k in keys)
            url = f"{SITE}/moon-stars-{ym}"
            desc = (f"{label} (magnitude {ev['vmag']:.1f}) {what} {zabbr(times[keys[0]])}, seen from {name}.\n"
                    f"The Moon is {c0['moon_alt']:.0f}° up in the {compass(c0['moon_az'])} · {sky_text(c0['sun_alt'])}. Binoculars show it.\n"
                    + ("A graze: the star skims the Moon's edge and may flicker.\n" if ev["graze"] else "")
                    + f"Every occultation this month, for anywhere: {url}")
            start = times[keys[0]]
            end = times[keys[-1]] if len(keys) == 2 else start + timedelta(minutes=2)
            # the same star can be occulted twice in a 31-day month: the minute of the first contact keeps them apart
            uid = hashlib.sha1(f"{ym}|{ev['label']}|{int(start.timestamp() // 60)}".encode()).hexdigest()[:12]
            rec = {"uid": f"star-{uid}-{slug}@{HOST}", "stamp": t0, "start": start, "end": end,
                   "summary": f"The Moon hides {label} · mag {ev['vmag']:.1f}", "description": desc, "url": url}
            items.append({"key": _W["double"].get(ev["label"], ev["label"]), "vmag": ev["vmag"], "short": label, "rec": rec,
                          "line": f"Its companion {label} (magnitude {ev['vmag']:.1f}) {what}."})
    out += merge_doubles(items)
    out += asteroid_events(name, slug, lat, lon, hms, zabbr, cutoff)
    out.sort(key=lambda x: (x["start"], x["uid"]))
    return name, slug, out


def asteroid_alarm(edge_km):
    """How long before a shadow the reminder is worth having. Inside the path you are already standing where you need
    to be, so it is the usual lead. Outside it you have to decide to go, pack a telescope, drive to the edge and set up
    in the dark — and a reminder that arrives after the moment you should have left is no reminder at all."""
    if edge_km <= 0:
        return ALARM_MIN
    want = ALARM_MIN + AST_PACK_MIN + 60.0 * edge_km / AST_DRIVE_KMH
    return int(min(AST_ALARM_MAX, 15 * math.ceil(want / 15)))


def asteroid_events(name, slug, lat, lon, hms, zabbr, cutoff):
    """The asteroid shadows that reach this place: inside the path, or within the 1-sigma margin where a chord from
    the edge is the most valuable observation of all."""
    from asteroid_occultations import local, to_centre
    from build_asteroids import chance, pct
    from build_moonstars import compass, sky_text
    out = []
    for a in _W["asteroids"]:
        lon0, lat0, lon1, lat1 = a["bbox"]
        if not (lon0 - AST_PAD_DEG <= lon <= lon1 + AST_PAD_DEG and lat0 - AST_PAD_DEG <= lat <= lat1 + AST_PAD_DEG):
            continue
        R, sig = a["el"]["R"], a["sigma_km"] or 0.0
        s = local(a["el"], lat, lon)
        if abs(s["d"]) > R + sig or s["star_alt"] < AST_ALT_MIN or s["sun_alt"] > AST_SUN_MAX:
            continue
        t = a["t0"] + timedelta(seconds=s["tau"])
        if t < cutoff:
            continue
        ground, brg = to_centre(a["el"], lat, lon)
        inside = abs(s["d"]) <= R
        who = f"({a['ast']['number']}) {a['ast']['name']}"
        url = f"{SITE}/asteroid?e={a['id']}"        # the page with the map, the pin and the download, not the month list
        edge = 0.0 if inside else ground * (abs(s["d"]) - R) / abs(s["d"])
        p = pct(chance({"el": a["el"], "sigma_km": a["sigma_km"]}, s))      # the same number the event page shows
        where = (f"You are inside the path, {ground:.0f} km from its centre line: the star vanishes for up to {s['dur']:.1f} s."
                 if inside else
                 f"The predicted edge passes {edge:.0f} km to the {compass(brg)}, so a miss is "
                 f"likely — but a chord from near the edge is the most valuable observation of all.")
        desc = (f"{who} hides a magnitude {a['star']['v']:.1f} star, seen from {name}.\n{where}\n"
                f"Chance of an occultation here: {p}, allowing for the path's 1σ of {sig:.0f} km.\n"
                f"Closest approach {hms(t)} {zabbr(t)}, give or take {a['sigma_s']:.0f} s. The star is {s['star_alt']:.0f}° up in the "
                f"{compass(s['star_az'])} · {sky_text(s['sun_alt'])}.\n"
                f"It fades {a['drop']:.1f} magnitudes for up to {a['dur']:.1f} s on the centre line, and the path is "
                f"{a['ast']['diameter_km']:.0f} km wide, give or take {sig:.0f} km.\n"
                f"The map, the finder chart and the path as KML: {url}")
        out.append({"uid": f"ast-{a['id']}-{slug}@{HOST}", "stamp": a["gen"], "start": t - timedelta(minutes=5),
                    "end": t + timedelta(minutes=5), "url": url, "alarm": asteroid_alarm(edge), "description": desc,
                    "summary": f"{who} hides a mag {a['star']['v']:.1f} star" + ("" if inside else " (just outside the path)") + f" · {p} chance"})
    return out


# ------------------------------------------------------------------------------------------ the page

CAL_CSS = """
    .feed-card { background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 0.9rem 1rem; margin: 0.8rem 0; }
    .feed-card label { display: block; font-size: 0.9rem; color: var(--muted); }
    .feed-card select { font: inherit; width: 100%; max-width: 26rem; padding: 0.45rem 0.6rem; border-radius: 10px; border: 1px solid var(--line);
                        background: var(--card); color: var(--text); margin-top: 0.3rem; }
    .feed-row { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; margin-top: 0.7rem; }
    .feed-city { font-size: 1.15rem; font-weight: 700; margin: 0.2rem 0 0; letter-spacing: -0.01em; }
    .feed-count { color: var(--muted); font-size: 0.9rem; }
    .feed-url { font: 0.8rem ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--muted); word-break: break-all; margin-top: 0.5rem; }
    .feed-next { list-style: none; padding: 0; margin: 0.6rem 0 0; display: grid; gap: 0.35rem; }
    .feed-next li { display: grid; grid-template-columns: 9.5rem 1fr; gap: 0.6rem; font-size: 0.92rem; }
    .feed-next time { color: var(--muted); font-variant-numeric: tabular-nums; }
    a.btn { display: inline-flex; align-items: center; text-decoration: none; }
"""

CAL_JS = r"""
(function () {
  var C = JSON.parse(document.getElementById('feed-cities').textContent), HOST = document.body.dataset.host;
  var sel = document.getElementById('feed-city'), out = document.getElementById('feed-out');
  function nearest(lat, lon) {
    var best = 0, bd = 1e9, R = Math.PI / 180;
    C.forEach(function (c, i) {
      var d = Math.acos(Math.min(1, Math.sin(lat * R) * Math.sin(c[2] * R) + Math.cos(lat * R) * Math.cos(c[2] * R) * Math.cos((lon - c[3]) * R)));
      if (d < bd) { bd = d; best = i; }
    });
    return best;
  }
  function unesc(s) { return s.replace(/\\n/g, ' ').replace(/\\([,;\\])/g, '$1'); }
  function show(i, why) {
    var c = C[i], path = '/ics/' + c[1] + '.ics', https = 'https://' + HOST + path, webcal = 'webcal://' + HOST + path;
    sel.value = String(i);
    document.getElementById('feed-name').textContent = 'Occultations from ' + c[0];
    document.getElementById('feed-why').textContent = why || '';
    document.getElementById('feed-count').textContent = c[4] + ' events in the feed now.';
    document.getElementById('feed-sub').href = webcal;
    document.getElementById('feed-google').href = 'https://calendar.google.com/calendar/render?cid=' + encodeURIComponent(webcal);
    if (/Android/i.test(navigator.userAgent)) {   // Chrome on Android does nothing with a webcal: link; its calendar is Google's
      document.getElementById('feed-sub').hidden = true;
      document.getElementById('feed-google').classList.add('btn-primary');
    }
    document.getElementById('feed-url').textContent = https;
    document.getElementById('feed-copy').onclick = function () {
      var b = this; (navigator.clipboard ? navigator.clipboard.writeText(https) : Promise.reject()).then(function () { b.textContent = 'Copied'; setTimeout(function () { b.textContent = 'Copy link'; }, 1500); }, function () {});
    };
    out.hidden = false;
    var list = document.getElementById('feed-next');
    list.innerHTML = '';
    fetch(path).then(function (r) { return r.text(); }).then(function (txt) {
      var now = Date.now(), items = [];
      txt.replace(/\r\n[ \t]/g, '').split('BEGIN:VEVENT').slice(1).forEach(function (b) {
        var s = /\nDTSTART:(\d{4})(\d\d)(\d\d)T(\d\d)(\d\d)(\d\d)Z/.exec(b), t = /\nSUMMARY:(.*)/.exec(b);
        if (!s || !t) return;
        var ms = Date.UTC(+s[1], +s[2] - 1, +s[3], +s[4], +s[5], +s[6]);
        if (ms > now - 3600e3) items.push([ms, unesc(t[1].trim())]);
      });
      items.slice(0, 6).forEach(function (it) {
        var li = document.createElement('li'), tm = document.createElement('time'), sp = document.createElement('span');
        tm.textContent = new Date(it[0]).toLocaleString(undefined, { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
        sp.textContent = it[1]; li.appendChild(tm); li.appendChild(sp); list.appendChild(li);
      });
      if (!items.length) list.innerHTML = '<li><span>Nothing coming up in this feed yet.</span></li>';
    }).catch(function () {});
  }
  sel.addEventListener('change', function () { if (sel.value !== '') show(+sel.value); });
  var geo = document.getElementById('feed-geo'); if (!navigator.geolocation) geo.hidden = true;
  geo.addEventListener('click', function () {
    geo.disabled = true; geo.textContent = 'Locating…';
    navigator.geolocation.getCurrentPosition(function (p) { geo.disabled = false; geo.textContent = 'Use my location';
      show(nearest(p.coords.latitude, p.coords.longitude), 'The nearest city we compute for.'); },
      function () { geo.disabled = false; geo.textContent = 'Location unavailable'; });
  });
  var saved = null; try { saved = JSON.parse(localStorage.getItem('occult-loc')); } catch (e) {}
  if (saved && isFinite(saved.lat)) show(nearest(saved.lat, saved.lon), 'Nearest to the place you picked on this site.');
})();
"""


def write_page(rows):
    cities = [[n, s, lat, lon, k] for n, s, lat, lon, k in rows]
    opts = "".join(f'<option value="{i}">{esc(c[0])}</option>' for i, c in enumerate(cities))
    cities_json = json.dumps(cities, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    desc = ("Subscribe to the occultations you can see from your city: the Moon hiding planets and stars, and the asteroid "
            "shadows whose paths cross your town.")
    body = f"""
<main class="wrap" data-x="">
  <h1>Occultations in your calendar</h1>
  <p class="sub">One feed per city. Your calendar app keeps it up to date.</p>
  <div class="feed-card">
    <label for="feed-city">City</label>
    <select id="feed-city"><option value="">Choose a city…</option>{opts}</select>
    <div class="feed-row"><button class="btn" id="feed-geo" type="button">Use my location</button></div>
    <div id="feed-out" hidden>
      <p class="feed-city" id="feed-name"></p>
      <p class="feed-count"><span id="feed-count"></span> <span id="feed-why"></span></p>
      <div class="feed-row">
        <a class="btn btn-primary" id="feed-sub" href="#">Subscribe</a>
        <a class="btn" id="feed-google" href="#" target="_blank" rel="noopener">Add to Google Calendar</a>
        <button class="btn" id="feed-copy" type="button">Copy link</button>
      </div>
      <p class="feed-url" id="feed-url"></p>
      <ol class="feed-next" id="feed-next" aria-label="Next in this feed"></ol>
    </div>
  </div>
  <h2>What's in a feed</h2>
  <p class="method">Every lunar occultation on this site's list that the city can see — planets and bright stars, with a reminder
  {ALARM_MIN} minutes before — and every occultation of a star bright enough for binoculars over the next {STAR_MONTHS} months,
  with the Moon at least 5° up and the sky dark enough. Each entry gives the disappearance and reappearance times, how high the
  Moon is and where, and a link to the full page. Asteroid shadows are in too, when the path crosses your town or comes within
  its margin of error and the star is at least {AST_ALT_MIN:.0f}° up in a dark sky — for a town in India, two or three a month,
  about half of them inside the path. Each says how far you are from the centre line and links the finder chart and the path
  to drive to. When the path passes to one side of you, the reminder comes early enough to act on — {ALARM_MIN} minutes if you
  can watch from where you are, and for a drive to the edge, that plus the packing and the driving, up to {AST_ALARM_MAX // 60} hours. Jupiter's and
  Saturn's moons are not included: they have several events a night. Times are computed from the JPL DE431 ephemeris, as on the
  rest of the site.</p>
  <h2>Adding it</h2>
  <p class="method"><b>iPhone, iPad, Mac:</b> tap Subscribe. <b>Google Calendar and Android:</b> use “Add to Google Calendar” on a
  computer; the calendar then appears on your phone. <b>Outlook:</b> Add calendar → Subscribe from web, and paste the link.
  Calendar apps check a subscribed feed every few hours to a day, and the feed changes whenever the site is updated.
  It is a subscription, not an account: nothing about you is sent anywhere.</p>
  <script type="application/json" id="feed-cities">{cities_json}</script>
</main>
{FOOTER}
<script>{CAL_JS}</script>
</body>
</html>
"""
    page = head(f"Calendar feeds · {SITE_NAME}", desc, "/calendar", extra=f"<style>{CAL_CSS}</style>", og="calendar").replace("<body>", f'<body data-host="{HOST}">', 1)
    (OUT / "calendar.html").write_text(page + body)


# ------------------------------------------------------------------------------------------ build

def build_all(seed, cities, workers=None):
    now = datetime.now(timezone.utc)
    places = feed_cities(cities, world_rank(seed))
    slugs = city_slugs(places)
    FEED_DIR.mkdir(parents=True, exist_ok=True)
    jobs = [(n, p["lat"], p["lon"], p["tz"], slugs[n], p["aliases"]) for n, p in places.items()]
    rows, written, total = [], 0, 0
    with ProcessPoolExecutor(max_workers=workers or os.cpu_count(), initializer=_init, initargs=(now.timestamp(),)) as ex:
        for name, slug, events in ex.map(_city_events, jobs, chunksize=4):
            v = places[name]
            text = ics_calendar(name, v["tz"], events)
            p, raw = FEED_DIR / f"{slug}.ics", text.encode("utf-8")
            if not p.exists() or p.read_bytes() != raw:      # bytes: read_text would turn the CRLFs into \n and never match
                p.write_bytes(raw)
                written += 1
            rows.append((name, slug, v["lat"], v["lon"], sum(1 for e in events if e["end"] >= now)))
            total += len(events)
    keep = {f"{s}.ics" for s in slugs.values()}
    for p in FEED_DIR.glob("*.ics"):
        if p.name not in keep:
            p.unlink()
    write_page(rows)
    print(f"wrote site/ics/: {len(rows)} feeds ({written} changed), {total} events; site/calendar.html")
    return rows


if __name__ == "__main__":
    import time
    t = time.time()
    seed = json.loads((ROOT / "seed.json").read_text())
    build_all(seed, collect_cities(seed))
    print(f"{time.time() - t:.0f} s")
