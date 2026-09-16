"""The built site. When the Moon rises or sets during an occultation a city sees only one half of it, and the event
page must say which; and the sitemap must list every asteroid event, since they all live at one URL with a query and a
crawler has no way to guess the ids. Data files only — no DE431 needed."""
import glob
import json
import os
import re
import sys
import zoneinfo

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import build_pages as bp  # noqa: E402


def _row(slug, name):
    d = json.load(open(os.path.join(HERE, "..", "data", f"{slug}.json")))
    return d, next(c for c in d["cities"] if c["name"] == name)


def test_moon_rising_leaves_only_the_reappearance():
    d, c = _row("jupiter-2026-10-06", "Mexico City, MX")      # the Moon rises while Jupiter is behind it
    seen, at = bp.horizon_split(d, c)
    assert seen == "rises" and at["D2"][0] < 0 < at["R1"][0]
    row = bp.city_row(c, d, zoneinfo.ZoneInfo("America/Mexico_City"))
    assert "Moon not yet up" in row and "at reappearance" in row and "below the horizon" not in row
    assert bp.verdict_text(c, d).startswith("reappearance only")


def test_moon_setting_leaves_only_the_disappearance():
    d, c = _row("mars-2026-10-05", "Beijing, CN")             # the Moon sets before Mars comes back
    seen, at = bp.horizon_split(d, c)
    assert seen == "sets" and at["D2"][0] > 0 > at["R1"][0]
    row = bp.city_row(c, d, zoneinfo.ZoneInfo("Asia/Shanghai"))
    assert "Moon has set" in row and "at reappearance" not in row


def test_whole_occultation_is_unchanged():
    d, c = _row("venus-2026-09-14", "Mumbai")
    seen, at = bp.horizon_split(d, c)
    assert seen == "both"
    row = bp.city_row(c, d, zoneinfo.ZoneInfo("Asia/Kolkata"))
    assert "not yet up" not in row and "has set" not in row


def test_element_azimuth_matches_the_generator():
    """The element geometry's Moon azimuth against the generator's Skyfield value at disappearance."""
    d, c = _row("venus-2026-09-14", "Mumbai")
    _, at = bp.horizon_split(d, c)
    assert abs(at["D2"][1] - c["moon_az"]) < 0.3 and abs(at["D2"][0] - c["moon_alt"]) < 0.2


def test_sitemap_lists_every_asteroid_event():
    """One page draws every asteroid occultation, chosen by `?e=<id>`, so the sitemap is the only way a crawler ever
    reaches one. Every event in every month file must be there, nothing stale must be left over, and the page itself
    must canonicalise to the same URL — the id alone, without whatever spot the reader last pinned."""
    site = os.path.join(HERE, "..", "site")
    path = os.path.join(site, "sitemap.xml")
    if not os.path.exists(path):
        import pytest
        pytest.skip("site not built")
    xml = open(path).read()
    listed = set(re.findall(r"<loc>[^<]*/asteroid\?e=([^<]+)</loc>", xml))
    want = {e["id"] for f in sorted(glob.glob(os.path.join(HERE, "..", "data", "asteroids-*.json")))
            for e in json.load(open(f))["events"]}
    assert listed == want, (sorted(want - listed)[:5], sorted(listed - want)[:5])
    assert "&" not in xml.replace("&amp;", ""), "a bare ampersand would make the sitemap invalid XML"
    page = open(os.path.join(site, "asteroid.html")).read()
    assert "'?e=' + encodeURIComponent(id)" in page and "rel=\"canonical\"" in page


def test_service_worker_is_wired_up():
    """The site is read in fields with no signal, so every page registers a worker that keeps what it fetched. What can
    go wrong quietly: a precached URL that 404s (a stale ?v= hash), a page that never registers the worker, or a worker
    served from cache so a fix can never reach anyone."""
    site = os.path.join(HERE, "..", "site")
    sw = os.path.join(site, "sw.js")
    if not os.path.exists(sw):
        import pytest
        pytest.skip("site not built")
    js = open(sw).read()
    assert "__VER__" not in js and "__CORE__" not in js, "the worker's placeholders were left unfilled"
    core = json.loads(re.search(r"CORE = (\[[^\]]*\])", js).group(1))
    assert "/" in core and "/asteroid" in core
    for u in core:
        if u in ("/", "/asteroid"):
            continue                                   # served without their .html by Cloudflare, not present as paths
        f = os.path.join(site, u.split("?")[0].lstrip("/"))
        assert os.path.exists(f), u
        assert u in open(os.path.join(site, "asteroid.html")).read(), f"{u} is not the URL the page itself asks for"
    for page in ("index.html", "asteroid.html", "calendar.html"):
        assert "navigator.serviceWorker.register('/sw.js')" in open(os.path.join(site, page)).read(), page
    headers = open(os.path.join(site, "_headers")).read()
    assert "/sw.js\n  Cache-Control: no-cache" in headers, "a cached worker cannot be replaced"
