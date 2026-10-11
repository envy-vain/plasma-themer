#!/usr/bin/env python3
"""Paint palette-matched wallpapers for a theme.

  tools/genwall.py <theme> [--style waves|aurora|dunes] [--size 2560x1440] [--out FILE]
"""
import argparse
import sys
import tomllib
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

REPO = Path(__file__).resolve().parents[1]


def rgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float32)


def blend(base, color, mask):
    return base * (1 - mask[..., None]) + color * mask[..., None]


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def waves(c, w, h, rng):
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    nx, ny = x / w, y / h
    img = np.zeros((h, w, 3), np.float32) + rgb(c["darker_background"])
    img = blend(img, rgb(c["background"]), smoothstep(0.0, 1.0, ny) * 0.8)
    layers = [c["muted"], c["magenta"], c["accent"], c["blue"], c["red"], c["yellow"]]
    n = 6
    for i in range(n):
        col = rgb(layers[i % len(layers)])
        base = 0.42 + i * 0.085
        amp = 0.05 + 0.02 * rng.random()
        f1, f2 = 1.2 + rng.random() * 1.6, 3.0 + rng.random() * 2.5
        p1, p2 = rng.random() * 6.28, rng.random() * 6.28
        curve = base + amp * np.sin(nx * f1 * 3.14 + p1) + amp * 0.35 * np.sin(nx * f2 * 3.14 + p2)
        below = smoothstep(curve - 0.002, curve + 0.002, ny)
        shade = 0.70 - 0.50 * (i / n)  # far layers bright, near layers sink into the dark
        layer = col * shade + rgb(c["darker_background"]) * (1 - shade)
        img = blend(img, layer, below)
        rim = np.exp(-((ny - curve) / 0.0025) ** 2) * 0.55
        img = blend(img, col, rim)
    return img


def aurora(c, w, h, rng):
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    nx, ny = x / w, y / h
    img = np.zeros((h, w, 3), np.float32) + rgb(c["darker_background"])
    for col, k in ((c["accent"], 0), (c["magenta"], 1), (c["cyan"], 2), (c["green"], 3)):
        cx, cy = 0.15 + rng.random() * 0.7, 0.15 + rng.random() * 0.5
        sx, sy = 0.25 + rng.random() * 0.25, 0.08 + rng.random() * 0.1
        band = cy + 0.08 * np.sin(nx * (4 + k) + rng.random() * 6) - ny
        m = np.exp(-(band / sy) ** 2) * np.exp(-((nx - cx) / sx) ** 2) * 0.55
        img = blend(img, rgb(col), m)
    # stars
    stars = rng.random((h, w)) > 0.9993
    img[stars] = rgb(c["bright_foreground"]) * (0.5 + 0.5 * rng.random((stars.sum(), 1)))
    # horizon hills
    hill = 0.82 + 0.04 * np.sin(nx * 5 + 1.3) + 0.02 * np.sin(nx * 13)
    img = blend(img, rgb(c["darker_background"]) * 0.7, smoothstep(hill - 0.002, hill + 0.002, ny))
    return img


def dunes(c, w, h, rng):
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    nx, ny = x / w, y / h
    sky = blend(np.zeros((h, w, 3), np.float32) + rgb(c["background"]), rgb(c["accent"]) * 0.6 +
                rgb(c["background"]) * 0.4, np.clip(1 - ny * 1.8, 0, 1) * 0.5)
    # sun
    d = np.hypot((nx - 0.68) * w / h, ny - 0.36)
    sky = blend(sky, rgb(c["yellow"]), smoothstep(0.105, 0.1, d))
    sky = blend(sky, rgb(c["orange"]), np.exp(-(d / 0.25) ** 2) * 0.25)
    img = sky
    cols = [c["magenta"], c["red"], c["muted"], c["lighter_background"], c["dark_background"]]
    for i, col in enumerate(cols):
        top = 0.5 + i * 0.1
        curve = top + 0.05 * np.sin(nx * (2 + i) * 3.14 + rng.random() * 6) + 0.015 * np.sin(nx * 21 + i)
        m = smoothstep(curve - 0.0015, curve + 0.0015, ny)
        shade = 0.35 + 0.13 * i
        img = blend(img, rgb(col) * (1 - shade) + rgb(c["darker_background"]) * shade, m)
    return img


