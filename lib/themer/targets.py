"""Every app integration. Each target is independent: one failing never blocks the others."""
from __future__ import annotations

import configparser
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from .core import (CACHE, rgb_csv, CURRENT, HOME, XDG_CACHE, XDG_CONFIG, XDG_DATA, Theme, have, kread, kwrite, log,
                   render, run, state_get, write)

TARGETS: list[tuple[str, callable]] = []


def target(name: str):
    def deco(fn):
        TARGETS.append((name, fn))
        return fn
    return deco


def _ab(current: str, base: str) -> str:
    """Alternate between two ids so KDE re-reads a regenerated file even if the theme is unchanged."""
    return base + "B" if current == base + "A" else base + "A"


def _marker_ok(p: Path) -> bool:
    """True if we may overwrite p (missing, or previously written by us)."""
    return not p.exists() or "plasma-themer" in p.read_text(errors="ignore")


# ---------------------------------------------------------------- Plasma

@target("plasma colors + accent")
def plasma_colors(t: Theme, ctx: dict, wallpaper: Path | None):
    schemes = XDG_DATA / "color-schemes"
    cur = kread("kdeglobals", ["General"], "ColorScheme")
    sid = _ab(cur, "Themer")
    write(schemes / f"{sid}.colors", render("kde.colors", {**ctx, "scheme_id": sid}))
    # Write the accent keys first; applying the (alternating) scheme then broadcasts the change.
    acc = rgb_csv(ctx["c"]["accent"])
    for k, v in (("AccentColor", acc), ("LastUsedCustomAccentColor", acc), ("accentColorFromWallpaper", "false")):
        kwrite("kdeglobals", ["General"], k, v)
    r = run("plasma-apply-colorscheme", sid)
    if r.returncode or "Successfully" not in r.stdout:
        raise RuntimeError((r.stdout + r.stderr).strip())
    (schemes / f"{_ab(sid, 'Themer')}.colors").unlink(missing_ok=True)


@target("wallpaper + lock screen")
def plasma_wallpaper(t: Theme, ctx: dict, wallpaper: Path | None):
    if not wallpaper:
        return "theme has no backgrounds"
    run("plasma-apply-wallpaperimage", str(wallpaper), check=True)
    for k in ("Image", "PreviewImage"):
        kwrite("kscreenlockerrc", ["Greeter", "Wallpaper", "org.kde.image", "General"], k, f"file://{wallpaper}")


def _icon_dirs() -> list[Path]:
    return [HOME / ".icons", XDG_DATA / "icons", Path("/usr/share/icons")]


def _icon_theme_exists(name: str) -> bool:
    return any((d / name).is_dir() for d in _icon_dirs())


@target("mouse cursor")
def cursor(t: Theme, ctx: dict, wallpaper: Path | None):
    want = t.meta.get("cursor", "breeze_cursors")
    if not _icon_theme_exists(want):
        log(f"cursor {want} not installed, using breeze_cursors")
        want = "breeze_cursors"
    if kread("kcminputrc", ["Mouse"], "cursorTheme") != want:
        run("plasma-apply-cursortheme", want, check=True)
    return want


