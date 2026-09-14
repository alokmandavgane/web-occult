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
Jupiter's and Saturn's moon events are left out: several a night is not a calendar anyone keeps.

Feeds are static, as fresh as the last deploy: events from PAST_DAYS ago onward. DTSTAMP comes from the data,
not the clock, so a rebuild rewrites a feed only when its events change.

    .venv/bin/python scripts/build_feeds.py      (also run by build_pages.py)
"""

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
ALARM_MIN = 30          # a reminder before the hand-picked events only


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
         f"X-WR-CALDESC:{ics_text(f'Lunar occultations you can see from {name}, computed by {HOST}')}",
         "REFRESH-INTERVAL;VALUE=DURATION:PT12H", "X-PUBLISHED-TTL:PT12H"]
    if tzname:
        L.append(f"X-WR-TIMEZONE:{tzname}")
    for ev in events:
        L += ["BEGIN:VEVENT", f"UID:{ev['uid']}", f"DTSTAMP:{stamp(ev['stamp'])}", f"DTSTART:{stamp(ev['start'])}",
              f"DTEND:{stamp(ev['end'])}", f"SUMMARY:{ics_text(ev['summary'])}", f"DESCRIPTION:{ics_text(ev['description'])}",
              f"URL:{ev['url']}", "TRANSP:TRANSPARENT"]
        if ev.get("alarm"):
            L += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{ics_text(ev['summary'])}", f"TRIGGER:-PT{ALARM_MIN}M", "END:VALARM"]
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
                       "rings": [np.asarray(r, dtype=float) for r in d["maps"]["world"]["region"]]})
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
    _W.update(now=now, events=events, months=months)


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
            con = {k: parse(v) for k, v in row["contacts"].items()}
            alt, az, sun, exact = row["moon_alt"], row["moon_az"], row["sun_alt"], True
            url = f"{SITE}/{e['slug']}?city={quote(hit)}"
        else:
            if not _near_region(e["rings"], lat, lon):
                continue
            r = solve_from_elements(e["elements"], lat, lon)
            if not r["contacts"]:
                continue
            geom = element_geometry(e["elements"], lat, lon)
            gs = {k: geom(m) for k, m in r["contacts_min"].items()}
            if max(g["alt_m"] for g in gs.values()) <= 0:
                continue
            con = {k: parse(v) for k, v in r["contacts"].items()}
            ref = next(k for k in ("D2", "D1", "R1", "R2") if k in gs)
            alt, az, sun, exact = float(gs[ref]["alt_m"]), None, float(gs[ref]["alt_s"]), False
            url = f"{SITE}/{e['slug']}?lat={lat:.4f}&lon={lon:.4f}"
        start, end = min(con.values()), max(con.values())
        if end < cutoff:
            continue
        d, rr = con.get("D2", con.get("D1")), con.get("R1", con.get("R2"))
        parts = ([f"disappears at {hms(d)}"] if d else []) + ([f"reappears at {hms(rr)}"] if rr else [])
        desc = (f"{e['target']} {' and '.join(parts)} {zabbr(start)}, seen from {name}.\n"
                f"The Moon is {alt:.0f}° up{f' in the {compass(az)}' if az is not None else ''} · {sky_text(sun)}.\n"
                + ("Times against the real lunar limb.\n" if exact else "Times for the Moon's mean limb, ±2 s.\n")
                + f"Map, timings and the view at the Moon's edge: {url}")
        out.append({"uid": f"occ-{e['slug']}-{slug}@{HOST}", "stamp": e["generated"], "start": start,
                    "end": end if end > start else start + timedelta(minutes=1),
                    "summary": f"The Moon occults {e['target']}", "description": desc, "url": url, "alarm": True})

    verb = {"D": "disappears", "R": "reappears"}
    seen_star = {}   # uid -> (vmag, index): the month star lists can carry one star twice under one name
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
            if rec["uid"] in seen_star:                      # same name, same minute: one calendar entry, the brighter
                v0, i0 = seen_star[rec["uid"]]
                if ev["vmag"] < v0:
                    out[i0], seen_star[rec["uid"]] = rec, (ev["vmag"], i0)
                continue
            seen_star[rec["uid"]] = (ev["vmag"], len(out))
            out.append(rec)
    out.sort(key=lambda x: (x["start"], x["uid"]))
    return name, slug, out


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
    a.btn { display: inline-block; text-decoration: none; }
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
    desc = "Subscribe to the lunar occultations you can see from your city: planets, bright stars and stars within reach of binoculars."
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
  Moon is and where, and a link to the full page. Jupiter's and Saturn's moons are not included: they have several events a
  night. Times are computed from the JPL DE431 ephemeris, as on the rest of the site.</p>
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
    page = head(f"Calendar feeds · {SITE_NAME}", desc, "/calendar", extra=f"<style>{CAL_CSS}</style>").replace("<body>", f'<body data-host="{HOST}">', 1)
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
