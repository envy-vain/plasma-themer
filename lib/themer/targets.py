"""Every app integration. Each target is independent: one failing never blocks the others."""
from __future__ import annotations

import configparser
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from .core import (CACHE, CURRENT, mix, HOME, XDG_CACHE, XDG_CONFIG, XDG_DATA, Theme, app_config, changeicons_tool, fonts,
                   have, kread, kwrite, lite, log, render, rgb_csv, run, screen_wallpaper, state_get, state_set,
                   write)

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
    # Same colors already live? Skip the apply: it makes every Qt app repaint, which is slow on weak machines.
    if cur.startswith("Themer") and (schemes / f"{cur}.colors").exists() and \
            (schemes / f"{cur}.colors").read_text() == render("kde.colors", {**ctx, "scheme_id": cur}):
        return "unchanged"
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
    img = screen_wallpaper(wallpaper)  # screen-sized copy: less RAM in plasmashell, faster lock/login
    run("plasma-apply-wallpaperimage", str(img), check=True)
    for k in ("Image", "PreviewImage"):
        kwrite("kscreenlockerrc", ["Greeter", "Wallpaper", "org.kde.image", "General"], k, f"file://{img}")


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


ICON_OVERLAY_VERSION = 8


def _tint_folder(svg: str, tint: str) -> str:
    """Papirus black folders: dark body/tab, a light paper strip (#dcdcdc) and a light-grey symbol (#c2c2c2 etc).
    Every light grey becomes the pastel tint; the strip gets a slightly deeper shade so it still reads as paper."""
    from .core import luminance
    strip = mix(tint, "#000000", 0.15)

    def repl(m):
        h = m.group(0)
        if len(h) != 7 or luminance(h) < 0.3:
            return h  # dark body/tab colors stay black
        return strip if h.lower() in ("#dcdcdc", "#e4e4e4") else tint
    return re.sub(r"#[0-9a-fA-F]{6}\b", repl, svg)


def _is_folder_icon(name: str) -> bool:
    # Only folder names. Generic ones like network.svg would hijack KDE's name fallback:
    # network-wireless-signal-excellent -> ... -> "network" turned the wifi tray icon into a folder.
    stem = name.removesuffix(".svg")
    return stem.startswith(("folder", "user-")) or stem == "inode-directory"


