"""themer — Omarchy-style theme switching for KDE Plasma."""
from __future__ import annotations

import argparse
import shutil
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import core
from .core import CURRENT, Theme, have, list_themes, load_theme, log, run, state_get, state_set
from .targets import TARGETS

SEQUENTIAL = {"plasma colors + accent", "icons (Papirus folders)"}  # both write kdeglobals: keep ordered
TTY = sys.stdout.isatty()


def _c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if TTY else s


def pick_wallpaper(t: Theme, step: int = 0) -> Path | None:
    bgs = t.backgrounds
    if not bgs:
        return None
    saved = state_get(f"bg/{t.slug}")
    names = [p.name for p in bgs]
    i = names.index(saved) if saved in names else 0
    i = (i + step) % len(bgs)
    state_set(f"bg/{t.slug}", names[i])
    return bgs[i]


def apply(slug: str, only: set[str] | None = None, quiet: bool = False) -> int:
    t = load_theme(slug)
    ctx = t.context()
    wp = pick_wallpaper(t)
    CURRENT.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    log(f"--- {time.ctime()} apply {slug}")
    if not quiet:
        print(_c("1", f"󰏘  {t.name}") + _c("2", f"  ({wp.name if wp else 'no wallpaper'})"))

    def go(item):
        name, fn = item
        t0 = time.monotonic()
        try:
            note = fn(t, ctx, wp) or ""
            ok = not str(note).startswith("WARN")
        except Exception as e:  # noqa: BLE001 — isolate every integration
            log(traceback.format_exc())
            note, ok = f"{type(e).__name__}: {str(e).strip().splitlines()[-1] if str(e).strip() else ''}", False
        return name, ok, note, time.monotonic() - t0

    todo = [x for x in TARGETS if not only or any(o in x[0] for o in only)]
    seq = [x for x in todo if x[0] in SEQUENTIAL]
    par = [x for x in todo if x[0] not in SEQUENTIAL]
    results = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        fut = ex.map(go, par)
        results += [go(x) for x in seq]
        results += list(fut)

    failed = 0
    for name, ok, note, dt in sorted(results, key=lambda r: [x[0] for x in TARGETS].index(r[0])):
        skipped = str(note).startswith("skipped")
        failed += not ok
        log(f"{'ok' if ok else 'FAIL'} {name}: {note}")
        if quiet:
            continue
        mark = _c("33", "–") if skipped else (_c("32", "✓") if ok else _c("31", "✗"))
        print(f"  {mark} {name:<26}{_c('2', str(note))}")

    state_set("current", slug)
    try:  # keep the hotkey's prepared picker data current
        from .picker import write_data
        write_data()
    except Exception:  # noqa: BLE001
        log(traceback.format_exc())
    total = time.monotonic() - started
    if not quiet:
        print(_c("2", f"  done in {total:.1f}s" + (f" — {failed} problem(s), see {core.LOG}" if failed else "")))
    if have("notify-send"):
        icon = str(wp) if wp else "preferences-desktop-color"
        run("notify-send", "-a", "Themer", "-i", icon, "-t", "2500", "-h", "string:x-canonical-private-synchronous:themer",
            f"󰏘 {t.name}", "Theme applied" + (f" — {failed} issue(s)" if failed else ""))
    return 1 if failed else 0


def cmd_list(a):
    cur = state_get("current")
    for s in list_themes():
        t = load_theme(s)
        sw = "".join(_c(f"48;2;{';'.join(map(str, core.hex_to_rgb(t.colors[k])))}", "  ")
                     for k in ("background", "red", "green", "yellow", "blue", "magenta", "cyan", "accent"))
        print(f"{'●' if s == cur else ' '} {sw} {s:<14} {_c('2', t.name)}")


def cmd_cycle(a, step):
    themes = list_themes()
    cur = state_get("current", themes[0])
    i = themes.index(cur) if cur in themes else -1
    return apply(themes[(i + step) % len(themes)])


def cmd_bg(a):
    t = load_theme(state_get("current") or list_themes()[0])
    step = {"next": 1, "prev": -1}.get(a.which, 0)
    wp = pick_wallpaper(t, step)
    if not wp:
        print("theme has no backgrounds"); return 1
    from .targets import plasma_wallpaper, login_screen, firefox
    ctx = t.context()
    plasma_wallpaper(t, ctx, wp)
    for fn in (login_screen, firefox):  # firefox: pywal colors.json carries the wallpaper path
        try:
            fn(t, ctx, wp)
        except Exception:
            log(traceback.format_exc())
    from .picker import write_data
    write_data()
    print(wp.name)


def cmd_lite(a):
    if a.mode:
        state_set("lite", a.mode)
        (core.STATE_DIR / "screen").unlink(missing_ok=True)  # re-detect resolution too
    print(f"lite mode: {state_get('lite', 'auto')} -> {'ON' if core.lite() else 'off'}")
    if a.mode and state_get("current"):
        return apply(state_get("current"), {"konsole"})  # the only target whose output depends on it


def cmd_pick_apply(a):
    """Called by the fast hotkey launcher once a theme was chosen in the picker."""
    if a.bg:
        state_set(f"bg/{a.theme}", a.bg)
    return apply(a.theme, quiet=True)


def cmd_pick(a):
    from .picker import run_picker
    return run_picker(apply)


def cmd_setup(a):
    """One-time: VSCodium theme extensions, Pywalfox native host, global shortcuts."""
    from .setup import setup
    return setup()


def cmd_doctor(a):
    from .setup import doctor
    return doctor()


def main(argv=None):
    p = argparse.ArgumentParser(prog="themer", description=__doc__)
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("list", help="list themes")
    s = sub.add_parser("set", help="apply a theme")
    s.add_argument("theme", choices=list_themes())
    s.add_argument("--only", nargs="+", help="only run targets whose name contains these words")
    sub.add_parser("next"); sub.add_parser("prev")
    sub.add_parser("current")
    sub.add_parser("reapply", help="re-render + apply the current theme")
    b = sub.add_parser("bg", help="wallpaper within current theme")
    b.add_argument("which", nargs="?", default="next", choices=["next", "prev", "current"])
    sub.add_parser("pick", help="open the overlay picker")
    pa = sub.add_parser("pick-apply")  # internal: used by the hotkey launcher
    pa.add_argument("theme", choices=list_themes())
    pa.add_argument("bg", nargs="?", default="")
    sub.add_parser("setup", help="one-time setup (extensions, pywalfox, shortcuts)")
    sub.add_parser("doctor", help="check what is installed / wired up")
    sub.add_parser("targets", help="list integrations")
    li = sub.add_parser("lite", help="lite mode for weak PCs: no blur/transparency/animations")
    li.add_argument("mode", nargs="?", choices=["on", "off", "auto"])
    a = p.parse_args(argv)

    match a.cmd:
        case "list" | None: cmd_list(a)
        case "set": return apply(a.theme, set(a.only) if a.only else None)
        case "next": return cmd_cycle(a, 1)
        case "prev": return cmd_cycle(a, -1)
        case "current": print(state_get("current", "none"))
        case "reapply": return apply(state_get("current") or list_themes()[0])
        case "bg": return cmd_bg(a)
        case "pick": return cmd_pick(a)
        case "pick-apply": return cmd_pick_apply(a)
        case "setup": return cmd_setup(a)
        case "doctor": return cmd_doctor(a)
        case "targets": print("\n".join(n for n, _ in TARGETS))
        case "lite": return cmd_lite(a)
    return 0
