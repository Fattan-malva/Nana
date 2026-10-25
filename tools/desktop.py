"""Aksi desktop Windows: buka app/URL/folder, fokus window, terminal.

Mapping aplikasi dibangun dinamis saat modul dimuat: daftar semua aplikasi
yang terpasang di laptop user (Start Menu, registry, Get-StartApps) dipindai,
lalu disimpan ke JSON (apps_map.json). Saat membuka app/terminal/folder,
hanya yang tersedia secara dinamis yang dipakai. Tersedia juga close_app/close_window."""

import ctypes
import json
import os
import re
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
from ctypes import wintypes

from . import keyboard, safety

user32 = ctypes.WinDLL("user32", use_last_error=True)

SW_RESTORE = 9
WM_CLOSE = 0x0010
CREATE_NEW_CONSOLE = 0x00000010
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

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


class AmbiguousError(DesktopError):
    """Dilempar saat ada beberapa kandidat mirip (app/folder)."""

    def __init__(self, message, candidates):
        super().__init__(message)
        self.candidates = list(candidates or [])


# Tidak ada daftar statis; mapping sepenuhnya dinamis dari aplikasi terpasang.

# Path file JSON untuk cache mapping dinamis.
APPS_MAP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "apps_map.json")

# Mapping dinamis: nama ternormalisasi -> target peluncuran (exe path / appid / perintah).
_dynamic_apps = {}


def _normalize(name):
    return re.sub(r"\s+", " ", str(name or "").strip().lower())


def _run_ps(script):
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=CREATE_NO_WINDOW,
        )
        return result.stdout or ""
    except Exception:
        return ""


