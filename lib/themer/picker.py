"""Launch the QML overlay picker and apply whatever it selects."""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import threading

from PIL import Image

from .core import CACHE, REPO, list_themes, load_theme, state_get, state_set

THUMBS = CACHE / "thumbs"


def thumb(src, w=560, h=315):
    out = THUMBS / src.parent.parent.name / (src.stem + ".jpg")
    if not out.exists() or out.stat().st_mtime < src.stat().st_mtime:
        out.parent.mkdir(parents=True, exist_ok=True)
        im = Image.open(src).convert("RGB")
        r = max(w / im.width, h / im.height)
        im = im.resize((round(im.width * r), round(im.height * r)), Image.LANCZOS)
        left, top = (im.width - w) // 2, (im.height - h) // 2
        im.crop((left, top, left + w, top + h)).save(out, quality=88)
    return out


def build_data() -> dict:
    themes = []
    for slug in list_themes():
        t = load_theme(slug)
        bgs = t.backgrounds
        saved = state_get(f"bg/{slug}")
        names = [b.name for b in bgs]
        themes.append({
            "slug": slug,
            "name": t.name,
            "colors": {k: v for k, v in t.colors.items() if isinstance(v, str) and v.startswith("#")},
            "wallpapers": [{"file": b.name, "full": str(b), "thumb": str(thumb(b))} for b in bgs],
            "bg": names.index(saved) if saved in names else 0,
        })
    return {"current": state_get("current", ""), "themes": themes}


def run_picker(apply) -> int:
    CACHE.mkdir(parents=True, exist_ok=True)
    lock = open(CACHE / "picker.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return 0  # already open
    data_file = CACHE / "picker.json"
    data_file.write_text(json.dumps(build_data()))
    # QT_FORCE_STDERR_LOGGING: with a piped stderr Qt logs to journald instead, and we'd never see APPLY:
    env = {**os.environ, "QML_XHR_ALLOW_FILE_READ": "1", "QT_QUICK_CONTROLS_STYLE": "Basic",
           "QT_FORCE_STDERR_LOGGING": "1"}
    proc = subprocess.Popen(["qml6", str(REPO / "picker/Picker.qml"), "--", str(data_file)],
                            stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True, env=env)
    worker = None
    for line in proc.stderr:
        if "APPLY:" in line:
            slug, _, bg = line.split("APPLY:", 1)[1].strip().partition(":")
            if bg:
                state_set(f"bg/{slug}", bg)
            worker = threading.Thread(target=apply, args=(slug,), kwargs={"quiet": True})
            worker.start()
    proc.wait()
    if worker:
        worker.join()
    return 0