@target("icons (Papirus folders)")
def icons(t: Theme, ctx: dict, wallpaper: Path | None):
    papirus = Path("/usr/share/icons/Papirus")
    if not papirus.is_dir():
        return "skipped: papirus-icon-theme not installed"
    color = t.meta.get("folders", "black-pastel")
    pastel = color.endswith("-pastel")
    if pastel:  # base Papirus color + accent-tinted symbol/strip, generated per accent
        base = color.removesuffix("-pastel")
        tint = mix(ctx["c"]["accent"], "#ffffff", 0.3)
        color = f"{base}-{tint.lstrip('#')}"
    cur = kread("kdeglobals", ["Icons"], "Theme")
    # Name is unique per color + overlay version: KDE caches icon lookups by theme *name*, so reusing a name
    # (the old A/B scheme) kept serving stale results from a previous overlay. Bump the version on changes.
    name = f"Themer-Papirus-{color}-{ICON_OVERLAY_VERSION}"
    root = XDG_DATA / "icons" / name
    if cur == name and (root / "index.theme").exists():
        return f"{color} (unchanged)"  # an icon-theme switch flushes every app's icon cache: skip when we can
    if (root / "index.theme").exists():  # built before for this color: just switch (overlays are tiny)
        _apply_icon_theme(name)
        _set_launcher_icon(_launcher_name(tint if pastel else mix(ctx["c"]["accent"], "#ffffff", 0.3)))
        return f"{color} (cached)"
    shutil.rmtree(root, ignore_errors=True)
    dirs = []
    # Mirror papirus-folders without touching /usr: per-user overlay that only redirects folder icons
    for size_dir in sorted(papirus.iterdir()):
        places = size_dir / "places"
        if not places.is_dir() or "@" in size_dir.name:
            continue
        out = root / size_dir.name / "places"
        made = False
        with os.scandir(places) as it:
            entries = [e.name for e in it if e.is_symlink() and _is_folder_icon(e.name)]
        for fname in entries:
            # follow chains like inode-directory -> folder -> folder-blue until a "-blue" hop
            hop, alt = fname, None
            for _ in range(6):
                if not (places / hop).is_symlink():
                    break
                hop = os.readlink(places / hop)
                if "-blue" in hop:
                    alt = hop.replace("-blue", f"-{color}")
                    break
            if pastel and alt:
                alt = alt.replace(f"-{color}", f"-{base}")
            if alt and (places / alt).exists():
                out.mkdir(parents=True, exist_ok=True)
                if pastel:
                    (out / fname).write_text(_tint_folder((places / alt).resolve().read_text(), tint))
                else:
                    (out / fname).symlink_to(places / alt)
                made = True
        if made:
            dirs.append(size_dir.name)
    sections = "".join(
        f"\n[{d}/places]\nSize={d.split('x')[0]}\nContext=Places\nType=Fixed\n" for d in dirs)
    # Launcher icon: Papirus' KDE logo as a black badge with the logo in the pastel tint ("themer-start";
    # a unique name so nothing else resolves to it, and not *-symbolic so Plasma doesn't flatten its colors).
    kde = Path("/usr/share/icons/Papirus/48x48/apps/kde.svg")
    if kde.exists():
        logo = tint if pastel else mix(ctx["c"]["accent"], "#ffffff", 0.3)
        svg = kde.resolve().read_text().replace("fill:#2c9bff", "fill:#313135")
        svg = svg.replace('<path style="fill:#ffffff"', f'<path style="fill:{logo}"')
        (root / "scalable/apps").mkdir(parents=True, exist_ok=True)
        (root / f"scalable/apps/{_launcher_name(logo)}.svg").write_text(svg)
        dirs_extra = "scalable/apps"
        sections += "\n[scalable/apps]\nSize=48\nMinSize=8\nMaxSize=512\nType=Scalable\nContext=Applications\n"
    else:
        dirs_extra = ""
    # Everything except folders comes from Breeze Dark: flat, monochrome and FollowsColorScheme, so tray/popup
    # icons take the theme's text color (Papirus' colorful status icons looked out of place). Papirus-Dark is
    # only a fallback for app icons Breeze lacks. Header copied from breeze-dark so Plasma treats it the same.
    header = []
    for line in Path("/usr/share/icons/breeze-dark/index.theme").read_text().splitlines()[1:]:
        if line.startswith("[") or line.startswith(("Directories=", "ScaledDirectories=")):
            break
        if "=" in line and not line.startswith(("Name", "Comment", "Inherits", "#")):
            header.append(line)
    write(root / "index.theme",
          f"[Icon Theme]\nName={name}\nComment=plasma-themer: Breeze Dark + black pastel folders\n"
          f"Inherits=breeze-dark,Papirus-Dark,hicolor\n" + "\n".join(header) + "\n"
          f"Directories={','.join([d + '/places' for d in dirs] + ([dirs_extra] if dirs_extra else []))}\n"
          + sections)
    _apply_icon_theme(name)
    _set_launcher_icon(_launcher_name(tint if pastel else mix(ctx["c"]["accent"], "#ffffff", 0.3)))
    for old in (XDG_DATA / "icons").glob("Themer-Papirus-*"):
        if not old.name.endswith(f"-{ICON_OVERLAY_VERSION}"):  # only drop overlays from older versions
            shutil.rmtree(old, ignore_errors=True)
    return color


def _launcher_name(logo: str) -> str:
    # color in the name: Plasma caches icons by name, so a fixed name kept the previous theme's logo color
    return f"themer-start-{logo.lstrip('#')}"


LAUNCHER_JS = """
var ps = panels();
for (var i = 0; i < ps.length; i++) {
  var ws = ps[i].widgets();
  for (var j = 0; j < ws.length; j++) {
    var t = ws[j].type;
    if (t != "org.kde.plasma.kickoff" && t != "org.kde.plasma.kicker" && t != "org.kde.plasma.kickerdash") continue;
    ws[j].currentConfigGroup = ["General"];
    var cur = String(ws[j].readConfig("icon", ""));
    // only replace the stock KDE logo or our own badge, never an icon the user picked
    if (cur == "" || cur.indexOf("themer-start") == 0 || cur.indexOf("start-here-kde") == 0 || cur == "kde-symbolic" || cur == "kde") {
      ws[j].writeConfig("icon", "%s");
      ws[j].reloadConfig();
    }
  }
}
"""


def _set_launcher_icon(icon: str) -> None:
    run("gdbus", "call", "--session", "--dest", "org.kde.plasmashell", "--object-path", "/PlasmaShell",
        "--method", "org.kde.PlasmaShell.evaluateScript", LAUNCHER_JS % icon)


