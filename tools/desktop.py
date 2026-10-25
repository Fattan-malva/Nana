"""Aksi desktop Windows: buka app/URL/folder, fokus window, terminal."""

import ctypes
import os
import re
import shutil
import subprocess
import time
from ctypes import wintypes

from . import keyboard, safety

user32 = ctypes.WinDLL("user32", use_last_error=True)

SW_RESTORE = 9
CREATE_NEW_CONSOLE = 0x00000010
CREATE_NEW_PROCESS_GROUP = 0x00000200

EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.EnumWindows.argtypes = (EnumWindowsProc, wintypes.LPARAM)
user32.EnumWindows.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = (wintypes.HWND,)
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsIconic.argtypes = (wintypes.HWND,)
user32.IsIconic.restype = wintypes.BOOL
user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
user32.ShowWindow.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.BringWindowToTop.argtypes = (wintypes.HWND,)
user32.BringWindowToTop.restype = wintypes.BOOL
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.AttachThreadInput.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.BOOL)
user32.SwitchToThisWindow.argtypes = (wintypes.HWND, wintypes.BOOL)
user32.SwitchToThisWindow.restype = None
user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
user32.GetClassNameW.restype = ctypes.c_int


class DesktopError(Exception):
    pass


APPS = {
    "vscode": ["code"],
    "vs code": ["code"],
    "visual studio code": ["code"],
    "code": ["code"],
    "notepad": ["notepad.exe"],
    "explorer": ["explorer.exe"],
    "file explorer": ["explorer.exe"],
    "files": ["explorer.exe"],
    "calculator": ["calc.exe"],
    "calc": ["calc.exe"],
    "chrome": ["chrome.exe"],
    "google chrome": ["chrome.exe"],
    "edge": ["msedge.exe"],
    "microsoft edge": ["msedge.exe"],
    "task manager": ["taskmgr.exe"],
    "paint": ["mspaint.exe"],
    "settings": ["ms-settings:"],
    "terminal": ["wt.exe"],
    "windows terminal": ["wt.exe"],
    "cmd": ["cmd.exe"],
    "command prompt": ["cmd.exe"],
    "powershell": ["powershell.exe"],
}

TERMINAL_CLASSES = {
    "ConsoleWindowClass",
    "CASCADIA_HOSTING_WINDOW_CLASS",
    "mintty",
    "PuTTY",
    "VirtualConsole",
    "ConsoleWindowClass",
}