@target("icons (Papirus folders)")
def icons(t: Theme, ctx: dict, wallpaper: Path | None):
    papirus = Path("/usr/share/icons/Papirus")
    if not papirus.is_dir():
        return "skipped: papirus-icon-theme not installed"
    color = t.meta.get("folders", "blue")
    cur = kread("kdeglobals", ["Icons"], "Theme")
    name = _ab(cur, "Themer-Papirus-")
    root = XDG_DATA / "icons" / name
    shutil.rmtree(root, ignore_errors=True)
    dirs = []
    # Mirror papirus-folders without touching /usr: per-user overlay that only redirects folder icons
    for size_dir in sorted(papirus.iterdir()):
        places = size_dir / "places"
        if not places.is_dir() or "@" in size_dir.name:
            continue
        out = root / size_dir.name / "places"
        made = False
        for f in places.iterdir():
            if not f.is_symlink():
                continue
            # follow chains like inode-directory -> folder -> folder-blue until a "-blue" hop
            hop, alt = f.name, None
            for _ in range(6):
                if not (places / hop).is_symlink():
                    break
                hop = os.readlink(places / hop)
                if "-blue" in hop:
                    alt = hop.replace("-blue", f"-{color}")
                    break
            if not alt:
                continue
            if (places / alt).exists():
                out.mkdir(parents=True, exist_ok=True)
                (out / f.name).symlink_to(places / alt)
                made = True
        if made:
            dirs.append(size_dir.name)
    sections = "".join(
        f"\n[{d}/places]\nSize={d.split('x')[0]}\nContext=Places\nType=Fixed\n" for d in dirs)
    write(root / "index.theme",
          f"[Icon Theme]\nName={name}\nComment=plasma-themer folder overlay ({color})\n"
          f"Inherits=Papirus-Dark,breeze-dark,hicolor\nDirectories={','.join(d + '/places' for d in dirs)}\n"
          + sections)
    run("/usr/lib/plasma-changeicons", name, check=True)
    old = XDG_DATA / "icons" / _ab(name, "Themer-Papirus-")
    shutil.rmtree(old, ignore_errors=True)
    return color


# ---------------------------------------------------------------- terminals

@target("konsole")
def konsole(t: Theme, ctx: dict, wallpaper: Path | None):
    kdir = XDG_DATA / "konsole"
    prof = kdir / "Themer.profile"
    cp = configparser.ConfigParser(interpolation=None)
    cp.optionxform = str
    if prof.exists():
        cp.read(prof)
    cur = cp.get("Appearance", "ColorScheme", fallback="")
    sid = _ab(cur, "Themer")
    write(kdir / f"{sid}.colorscheme", render("konsole.colorscheme", ctx))
    for sec in ("Appearance", "General", "Scrolling", "Terminal Features"):
        if not cp.has_section(sec):
            cp.add_section(sec)
    cp["Appearance"]["ColorScheme"] = sid
    if _font_installed("JetBrainsMono Nerd Font"):
        cp["Appearance"].setdefault("Font", "JetBrainsMono Nerd Font,11,-1,5,400,0,0,0,0,0,0,0,0,0,0,1")
    cp["General"]["Name"] = "Themer"
    cp["General"]["Parent"] = "FALLBACK/"
    cp["General"].setdefault("TerminalMargin", "8")
    cp["General"].setdefault("TerminalCenter", "true")
    cp["Scrolling"].setdefault("ScrollBarPosition", "2")
    cp["Terminal Features"].setdefault("BlinkingCursorEnabled", "true")
    with prof.open("w") as f:
        cp.write(f, space_around_delimiters=False)
    (kdir / f"{_ab(sid, 'Themer')}.colorscheme").unlink(missing_ok=True)
    kwrite("konsolerc", ["Desktop Entry"], "DefaultProfile", "Themer.profile")
    # live: switch every open session
    n = 0
    for svc in run("qdbus6").stdout.split():
        if svc.startswith("org.kde.konsole") or svc.startswith("org.kde.yakuake"):
            for path in run("qdbus6", svc).stdout.split():
                if re.fullmatch(r"/Sessions/\d+", path):
                    run("qdbus6", svc, path, "org.kde.konsole.Session.setProfile", "Themer")
                    n += 1
    return f"{n} live sessions"