def _apply_icon_theme(name: str) -> None:
    # plasma-changeicons is ~0.5 s, but setting the key + broadcasting KIconLoader/KGlobalSettings signals
    # ourselves didn't reliably refresh running apps (Dolphin kept old folder colors), so only fall back to that.
    tool = changeicons_tool()
    if tool:
        run(tool, name, check=True)
        return
    kwrite("kdeglobals", ["Icons"], "Theme", name)
    run("dbus-send", "--session", "--type=signal", "/KIconLoader", "org.kde.KIconLoader.iconChanged", "int32:0")
    run("dbus-send", "--session", "--type=signal", "/KGlobalSettings", "org.kde.KGlobalSettings.notifyChange",
        "int32:4", "int32:0")


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
    # live: switch every open session (in-process D-Bus; one qdbus6 process per call is slow on weak CPUs)
    n = _konsole_set_profile_all("Themer")
    return f"{n} live sessions"


def _konsole_set_profile_all(profile: str) -> int:
    try:
        import dbus
        bus = dbus.SessionBus()
        n = 0
        for svc in bus.list_names():
            if not svc.startswith(("org.kde.konsole", "org.kde.yakuake")):
                continue
            xml = bus.get_object(svc, "/Sessions", introspect=False).Introspect(
                dbus_interface="org.freedesktop.DBus.Introspectable")
            for sid in re.findall(r'<node name="(\d+)"', str(xml)):  # ids have gaps after closed tabs
                obj = bus.get_object(svc, f"/Sessions/{sid}", introspect=False)
                obj.setProfile(profile, dbus_interface="org.kde.konsole.Session")
                n += 1
        return n
    except ImportError:
        n = 0
        for svc in run("qdbus6").stdout.split():
            if svc.startswith(("org.kde.konsole", "org.kde.yakuake")):
                for path in run("qdbus6", svc).stdout.split():
                    if re.fullmatch(r"/Sessions/\d+", path):
                        run("qdbus6", svc, path, "org.kde.konsole.Session.setProfile", profile)
                        n += 1
        return n