def _parse_ps_json(out):
    out = (out or "").strip()
    if not out:
        return []
    try:
        data = json.loads(out)
    except Exception:
        # Coba baris per baris (beberapa cmdlet mengeluarkan banyak objek).
        items = []
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except Exception:
                pass
        return items
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return data
    return []


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
    terminal_markers = ("console", "terminal", "cmd", "powershell", "mintty", "putty", "cascadia")
    low_cls = (cls or "").lower()
    low_title = (title or "").lower()
    is_terminal = any(m in low_cls or m in low_title for m in terminal_markers)
    return {
        "hwnd": int(hwnd or 0),
        "title": title,
        "class": cls,
        "is_terminal": is_terminal,
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
        # Fallback via pywinauto (lebih andal).
        try:
            from pywinauto import Desktop as _PwDesktop
            pw = _PwDesktop(backend="uia").window(handle=win["hwnd"])
            pw.set_focus()
            time.sleep(0.2)
            ok = True
        except Exception:
            ok = False
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


def _launch_target(target):
    """Luncurkan target dinamis (exe path / appid / perintah)."""
    target = str(target or "").strip()
    if not target:
        raise DesktopError("target aplikasi kosong")

    if target.startswith(("http://", "https://", "ms-settings:")):
        _startfile(target)
        return target

    # UWP app id (mengandung '!') -> buka via shell:AppsFolder
    if "!" in target and not os.path.isfile(target):
        subprocess.Popen(
            ["explorer.exe", "shell:AppsFolder\\%s" % target],
            creationflags=CREATE_NO_WINDOW,
        )
        return target

    found = shutil.which(target)
    if found:
        _startfile(found)
        return found

    if os.path.isfile(target):
        _startfile(target)
        return target

    # Coba sebagai app id generik.
    if "\\" not in target and not target.lower().endswith(".exe"):
        try:
            subprocess.Popen(
                ["explorer.exe", "shell:AppsFolder\\%s" % target],
                creationflags=CREATE_NO_WINDOW,
            )
            return target
        except Exception:
            pass

    _startfile(target)
    return target


def _lookup_app(key):
    """Cari target di map dinamis (exact lalu fuzzy contains)."""
    if key in _dynamic_apps:
        return _dynamic_apps[key]
    best = None
    for k, v in _dynamic_apps.items():
        if key in k or k in key:
            if best is None or len(k) < len(best[0]):
                best = (k, v)
    return best[1] if best else None


def _app_candidates(key):
    """Kembalikan list (nama, target) kandidat mirip untuk key."""
    if key in _dynamic_apps:
        return [(key, _dynamic_apps[key])]
    matches = [(k, v) for k, v in _dynamic_apps.items() if (key in k or k in key)]
    matches.sort(key=lambda x: (len(x[0]), x[0]))
    return matches


def refresh_app_map():
    """Pindai aplikasi terpasang di laptop user dan simpan ke JSON."""
    global _dynamic_apps

    mapping = {}

    # 1) Get-StartApps (Windows 8+): mencakup Win32 + UWP.
    out = _run_ps("Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Depth 2")
    for item in _parse_ps_json(out):
        name = _normalize(item.get("Name", ""))
        appid = str(item.get("AppID", "")).strip()
        if name and appid:
            # Jangan timpa entri yang sudah ada (statis lebih spesifik).
            mapping.setdefault(name, appid)

    # 2) Shortcut Start Menu -> resolve target exe.
    shortcut_script = r'''
$shell = New-Object -ComObject WScript.Shell
$paths = @("$env:ProgramData\Microsoft\Windows\Start Menu\Programs","$env:APPDATA\Microsoft\Windows\Start Menu\Programs")
$items = @()
foreach ($p in $paths) {
  if (Test-Path $p) {
    Get-ChildItem -Path $p -Recurse -Filter *.lnk -ErrorAction SilentlyContinue | ForEach-Object {
      try {
        $sc = $shell.CreateShortcut($_.FullName)
        if ($sc.TargetPath) {
          $items += [PSCustomObject]@{ Name = $_.BaseName; Target = $sc.TargetPath }
        }
      } catch {}
    }
  }
}
$items | ConvertTo-Json -Depth 2
'''
    out = _run_ps(shortcut_script)
    for item in _parse_ps_json(out):
        name = _normalize(item.get("Name", ""))
        target = str(item.get("Target", "")).strip()
        if name and target:
            low = target.lower()
            if low.endswith(".exe") or os.path.isfile(target):
                # Shortcut lebih langsung -> timpa.
                mapping[name] = target

    # 3) Registry uninstall -> DisplayIcon exe.
    registry_script = r'''
$roots = @(
 "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
 "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
 "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*"
)
$items = @()
foreach ($r in $roots) {
  Get-ItemProperty $r -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName } | ForEach-Object {
    $target = $null
    if ($_.DisplayIcon) { $target = ($_.DisplayIcon -split ',')[0].Trim().Trim('"') }
    if ($target -and $target.ToLower().EndsWith('.exe')) {
      $items += [PSCustomObject]@{ Name = $_.DisplayName; Target = $target }
    }
  }
}
$items | ConvertTo-Json -Depth 2
'''
    out = _run_ps(registry_script)
    for item in _parse_ps_json(out):
        name = _normalize(item.get("Name", ""))
        target = str(item.get("Target", "")).strip()
        if name and target and target.lower().endswith(".exe"):
            mapping.setdefault(name, target)

    # Bersihkan entri kosong.
    mapping = {k: v for k, v in mapping.items() if k and v}

    # Simpan ke JSON.
    try:
        with open(APPS_MAP_PATH, "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    _dynamic_apps = mapping
    return mapping


def open_app(name):
    key = _normalize(name)
    if not key:
        raise DesktopError("nama aplikasi kosong")

    if not re.fullmatch(r"[a-zA-Z0-9 ._\-]+", key):
        raise DesktopError("nama aplikasi tidak valid")

    if key in ("vscode", "vs code", "code", "visual studio code"):
        exe = _vscode_exe()
        if exe:
            _startfile(exe)
            return exe

    matches = _app_candidates(key)
    if not matches:
        # Fallback terakhir: coba nama mentah sebagai perintah.
        launched = _launch([key])
        return launched

    if len(matches) == 1:
        return _launch_target(matches[0][1])

    # Ambigu: beberapa aplikasi mirip.
    opts = ", ".join(m[0] for m in matches[:10])
    raise AmbiguousError(
        f"beberapa aplikasi mirip '{name}': {opts}. Tanyakan pilihan ke user.",
        [m[0] for m in matches[:10]],
    )


def open_url(url):
    target = str(url or "").strip()
    if not target.lower().startswith(("http://", "https://")):
        raise DesktopError("hanya URL http/https yang diizinkan")
    _startfile(target)
    return target


def _resolve_folder(path):
    """Resolve path folder secara toleran (case/spasi) ke path yang benar-benar ada."""
    raw = os.path.expandvars(os.path.expanduser(str(path or "").strip().strip('"').strip("'")))
    if os.path.isdir(raw):
        return raw

    # Coba normalisasi spasi (collapse) pada tiap komponen.
    parts = re.split(r"[\\/]+", raw)
    norm_parts = [re.sub(r"\s+", " ", p.strip()) for p in parts if p.strip()]
    cand = os.path.join(*norm_parts) if norm_parts else raw
    if os.path.isdir(cand):
        return cand

    # Pencarian fuzzy di root umum untuk nama folder (toleran huruf/spasi).
    target_name = _normalize(os.path.basename(raw.rstrip("\\/")))
    if not target_name:
        return raw

    roots = []
    home = os.path.expanduser("~")
    roots.append(home)
    for sub in ("Desktop", "Documents", "Downloads", "OneDrive", "Pictures", "Music", "Videos"):
        p = os.path.join(home, sub)
        if os.path.isdir(p):
            roots.append(p)
    # Juga coba parent dari path asli jika ada.
    parent = os.path.dirname(raw)
    if os.path.isdir(parent):
        roots.append(parent)

    matches = []
    for root in roots:
        try:
            for dirpath, dirnames, _ in os.walk(root):
                depth = dirpath[len(root):].count(os.sep)
                if depth > 3:
                    dirnames[:] = []
                    continue
                for d in list(dirnames):
                    if _normalize(d) == target_name or target_name in _normalize(d):
                        matches.append(os.path.join(dirpath, d))
        except Exception:
            continue

    if matches:
        return min(matches, key=lambda x: (len(x), x))

    return raw


def _find_folders(path):
    """Kembalikan list path folder kandidat (fuzzy) untuk input path."""
    raw = os.path.expandvars(os.path.expanduser(str(path or "").strip().strip('"').strip("'")))
    if os.path.isdir(raw):
        return [raw]

    parts = re.split(r"[\\/]+", raw)
    norm_parts = [re.sub(r"\s+", " ", p.strip()) for p in parts if p.strip()]
    cand = os.path.join(*norm_parts) if norm_parts else raw
    if os.path.isdir(cand):
        return [cand]

    target_name = _normalize(os.path.basename(raw.rstrip("\\/")))
    if not target_name:
        return []

    roots = []
    home = os.path.expanduser("~")
    roots.append(home)
    for sub in ("Desktop", "Documents", "Downloads", "OneDrive", "Pictures", "Music", "Videos"):
        p = os.path.join(home, sub)
        if os.path.isdir(p):
            roots.append(p)
    parent = os.path.dirname(raw)
    if os.path.isdir(parent):
        roots.append(parent)

    matches = []
    seen = set()
    for root in roots:
        try:
            for dirpath, dirnames, _ in os.walk(root):
                depth = dirpath[len(root):].count(os.sep)
                if depth > 3:
                    dirnames[:] = []
                    continue
                for d in list(dirnames):
                    if _normalize(d) == target_name or target_name in _normalize(d):
                        full = os.path.join(dirpath, d)
                        if full not in seen:
                            seen.add(full)
                            matches.append(full)
        except Exception:
            continue
    return matches


def open_folder(path):
    raw = os.path.expandvars(os.path.expanduser(str(path or "").strip().strip('"').strip("'")))

    if os.path.isdir(raw):
        p = raw
    else:
        parts = re.split(r"[\\/]+", raw)
        norm_parts = [re.sub(r"\s+", " ", p.strip()) for p in parts if p.strip()]
        cand = os.path.join(*norm_parts) if norm_parts else raw
        if os.path.isdir(cand):
            p = cand
        else:
            matches = _find_folders(raw)
            if len(matches) > 1:
                raise AmbiguousError(
                    f"beberapa folder mirip '{path}': {', '.join(matches[:10])}. Tanyakan pilihan ke user.",
                    matches[:10],
                )
            if len(matches) == 1:
                p = matches[0]
            else:
                p = raw

    p = safety.check_user_path(p)
    if not os.path.isdir(p):
        raise DesktopError(f"bukan folder: {p}")
    _startfile(p)
    return p


def close_window(title):
    needle = str(title or "").strip()
    if not needle:
        raise DesktopError("judul window kosong")

    win = _find_window(needle)
    if not win:
        raise DesktopError(f"window '{needle}' tidak ditemukan")

    user32.PostMessageW(win["hwnd"], WM_CLOSE, 0, 0)
    return win["title"]


def close_tab(title=None, count=1):
    needle = str(title or "").strip().lower()
    try:
        count = int(count)
    except (TypeError, ValueError):
        count = 1
    count = max(1, min(20, count))

    closed = []
    for i in range(count):
        browser_wins = []
        for w in list_windows():
            t = w["title"].lower()
            if any(b in t for b in ("chrome", "edge", "firefox", "brave", "opera")):
                browser_wins.append(w)

        target_win = None
        if needle and i == 0:
            for w in browser_wins:
                if needle in w["title"].lower():
                    target_win = w
                    break
        if target_win is None and browser_wins:
            target_win = browser_wins[0]
        if target_win is None:
            raise DesktopError("window browser tidak ditemukan")

        try:
            from pywinauto import Desktop as _PwDesktop
            pw = _PwDesktop(backend="uia").window(handle=target_win["hwnd"])
            pw.set_focus()
            time.sleep(0.25)
            if i == 0 and needle:
                tabs = [t for t in pw.descendants() if getattr(t.element_info, "control_type", "") == "TabItem"]
                for t in tabs:
                    if needle in (t.window_text() or "").lower():
                        try:
                            t.select()
                        except Exception:
                            try:
                                t.click_input()
                            except Exception:
                                pass
                        time.sleep(0.4)
                        break
            try:
                pw.set_focus()
            except Exception:
                pass
        except Exception:
            try:
                focus_window(target_win["title"])
            except Exception:
                pass
            time.sleep(0.2)

        time.sleep(0.15)
        keyboard.press_key("ctrl+w")
        closed.append(target_win["title"])
        time.sleep(0.8)

    return ", ".join(closed)

def close_browser(title=None):
    needle = str(title or "").strip()
    win = None
    if needle:
        win = _find_window(needle)
    if not win:
        for cand in ("Google Chrome", "Chrome", "Microsoft Edge", "Edge", "Mozilla Firefox", "Firefox"):
            win = _find_window(cand)
            if win:
                break
    if not win:
        raise DesktopError("window browser tidak ditemukan")
    user32.PostMessageW(win["hwnd"], WM_CLOSE, 0, 0)
    return win["title"]


def close_app(name):
    key = _normalize(name)
    if not key:
        raise DesktopError("nama aplikasi kosong")

    # Utamakan menutup window yang cocok (WM_CLOSE, lebih sopan).
    win = _find_window(name)
    if win:
        user32.PostMessageW(win["hwnd"], WM_CLOSE, 0, 0)
        return win["title"]

    # Fallback: taskkill berdasarkan exe dari map dinamis.
    target = _lookup_app(key)
    if target:
        base = os.path.basename(str(target)).lower()
        if base.endswith(".exe"):
            try:
                subprocess.run(
                    ["taskkill", "/IM", base, "/F"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                    creationflags=CREATE_NO_WINDOW,
                )
                return base
            except Exception as e:
                raise DesktopError(f"gagal menutup {base}: {e}")

    raise DesktopError(f"aplikasi '{name}' tidak ditemukan untuk ditutup")


def _vscode_exe():
    # Hanya dari map dinamis + PATH (tanpa path hardcoded).
    for k in ("visual studio code", "vscode", "vs code", "code"):
        if k in _dynamic_apps:
            t = _dynamic_apps[k]
            if isinstance(t, str) and t.lower().endswith("code.exe") and os.path.isfile(t):
                return t
            # Jika target adalah app id/perintah, coba resolve via which.
            if isinstance(t, str):
                found = shutil.which(t)
                if found:
                    base = os.path.dirname(os.path.dirname(found))
                    exe = os.path.join(base, "Code.exe")
                    if os.path.isfile(exe):
                        return exe

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
    key = _normalize(target)

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

    # Dinamis: cari terminal/aplikasi di map yang tersedia.
    t = _lookup_app(key)
    if t is not None:
        return _launch_target(t)

    launched = _launch([key])
    return launched


# (dihapus: gunakan browser_open/search manual agar interaktif)


# (dihapus: gunakan browser_open/search manual agar interaktif)


def _ab_bin():
    found = shutil.which("agent-browser")
    if found:
        return found
    # Windows: agent-browser.cmd
    found = shutil.which("agent-browser.cmd")
    if found:
        return found
    return None


def _run_ab(args):
    bin_path = _ab_bin()
    if not bin_path:
        raise DesktopError("agent-browser tidak terpasang")
    try:
        result = subprocess.run(
            [bin_path] + list(args),
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=CREATE_NO_WINDOW,
        )
        out = (result.stdout or "").strip()
        err = (result.stderr or "").strip()
        if result.returncode != 0 and not out:
            raise DesktopError(err or "agent-browser gagal")
        return out if out else (err or "ok")
    except subprocess.TimeoutExpired:
        raise DesktopError("agent-browser timeout")
    except Exception as e:
        raise DesktopError(f"agent-browser error: {e}")


def browser_open(url):
    target = str(url or "").strip()
    if not target.lower().startswith(("http://", "https://")):
        raise DesktopError("hanya URL http/https yang diizinkan")
    return _run_ab(["open", target])


def browser_snapshot(interactive=True):
    args = ["snapshot"]
    if interactive:
        args.append("-i")
    return _run_ab(args)


def browser_click(ref):
    r = str(ref or "").strip()
    if not r:
        raise DesktopError("ref/selector kosong")
    return _run_ab(["click", r])


def browser_type(ref, text):
    r = str(ref or "").strip()
    if not r:
        raise DesktopError("ref kosong")
    return _run_ab(["fill", r, str(text or "")])


def browser_press(key):
    k = str(key or "").strip()
    if not k:
        raise DesktopError("tombol kosong")
    return _run_ab(["press", k])


def browser_scroll(direction, amount=None):
    d = str(direction or "").strip().lower()
    if d not in ("up", "down", "left", "right"):
        raise DesktopError("arah scroll tidak valid")
    args = ["scroll", d]
    if amount is not None:
        args.append(str(amount))
    return _run_ab(args)


def browser_close():
    return _run_ab(["close"])


def search_web(query):
    """Cari di web dan buka hasil pertama (generik, dinamis via Google I'm Feeling Lucky)."""
    q = str(query or "").strip()
    if not q:
        raise DesktopError("query kosong")
    lucky = "https://www.google.com/search?q=%s&btnI=1" % urllib.parse.quote(q)
    target = lucky
    try:
        req = urllib.request.Request(lucky, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            final = resp.geturl()
            html = resp.read().decode("utf-8", errors="ignore")
        if final and "google.com/url" in final:
            m = re.search(r"https?://(?!www\.google\.com)[^\s\"<>]+", html)
            if m:
                target = m.group(0)
        elif "Redirect Notice" in html or "Notifikasi Pengalihan" in html:
            m = re.search(r"https?://(?!www\.google\.com)[^\s\"<>]+", html)
            if m:
                target = m.group(0)
        else:
            target = final or lucky
    except Exception:
        target = lucky
    # Reuse tab browser yang sudah terbuka jika ada, agar tidak menambah tab baru.
    browser_win = None
    for w in list_windows():
        t = w["title"].lower()
        if any(b in t for b in ("chrome", "edge", "firefox", "brave", "opera")):
            browser_win = w
            break
    if browser_win is not None:
        try:
            from pywinauto import Desktop as _PwDesktop
            pw = _PwDesktop(backend="uia").window(handle=browser_win["hwnd"])
            pw.set_focus()
            time.sleep(0.3)
            keyboard.press_key("ctrl+l")
            time.sleep(0.2)
            keyboard.type_text(target)
            time.sleep(0.1)
            keyboard.press_key("enter")
            return target
        except Exception:
            pass
    open_url(target)
    return target


def volume_up(steps=1):
    for _ in range(max(1, int(steps))):
        user32.keybd_event(0xAF, 0, 0, 0)
        user32.keybd_event(0xAF, 0, 2, 0)
        time.sleep(0.05)
    return "volume up"


def volume_down(steps=1):
    for _ in range(max(1, int(steps))):
        user32.keybd_event(0xAE, 0, 0, 0)
        user32.keybd_event(0xAE, 0, 2, 0)
        time.sleep(0.05)
    return "volume down"


def volume_mute():
    user32.keybd_event(0xAD, 0, 0, 0)
    user32.keybd_event(0xAD, 0, 2, 0)
    return "mute toggled"


def wait_for_window(title, timeout=8.0):
    needle = str(title or "").strip()
    if not needle:
        raise DesktopError("judul window kosong")
    deadline = time.time() + float(timeout)
    while time.time() < deadline:
        win = _find_window(needle)
        if win:
            return win["title"]
        time.sleep(0.3)
    raise DesktopError(f"window '{needle}' tidak muncul dalam {timeout}s")


def wait(ms):
    try:
        value = int(ms)
    except (TypeError, ValueError):
        raise DesktopError("durasi harus angka (ms)")
    value = max(100, min(3000, value))
    time.sleep(value / 1000.0)
    return value


# Bangun mapping dinamis saat modul dimuat (simpan ke JSON).
try:
    refresh_app_map()
except Exception:
    # Fallback: coba muat dari cache JSON yang ada.
    try:
        with open(APPS_MAP_PATH, encoding="utf-8") as f:
            _dynamic_apps = json.load(f)
    except Exception:
        _dynamic_apps = {}