def _title(hwnd):
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _class(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def list_windows():
    windows = []

    def _cb(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            title = _title(hwnd).strip()
            if title:
                windows.append({"hwnd": int(hwnd), "title": title, "class": _class(hwnd)})
        return True

    user32.EnumWindows(EnumWindowsProc(_cb), 0)
    return windows


def foreground_info():
    hwnd = user32.GetForegroundWindow()
    title = _title(hwnd) if hwnd else ""
    cls = _class(hwnd) if hwnd else ""
    return {
        "hwnd": int(hwnd or 0),
        "title": title,
        "class": cls,
        "is_terminal": cls in TERMINAL_CLASSES,
    }


def _score(title, needle):
    t = title.lower()
    n = needle.lower().strip()
    if not n:
        return 0
    if t == n:
        return 100
    if t.startswith(n):
        return 80
    if n in t:
        return 60
    return 0


def _find_window(needle):
    best = None
    best_score = 0
    for win in list_windows():
        score = _score(win["title"], needle)
        if score > best_score:
            best, best_score = win, score
    return best


def _focus_handle(hwnd):
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.15)

    for attempt in range(2):
        if user32.GetForegroundWindow() == hwnd:
            return True

        fg = user32.GetForegroundWindow()
        target_thread = user32.GetWindowThreadProcessId(hwnd, None)
        fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0

        attached = False
        if fg_thread and target_thread and fg_thread != target_thread:
            attached = bool(user32.AttachThreadInput(fg_thread, target_thread, True))

        try:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(fg_thread, target_thread, False)

        time.sleep(0.2)
        if user32.GetForegroundWindow() == hwnd:
            return True

        # Fallback untuk kasus Windows menolak SetForegroundWindow.
        user32.SwitchToThisWindow(hwnd, True)
        time.sleep(0.2)
        if user32.GetForegroundWindow() == hwnd:
            return True

    return False


def focus_window(title):
    needle = str(title or "").strip()
    if not needle:
        raise DesktopError("judul window kosong")

    win = _find_window(needle)
    if not win:
        raise DesktopError(f"window '{needle}' tidak ditemukan")

    ok = _focus_handle(win["hwnd"])
    if not ok:
        raise DesktopError(f"gagal fokus ke '{win['title']}' (diblokir Windows)")
    return win["title"]


def _startfile(target):
    try:
        os.startfile(target)  # type: ignore[attr-defined]
    except OSError as e:
        raise DesktopError(f"gagal membuka {target}: {e}")


def _launch(candidates):
    last_error = None
    for cand in candidates:
        try:
            if cand.startswith(("http://", "https://", "ms-settings:")):
                _startfile(cand)
                return cand
            found = shutil.which(cand)
            if found:
                _startfile(found)
                return found
            if os.path.isfile(cand):
                _startfile(cand)
                return cand
            _startfile(cand)
            return cand
        except DesktopError as e:
            last_error = e
    raise last_error or DesktopError("aplikasi tidak ditemukan")


def open_app(name):
    key = re.sub(r"\s+", " ", str(name or "").strip().lower())
    if not key:
        raise DesktopError("nama aplikasi kosong")

    if not re.fullmatch(r"[a-zA-Z0-9 ._\-]+", key):
        raise DesktopError("nama aplikasi tidak valid")

    if key in ("vscode", "vs code", "code", "visual studio code"):
        exe = _vscode_exe()
        if exe:
            _startfile(exe)
            return exe

    candidates = APPS.get(key, [key])
    launched = _launch(candidates)
    return launched


def open_url(url):
    target = str(url or "").strip()
    if not target.lower().startswith(("http://", "https://")):
        raise DesktopError("hanya URL http/https yang diizinkan")
    _startfile(target)
    return target


def open_folder(path):
    p = safety.check_user_path(path)
    if not os.path.isdir(p):
        raise DesktopError(f"bukan folder: {p}")
    _startfile(p)
    return p


def _vscode_exe():
    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
        r"C:\Program Files\Microsoft VS Code\Code.exe",
        r"C:\Program Files (x86)\Microsoft VS Code\Code.exe",
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path

    found = shutil.which("code")
    if found:
        base = os.path.dirname(os.path.dirname(found))
        exe = os.path.join(base, "Code.exe")
        if os.path.isfile(exe):
            return exe
    return None


def open_in_vscode(path):
    p = safety.check_user_path(path)
    exe = _vscode_exe()
    if not exe:
        raise DesktopError("VS Code tidak ditemukan")
    subprocess.Popen(
        [exe, "--reuse-window", p],
        creationflags=CREATE_NEW_PROCESS_GROUP,
    )
    return p


def open_terminal(target="vscode"):
    key = re.sub(r"\s+", " ", str(target or "").strip().lower())

    if key in ("vscode", "vs code", "code", "visual studio code"):
        if not _find_window("Visual Studio Code"):
            open_app("vscode")
            deadline = time.time() + 8.0
            while time.time() < deadline and not _find_window("Visual Studio Code"):
                time.sleep(0.3)
        if not _find_window("Visual Studio Code"):
            raise DesktopError("VS Code tidak terbuka")

        focus_window("Visual Studio Code")
        time.sleep(0.35)
        # Ctrl+Shift+` = "Terminal: Create New Terminal" (selalu membuka panel)
        keyboard.press_key("ctrl+shift+`")
        return "terminal VS Code"

    if key in ("cmd", "command prompt", "command"):
        subprocess.Popen(["cmd.exe"], creationflags=CREATE_NEW_CONSOLE)
        return "Command Prompt"

    if key in ("powershell", "pwsh"):
        subprocess.Popen(["powershell.exe"], creationflags=CREATE_NEW_CONSOLE)
        return "PowerShell"

    if key in ("terminal", "windows terminal", "wt"):
        try:
            os.startfile("wt.exe")  # type: ignore[attr-defined]
            return "Windows Terminal"
        except OSError:
            subprocess.Popen(["cmd.exe"], creationflags=CREATE_NEW_CONSOLE)
            return "Command Prompt"

    raise DesktopError(f"terminal '{target}' tidak dikenal")


def wait(ms):
    try:
        value = int(ms)
    except (TypeError, ValueError):
        raise DesktopError("durasi harus angka (ms)")
    value = max(100, min(3000, value))
    time.sleep(value / 1000.0)
    return value
