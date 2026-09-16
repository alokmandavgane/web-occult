#!/usr/bin/env python3
"""Open Graph images, one per kind of page: site/og/<name>.png, 1200×630, in the site's night palette.

Only link previews (WhatsApp, X, Slack, search) fetch these — no page loads them — so they cost the site nothing.
Drawn with Pillow from the Mac's system fonts (Iowan Old Style, Avenir Next). When Pillow or a font is missing the
committed PNGs are left as they are. `build_pages.head(..., og=key)` links them with a content-hash `?v=`.

    .venv/bin/python scripts/build_og.py      (also run by build_pages.py)
"""

from pathlib import Path

from build_pages import OG, OUT

W, H, S = 1200, 630, 2                  # drawn at 2x, then downsampled: smooth edges without an antialiasing API
BG = (12, 15, 23)
INK = (236, 232, 221)
MUTED = (154, 160, 174)
LIT = (239, 231, 206)
DARK = (30, 36, 52)
ACCENT = (169, 193, 240)
COL = {"home": ACCENT, "occ": (242, 181, 74), "ms": (108, 199, 224), "ast": (240, 138, 163), "jupiter": (195, 177, 245),
       "saturn": (111, 211, 148), "calendar": ACCENT}
TEXT = {   # kicker, title, subtitle
    "home": ("Lunar occultations, computed", "What passes in front of what — and when you can see it",
             "Maps and times for your city, from JPL ephemerides"),
    "occ": ("Lunar occultation", "When the Moon hides a planet or a bright star",
            "Where on Earth it can be seen, and the times for your city"),
    "ms": ("The Moon and the stars", "Every star the Moon hides this month",
           "Disappearance and reappearance times for where you are"),
    "ast": ("Asteroid occultations", "A star blinks out as an asteroid's shadow crosses India",
            "A map of every path, and how close it passes you"),
    "jupiter": ("Jupiter's moons", "Eclipses, transits and shadows, night by night",
                "Io, Europa, Ganymede, Callisto — and the Great Red Spot"),
    "saturn": ("Saturn's moons", "Titan and company hide, transit and cast shadows",
               "Night by night, for where you are"),
    "calendar": ("Calendar feeds", "Occultations in your calendar",
                 "One subscription per city: planets, bright stars and binocular stars"),
}
SERIF = "/System/Library/Fonts/Supplemental/Iowan Old Style.ttc"
SANS = "/System/Library/Fonts/Avenir Next.ttc"


def _face(path, style, size):
    from PIL import ImageFont
    for i in range(32):
        try:
            f = ImageFont.truetype(path, size, index=i)
        except OSError:
            break
        if f.getname()[1] == style:
            return f
    raise LookupError(f"{style} not in {path}")


def _wrap(draw, text, font, width):
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= width or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    return lines + [cur]


def _glow(img, cx, cy, r, color, alpha):
    from PIL import Image, ImageDraw, ImageFilter
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse([cx - r, cy - r, cx + r, cy + r], fill=color + (alpha,))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(r * 0.45)))


def _moon(img, cx, cy, r, cut_dx, cut_dy, craters=True):
    """A dark disc with a lit crescent: the lit disc minus an offset circle."""
    from PIL import Image, ImageChops, ImageDraw
    d = ImageDraw.Draw(img)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=DARK)
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    cut = Image.new("L", img.size, 0)
    ImageDraw.Draw(cut).ellipse([cx + cut_dx - r, cy + cut_dy - r, cx + cut_dx + r, cy + cut_dy + r], fill=255)
    lit = Image.new("RGBA", img.size, LIT + (255,))
    img.paste(lit, (0, 0), ImageChops.subtract(mask, cut))
    if craters:   # a hint of the face, as on the event pages
        rim = ImageDraw.Draw(img)
        for fx, fy, fr in ((0.78, 0.12, 0.08), (0.55, 0.66, 0.09), (0.12, 0.88, 0.05), (0.84, -0.32, 0.05), (0.68, 0.38, 0.04)):
            x, y, rr = cx + fx * r, cy + fy * r, fr * r
            rim.ellipse([x - rr, y - rr, x + rr, y + rr], outline=(150, 138, 108), width=max(2, int(r * 0.012)))


