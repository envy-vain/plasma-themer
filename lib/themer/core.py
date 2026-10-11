"""Paths, palette loading, color math and template rendering."""
from __future__ import annotations

import json
import os
import subprocess
import tomllib
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HOME = Path.home()
XDG_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config"))
XDG_DATA = Path(os.environ.get("XDG_DATA_HOME", HOME / ".local/share"))
XDG_CACHE = Path(os.environ.get("XDG_CACHE_HOME", HOME / ".cache"))

THEMES_DIRS = [XDG_CONFIG / "plasma-themer/themes", REPO / "themes"]  # user themes win
STATE_DIR = XDG_CONFIG / "plasma-themer"
CURRENT = XDG_DATA / "plasma-themer/current"  # rendered files for the active theme
CACHE = XDG_CACHE / "plasma-themer"
LOG = CACHE / "themer.log"


# ---------------------------------------------------------------- colors

def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(r: float, g: float, b: float) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(c))) for c in (r, g, b))


def mix(a: str, b: str, t: float) -> str:
    """t=0 -> a, t=1 -> b"""
    ra, rb = hex_to_rgb(a), hex_to_rgb(b)
    return rgb_to_hex(*(x + (y - x) * t for x, y in zip(ra, rb)))


def luminance(h: str) -> float:
    def ch(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in hex_to_rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_on(bg: str, light: str = "#ffffff", dark: str = "#000000") -> str:
    """Pick whichever of light/dark reads better on bg."""
    lb = luminance(bg)
    cl = (luminance(light) + 0.05) / (lb + 0.05)
    cd = (lb + 0.05) / (luminance(dark) + 0.05)
    return light if cl >= cd else dark


def rgb_csv(h: str) -> str:
    return ",".join(map(str, hex_to_rgb(h)))


def alpha_hex(h: str, a: float) -> str:
    return h + "%02x" % round(a * 255)


# ---------------------------------------------------------------- themes

@dataclass
class Theme:
    slug: str
    path: Path
    meta: dict
    colors: dict
    vscode: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.meta.get("name", self.slug.replace("-", " ").title())

    @property
    def backgrounds(self) -> list[Path]:
        bg = self.path / "backgrounds"
        exts = {".jpg", ".jpeg", ".png", ".webp"}
        return sorted(p for p in bg.iterdir() if p.suffix.lower() in exts) if bg.is_dir() else []

    def context(self) -> dict:
        """Everything templates can use."""
        c = dict(self.colors)
        c.setdefault("selection_background", c["selection"])
        c.setdefault("selection_foreground", c["bright_foreground"])
        c["accent_foreground"] = contrast_on(c["accent"], c["bright_foreground"], c["darker_background"])
        c["border"] = mix(c["background"], c["foreground"], 0.15)
        c["surface"] = mix(c["background"], c["foreground"], 0.06)
        c["surface2"] = mix(c["background"], c["foreground"], 0.11)
        c["ansi"] = [
            c["background"], c["red"], c["green"], c["yellow"], c["blue"], c["magenta"], c["cyan"], c["foreground"],
            c["muted"], c["bright_red"], c["bright_green"], c["bright_yellow"], c["bright_blue"],
            c["bright_magenta"], c["bright_cyan"], c["bright_foreground"],
        ]
        return {"c": c, "theme": self, "slug": self.slug, "name": self.name, "meta": self.meta, "lite": lite()}


def load_theme(slug: str) -> Theme:
    for d in THEMES_DIRS:
        p = d / slug
        if (p / "colors.toml").is_file():
            meta = tomllib.loads((p / "theme.toml").read_text()) if (p / "theme.toml").exists() else {}
            colors = tomllib.loads((p / "colors.toml").read_text())
            vscode = json.loads((p / "vscode.json").read_text()) if (p / "vscode.json").exists() else {}
            return Theme(slug, p, meta, colors, vscode)
    raise SystemExit(f"themer: unknown theme '{slug}' (try: themer list)")


def list_themes() -> list[str]:
    seen: dict[str, None] = {}
    for d in THEMES_DIRS:
        if d.is_dir():
            for p in sorted(d.iterdir()):
                if (p / "colors.toml").is_file():
                    seen.setdefault(p.name)
    return list(seen)


# ---------------------------------------------------------------- state

def state_get(key: str, default: str | None = None) -> str | None:
    f = STATE_DIR / key
    return f.read_text().strip() if f.exists() else default


def state_set(key: str, value: str) -> None:
    f = STATE_DIR / key
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(value + "\n")


# ---------------------------------------------------------------- helpers

@cache
def _env():
    # jinja2 is imported lazily: `themer current`, `themer pick` etc. never pay for it
    from jinja2 import Environment, FileSystemLoader, StrictUndefined
    env = Environment(loader=FileSystemLoader(str(REPO / "templates")), undefined=StrictUndefined,
                      keep_trailing_newline=True)
    env.filters.update(rgb=rgb_csv, mix=mix, alpha=alpha_hex, on=contrast_on,
                       nohash=lambda h: h.lstrip("#"), lum=luminance)
    return env


def render(template: str, ctx: dict) -> str:
    return _env().get_template(template).render(**ctx)


def write(path: Path, text: str) -> bool:
    """Write only if changed (avoids needless file-watch reloads). Returns True if written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text() == text:
        return False
    tmp = path.with_name(path.name + ".themer-tmp")
    tmp.write_text(text)
    tmp.replace(path)
    return True


def have(cmd: str) -> bool:
    from shutil import which
    return which(cmd) is not None


def run(*cmd: str, check: bool = False, quiet: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, text=True,
                          stdout=subprocess.PIPE if quiet else None,
                          stderr=subprocess.PIPE if quiet else None)


def kwrite(file: str, groups: list[str], key: str, value: str) -> None:
    args = ["kwriteconfig6", "--file", file]
    for g in groups:
        args += ["--group", g]
    run(*args, "--key", key, value)


def kread(file: str, groups: list[str], key: str) -> str:
    args = ["kreadconfig6", "--file", file]
    for g in groups:
        args += ["--group", g]
    return run(*args, "--key", key).stdout.strip()


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(msg.rstrip() + "\n")


@cache
def fonts() -> str:
    return run("fc-list", ":", "family").stdout.lower()


# ---------------------------------------------------------------- performance

def screen_size() -> tuple[int, int]:
    """Largest output in physical pixels, cached in state (refresh: `themer lite` or delete the file)."""
    saved = state_get("screen")
    if saved:
        w, h = map(int, saved.split("x"))
        return w, h
    w, h = 1920, 1080
    try:
        outs = json.loads(run("kscreen-doctor", "-j").stdout)["outputs"]
        sizes = [(o["size"]["width"], o["size"]["height"]) for o in outs if o.get("enabled") and o.get("size")]
        if sizes:
            w, h = max(sizes, key=lambda s: s[0] * s[1])
    except Exception:  # noqa: BLE001 — headless / not KDE: keep the default
        pass
    state_set("screen", f"{w}x{h}")
    return w, h


def lite() -> bool:
    """Lite mode: no blur/transparency/animations. `themer lite on|off|auto` (default auto)."""
    mode = state_get("lite", "auto")
    if mode in ("on", "off"):
        return mode == "on"
    gpu = any(Path("/dev/dri").glob("renderD*"))
    try:
        mem_gb = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30
    except (ValueError, OSError):
        mem_gb = 8
    return not gpu or (os.cpu_count() or 1) <= 2 or mem_gb < 4


def _cover(im, w: int, h: int):
    """Scale + center-crop to exactly w x h. Uses JPEG draft / reduce() so huge sources decode fast."""
    from PIL import Image
    r = max(w / im.width, h / im.height)
    if im.format == "JPEG":
        im.draft("RGB", (round(im.width * r), round(im.height * r)))
    im = im.convert("RGB")
    r = max(w / im.width, h / im.height)
    im = im.resize((max(w, round(im.width * r)), max(h, round(im.height * r))), Image.LANCZOS, reducing_gap=2.0)
    left, top = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((left, top, left + w, top + h))


def screen_wallpaper(src: Path) -> Path:
    """Copy of src at screen resolution (JPEG). An 8K webp costs Plasma ~150 MB and a slow decode on every
    login/lock; the scaled copy is decoded once here and reused by wallpaper, lock screen and login screen."""
    w, h = screen_size()
    out = CACHE / "wallpapers" / src.parent.parent.name / f"{src.stem}-{w}x{h}.jpg"
    if out.exists() and out.stat().st_mtime >= src.stat().st_mtime:
        return out
    from PIL import Image
    with Image.open(src) as im:
        if im.width <= w * 1.1 and im.height <= h * 1.1 and im.format == "JPEG":
            return src  # already small enough
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".tmp.jpg")
        _cover(im, w, h).save(tmp, quality=90, optimize=True)
        tmp.replace(out)
    return out
