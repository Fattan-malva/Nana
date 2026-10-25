"""Verification helpers: check real outcomes (window, file, process)."""

import os

import psutil

from . import desktop


def verify_window(title):
    wins = desktop.list_windows()
    matches = [w for w in wins if title.lower() in w["title"].lower()]
    if matches:
        return {"ok": True, "message": "window ditemukan", "matches": [w["title"] for w in matches[:5]]}
    return {"ok": False, "message": "window tidak ditemukan"}


def verify_file(path):
    p = os.path.expandvars(os.path.expanduser(str(path or "")))
    if os.path.exists(p):
        return {"ok": True, "message": "path ada", "path": p, "is_dir": os.path.isdir(p)}
    return {"ok": False, "message": "path tidak ada"}


def verify_process(name):
    target = str(name or "").lower()
    for proc in psutil.process_iter(["name"]):
        try:
            if target in (proc.info.get("name") or "").lower():
                return {"ok": True, "message": "proses berjalan", "pid": proc.pid}
        except Exception:
            continue
    return {"ok": False, "message": "proses tidak berjalan"}