def _globe(img, cx, cy, rx, ry, base, band, bands, spot=None):
    """An oblate planet with cloud bands clipped to its disc: bands = (top, height) as fractions of rx."""
    from PIL import Image, ImageDraw
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rectangle([cx - rx, cy - ry, cx + rx, cy + ry], fill=base)
    for fy, fh in bands:
        d.rectangle([cx - rx, cy + fy * rx, cx + rx, cy + (fy + fh) * rx], fill=band)
    if spot:
        sx, sy, col = spot
        d.ellipse([cx + sx * rx - 0.14 * rx, cy + sy * rx - 0.085 * rx, cx + sx * rx + 0.14 * rx, cy + sy * rx + 0.085 * rx], fill=col)
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=255)
    img.paste(layer, (0, 0), mask)


def _mark(img, x, y, size, lit=LIT):
    """The site's mark (build_pages.MARK_SVG, a 32-unit box): a crescent, and a star just off its dark limb."""
    from PIL import Image, ImageChops, ImageDraw
    u = size / 32
    m = Image.new("L", img.size, 0)
    ImageDraw.Draw(m).ellipse([x + 4 * u, y + 7 * u, x + 25 * u, y + 28 * u], fill=255)
    cut = Image.new("L", img.size, 0)
    ImageDraw.Draw(cut).ellipse([x + 10 * u, y + 4 * u, x + 29 * u, y + 23 * u], fill=255)
    img.paste(Image.new("RGBA", img.size, lit + (255,)), (0, 0), ImageChops.subtract(m, cut))
    ImageDraw.Draw(img).ellipse([x + 23.2 * u, y + 5.2 * u, x + 27.8 * u, y + 9.8 * u], fill=COL["occ"])


def write_icons():
    """App icons for the web manifest and iOS: the mark on the night background."""
    from PIL import Image
    out = OUT / "icons"
    out.mkdir(parents=True, exist_ok=True)
    for name, px, inset in (("icon-192.png", 192, 0.12), ("icon-512.png", 512, 0.12),
                            ("icon-maskable-512.png", 512, 0.24), ("apple-touch-icon.png", 180, 0.14)):
        n = px * 4
        img = Image.new("RGBA", (n, n), BG + (255,))
        _glow(img, int(n * 0.62), int(n * 0.36), int(n * 0.42), ACCENT, 34)
        _mark(img, n * inset, n * inset, n * (1 - 2 * inset))
        img.convert("RGB").resize((px, px), Image.LANCZOS).save(out / name, optimize=True)


def _star(d, x, y, r, color):
    d.polygon([(x, y - r), (x + r * 0.22, y - r * 0.22), (x + r, y), (x + r * 0.22, y + r * 0.22),
               (x, y + r), (x - r * 0.22, y + r * 0.22), (x - r, y), (x - r * 0.22, y - r * 0.22)], fill=color)


