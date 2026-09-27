"""Generate the Power BI page background: a faint dot map of every US county (one dot per county, placed at its
centre with an Albers projection) on warm off-white, with soft colour glows behind the title and the corner.
Written to dashboard/assets/page_background.png at 2x the 1280x720 page size so it stays sharp.
"""
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dashboard" / "assets" / "page_background.png"
W, H, K = 1280, 720, 2
BASE = (245, 246, 241)
EMERALD, SUN, ROSE = (14, 159, 110), (245, 183, 0), (214, 63, 108)


def albers(lon, lat, lon0=-96, lat0=37.5, p1=29.5, p2=45.5):
    lon, lat, lon0, lat0, p1, p2 = map(np.radians, (lon, lat, lon0, lat0, p1, p2))
    n = (np.sin(p1) + np.sin(p2)) / 2
    c = np.cos(p1) ** 2 + 2 * n * np.sin(p1)
    rho = np.sqrt(c - 2 * n * np.sin(lat)) / n
    rho0 = np.sqrt(c - 2 * n * np.sin(lat0)) / n
    return rho * np.sin(n * (lon - lon0)), rho0 - rho * np.cos(n * (lon - lon0))


def county_points():
    geo = json.loads((ROOT / "Data" / "raw" / "geojson-counties-fips.json").read_text())
    pts = []
    for f in geo["features"]:
        if f["id"][:2] in ("02", "15", "72"):
            continue
        g = f["geometry"]
        ring = g["coordinates"][0] if g["type"] == "Polygon" else max(g["coordinates"], key=lambda p: len(p[0]))[0]
        xy = np.array(ring)
        pts.append(albers(xy[:, 0].mean(), xy[:, 1].mean()))
    return np.array(pts)


def glow(size, centre, radius, colour, strength):
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x, y = centre
    d.ellipse([x - radius, y - radius, x + radius, y + radius], fill=(*colour, strength))
    return layer.filter(ImageFilter.GaussianBlur(radius * 0.55))


def main():
    size = (W * K, H * K)
    img = Image.new("RGBA", size, (*BASE, 255))
    # very soft corner glows only; the header sits on its own white app bar
    img = Image.alpha_composite(img, glow(size, (1180 * K, 120 * K), 300 * K, EMERALD, 22))
    img = Image.alpha_composite(img, glow(size, (80 * K, 700 * K), 280 * K, ROSE, 16))

    # county dot map across the page, very faint: visible in the gaps between cards and behind the header
    pts = county_points()
    x, y = pts[:, 0], pts[:, 1]
    x = (x - x.min()) / (x.max() - x.min())
    y = (y - y.min()) / (y.max() - y.min())
    left, right, top, bottom = 150, 1250, 40, 690
    px = left + x * (right - left)
    py = bottom - y * (bottom - top)
    dots = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(dots)
    r = 1.6 * K
    for a, b in zip(px * K, py * K):
        d.ellipse([a - r, b - r, a + r, b + r], fill=(*EMERALD, 38))
    img = Image.alpha_composite(img, dots)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(OUT, optimize=True)
    print(f"wrote {OUT.relative_to(ROOT)} ({len(pts):,} county dots)")


if __name__ == "__main__":
    main()