@target("alacritty")
def alacritty(t: Theme, ctx: dict, wallpaper: Path | None):
    theme_file = CURRENT / "alacritty.toml"
    write(theme_file, render("alacritty.toml", ctx))
    cfg = XDG_CONFIG / "alacritty/alacritty.toml"
    if not cfg.exists():
        font = "JetBrainsMono Nerd Font" if _font_installed("JetBrainsMono Nerd Font") else "FantasqueSansM Nerd Font"
        write(cfg, f"""# plasma-themer: colors are imported from the active theme (live-reloads on switch)
[general]
import = ["{theme_file}"]
live_config_reload = true

[window]
padding = {{ x = 14, y = 14 }}
opacity = 0.94
blur = true
decorations = "Full"

[font]
normal = {{ family = "{font}" }}
size = 11

[cursor]
style = {{ shape = "Beam", blinking = "On" }}
""")
    elif str(theme_file) not in (txt := cfg.read_text()):
        # Inline color tables beat imports in Alacritty, so drop them and import ours instead.
        txt = re.sub(r"^\[colors\.(primary|normal|bright|dim|cursor|selection)\]\n(?:(?!\[).*\n?)*", "", txt, flags=re.M)
        imp = f'import = ["{theme_file}"]  # plasma-themer\n'
        if re.search(r"^\[general\]\s*$", txt, flags=re.M):
            txt = re.sub(r"^\[general\]\s*\n", lambda m: m.group(0) + imp, txt, count=1, flags=re.M)
        else:
            txt = f"[general]\n{imp}\n" + txt
        write(cfg, txt)
        return "wired import into your config (inline colors removed)"


def _font_installed(family: str) -> bool:
    return family.lower() in run("fc-list", ":", "family").stdout.lower()


# ---------------------------------------------------------------- shell + CLI

@target("fish + pure prompt + fzf")
def fish(t: Theme, ctx: dict, wallpaper: Path | None):
    if not have("fish"):
        return "skipped"
    c = {k: v.lstrip("#") for k, v in ctx["c"].items() if isinstance(v, str) and v.startswith("#")}
    write(CURRENT / "fzf.opts",
          f"--color=bg+:{ctx['c']['selection']},bg:-1,spinner:{ctx['c']['accent']},hl:{ctx['c']['red']}\n"
          f"--color=fg:{ctx['c']['foreground']},header:{ctx['c']['red']},info:{ctx['c']['magenta']},"
          f"pointer:{ctx['c']['accent']}\n"
          f"--color=marker:{ctx['c']['green']},fg+:{ctx['c']['bright_foreground']},prompt:{ctx['c']['accent']},"
          f"hl+:{ctx['c']['red']},border:{ctx['c']['border']}\n--border=rounded --layout=reverse\n")
    v = {
        # fish syntax highlighting
        "fish_color_normal": c["foreground"], "fish_color_command": c["blue"], "fish_color_keyword": c["magenta"],
        "fish_color_quote": c["green"], "fish_color_redirection": c["cyan"], "fish_color_end": c["orange"],
        "fish_color_error": c["red"], "fish_color_param": c["foreground"], "fish_color_option": c["cyan"],
        "fish_color_comment": c["dark_foreground"], "fish_color_operator": c["accent"],
        "fish_color_escape": c["magenta"], "fish_color_autosuggestion": c["muted"],
        "fish_color_valid_path": "--underline", "fish_color_selection": f"--background={c['selection']}",
        "fish_color_search_match": f"--background={c['selection']}",
        "fish_pager_color_prefix": c["accent"], "fish_pager_color_completion": c["foreground"],
        "fish_pager_color_description": c["dark_foreground"], "fish_pager_color_progress": c["accent"],
        "fish_pager_color_selected_background": f"--background={c['selection']}",
        # pure prompt
        "pure_color_primary": c["accent"], "pure_color_info": c["cyan"], "pure_color_mute": c["dark_foreground"],
        "pure_color_success": c["magenta"], "pure_color_danger": c["red"], "pure_color_warning": c["yellow"],
        "pure_color_light": c["bright_foreground"], "pure_color_dark": c["background"],
        "pure_color_normal": c["foreground"],
    }
    script = "".join(f"set -U {k} {val}\n" for k, val in v.items())
    script += f"set -Ux FZF_DEFAULT_OPTS_FILE {CURRENT / 'fzf.opts'}\nset -Ux BAT_THEME ansi\n"
    r = subprocess.run(["fish", "--no-config", "-c", "source"], input=script, text=True, capture_output=True)
    if r.returncode:
        raise RuntimeError(r.stderr)