def _art(key, img):
    from PIL import ImageDraw
    d = ImageDraw.Draw(img)
    c = COL[key]
    cx, cy = 925 * S, 322 * S
    if key in ("home", "occ", "ms", "calendar"):
        r = {"home": 190, "occ": 190, "ms": 165, "calendar": 122}[key] * S
        mx, my = (cx, cy) if key != "calendar" else (cx + 40 * S, cy - 118 * S)
        _glow(img, mx, my, int(r * 1.25), ACCENT, 38)
        # the target just off the dark limb (upper left), about to be covered
        tx, ty = mx - r * 0.83, my - r * 0.73
        if key == "occ":
            _glow(img, int(tx), int(ty), 40 * S, c, 150)
            d.ellipse([tx - 17 * S, ty - 17 * S, tx + 17 * S, ty + 17 * S], fill=c)
        _moon(img, mx, my, r, -0.42 * r, -0.30 * r)
        d = ImageDraw.Draw(img)
        if key in ("home", "ms"):
            _glow(img, int(tx), int(ty), 26 * S, c, 140)
            d = ImageDraw.Draw(img)
            _star(d, tx, ty, 18 * S, c)
        if key == "ms":
            for sx, sy, sr in ((1.35, -0.2, 7), (1.15, 0.72, 5), (-1.3, 0.55, 6), (0.55, -1.2, 5), (-0.35, 1.25, 4), (1.5, 0.35, 4)):
                _star(d, mx + sx * r, my + sy * r, sr * S, INK)
        if key == "calendar":
            gx, gy, cell, gap = 715 * S, 395 * S, 50 * S, 10 * S
            for row in range(3):
                for col in range(7):
                    x0, y0 = gx + col * (cell + gap), gy + row * (cell + gap)
                    on = (row, col) in ((0, 2), (1, 5), (2, 1))
                    d.rounded_rectangle([x0, y0, x0 + cell, y0 + cell], radius=9 * S, outline=c if on else (58, 66, 86),
                                        width=3 * S if on else 2 * S, fill=(c[0] // 5, c[1] // 5, c[2] // 5) if on else None)
                    if on:
                        d.ellipse([x0 + cell / 2 - 7 * S, y0 + cell / 2 - 7 * S, x0 + cell / 2 + 7 * S, y0 + cell / 2 + 7 * S], fill=c)
    elif key == "ast":
        # the shadow's narrow band across a dark Earth, a lumpy asteroid and the star it hides
        from PIL import Image
        band = Image.new("RGBA", img.size, (0, 0, 0, 0))
        bd = ImageDraw.Draw(band)
        bd.polygon([(640 * S, 520 * S), (1200 * S, 350 * S), (1200 * S, 410 * S), (640 * S, 580 * S)], fill=c + (60,))
        bd.line([(640 * S, 520 * S), (1200 * S, 350 * S)], fill=c + (200,), width=4 * S)
        bd.line([(640 * S, 580 * S), (1200 * S, 410 * S)], fill=c + (200,), width=4 * S)
        img.alpha_composite(band)
        d = ImageDraw.Draw(img)
        sx, sy = 1015 * S, 150 * S
        _glow(img, sx, sy, 70 * S, INK, 120)
        d = ImageDraw.Draw(img)
        _star(d, sx, sy, 26 * S, INK)
        ax, ay, ar = 905 * S, 250 * S, 95 * S
        pts = []
        for j in range(24):
            th = 2 * 3.14159265 * j / 24
            rr = ar * (1 + 0.16 * __import__("math").sin(3 * th + 0.7) + 0.09 * __import__("math").cos(5 * th))
            pts.append((ax + rr * __import__("math").cos(th) * 1.25, ay + rr * __import__("math").sin(th)))
        d.polygon(pts, fill=DARK, outline=(92, 98, 116))
        for fx, fy, fr in ((-0.35, -0.2, 0.16), (0.3, 0.25, 0.12), (0.55, -0.35, 0.08)):
            x, y, rr = ax + fx * ar, ay + fy * ar, fr * ar
            d.ellipse([x - rr, y - rr, x + rr, y + rr], outline=(70, 76, 94), width=3 * S)
    elif key == "jupiter":
        r, cx = 108 * S, 985 * S
        _glow(img, cx, cy, int(r * 1.5), c, 40)
        ImageDraw.Draw(img).line([700 * S, cy, 1190 * S, cy], fill=(40, 48, 66), width=2 * S)
        _globe(img, cx, cy, r, r * 0.94, (214, 186, 140), (168, 124, 82), ((-0.42, 0.14), (-0.08, 0.2), (0.3, 0.16)),
               spot=(0.2, 0.42, (194, 80, 47)))
        d = ImageDraw.Draw(img)
        for x, rr, col in ((-265, 10, (245, 158, 11)), (-210, 9, (96, 165, 250)), (-150, 13, (167, 139, 250)), (160, 12, (52, 211, 153))):
            d.ellipse([cx + x * S - rr * S, cy - rr * S, cx + x * S + rr * S, cy + rr * S], fill=col)
    elif key == "saturn":
        r = 92 * S
        _glow(img, cx, cy, int(r * 1.8), c, 36)
        d = ImageDraw.Draw(img)
        ro, ri, tilt = 250 * S, 175 * S, 0.2
        ring = (201, 178, 122)
        d.arc([cx - ro, cy - ro * tilt, cx + ro, cy + ro * tilt], 180, 360, fill=ring, width=16 * S)       # far half
        _globe(img, cx, cy, r, r * 0.9, (227, 207, 154), (196, 170, 112), ((-0.35, 0.15),))
        d = ImageDraw.Draw(img)
        d.arc([cx - ro, cy - ro * tilt, cx + ro, cy + ro * tilt], 0, 180, fill=ring, width=16 * S)         # near half
        d.ellipse([cx - 205 * S - 13 * S, cy - 120 * S - 13 * S, cx - 205 * S + 13 * S, cy - 120 * S + 13 * S], fill=(249, 115, 22))   # Titan
        for x, y, rr in ((-150, 125, 5), (170, -115, 6), (205, 120, 5)):
            d.ellipse([cx + x * S - rr * S, cy + y * S - rr * S, cx + x * S + rr * S, cy + y * S + rr * S], fill=INK)


def draw(key):
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (W * S, H * S), BG + (255,))
    _glow(img, 1150 * S, -80 * S, 520 * S, ACCENT, 26)
    _art(key, img)
    d = ImageDraw.Draw(img)
    c = COL[key]
    kicker, title, sub = TEXT[key]
    x = 78 * S
    d.rounded_rectangle([x, 92 * S, x + 58 * S, 97 * S], radius=3 * S, fill=c)
    kf = _face(SANS, "Demi Bold", 25 * S)
    kx = x
    for ch in kicker.upper():                          # letter-spaced, like the site's section labels
        d.text((kx, 122 * S), ch, font=kf, fill=c)
        kx += d.textlength(ch, font=kf) + 2.6 * S
    sf = _face(SANS, "Regular", 30 * S)
    sub_lines = _wrap(d, sub, sf, 560 * S)
    for size in (64, 58, 52, 46):                      # the largest title that leaves room above the address line
        tf = _face(SERIF, "Bold", size * S)
        lines = _wrap(d, title, tf, 590 * S)
        if 172 + len(lines) * size * 1.16 + 18 + len(sub_lines) * 42 <= 520:
            break
    y = 172 * S
    for line in lines:
        d.text((x, y), line, font=tf, fill=INK)
        y += int(size * 1.16) * S
    y += 18 * S
    for line in sub_lines:
        d.text((x, y), line, font=sf, fill=MUTED)
        y += 42 * S
    # the site's mark and address
    bx, by = x, 548 * S
    _mark(img, bx, by - 4 * S, 40 * S)
    d.text((bx + 50 * S, by - 2 * S), "occult.alokm.com", font=_face(SANS, "Demi Bold", 27 * S), fill=MUTED)
    return img.convert("RGB").resize((W, H), Image.LANCZOS)


def write_all():
    try:
        import PIL  # noqa: F401
        for p in (SERIF, SANS):
            if not Path(p).exists():
                raise FileNotFoundError(p)
    except (ImportError, FileNotFoundError) as e:
        print(f"og images: skipped ({e}); keeping the committed PNGs")
        return
    (OUT / "og").mkdir(parents=True, exist_ok=True)
    for key, (name, _alt) in OG.items():
        p = OUT / "og" / name
        draw(key).save(p, optimize=True)
    write_icons()
    print(f"wrote site/og/: {len(OG)} images; site/icons/: 4 app icons")


if __name__ == "__main__":
    write_all()
