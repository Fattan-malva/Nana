"""Recovery helpers: safe retries and focus recovery."""

import time

from tools import desktop


def retry_action(fn, attempts=2, delay=0.5):
    last = None
    for i in range(max(1, attempts)):
        try:
            res = fn()
            if isinstance(res, dict) and res.get("ok") is False:
                last = res
            else:
                return res if res is not None else {"ok": True, "message": "ok"}
        except Exception as e:
            last = {"ok": False, "message": str(e)}
        time.sleep(delay)
    return last or {"ok": False, "message": "gagal setelah retry"}


def recover_focus(title):
    try:
        desktop.focus_window(title)
        return {"ok": True, "message": "fokus dipulihkan"}
    except Exception as e:
        return {"ok": False, "message": str(e)}