def _font(size):
    from PIL import ImageFont
    import subprocess
    try:
        path = subprocess.run(["fc-match", "-f", "%{file}", "monospace:bold"], capture_output=True, text=True).stdout
        return ImageFont.truetype(path, size)
    except Exception:  # noqa: BLE001
        return ImageFont.load_default()


def ascii_art(c, w, h, rng):
    """Dot/ASCII-matrix render of a lit moon over a drifting sea (the old desktop's wallpaper style)."""
    from PIL import Image, ImageDraw
    cw, ch = max(8, w // 200), max(12, w // 130)  # glyph cell
    cols, rows = w // cw, h // ch
    y, x = np.mgrid[0:rows, 0:cols].astype(np.float32)
    nx, ny = x / cols, y / rows
    aspect = (cols * cw) / (rows * ch)
    # moon: sphere shading lit from the upper left, plus soft craters
    mx, my, r = 0.62 + rng.random() * 0.12, 0.34, 0.17
    dx, dy = (nx - mx) * aspect, ny - my
    d = np.sqrt(dx ** 2 + dy ** 2) / r
    z = np.sqrt(np.clip(1 - d ** 2, 0, 1))
    light = np.clip((-dx / r * 0.55 - dy / r * 0.45 + z * 0.8), 0, 1) * (d < 1)
    for _ in range(7):
        cx, cy, cr = rng.normal(0, 0.45, 2).tolist() + [0.08 + rng.random() * 0.12]
        light *= 1 - 0.35 * np.exp(-(((dx / r - cx) ** 2 + (dy / r - cy) ** 2) / cr ** 2))
    # sea: horizontal bands that catch the moonlight under it
    sea = (ny > 0.62) * np.clip(np.sin(nx * 40 + ny * 90 + rng.random() * 6) * 0.5 + 0.5, 0, 1)
    sea *= np.exp(-((nx - mx) * aspect / 0.18) ** 2) * np.clip((ny - 0.62) * 3, 0, 1) * 0.8
    glow = np.exp(-((d - 1) / 0.35) ** 2) * 0.12 * (d >= 1)
    field = np.clip(np.maximum(light, sea) + glow, 0, 1)

    img = Image.new("RGB", (w, h), tuple(int(v) for v in rgb(c["background"])))
    draw = ImageDraw.Draw(img)
    font = _font(ch - 2)
    ramp = " .·:-=+*#%@"
    lo, mid, hi = rgb(c["muted"]), rgb(c["accent"]), rgb(c["yellow"])
    for j in range(rows):
        for i in range(cols):
            v = field[j, i]
            if v < 0.04:
                continue
            g = ramp[min(len(ramp) - 1, int(v * len(ramp)))]
            col = lo + (mid - lo) * min(1, v * 1.6) if v < 0.6 else mid + (hi - mid) * (v - 0.6) / 0.4
            draw.text((i * cw, j * ch), g, fill=tuple(int(t) for t in col), font=font)
    return np.asarray(img).astype(np.float32)


STYLES = {"waves": waves, "aurora": aurora, "dunes": dunes, "ascii": ascii_art}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("theme")
    ap.add_argument("--style", default="waves", choices=STYLES)
    ap.add_argument("--size", default="2560x1440")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out")
    a = ap.parse_args()
    tdir = REPO / "themes" / a.theme
    c = tomllib.loads((tdir / "colors.toml").read_text())
    w, h = map(int, a.size.split("x"))
    rng = np.random.default_rng(a.seed)
    img = STYLES[a.style](c, w, h, rng)
    if a.style != "ascii":
        img += rng.normal(0, 2.2, img.shape)  # film grain kills banding
    im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))
    if a.style != "ascii":
        im = im.filter(ImageFilter.SMOOTH)
    out = Path(a.out) if a.out else tdir / "backgrounds" / f"gen-{a.style}.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out, quality=92)
    print(out)


if __name__ == "__main__":
    sys.exit(main())