@target("alacritty")
def alacritty(t: Theme, ctx: dict, wallpaper: Path | None):
    theme_file = CURRENT / "alacritty.toml"
    write(theme_file, render("alacritty.toml", ctx))
    cfg = XDG_CONFIG / "alacritty/alacritty.toml"
    if not cfg.exists():
        font = "JetBrainsMono Nerd Font" if _font_installed("JetBrainsMono Nerd Font") else "monospace"
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
    return family.lower() in fonts()  # fc-list once per run, not per target


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
    # fish's `set` stops option parsing after the name, so --background=... values need no `--`
    script = "".join(f"set -U {k} {val}\n" for k, val in v.items())
    script += f"set -Ux FZF_DEFAULT_OPTS_FILE {CURRENT / 'fzf.opts'}\nset -Ux BAT_THEME ansi\n"
    # --no-config would also disable universal variables (fish 4), and the user's config.fish may run slow things
    # (a fetch on every start). So point fish at a throwaway config dir whose only file is a symlink to the real
    # fish_variables: no user config runs, and fish writes through the symlink to the real file.
    import tempfile
    real = XDG_CONFIG / "fish/fish_variables"
    script += "echo themer-ok >&2\n"
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "fish").mkdir()
        if real.exists():
            (Path(tmp) / "fish/fish_variables").symlink_to(real.resolve())
        env = {**os.environ, "XDG_CONFIG_HOME": tmp}
        r = subprocess.run(["fish", "-c", script], text=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.PIPE, timeout=15, env=env)
    if "themer-ok" not in r.stderr:
        raise RuntimeError(r.stderr.strip()[-300:] or f"fish exited {r.returncode}")


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
    for base in (XDG_CONFIG / "mozilla/firefox", HOME / ".mozilla/firefox",
                 HOME / "snap/firefox/common/.mozilla/firefox",              # Ubuntu's snap
                 HOME / ".var/app/org.mozilla.firefox/.mozilla/firefox"):   # Flatpak
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
    if have("pywalfox"):  # fire and forget: it only relays to the add-on
        subprocess.Popen(["pywalfox", "update"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    else:
        notes.append("pywalfox not installed (no live recolor)")
    return "; ".join(notes)


GEN_EXT_ID = "local.plasma-themer"


def _vscodium_ext_dir() -> Path:
    native = HOME / ".vscode-oss/extensions"
    flatpak = HOME / ".var/app/com.vscodium.codium/data/vscode/extensions"
    return flatpak if not native.exists() and flatpak.exists() else native


def _vscodium_generated_theme(ctx: dict) -> str:
    """Build a color theme from the palette (template from Omarchy) as a local extension. Returns its label."""
    import zlib
    base = _vscodium_ext_dir()
    theme = render("vscode-theme.json", {**ctx["c"], "theme_type": "dark"})
    # VSCodium caches themes per extension version, so derive the version from the content (as Omarchy does).
    version = f"1.0.{zlib.crc32(theme.encode())}"
    ext = base / f"{GEN_EXT_ID}-{version}"
    for old in base.glob(f"{GEN_EXT_ID}-*"):
        if old != ext:
            shutil.rmtree(old, ignore_errors=True)
    write(ext / "themes/plasma-themer-color-theme.json", theme)
    write(ext / "package.json", json.dumps({
        "name": "plasma-themer", "displayName": "Plasma Themer", "publisher": "local", "version": version,
        "description": "Generated from the active plasma-themer palette", "engines": {"vscode": "^1.70.0"},
        "categories": ["Themes"],
        "contributes": {"themes": [{"label": "Plasma Themer", "uiTheme": "vs-dark",
                                    "path": "./themes/plasma-themer-color-theme.json", "_watch": True}]},
    }, indent=2) + "\n")
    # register it, or VSCodium ignores the folder
    reg = base / "extensions.json"
    entries = json.loads(reg.read_text()) if reg.exists() else []
    entries = [e for e in entries if e.get("identifier", {}).get("id") != GEN_EXT_ID]
    entries.append({"identifier": {"id": GEN_EXT_ID}, "version": version,
                    "location": {"$mid": 1, "fsPath": str(ext), "external": f"file://{ext}", "path": str(ext),
                                 "scheme": "file"},
                    "relativeLocation": ext.name})
    write(reg, json.dumps(entries))
    return "Plasma Themer"


@target("vscodium")
def vscodium(t: Theme, ctx: dict, wallpaper: Path | None):
    settings = app_config(XDG_CONFIG / "VSCodium", "com.vscodium.codium", "VSCodium") / "User/settings.json"
    if not have("codium") and not settings.parent.parent.exists():
        return "skipped: VSCodium not installed"
    name = t.vscode.get("name") or _vscodium_generated_theme(ctx)
    txt = settings.read_text() if settings.exists() else "{\n}\n"
    entry = f'"workbench.colorTheme": {json.dumps(name, ensure_ascii=False)}'
    if re.search(r'"workbench\.colorTheme"\s*:', txt):
        txt = re.sub(r'"workbench\.colorTheme"\s*:\s*"[^"]*"', lambda m: entry, txt)
    else:
        txt = re.sub(r"^\s*\{", lambda m: "{\n  " + entry + ",", txt, count=1)
        txt = re.sub(r",(\s*)\}\s*$", r"\1}\n", txt)  # `{ "x": 1, }` if file was empty
    write(settings, txt)
    ext = t.vscode.get("extension")
    # check the extensions dir instead of `codium --list-extensions` (that boots Electron: ~0.3s fast PC, seconds slow)
    ext_dir = _vscodium_ext_dir()
    if ext and ext_dir.is_dir() and not any(d.name.lower().startswith(ext.lower() + "-") for d in ext_dir.iterdir()):
        return f"WARN: theme extension {ext} missing — run: themer setup"
    return "" if t.vscode.get("name") else "generated from palette"


@target("vesktop (discord)")
def vesktop(t: Theme, ctx: dict, wallpaper: Path | None):
    root = app_config(XDG_CONFIG / "vesktop", "dev.vencord.Vesktop", "vesktop")
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
    # One-time root setup (install/system-setup.sh) makes /var/lib/plasma-themer user-owned and points the login
    # manager at files in it, so switching needs no sudo:
    #   Plasma Login Manager: /etc/plasmalogin.conf -> login-background.jpg
    #   SDDM (Breeze theme):  breeze/theme.conf.user -> sddm-breeze.conf (symlink), which we rewrite here
    root = Path("/var/lib/plasma-themer")
    if not (root.is_dir() and os.access(root, os.W_OK)):
        return "skipped: run install/system-setup.sh once"
    if not wallpaper:
        return "no wallpaper"
    tmp = root / ".login-background.tmp.jpg"
    src = screen_wallpaper(wallpaper)  # already decoded + scaled once; this is just a file copy
    if src.suffix.lower() in (".jpg", ".jpeg"):
        shutil.copyfile(src, tmp)
    else:
        from PIL import Image
        with Image.open(src) as im:
            im.convert("RGB").save(tmp, quality=90)
    os.chmod(tmp, 0o644)
    tmp.replace(root / "login-background.jpg")
    if (root / "sddm-breeze.conf").exists():
        write(root / "sddm-breeze.conf", f"# plasma-themer: {t.name}\n[General]\ntype=image\n"
                                          f"background={root / 'login-background.jpg'}\ncolor={ctx['c']['accent']}\n")
        os.chmod(root / "sddm-breeze.conf", 0o644)
        return "sddm"