@target("btop")
def btop(t: Theme, ctx: dict, wallpaper: Path | None):
    write(XDG_CONFIG / "btop/themes/plasma-themer.theme", render("btop.theme", ctx))
    conf = XDG_CONFIG / "btop/btop.conf"
    if conf.exists():
        txt = conf.read_text()
        new = re.sub(r'^color_theme = .*$', 'color_theme = "plasma-themer"', txt, flags=re.M)
        write(conf, new)
    run("pkill", "-USR2", "-x", "btop")


@target("tmux")
def tmux(t: Theme, ctx: dict, wallpaper: Path | None):
    f = CURRENT / "tmux.conf"
    write(f, render("tmux.conf", ctx))
    rc = HOME / ".tmux.conf"
    line = f"source-file -q {f}"
    if not rc.exists():
        write(rc, f"# plasma-themer\nset -g default-terminal \"tmux-256color\"\nset -ag terminal-overrides \",*:RGB\"\n"
                  f"set -g mouse on\n{line}\n")
    elif line not in rc.read_text():
        rc.write_text(rc.read_text().rstrip() + f"\n# plasma-themer\n{line}\n")
    if have("tmux"):
        run("tmux", "source-file", str(f))


@target("vim")
def vim(t: Theme, ctx: dict, wallpaper: Path | None):
    write(HOME / ".vim/colors/themer.vim", render("themer.vim", ctx))
    rc = HOME / ".vimrc"
    if not rc.exists():
        write(rc, "\" plasma-themer\nunlet! skip_defaults_vim\nsource $VIMRUNTIME/defaults.vim\n"
                  "set number\nsilent! colorscheme themer\n")


@target("fastfetch")
def fastfetch(t: Theme, ctx: dict, wallpaper: Path | None):
    f = CURRENT / "fastfetch.jsonc"
    write(f, render("fastfetch.jsonc", ctx))
    link = XDG_CONFIG / "fastfetch/config.jsonc"
    if not link.exists() and not link.is_symlink():
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(f)
    elif not link.is_symlink():
        return f"kept your own {link}"


# ---------------------------------------------------------------- apps

def _firefox_profile() -> Path | None:
    for base in (XDG_CONFIG / "mozilla/firefox", HOME / ".mozilla/firefox"):
        ini = base / "installs.ini"
        if ini.exists():
            cp = configparser.ConfigParser(interpolation=None)
            cp.read(ini)
            for s in cp.sections():
                if cp.has_option(s, "Default"):
                    return base / cp.get(s, "Default")
    return None


def _pywal_json(t: Theme, ctx: dict, wallpaper: Path | None) -> str:
    c = ctx["c"]
    # pywalfox: color0 = background, color15 = text, color1/2 = accents (its default mapping)
    cols = [c["background"], c["accent"], c["magenta"], c["green"], c["yellow"], c["blue"], c["cyan"],
            c["foreground"], c["surface2"], c["accent"], c["bright_magenta"], c["bright_green"],
            c["bright_yellow"], c["bright_blue"], c["bright_cyan"], c["bright_foreground"]]
    return json.dumps({
        "wallpaper": str(wallpaper or ""), "alpha": "100",
        "special": {"background": c["background"], "foreground": c["foreground"], "cursor": c["accent"]},
        "colors": {f"color{i}": v for i, v in enumerate(cols)},
    }, indent=2) + "\n"


@target("firefox")
def firefox(t: Theme, ctx: dict, wallpaper: Path | None):
    prof = _firefox_profile()
    if not prof or not prof.is_dir():
        return "skipped: no default profile"
    chrome = prof / "chrome"
    notes = []
    for tpl in ("themer-colors.css", "userChrome.css", "userContent.css"):
        dest = chrome / tpl
        if _marker_ok(dest):
            write(dest, render(tpl, ctx))
        else:
            notes.append(f"kept your {tpl}")
    userjs = prof / "user.js"
    pref = 'user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);'
    if pref not in (userjs.read_text() if userjs.exists() else ""):
        with userjs.open("a") as f:
            f.write(f"// plasma-themer\n{pref}\n")
        notes.append("restart Firefox once to enable userChrome")
    # Pywalfox: live recolor of the browser UI
    write(XDG_CACHE / "wal/colors.json", _pywal_json(t, ctx, wallpaper))
    if have("pywalfox"):
        run("pywalfox", "update")
    else:
        notes.append("pywalfox not installed (no live recolor)")
    return "; ".join(notes)


