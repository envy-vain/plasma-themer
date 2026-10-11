"""One-time wiring (themer setup) and diagnostics (themer doctor)."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from .core import HOME, REPO, kwrite, qml_runtime, XDG_CONFIG, XDG_DATA, have, list_themes, load_theme, run, state_get
from .targets import _firefox_profile, _icon_theme_exists

# Qt key codes: Meta | Ctrl | Shift | Space
META, CTRL, SHIFT, ALT, SPACE = 0x10000000, 0x04000000, 0x02000000, 0x08000000, 0x20

SHORTCUTS = [
    # desktop id, name, exec, key
    ("themer-picker.desktop", "Theme picker", "themer pick", META | CTRL | SHIFT | SPACE),
    ("themer-bg-next.desktop", "Next wallpaper", "themer bg next", META | CTRL | SPACE),
    ("themer-next.desktop", "Next theme", "themer next", META | CTRL | ALT | SPACE),
]


def _keyname(key: int) -> str:
    mods = [n for bit, n in ((META, "Meta"), (CTRL, "Ctrl"), (ALT, "Alt"), (SHIFT, "Shift")) if key & bit]
    return "+".join(mods + ["Space"])


def _bin() -> str:
    p = HOME / ".local/bin/themer"
    return str(p) if p.exists() else str(REPO / "bin/themer")


def shortcuts() -> list[str]:
    apps = XDG_DATA / "applications"
    apps.mkdir(parents=True, exist_ok=True)
    out = []
    for did, name, cmd, key in SHORTCUTS:
        (apps / did).write_text(
            "[Desktop Entry]\nType=Application\n"
            f"Name=Themer: {name}\nExec={_bin()} {cmd.split(' ', 1)[1]}\n"
            "Icon=preferences-desktop-color\nNoDisplay=true\nX-KDE-GlobalAccel-CommandShortcut=true\n")
        ident = f"['{did}', '_launch', '{name}', '{name}']"
        run("gdbus", "call", "--session", "--dest", "org.kde.kglobalaccel", "--object-path", "/kglobalaccel",
            "--method", "org.kde.KGlobalAccel.doRegister", ident)
        # flags 2|4 = SetPresent | NoAutoloading: marks the action active now, not just stored
        r = run("gdbus", "call", "--session", "--dest", "org.kde.kglobalaccel", "--object-path", "/kglobalaccel",
                "--method", "org.kde.KGlobalAccel.setShortcut", ident, f"[{key}]", "uint32 6")
        # persist so the binding survives re-login (kglobalaccel loads [services] at startup)
        kwrite("kglobalshortcutsrc", ["services", did], "_launch", _keyname(key))
        out.append(f"{name} ({_keyname(key)}): {'ok' if r.returncode == 0 else r.stderr.strip()}")
    run("kbuildsycoca6")
    return out


def vscodium_extensions() -> list[str]:
    if not have("codium"):
        return ["VSCodium not installed — skipped"]
    have_ext = run("codium", "--list-extensions").stdout.lower().split()
    out = []
    for slug in list_themes():
        ext = load_theme(slug).vscode.get("extension")
        if ext and ext.lower() not in have_ext:
            r = run("codium", "--install-extension", ext)
            out.append(f"{ext}: {'installed' if r.returncode == 0 else 'FAILED (not on Open VSX?)'}")
    return out or ["all theme extensions present"]


def pywalfox() -> list[str]:
    if not have("pywalfox"):
        return ["pywalfox not installed — skipped"]
    run("pywalfox", "install")
    # Firefox using the XDG profile dir looks for native hosts under ~/.config/mozilla too
    src = HOME / ".mozilla/native-messaging-hosts/pywalfox.json"
    if src.exists():
        dst = XDG_CONFIG / "mozilla/native-messaging-hosts/pywalfox.json"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return ["native host installed — now add the add-on: https://addons.mozilla.org/firefox/addon/pywalfox/"]


def launcher_icon() -> list[str]:
    """The launcher badge is (re)applied by the icons target on every switch; run it once now."""
    cur = state_get("current")
    if not cur:
        return ["no theme applied yet"]
    from .cli import apply
    apply(cur, {"icons"}, quiet=True)
    return ["launcher set to the black KDE badge"]


def prebake() -> list[str]:
    from .picker import warm
    return [f"{warm()} wallpaper(s) scaled + picker art baked"]


def setup() -> int:
    for title, fn in (("Shortcuts", shortcuts), ("VSCodium", vscodium_extensions), ("Pywalfox", pywalfox),
                      ("Wallpaper cache", prebake), ("Launcher icon", launcher_icon)):
        print(f"\033[1m{title}\033[0m")
        for line in fn():
            print("  " + line)
    if not state_get("current"):
        print("\nNo theme applied yet — try: themer pick")
    return 0


def doctor() -> int:
    checks = [
        ("QML runtime (picker)", bool(qml_runtime())),
        ("Papirus icons", Path("/usr/share/icons/Papirus").is_dir()),
        ("Bibata cursors", _icon_theme_exists("Bibata-Modern-Ice")),
        ("JetBrainsMono Nerd Font", "jetbrainsmono nerd" in run("fc-list").stdout.lower()),
        ("Firefox profile", bool(_firefox_profile())),
        ("pywalfox", have("pywalfox")),
        ("VSCodium", have("codium")),
        ("Vesktop", have("vesktop") or (XDG_CONFIG / "vesktop").is_dir()),
        ("login screen", os.access("/var/lib/plasma-themer", os.W_OK)),
        ("shortcuts", (XDG_DATA / "applications/themer-picker.desktop").exists()),
    ]
    for name, ok in checks:
        print(f"  {'\033[32m✓' if ok else '\033[33m–'}\033[0m {name}")
    print(f"  current theme: {state_get('current', 'none')}")
    return 0
