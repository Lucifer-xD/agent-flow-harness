"""Draw the AFH mark as PNG app icons (the phone apps and the /m/ pages need bitmaps).

python scripts/make-icons.py  ->  the Android app's launcher icons and splash screens (mobile/android),
the iPhone app's (mobile/resources/ios, copied in by the iOS build) and relay/static/m/icon-*.png.
"""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
BG = (10, 8, 7)
# the three strands of website/assets/mark.svg (viewBox 240x140): curve, gradient, end dots
STRANDS = [
    (((46, 112), (108, 112), (116, 66), (146, 66)), ((146, 66), (172, 66), (170, 112), (194, 112)), ("#ff3d8a", "#e0169a")),
    (((46, 70), (92, 70), (98, 58), (120, 60)), ((120, 60), (150, 63), (152, 82), (194, 70)), ("#ff7747", "#ff4a68")),
    (((46, 28), (104, 28), (108, 74), (134, 74)), ((134, 74), (160, 74), (164, 28), (194, 28)), ("#ffb11f", "#ff7a3d")),
]
DOTS = [((46, 112), "#ff3d8a"), ((194, 112), "#e0169a"), ((46, 70), "#ff7747"), ((194, 70), "#ff4a68"), ((46, 28), "#ffb11f"), ((194, 28), "#ff7a3d")]


def rgb(h: str) -> tuple[int, int, int]:
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def bezier(p0, p1, p2, p3, n=400):
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        yield (u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
               u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1])


def draw(size: int, *, background: bool, mark_width: float) -> Image.Image:
    s = size * 4  # supersample, then shrink for smooth edges
    img = Image.new("RGBA", (s, s), (*BG, 255) if background else (0, 0, 0, 0))
    scale = s * mark_width / 240
    ox, oy = (s - 240 * scale) / 2, (s - 140 * scale) / 2
    at = lambda p: (ox + p[0] * scale, oy + p[1] * scale)
    r = 7 * scale
    for a, b, (c0, c1) in STRANDS:
        mask = Image.new("L", (s, s), 0)
        md = ImageDraw.Draw(mask)
        for seg in (a, b):
            for x, y in map(at, bezier(*seg)):
                md.ellipse((x - r, y - r, x + r, y + r), fill=255)
        x0, x1 = at((46, 0))[0], at((194, 0))[0]
        grad = Image.new("RGBA", (s, s))
        gd = ImageDraw.Draw(grad)
        g0, g1 = rgb(c0), rgb(c1)
        for x in range(s):
            t = min(1, max(0, (x - x0) / (x1 - x0)))
            gd.line([(x, 0), (x, s)], fill=tuple(round(g0[i] + (g1[i] - g0[i]) * t) for i in range(3)) + (255,))
        img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    for p, c in DOTS:
        x, y = at(p)
        R = 15 * scale
        d.ellipse((x - R, y - R, x + R, y + R), fill=rgb(c))
    return img.resize((size, size), Image.LANCZOS)


def splash(w: int, h: int) -> Image.Image:
    img = Image.new("RGBA", (w, h), (*BG, 255))
    n = int(min(w, h) * 0.42)
    img.alpha_composite(draw(n, background=False, mark_width=0.9), ((w - n) // 2, (h - n) // 2))
    return img


def round_icon(size: int) -> Image.Image:
    img = draw(size, background=True, mark_width=0.66)
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
    img.putalpha(mask.resize((size, size), Image.LANCZOS))
    return img


def main() -> None:
    android = ROOT / "mobile" / "android" / "app" / "src" / "main" / "res"
    if android.is_dir():
        for dpi, scale in {"mdpi": 1, "hdpi": 1.5, "xhdpi": 2, "xxhdpi": 3, "xxxhdpi": 4}.items():
            d = android / f"mipmap-{dpi}"
            d.mkdir(exist_ok=True)
            draw(round(48 * scale), background=True, mark_width=0.74).save(d / "ic_launcher.png")
            round_icon(round(48 * scale)).save(d / "ic_launcher_round.png")
            # adaptive icons show the middle 66% of a 108dp square, cropped to the phone's shape
            draw(round(108 * scale), background=False, mark_width=0.48).save(d / "ic_launcher_foreground.png")
        for f in android.glob("drawable*/splash.png"):
            w, h = Image.open(f).size
            splash(w, h).convert("RGB").save(f)
        (android / "values" / "ic_launcher_background.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n    <color name="ic_launcher_background">#0A0807</color>\n</resources>\n', encoding="utf-8")
    ios = ROOT / "mobile" / "resources" / "ios"
    ios.mkdir(parents=True, exist_ok=True)
    draw(1024, background=True, mark_width=0.74).convert("RGB").save(ios / "AppIcon-512@2x.png")  # no alpha: Apple rejects it
    big = splash(2732, 2732).convert("RGB")
    for name in ("splash-2732x2732.png", "splash-2732x2732-1.png", "splash-2732x2732-2.png"):
        big.save(ios / name)
    web = ROOT / "relay" / "static" / "m"
    for n in (180, 192, 512):
        draw(n, background=True, mark_width=0.74).save(web / f"icon-{n}.png")
    print("icons written")


if __name__ == "__main__":
    main()