@target("vscodium")
def vscodium(t: Theme, ctx: dict, wallpaper: Path | None):
    name = t.vscode.get("name")
    if not name:
        return "no vscode theme"
    settings = XDG_CONFIG / "VSCodium/User/settings.json"
    if not have("codium") and not settings.exists():
        return "skipped: VSCodium not installed"
    txt = settings.read_text() if settings.exists() else "{\n}\n"
    entry = f'"workbench.colorTheme": {json.dumps(name, ensure_ascii=False)}'
    if re.search(r'"workbench\.colorTheme"\s*:', txt):
        txt = re.sub(r'"workbench\.colorTheme"\s*:\s*"[^"]*"', lambda m: entry, txt)
    else:
        txt = re.sub(r"^\s*\{", lambda m: "{\n  " + entry + ",", txt, count=1)
        txt = re.sub(r",(\s*)\}\s*$", r"\1}\n", txt)  # `{ "x": 1, }` if file was empty
    write(settings, txt)
    ext = t.vscode.get("extension")
    if ext and have("codium") and ext.lower() not in run("codium", "--list-extensions").stdout.lower():
        return f"WARN: theme extension {ext} missing — run: themer setup"


@target("vesktop (discord)")
def vesktop(t: Theme, ctx: dict, wallpaper: Path | None):
    root = XDG_CONFIG / "vesktop"
    if not root.is_dir() and not have("vesktop"):
        return "skipped: Vesktop not installed"
    (root / "settings").mkdir(parents=True, exist_ok=True)
    write(root / "themes/plasma-themer.css", render("vesktop.css", ctx))
    s = root / "settings/settings.json"
    if True:  # Vencord merges its defaults into whatever is here
        data = json.loads(s.read_text()) if s.exists() else {}
        enabled = data.setdefault("enabledThemes", [])
        if "plasma-themer.css" not in enabled:
            enabled.append("plasma-themer.css")
            write(s, json.dumps(data, indent=4) + "\n")
            return "theme enabled (restart Vesktop once)"


@target("obsidian")
def obsidian(t: Theme, ctx: dict, wallpaper: Path | None):
    idx = XDG_CONFIG / "obsidian/obsidian.json"
    if not idx.exists():
        return "skipped"
    css = render("obsidian.css", ctx)
    vaults = json.loads(idx.read_text()).get("vaults", {}).values()
    for v in vaults:
        dot = Path(v["path"]) / ".obsidian"
        if not dot.is_dir():
            continue
        write(dot / "snippets/plasma-themer.css", css)
        app = dot / "appearance.json"
        data = json.loads(app.read_text()) if app.exists() else {}
        snippets = data.setdefault("enabledCssSnippets", [])
        if "plasma-themer" not in snippets:
            snippets.append("plasma-themer")
            write(app, json.dumps(data, indent=2))
    return f"{len(list(vaults))} vault(s)"


@target("login screen")
def login_screen(t: Theme, ctx: dict, wallpaper: Path | None):
    # One-time root setup (install/system-setup.sh) makes /var/lib/plasma-themer user-owned and points
    # /etc/plasmalogin.conf at login-background.jpg in it, so switching needs no sudo.
    root = Path("/var/lib/plasma-themer")
    if not (root.is_dir() and os.access(root, os.W_OK)):
        return "skipped: run install/system-setup.sh once"
    if not wallpaper:
        return "no wallpaper"
    from PIL import Image
    tmp = root / ".login-background.tmp.jpg"
    Image.open(wallpaper).convert("RGB").save(tmp, quality=92)
    os.chmod(tmp, 0o644)
    tmp.replace(root / "login-background.jpg")
