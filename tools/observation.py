"""Observation: window/control info (no screenshot storage)."""

import ctypes

from pywinauto import Desktop


def _fg_handle():
    return ctypes.windll.user32.GetForegroundWindow()


def active_window():
    try:
        hwnd = _fg_handle()
        desktop = Desktop(backend="uia")
        win = desktop.window(handle=hwnd)
        rect = win.rectangle()
        return {
            "title": win.window_text(),
            "class": win.class_name(),
            "rect": [rect.left, rect.top, rect.right, rect.bottom],
        }
    except Exception as e:
        return {"error": str(e)}


def control_tree(title=None, depth=2, limit=60):
    try:
        desktop = Desktop(backend="uia")
        if title:
            win = desktop.window(title_re=".*%s.*" % title)
        else:
            win = desktop.window(handle=_fg_handle())
        win.wait("visible", timeout=5)
        items = []
        try:
            descendants = win.descendants(depth=depth)
        except Exception:
            descendants = []
        for c in descendants[:limit]:
            try:
                rect = c.rectangle()
                try:
                    ctype = c.element_info.control_type
                except Exception:
                    ctype = c.friendly_class_name()
                auto_id = c.automation_id() if callable(getattr(c, "automation_id", None)) else getattr(c, "automation_id", "")
                items.append({
                    "name": c.window_text(),
                    "type": ctype,
                    "auto_id": auto_id,
                    "rect": [rect.left, rect.top, rect.right, rect.bottom],
                })
            except Exception:
                continue
        return {"window": win.window_text(), "controls": items}
    except Exception as e:
        return {"error": str(e)}