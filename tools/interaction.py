"""Universal interaction helpers using UI Automation with fallbacks."""

import ctypes
import time

from pywinauto import Desktop


def _window(title=None):
    desktop = Desktop(backend="uia")
    if title:
        return desktop.window(title_re=".*%s.*" % title)
    return desktop.window(handle=ctypes.windll.user32.GetForegroundWindow())


def click_control(window_title=None, name=None, auto_id=None, control_type=None):
    try:
        win = _window(window_title)
        win.wait("visible", timeout=5)
        kwargs = {}
        if name:
            kwargs["title"] = name
        if auto_id:
            kwargs["auto_id"] = auto_id
        if control_type:
            kwargs["control_type"] = control_type
        ctrl = win.child_window(**kwargs)
        ctrl.wait("visible", timeout=5)
        ctrl.click_input()
        return {"ok": True, "message": "klik berhasil"}
    except Exception as e:
        return {"ok": False, "message": str(e)}


def type_control(window_title=None, name=None, auto_id=None, text=""):
    try:
        win = _window(window_title)
        win.wait("visible", timeout=5)
        kwargs = {}
        if name:
            kwargs["title"] = name
        if auto_id:
            kwargs["auto_id"] = auto_id
        ctrl = win.child_window(**kwargs)
        ctrl.wait("visible", timeout=5)
        ctrl.set_edit_text(text)
        return {"ok": True, "message": "teks diisi"}
    except Exception as e:
        return {"ok": False, "message": str(e)}


def click_at(x, y, button="left"):
    try:
        import ctypes
        ctypes.windll.user32.SetCursorPos(int(x), int(y))
        time.sleep(0.05)
        if button == "right":
            ctypes.windll.user32.mouse_event(0x0008, 0, 0, 0, 0)  # right down
            ctypes.windll.user32.mouse_event(0x0010, 0, 0, 0, 0)  # right up
        else:
            ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)  # left down
            ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)  # left up
        return {"ok": True, "message": "klik di koordinat dilakukan"}
    except Exception as e:
        return {"ok": False, "message": str(e)}


def wait_for_control(window_title=None, name=None, auto_id=None, timeout=8.0):
    deadline = time.time() + float(timeout)
    while time.time() < deadline:
        try:
            win = _window(window_title)
            kwargs = {}
            if name:
                kwargs["title"] = name
            if auto_id:
                kwargs["auto_id"] = auto_id
            ctrl = win.child_window(**kwargs)
            if ctrl.exists(timeout=0.5):
                return {"ok": True, "message": "kontrol ditemukan"}
        except Exception:
            pass
        time.sleep(0.3)
    return {"ok": False, "message": "kontrol tidak ditemukan (timeout)"}


def dismiss_dialog(key="esc"):
    try:
        import ctypes
        # VK_ESCAPE = 0x1B
        ctypes.windll.user32.keybd_event(0x1B, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0x1B, 0, 2, 0)
        return {"ok": True, "message": "dialog ditutup (Esc)"}
    except Exception as e:
        return {"ok": False, "message": str(e)}


def scroll(direction="down", amount=3):
    # Fallback: gunakan keyboard PageDown/PageUp
    try:
        import ctypes
        VK_NEXT = 0x22
        VK_PRIOR = 0x21
        key = VK_NEXT if direction in ("down", "right") else VK_PRIOR
        for _ in range(max(1, int(amount))):
            ctypes.windll.user32.keybd_event(key, 0, 0, 0)
            ctypes.windll.user32.keybd_event(key, 0, 2, 0)
            time.sleep(0.05)
        return {"ok": True, "message": "scroll dilakukan"}
    except Exception as e:
        return {"ok": False, "message": str(e)}
