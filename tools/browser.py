"""Kendali browser milik user lewat Windows UI Automation.

Nana tidak membuat profil browser sendiri. Semua
tugas browser memakai browser yang sudah terpasang dan dipakai user, lengkap
dengan profil, login, dan history-nya.

- Kalau browser sudah terbuka, Nana menambah tab baru di window itu.
- Kalau belum terbuka, Nana membuka browser default Windows (atau browser yang
  diminta user, mis. Brave) dengan profil normal user.
- Kontrol memakai UI Automation + keyboard pada window browser user.

Prinsip: jangan pernah menebak. Kalau tab yang diminta tidak ditemukan,
kembalikan daftar tab yang benar-benar ada, jangan menutup tab sembarangan.
"""

import difflib
import os
import re
import shutil
import subprocess
import time
from urllib.parse import urlparse


class BrowserError(Exception):
    pass


class AmbiguousTab(BrowserError):
    pass


# --------------------------------------------------------------------------- site

SITES = {
    "youtube": "https://www.youtube.com",
    "youtube music": "https://music.youtube.com",
    "yt music": "https://music.youtube.com",
    "spotify": "https://open.spotify.com",
    "google": "https://www.google.com",
    "bing": "https://www.bing.com",
    "duckduckgo": "https://duckduckgo.com",
    "tokopedia": "https://www.tokopedia.com",
    "shopee": "https://shopee.co.id",
    "lazada": "https://www.lazada.co.id",
    "bukalapak": "https://www.bukalapak.com",
    "blibli": "https://www.blibli.com",
    "amazon": "https://www.amazon.com",
    "github": "https://github.com",
    "gitlab": "https://gitlab.com",
    "stackoverflow": "https://stackoverflow.com",
    "wikipedia": "https://id.wikipedia.org",
    "netflix": "https://www.netflix.com",
    "tiktok": "https://www.tiktok.com",
    "instagram": "https://www.instagram.com",
    "facebook": "https://www.facebook.com",
    "x": "https://x.com",
    "twitter": "https://x.com",
    "reddit": "https://www.reddit.com",
    "gmail": "https://mail.google.com",
    "google maps": "https://maps.google.com",
    "maps": "https://maps.google.com",
    "google translate": "https://translate.google.com",
    "translate": "https://translate.google.com",
    "detik": "https://www.detik.com",
    "kompas": "https://www.kompas.com",
    "cnn indonesia": "https://www.cnnindonesia.com",
    "tribun": "https://www.tribunnews.com",
    "kaggle": "https://www.kaggle.com",
    "figma": "https://www.figma.com",
    "canva": "https://www.canva.com",
    "whatsapp": "https://web.whatsapp.com",
    "telegram": "https://web.telegram.org",
}

BROWSER_PROCESSES = (
    "brave.exe",
    "msedge.exe",
    "chrome.exe",
    "vivaldi.exe",
    "opera.exe",
    "firefox.exe",
)
_FAMILY_BY_PROCESS = {
    "brave.exe": "brave",
    "chrome.exe": "chrome",
    "msedge.exe": "edge",
    "vivaldi.exe": "vivaldi",
    "opera.exe": "opera",
    "firefox.exe": "firefox",
}
_BROWSER_NAMES = {
    "brave": "Brave",
    "chrome": "Chrome",
    "edge": "Edge",
    "vivaldi": "Vivaldi",
    "opera": "Opera",
    "firefox": "Firefox",
}
_USER_DATA_DIR = {
    "brave": r"BraveSoftware\Brave-Browser\User Data",
    "chrome": r"Google\Chrome\User Data",
    "edge": r"Microsoft\Edge\User Data",
    "vivaldi": r"Vivaldi\User Data",
    "opera": r"Opera Software\Opera Stable",
}

_SEARCH_URL_RX = re.compile(
    r"(?:google\.[a-z.]+/search|bing\.com/search|search\.yahoo\.com/search|"
    r"duckduckgo\.com/(?:html/)?\?(?:[^#]*&)?q=|"
    r"youtube\.com/results\?search_query=|yandex\.[a-z.]+/search|baidu\.com/s\?)",
    re.IGNORECASE,
)

_last_hwnd = 0


# ---------------------------------------------------------------------- utilities


def _normalize(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _clean_tab_name(name) -> str:
    """Buang embel-embel aksesibilitas Chromium: ' - Pinned', ' - Memory usage ...'."""
    text = re.split(
        r"\s+-\s+(?:Pinned|Memory usage|Audio playing|Muted)\b",
        str(name or ""),
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return re.sub(r"\s+", " ", text).strip()


def _fuzzy_score(name, needle) -> int:
    a = _normalize(name)
    b = _normalize(needle)
    if not a or not b:
        return 0
    if a == b:
        return 100
    if a.startswith(b) or a.endswith(b):
        return 90
    if b in a:
        return 80
    tokens = [t for t in b.split(" ") if len(t) > 2]
    if tokens and all(t in a for t in tokens):
        return 70
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    if ratio >= 0.72:
        return int(ratio * 60)
    return 0


def _site_url(site):
    raw = str(site or "").strip()
    if not raw:
        return None
    url = None
    if raw.lower().startswith(("http://", "https://")):
        url = raw
    else:
        key = _normalize(raw)
        if key in SITES:
            url = SITES[key]
        elif "." in key and " " not in key:
            url = "https://" + raw
        else:
            for name, candidate in SITES.items():
                if key in name or name in key:
                    url = candidate
                    break
        if url is None:
            raise BrowserError(f"situs '{site}' tidak dikenal; berikan URL lengkap")
    if is_search_url(url):
        raise BrowserError(
            "URL pencarian tidak dipakai. Gunakan browser_search(query=..., site=...) "
            "supaya Nana mengetik di kolom pencarian asli situs itu."
        )
    return url


def is_search_url(url) -> bool:
    """True untuk URL hasil search engine (yang sengaja tidak dipakai Nana)."""
    return bool(_SEARCH_URL_RX.search(str(url or "")))


# -------------------------------------------------------------- browser discovery


def _browser_family(name):
    value = _normalize(name or "")
    aliases = {
        "brave": "brave",
        "brave browser": "brave",
        "chrome": "chrome",
        "google chrome": "chrome",
        "edge": "edge",
        "msedge": "edge",
        "microsoft edge": "edge",
        "vivaldi": "vivaldi",
        "opera": "opera",
        "firefox": "firefox",
    }
    if value in ("", "auto", "otomatis", "any"):
        return ""
    return aliases.get(value, value)


def _default_browser_family():
    """Baca browser default Windows (profil/history user yang dipakai)."""
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice",
        )
        try:
            prog_id = str(winreg.QueryValueEx(key, "ProgId")[0] or "").lower()
        finally:
            winreg.CloseKey(key)
    except Exception:
        return ""

    mapping = (
        ("brave", "brave"),
        ("chrome", "chrome"),
        ("microsoft edge", "edge"),
        ("mseedge", "edge"),
        ("edge", "edge"),
        ("vivaldi", "vivaldi"),
        ("opera", "opera"),
        ("firefox", "firefox"),
    )
    for marker, family in mapping:
        if marker in prog_id:
            return family
    return ""


def _browser_exe(family):
    """Cari executable browser yang sudah terpasang di laptop user."""
    family = _browser_family(family)
    commands = {
        "brave": ["brave", "brave-browser"],
        "chrome": ["chrome"],
        "edge": ["msedge", "microsoft-edge"],
        "vivaldi": ["vivaldi"],
        "opera": ["opera"],
        "firefox": ["firefox"],
    }
    for command in commands.get(family, []):
        found = shutil.which(command)
        if found:
            return found

    roots = [
        os.environ.get("PROGRAMFILES", r"C:\Program Files"),
        os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
        os.environ.get("LOCALAPPDATA", ""),
    ]
    relative = {
        "brave": [
            r"BraveSoftware\Brave-Browser\Application\brave.exe",
            r"Programs\BraveSoftware\Brave-Browser\Application\brave.exe",
        ],
        "chrome": [
            r"Google\Chrome\Application\chrome.exe",
            r"Programs\Google\Chrome\Application\chrome.exe",
        ],
        "edge": [r"Microsoft\Edge\Application\msedge.exe"],
        "vivaldi": [r"Vivaldi\Application\vivaldi.exe", r"Programs\Vivaldi\Application\vivaldi.exe"],
        "opera": [r"Programs\Opera\opera.exe", r"Opera\opera.exe"],
        "firefox": [r"Mozilla Firefox\firefox.exe"],
    }
    for root in roots:
        if not root:
            continue
        for rel in relative.get(family, []):
            path = os.path.join(root, rel)
            if os.path.isfile(path):
                return path

    try:
        from . import desktop

        names = {
            "brave": "brave",
            "chrome": "google chrome",
            "edge": "microsoft edge",
            "vivaldi": "vivaldi",
            "opera": "opera",
            "firefox": "firefox",
        }
        target = desktop._dynamic_apps.get(names.get(family, ""))
        if target and str(target).lower().endswith(".exe") and os.path.isfile(target):
            return target
    except Exception:
        pass
    return ""


def _requested_family(browser_name=None):
    explicit = _browser_family(browser_name) or _browser_family(os.getenv("NANA_BROWSER"))
    return explicit or _default_browser_family()


def _foreground_hwnd():
    try:
        import ctypes

        return int(ctypes.windll.user32.GetForegroundWindow() or 0)
    except Exception:
        return 0


def _pid_for_window(hwnd):
    try:
        import ctypes
        from ctypes import wintypes

        pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(int(hwnd), ctypes.byref(pid))
        return int(pid.value or 0)
    except Exception:
        return 0


def _window_owner(hwnd):
    try:
        import ctypes

        return int(ctypes.windll.user32.GetWindow(int(hwnd), 4) or 0)  # GW_OWNER
    except Exception:
        return 0


def _process_details(pid):
    details = {"pid": int(pid or 0), "process": "", "exe": "", "cmdline": []}
    if not pid:
        return details
    try:
        import psutil

        proc = psutil.Process(int(pid))
        details["process"] = proc.name().lower()
        try:
            details["exe"] = proc.exe() or ""
        except Exception:
            pass
        try:
            details["cmdline"] = proc.cmdline() or []
        except Exception:
            pass
    except Exception:
        pass
    return details


def _browser_windows():
    try:
        from . import desktop
    except Exception:
        return []
    windows = []
    for win in desktop.list_windows():
        hwnd = int(win["hwnd"])
        if _window_owner(hwnd):
            continue  # popup/dialog milik browser, bukan window utama
        details = _process_details(_pid_for_window(hwnd))
        proc = details["process"]
        if proc in BROWSER_PROCESSES:
            item = dict(win)
            item.update(details)
            item["family"] = _FAMILY_BY_PROCESS.get(proc, "")
            windows.append(item)
    return windows


def _default_user_data_dir(family):
    rel = _USER_DATA_DIR.get(_normalize(family))
    if not rel:
        return ""
    root = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    return os.path.join(root, rel)


def _cmdline_value(cmdline, flag):
    args = [str(a).strip().strip('"') for a in (cmdline or [])]
    flag = flag.lower()
    for index, arg in enumerate(args):
        low = arg.lower()
        if low.startswith(flag + "="):
            return arg.split("=", 1)[1].strip('"')
        if low == flag and index + 1 < len(args):
            return args[index + 1].strip('"')
    return ""


def _user_browser_groups():
    """Kelompokkan window browser user berdasarkan family + profil."""
    groups = {}
    for win in _browser_windows():
        family = win.get("family") or ""
        if family not in _BROWSER_NAMES:
            continue
        udd = _cmdline_value(win.get("cmdline"), "--user-data-dir") or _default_user_data_dir(family)
        profile = _cmdline_value(win.get("cmdline"), "--profile-directory") or "Default"
        key = (family, os.path.normcase(os.path.normpath(udd)), profile.lower())
        group = groups.get(key)
        if group is None:
            group = {
                "family": family,
                "user_data_dir": udd,
                "profile": profile,
                "exe": win.get("exe") or "",
                "windows": [],
            }
            groups[key] = group
        if not group["exe"] and win.get("exe"):
            group["exe"] = win["exe"]
        group["windows"].append(win)
    return list(groups.values())


def _group_label(group):
    name = _BROWSER_NAMES.get(group.get("family"), group.get("family") or "Browser")
    return f"{name} (profil {group.get('profile') or 'Default'})"


def _choose_browser_window(browser_name=None):
    """Pilih window browser user tanpa menebak profil/window yang salah."""
    global _last_hwnd

    windows = [w for w in _browser_windows() if (w.get("title") or "").strip()]
    if not windows:
        return None

    wanted = _requested_family(browser_name)
    explicit = bool(_browser_family(browser_name) or _browser_family(os.getenv("NANA_BROWSER")))
    if wanted:
        matching = [w for w in windows if w.get("family") == wanted]
        if matching:
            windows = matching
        elif explicit:
            return None

    foreground = _foreground_hwnd()
    for win in windows:
        if int(win.get("hwnd") or 0) == foreground:
            return win
    if _last_hwnd:
        for win in windows:
            if int(win.get("hwnd") or 0) == _last_hwnd:
                return win

    if len(windows) == 1:
        return windows[0]

    families = {w.get("family") for w in windows}
    if len(families) == 1:
        return windows[0]

    if explicit:
        matching = [w for w in windows if w.get("family") == _requested_family(browser_name)]
        if not matching:
            return None

    listing = "; ".join(
        f"{w['title']} ({_BROWSER_NAMES.get(w.get('family'), w.get('family'))})"
        for w in windows
    )
    raise BrowserError(
        f"ada beberapa browser terbuka ({listing}). Sebutkan browser=brave/chrome/edge/firefox, "
        "atau fokuskan window yang ingin dipakai."
    )


def _window_for_hwnd(hwnd):
    from pywinauto import Desktop as PwDesktop

    return PwDesktop(backend="uia").window(handle=int(hwnd))


def _focus_browser_window(win):
    """Fokuskan window browser user; jangan pernah menutup/restart."""
    global _last_hwnd

    hwnd = int(win.get("hwnd") or 0)
    if not hwnd:
        raise BrowserError("window browser tidak ditemukan")
    try:
        wrapper = _window_for_hwnd(hwnd)
        try:
            if wrapper.is_minimized():
                wrapper.restore()
        except Exception:
            pass
        wrapper.set_focus()
        _last_hwnd = hwnd
        time.sleep(0.25)
        return wrapper
    except Exception as e:
        raise BrowserError(f"tidak bisa memfokuskan browser: {str(e).splitlines()[0]}") from e


def _launch_browser(url=None, browser_name=None):
    """Buka browser default/user dengan profil normal (bukan profil Nana)."""
    wanted = _requested_family(browser_name)
    explicit = bool(_browser_family(browser_name) or _browser_family(os.getenv("NANA_BROWSER")))
    family = wanted if explicit else (_default_browser_family() or wanted)
    if not family:
        for candidate in ("brave", "chrome", "edge", "firefox", "vivaldi", "opera"):
            if _browser_exe(candidate):
                family = candidate
                break
    exe = _browser_exe(family) if family else ""
    before = {int(w.get("hwnd") or 0) for w in _browser_windows()}

    try:
        if exe and os.path.isfile(exe):
            subprocess.Popen([exe] + ([url] if url else []), close_fds=True)
        elif url:
            os.startfile(url)  # type: ignore[attr-defined]
        else:
            raise BrowserError("browser default tidak ditemukan")
    except BrowserError:
        raise
    except Exception as e:
        raise BrowserError(f"gagal membuka browser: {str(e).splitlines()[0]}") from e

    deadline = time.time() + 20
    while time.time() < deadline:
        windows = [w for w in _browser_windows() if (w.get("title") or "").strip()]
        if family:
            matching = [w for w in windows if w.get("family") == family]
        else:
            matching = windows
        fresh = [w for w in matching if int(w.get("hwnd") or 0) not in before]
        if fresh:
            win = fresh[0]
            _focus_browser_window(win)
            return win
        if matching and not before:
            win = matching[0]
            _focus_browser_window(win)
            return win
        time.sleep(0.5)

    label = _BROWSER_NAMES.get(family, family or "browser default")
    raise BrowserError(f"{label} sudah dijalankan tetapi window-nya belum terdeteksi. Coba lagi.")


# ------------------------------------------------------------------ UI Automation


def _uia_descendants(win, depth=18, control_type=None):
    """Ambil descendant UIA dengan wrapper baru + retry.

    Chromium mengganti dokumen saat navigasi; wrapper pywinauto lama bisa
    kehilangan pohon aksesibilitas. Selalu resolve ulang dari hwnd. Kalau
    control_type diberikan, UIA memfilter di sisi native (jauh lebih cepat).
    """
    try:
        hwnd = int(win.handle)
        target = _window_for_hwnd(hwnd) if hwnd else win
    except Exception:
        target = win
    for _ in range(3):
        try:
            if control_type:
                return list(target.descendants(control_type=control_type, depth=depth))
            return list(target.descendants(depth=depth))
        except Exception:
            time.sleep(0.4)
            try:
                hwnd = int(win.handle)
                target = _window_for_hwnd(hwnd) if hwnd else win
            except Exception:
                target = win
    return []


def _uia_rect(control):
    try:
        r = control.rectangle()
        return (int(r.left), int(r.top), int(r.right), int(r.bottom))
    except Exception:
        return None


def _rect_parts(control):
    return _uia_rect(control)


def _uia_name(control):
    try:
        return re.sub(r"\s+", " ", control.window_text() or "").strip()
    except Exception:
        return ""


def _uia_visible(control):
    rect = _uia_rect(control)
    if rect is None:
        return False
    return (rect[2] - rect[0]) > 2 and (rect[3] - rect[1]) > 2


def _uia_controls(win, depth=18, control_type=None):
    return [
        c for c in _uia_descendants(win, depth=depth, control_type=control_type)
        if _uia_visible(c)
    ]


_UIA_TYPE_NAMES = {
    "button": "Button",
    "hyperlink": "Hyperlink",
    "edit": "Edit",
    "combobox": "ComboBox",
    "listitem": "ListItem",
    "dataitem": "DataItem",
    "text": "Text",
    "menuitem": "MenuItem",
    "tabitem": "TabItem",
    "checkbox": "CheckBox",
    "radio button": "RadioButton",
}


def _uia_find_matches(win, target, types=None, content_only=True):
    needle = str(target or "").strip()
    if not needle:
        return []
    requested = types or ("Button", "Hyperlink", "Text", "ListItem", "DataItem")
    native_types = []
    for item in requested:
        key = str(item).lower()
        native_types.append(_UIA_TYPE_NAMES.get(key, item))
    controls = []
    for native_type in dict.fromkeys(native_types):
        native_depth = 18 if native_type == "Hyperlink" else 14
        controls.extend(_uia_controls(win, depth=native_depth, control_type=native_type))
    if content_only:
        win_rect = _rect_parts(win) or (0, 0, 0, 0)
        content_top = win_rect[1] + 90
        content_bottom = win_rect[3] - 8
        content_left = win_rect[0]
        content_right = win_rect[2]
        filtered = []
        for control in controls:
            rect = _uia_rect(control) or (0, 0, 0, 0)
            if (
                content_top <= rect[1] < content_bottom
                and content_left <= rect[0] < content_right
            ):
                filtered.append(control)
        controls = filtered
    wanted_types = {str(t).lower() for t in requested}
    matches = []
    for control in controls:
        try:
            control_type = str(control.element_info.control_type).lower()
            if wanted_types and control_type not in wanted_types:
                continue
            score = _fuzzy_score(_uia_name(control), needle)
            if score > 0:
                matches.append((score, control))
        except Exception:
            continue
    matches.sort(key=lambda item: -item[0])
    return matches


def _uia_click(control):
    """Klik kontrol lewat UIA (tanpa bergantung window di depan)."""
    try:
        control_type = str(control.element_info.control_type).lower()
    except Exception:
        control_type = ""

    try:
        control.set_focus()
    except Exception:
        pass

    if control_type == "tabitem":
        try:
            control.select()
            return True
        except Exception:
            pass

    if control_type in (
        "button",
        "hyperlink",
        "menuitem",
        "listitem",
        "dataitem",
        "checkbox",
        "radio button",
    ):
        try:
            control.invoke()
            return True
        except Exception:
            pass

    if control_type in ("edit", "combobox", "document"):
        # Untuk kolom input cukup fokus UIA; tidak perlu klik fisik.
        try:
            control.set_focus()
            return True
        except Exception:
            pass

    try:
        control.scroll_into_view()
    except Exception:
        pass
    try:
        control.click_input()
        return True
    except Exception:
        return False


def _uia_click_text(win, target, types=None):
    matches = _uia_find_matches(win, target, types=types)
    if not matches:
        return None
    top = matches[0][0]
    ties = [(score, control) for score, control in matches if score >= top - 4]
    names = []
    for _score, control in ties[:8]:
        name = _uia_name(control)
        if name and name not in names:
            names.append(name)
    if len(names) > 1:
        raise BrowserError(
            f"'{target}' cocok dengan beberapa elemen:\n- " + "\n- ".join(names) +
            "\nSebutkan teks yang lebih spesifik."
        )
    control = ties[0][1]
    if not _uia_click(control):
        raise BrowserError(f"elemen '{target}' tidak bisa diklik")
    return control


def _tab_strip_item(control, win_rect, max_top=150):
    """TabItem harus berada di tab strip atas, bukan konten web."""
    rect = _uia_rect(control)
    if rect is None:
        return True
    left, top, right, bottom = rect
    if top > win_rect[1] + max_top:
        return False
    if bottom - top > 110:
        return False
    return True


def _uia_tabs(hwnd):
    # Tab strip bisa kosong sesaat saat dokumen sedang navigasi.
    tabs = []
    for attempt in range(5):
        tabs = _uia_tabs_scan(hwnd)
        if tabs or attempt == 4:
            return tabs
        time.sleep(0.35)
    return tabs


def _uia_tabs_scan(hwnd):
    try:
        win = _window_for_hwnd(hwnd)
        win_rect = _rect_parts(win)
        if win_rect is None:
            win_rect = (0, 0, 1920, 1080)
        win_width = max(1, win_rect[2] - win_rect[0])

        # Jalur cepat: pilih kontrol Tab paling atas yang lebar (tab strip).
        strips = []
        try:
            for strip in win.descendants(control_type="Tab", depth=8):
                rect = _rect_parts(strip)
                if rect is None:
                    continue
                width = max(0, rect[2] - rect[0])
                if rect[1] > win_rect[1] + 150 or width < win_width * 0.4:
                    continue
                strips.append((rect[1], strip))
        except Exception:
            strips = []
        strips.sort(key=lambda item: item[0])

        for _top, strip in strips:
            tabs = []
            try:
                children = strip.children()
            except Exception:
                continue
            for control in children:
                try:
                    if str(control.element_info.control_type).lower() != "tabitem":
                        continue
                    name = _clean_tab_name(control.window_text())
                    if name and _tab_strip_item(control, win_rect):
                        tabs.append((name, control))
                except Exception:
                    continue
            if tabs:
                return tabs

        tabs = []
        for control in win.descendants(control_type="TabItem", depth=8):
            try:
                if not _tab_strip_item(control, win_rect):
                    continue
                name = _clean_tab_name(control.window_text())
                if name:
                    tabs.append((name, control))
            except Exception:
                continue
        return tabs
    except Exception:
        return []


def _uia_all_tabs():
    result = []
    for win in _browser_windows()[:8]:
        for name, control in _uia_tabs(win["hwnd"]):
            result.append(
                {"window": win["title"], "hwnd": win["hwnd"], "title": name, "control": control}
            )
    return result


def _uia_find_tab(needle):
    needle = str(needle or "")
    matches = []
    for index, tab in enumerate(_uia_all_tabs()):
        score = _fuzzy_score(tab["title"], needle)
        if score >= 60:
            matches.append((score, index, tab))
    if not matches:
        return None
    matches.sort(key=lambda item: (-item[0], item[1]))
    top = matches[0][0]
    ties = [item for item in matches if item[0] >= top - 4]
    if len(ties) > 1:
        listing = "\n".join(
            f"- {tab['title']} (window: {tab['window']})" for _, _, tab in ties[:8]
        )
        raise AmbiguousTab(
            f"'{needle}' cocok dengan beberapa tab user:\n{listing}\n"
            "Sebutkan judul yang lebih spesifik."
        )
    return matches[0][2]


def _uia_focus(tab):
    """Fokuskan tab user dan pastikan benar-benar tab itu yang aktif."""
    control = tab.get("control")
    if control is None:
        return False
    for action in ("select", "click_input"):
        try:
            getattr(control, action)()
        except Exception:
            continue
        time.sleep(0.35)
        try:
            if control.is_selected():
                return True
        except Exception:
            break

    try:
        win = _window_for_hwnd(tab["hwnd"])
        return _fuzzy_score(win.window_text(), tab["title"]) >= 70
    except Exception:
        return False


def _uia_activate_tab(needle):
    tab = _uia_find_tab(needle)
    if not tab:
        return None
    if not _uia_focus(tab):
        return None
    time.sleep(0.3)
    return tab["title"]


def _uia_tab_labels(win):
    labels = []
    for name, control in _uia_tabs(int(win.get("hwnd") or 0)):
        active = False
        try:
            active = bool(control.is_selected())
        except Exception:
            pass
        labels.append({"title": name, "active": active})
    return labels


def _uia_address_candidate(win):
    win_rect = _rect_parts(win) or (0, 0, 0, 0)
    width = max(1, win_rect[2] - win_rect[0])
    best = None
    best_score = -1
    for control in _uia_descendants(win, depth=14, control_type="Edit"):
        try:
            if str(control.element_info.control_type).lower() != "edit":
                continue
            rect = _uia_rect(control)
            if not rect:
                continue
            if rect[1] > win_rect[1] + 130 or (rect[2] - rect[0]) < width * 0.3:
                continue
            name = _uia_name(control)
            value = name
            if not value:
                try:
                    value = str(control.get_value() or "")
                except Exception:
                    value = ""
            low_value = value.lower()
            low_name = name.lower()
            score = 0
            if low_value.startswith(("http://", "https://")):
                score += 100
            elif re.match(r"^[\w.-]+\.[a-z]{2,}(?:[/:?#]|$)", low_value):
                score += 80
            if "address" in low_name or "search or type" in low_name:
                score += 60
            if rect[1] <= win_rect[1] + 90:
                score += 40
            if (rect[2] - rect[0]) >= width * 0.5:
                score += 20
            if any(word in low_name for word in ("search", "cari", "telusuri", "pencarian")):
                score -= 50
            if score > best_score:
                best, best_score = (control, value), score
        except Exception:
            continue
    return best


def _uia_address(win):
    item = _uia_address_candidate(win)
    return item[1] if item else ""


def _uia_address_control(win):
    item = _uia_address_candidate(win)
    return item[0] if item else None


def _uia_document_title(win):
    for control in _uia_descendants(win, depth=14, control_type="Document"):
        try:
            if str(control.element_info.control_type).lower() == "document":
                name = _uia_name(control)
                if name:
                    return name
        except Exception:
            continue
    title = _uia_name(win)
    return re.split(
        r"\s+-\s+(?:Profile \d+\s+-\s+)?(?:Brave|Google Chrome|Microsoft\u200b?\s*Edge|Vivaldi|Opera|Firefox)\b",
        title,
        maxsplit=1,
    )[0]


def _uia_media_controls(win):
    controls = []
    for control_type in ("Button", "Slider"):
        controls.extend(_uia_controls(win, depth=16, control_type=control_type))
    return controls


def _uia_media_state(controls):
    playing = False
    muted = False
    position = 0
    duration = 0
    present = False
    for control in controls:
        try:
            control_type = str(control.element_info.control_type).lower()
            name = _uia_name(control)
            low = name.lower()
            if control_type == "button":
                if re.search(r"^(pause|jeda)\b", low):
                    playing = True
                    present = True
                elif re.search(r"^(play|putar)\b", low):
                    present = True
                if low.startswith("unmute"):
                    muted = True
                if re.search(r"^(mute|bisukan)\b", low):
                    muted = False
            if control_type == "slider" and ("seek" in low or "progress" in low or "posisi" in low):
                present = True
                try:
                    value = control.get_value()
                    if value:
                        position = int(float(value))
                except Exception:
                    pass
                try:
                    maximum = control.maximum_value()
                    if maximum:
                        duration = int(float(maximum))
                except Exception:
                    pass
        except Exception:
            continue
    return {
        "present": present,
        "playing": playing,
        "muted": muted,
        "time": position,
        "duration": duration,
    }


def _uia_state(win):
    controls = []
    for control_type in ("Edit", "ComboBox", "Button", "Hyperlink", "Text"):
        native_depth = 18 if control_type == "Hyperlink" else 14
        controls.extend(_uia_controls(win, depth=native_depth, control_type=control_type))
    win_rect = _rect_parts(win) or (0, 0, 0, 0)
    content_top = win_rect[1] + 90
    content_bottom = win_rect[3] - 8
    fields = []
    buttons = []
    links = []
    texts = []
    seen = set()
    for control in controls:
        try:
            control_type = str(control.element_info.control_type).lower()
            name = _uia_name(control)
            rect = _uia_rect(control) or (0, 0, 0, 0)
            if (
                rect[1] < content_top
                or rect[1] >= content_bottom
                or rect[0] < win_rect[0]
                or rect[0] >= win_rect[2]
                or not name
            ):
                continue
            key = (control_type, _normalize(name))
            if key in seen:
                continue
            seen.add(key)
            if control_type in ("edit", "combobox"):
                fields.append(name)
            elif control_type == "button":
                buttons.append(name)
            elif control_type == "hyperlink":
                links.append(name)
            elif control_type == "text":
                texts.append((rect[1], rect[0], name))
        except Exception:
            continue
    texts.sort()
    return {
        "url": _uia_address(win),
        "title": _uia_document_title(win),
        "fields": fields[:12],
        "buttons": buttons[:20],
        "links": links[:20],
        "text": " ".join(item[2] for item in texts)[:1800],
        "media": _uia_media_state(_uia_media_controls(win)),
    }


def _uia_state_text(win):
    data = _uia_state(win)
    lines = [
        f"URL: {data.get('url') or '(tidak terbaca)'}",
        f"Judul: {data.get('title') or '(tidak terbaca)'}",
        "Mode: UI Automation (profil/history browser user)",
    ]
    media = data.get("media") or {}
    if media.get("present"):
        status = "playing" if media.get("playing") else "paused"
        duration = media.get("duration") or 0
        position = media.get("time") or 0
        extra = " (mute)" if media.get("muted") else ""
        if duration:
            lines.append(f"Media: {status} ({position}s/{duration}s){extra}")
        else:
            lines.append(f"Media: {status}{extra}")
    fields = data.get("fields") or []
    if fields:
        lines.append("Kolom input: " + " | ".join(fields))
    buttons = data.get("buttons") or []
    if buttons:
        lines.append("Tombol: " + " | ".join(buttons[:14]))
    links = data.get("links") or []
    if links:
        lines.append("Link: " + " | ".join(links[:14]))
    text = data.get("text") or ""
    if text:
        lines.append("Teks: " + text[:900])
    return "\n".join(lines)


def _uia_search_input(win):
    controls = []
    for control_type in ("Edit", "ComboBox"):
        controls.extend(_uia_controls(win, depth=14, control_type=control_type))
    win_rect = _rect_parts(win) or (0, 0, 0, 0)
    content_top = win_rect[1] + 90
    best = None
    best_score = 0
    for control in controls:
        try:
            control_type = str(control.element_info.control_type).lower()
            if control_type not in ("edit", "combobox"):
                continue
            rect = _uia_rect(control) or (0, 0, 0, 0)
            if rect[1] < content_top:
                continue
            name = _uia_name(control)
            low = name.lower()
            score = 0
            if any(word in low for word in ("search", "cari", "telusuri", "pencarian", "query")):
                score += 100
            if "what do you want" in low or "search or jump" in low:
                score += 90
            if rect[1] < content_top + 220:
                score += 20
            if score > best_score:
                best, best_score = control, score
        except Exception:
            continue
    return best if best_score >= 20 else None


def _uia_wait_address(win, host="", before="", before_title="", timeout=20):
    deadline = time.time() + timeout
    title_changed_at = 0.0
    current = ""
    while time.time() < deadline:
        current = _uia_address(win)
        title = _uia_document_title(win)
        if host and host in current.lower():
            return current
        if not host and current and current != before:
            return current
        if title and before_title and title != before_title and not title_changed_at:
            title_changed_at = time.time()
        # Kalau address bar tidak terbaca di browser tertentu, tetap beri waktu
        # halaman selesai loading setelah judul berubah.
        if title_changed_at and time.time() - title_changed_at >= 8 and current:
            return current
        time.sleep(0.4)
    return current or _uia_address(win)


def _uia_wait_controls(win, timeout=4, min_count=2):
    controls = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        controls = []
        for control_type in ("Button", "Hyperlink", "Text", "Edit"):
            controls.extend(_uia_controls(win, depth=14, control_type=control_type))
            if len(controls) >= min_count:
                return controls
        time.sleep(0.4)
    return controls


def _uia_new_tab(win):
    """Buka tab baru lewat tombol tab strip; fallback Ctrl+T."""
    before = len(_uia_tabs(int(win.get("hwnd") or 0)))
    win_rect = _rect_parts(win) or (0, 0, 0, 0)
    for control in _uia_controls(win, depth=8):
        try:
            if str(control.element_info.control_type).lower() != "button":
                continue
            rect = _uia_rect(control) or (0, 0, 0, 0)
            if rect[1] < win_rect[1] or rect[1] > win_rect[1] + 150:
                continue
            if (rect[2] - rect[0]) > 80:
                continue
            label = _normalize(_uia_name(control))
            if not (
                label.startswith("new tab")
                or label.startswith("tab baru")
                or label in ("open a new tab", "buka tab baru")
            ):
                continue
            if _uia_click(control):
                for _ in range(10):
                    time.sleep(0.3)
                    if len(_uia_tabs(int(win.get("hwnd") or 0))) > before:
                        return True
        except Exception:
            continue

    from . import keyboard

    try:
        _focus_browser_window(win)
        keyboard.press_key("ctrl+t")
    except Exception:
        return False
    for _ in range(10):
        time.sleep(0.3)
        if len(_uia_tabs(int(win.get("hwnd") or 0))) > before:
            return True
    return False


def _uia_navigate(win, url, new_tab=True):
    """Navigasi di window tepat yang dipilih, memakai profil user itu."""
    wrapper = _focus_browser_window(win)
    from . import keyboard

    before = _uia_address(wrapper)
    before_title = _uia_document_title(wrapper)
    host = urlparse(url).netloc.lower().replace("www.", "")
    try:
        if new_tab:
            if not _uia_new_tab(win):
                raise BrowserError(
                    "tidak bisa membuka tab baru di browser user; "
                    "Nana tidak mengganti tab yang sedang dipakai."
                )
            wrapper = _focus_browser_window(win)
            time.sleep(0.4)
        target = _uia_address_control(wrapper)
        if target is None:
            _uia_wait_controls(wrapper, timeout=6)
            target = _uia_address_control(wrapper)
        if target is not None:
            _uia_click(target)
            time.sleep(0.2)
            keyboard.press_key("ctrl+a")
        else:
            keyboard.press_key("ctrl+l")
        time.sleep(0.2)
        keyboard.type_text(url)
        time.sleep(0.2)
        keyboard.press_key("enter")
    except BrowserError:
        raise
    except Exception as e:
        raise BrowserError(f"gagal membuka {url} di browser user: {str(e).splitlines()[0]}") from e

    current = _uia_wait_address(wrapper, host=host, before=before, before_title=before_title, timeout=20)
    title = _uia_document_title(wrapper)
    if host and host not in str(current).lower() and (not title or title == before_title):
        raise BrowserError(
            f"navigasi ke {url} belum terverifikasi di browser user. "
            "Nana tidak mengklaim tab sudah berpindah; cek browser_tabs/browser_state."
        )
    try:
        _uia_dismiss_consent(wrapper)
    except Exception:
        pass
    time.sleep(0.8)
    return wrapper, title or _uia_document_title(wrapper), current or _uia_address(wrapper)


def _uia_open_url(url, browser_name=None, new_tab=True):
    win = _choose_browser_window(browser_name)
    if win is None:
        win = _launch_browser(url=url, browser_name=browser_name)
        wrapper = _window_for_hwnd(win["hwnd"])
        host = urlparse(url).netloc.lower().replace("www.", "")
        _uia_wait_address(wrapper, host=host, timeout=20)
        time.sleep(0.6)
        return win, _uia_document_title(wrapper), _uia_address(wrapper)
    wrapper, title, current = _uia_navigate(win, url, new_tab=new_tab)
    return win, title, current


def _uia_current_window(browser_name=None):
    win = _choose_browser_window(browser_name)
    if win is None:
        raise BrowserError(
            "tidak ada browser user yang terbuka. Buka browser dulu, "
            "atau jalankan browser_open/browser_search."
        )
    return win, _focus_browser_window(win)


_CONSENT_LABELS = {
    "accept all",
    "terima semua",
    "i agree",
    "setuju",
    "accept",
    "terima",
    "got it",
    "mengerti",
    "no thanks",
    "not now",
    "nanti saja",
    "skip",
    "lewati",
    "maybe later",
    "close",
}


def _uia_dismiss_consent(win):
    try:
        controls = _uia_controls(win, depth=14, control_type="Button")
    except Exception:
        return False
    win_rect = _rect_parts(win) or (0, 0, 0, 0)
    content_top = win_rect[1] + 90
    for control in controls:
        try:
            if str(control.element_info.control_type).lower() != "button":
                continue
            label = _normalize(_uia_name(control))
            if label not in _CONSENT_LABELS:
                continue
            rect = _uia_rect(control) or (0, 0, 0, 0)
            # Jangan pernah menekan tombol tutup di tab strip/toolbar browser.
            if rect[1] < content_top or rect[1] > content_top + 260:
                continue
            _uia_click(control)
            time.sleep(0.4)
            return True
        except Exception:
            continue
    return False


def _uia_search(win, query, site=None):
    """Cari lewat kolom pencarian situs, bukan URL search engine."""
    if isinstance(win, dict):
        wrapper = _focus_browser_window(win)
    else:
        wrapper = win
        try:
            wrapper.set_focus()
        except Exception:
            pass
    _uia_wait_controls(wrapper, timeout=10)
    _uia_dismiss_consent(wrapper)
    site_key = _normalize(site or "")
    if any(key in site_key for key in ("youtube", "spotify")):
        _uia_wait_content_links(wrapper, min_count=6, timeout=10)
    box = _uia_search_input(wrapper)
    used_shortcut = False

    if box is not None:
        _uia_click(box)
        time.sleep(0.2)
    else:
        if "youtube" in site_key:
            try:
                from . import keyboard

                keyboard.press_key("esc")
                keyboard.press_key("/")
                time.sleep(0.3)
                used_shortcut = True
            except Exception:
                used_shortcut = False
        if not used_shortcut:
            button = None
            for label in ("Search", "Cari", "Telusuri"):
                button = _uia_click_text(wrapper, label, types=("Button",))
                if button is not None:
                    break
            if button is None:
                raise BrowserError(
                    "kolom pencarian situs tidak ditemukan di browser user. "
                    "Coba browser_state untuk melihat halaman."
                )
            time.sleep(0.4)
            box = _uia_search_input(wrapper)
            if box is not None:
                _uia_click(box)
                time.sleep(0.2)
            else:
                used_shortcut = True

    from . import keyboard

    if box is not None:
        keyboard.press_key("ctrl+a")
    keyboard.type_text(str(query))
    time.sleep(0.2)
    keyboard.press_key("enter")
    time.sleep(3.0)
    return used_shortcut


_UIA_NAV_NAMES = {
    "home",
    "shorts",
    "subscriptions",
    "you",
    "history",
    "sign in",
    "music",
    "movies",
    "gaming",
    "show more",
    "settings",
    "about",
    "press",
    "copyright",
    "contact us",
    "creators",
    "advertise",
    "developers",
    "terms",
    "privacy",
    "policy & safety",
    "how youtube works",
    "test new features",
    "youtube premium",
    "youtube music",
    "youtube kids",
    "report history",
    "learn more",
    "manage favorites now",
    "search",
    "search with your voice",
    "install youtube",
    "guide",
    "skip navigation",
    "close",
    "minimize",
    "maximize",
    "restore",
    "back",
    "forward",
    "reload",
    "menu",
    "help",
    "accept all",
    "terima semua",
    "setuju",
    "got it",
    "disable",
    "sign out",
}


def _collect_uia_results(win, query):
    controls = []
    for control_type in ("Hyperlink", "ListItem", "DataItem"):
        controls.extend(_uia_controls(win, depth=18, control_type=control_type))
    win_rect = _rect_parts(win) or (0, 0, 0, 0)
    content_top = win_rect[1] + 150
    content_bottom = win_rect[3] - 8
    items = []
    seen = set()
    for control in controls:
        try:
            control_type = str(control.element_info.control_type).lower()
            if control_type not in ("hyperlink", "listitem", "dataitem"):
                continue
            name = _uia_name(control)
            if len(name) < 3 or _normalize(name) in _UIA_NAV_NAMES:
                continue
            rect = _uia_rect(control) or (0, 0, 0, 0)
            if (
                rect[1] < content_top
                or rect[1] >= content_bottom
                or rect[0] < win_rect[0]
                or rect[0] >= win_rect[2]
                or rect[2] - rect[0] < 240
            ):
                continue
            key = _normalize(name)
            if key in seen:
                continue
            seen.add(key)
            items.append({"title": name, "href": "", "control": control, "top": rect[1]})
        except Exception:
            continue

    words = [w for w in re.split(r"[^a-z0-9]+", _normalize(query)) if len(w) > 2]
    scored = []
    for item in items:
        title = _normalize(item["title"])
        hits = sum(1 for word in words if word in title)
        score = hits * 10
        if words and hits == 0:
            score -= 5
        scored.append((score, item))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["top"]))
    return [item for _score, item in scored]


def _uia_results(win, query):
    deadline = time.time() + 8
    results = []
    while time.time() < deadline:
        results = _collect_uia_results(win, query)
        if len(results) >= 3:
            return results
        time.sleep(0.5)
    return results


def _pick_result(candidates, query):
    words = [w for w in re.split(r"[^a-z0-9]+", _normalize(query)) if len(w) > 2]
    best = None
    best_score = -1.0
    for index, item in enumerate(candidates or []):
        title = _normalize(item.get("title"))
        href = item.get("href") or ""
        if not title:
            continue
        if any(bad in href for bad in ("/shorts/", "javascript:", "login", "signin")):
            continue
        score = 0.0
        hits = sum(1 for word in words if word in title)
        if words:
            score += 60.0 * hits / len(words)
        ratio = difflib.SequenceMatcher(None, title, _normalize(query)).ratio()
        score += ratio * 20
        score += max(0.0, 15.0 - index * 2.5)
        if "youtube.com/watch" in href:
            score += 8
        if score > best_score:
            best, best_score = item, score
    return best if best_score >= 18 else None


def _uia_playing(win, timeout=20):
    deadline = time.time() + timeout
    state = None
    play_clicked = False
    while time.time() < deadline:
        controls = _uia_media_controls(win)
        state = _uia_media_state(controls)
        if state.get("playing"):
            return state

        if not play_clicked:
            play_button = None
            for control in controls:
                try:
                    if str(control.element_info.control_type).lower() != "button":
                        continue
                    label = _normalize(_uia_name(control))
                    if re.match(r"^(play|putar)(?:\s|\(|$)", label):
                        play_button = control
                        break
                except Exception:
                    continue
            if play_button is not None:
                if _uia_click(play_button):
                    play_clicked = True
                    time.sleep(2.0)
                    continue
        time.sleep(0.8)

    return state or {"present": False, "playing": False, "muted": False, "time": 0, "duration": 0}


# --------------------------------------------------------------------- public API


def list_tabs_text():
    groups = _user_browser_groups()
    if not groups:
        return (
            "Tidak ada browser yang terbuka. Nana akan membuka browser default user "
            "saat ada tugas browser."
        )
    lines = ["Browser user (UI Automation, profil/history user):"]
    for group in groups:
        lines.append(f"  {_group_label(group)}")
        for win in group.get("windows") or []:
            tabs = _uia_tab_labels(win)
            if len(group.get("windows") or []) > 1:
                lines.append(f"    Window: {win.get('title', '')[:80]}")
            if not tabs:
                lines.append("      (tidak ada tab yang terbaca)")
                continue
            for tab in tabs[:30]:
                prefix = "[aktif] " if tab.get("active") else "- "
                lines.append(f"      {prefix}{tab['title']}")
    return "\n".join(lines)


def activate_tab(title, source="auto"):
    needle = str(title or "").strip()
    if not needle:
        raise BrowserError("judul tab kosong")
    activated = _uia_activate_tab(needle)
    if not activated:
        raise BrowserError(f"tab '{needle}' tidak ditemukan.\n{list_tabs_text()}")
    return f"Fokus ke tab browser user: {activated}"


def close_tab(title=None, count=1, source="auto"):
    needle = str(title or "").strip()
    if not needle:
        raise BrowserError(
            "judul tab kosong. Sebutkan tab yang mau ditutup "
            "(lihat daftar dari browser_tabs)."
        )
    try:
        amount = max(1, min(10, int(count or 1)))
    except (TypeError, ValueError):
        amount = 1

    closed = []
    for _ in range(amount):
        try:
            tab = _uia_find_tab(needle)
        except AmbiguousTab as e:
            raise BrowserError(f"{e}\n{list_tabs_text()}") from e
        if tab is None:
            raise BrowserError(f"tab '{needle}' tidak ditemukan.\n{list_tabs_text()}")
        closed_title = tab["title"]
        if not _uia_focus(tab):
            raise BrowserError(
                f"tab '{closed_title}' tidak bisa difokuskan. "
                "Nana tidak menutup tab lain supaya aman."
            )
        from . import keyboard

        try:
            _focus_browser_window({"hwnd": tab["hwnd"], "title": closed_title})
        except Exception:
            pass
        keyboard.press_key("ctrl+w")
        time.sleep(0.8)
        remaining = [name for name, _ in _uia_tabs(tab["hwnd"])]
        if any(_normalize(name) == _normalize(closed_title) for name in remaining):
            raise BrowserError(
                f"tab '{closed_title}' belum tertutup. Cek kembali dengan browser_tabs."
            )
        closed.append(closed_title)
    return "Tab ditutup: " + ", ".join(closed)


def attach_user(browser_name=None):
    """Gunakan browser user yang sudah terbuka, atau buka browser default."""
    win = _choose_browser_window(browser_name)
    if win is None:
        win = _launch_browser(url=None, browser_name=browser_name)
    wrapper = _focus_browser_window(win)
    tabs = _uia_tab_labels(win)
    family = win.get("family") or ""
    family_name = _BROWSER_NAMES.get(family, family or "Browser")
    profile = _cmdline_value(win.get("cmdline"), "--profile-directory") or "Default"
    lines = [
        f"Browser user siap: {family_name} (profil {profile}).",
        "Mode: UI Automation pada window browser user; tanpa profil Nana, tanpa restart.",
        f"Tab terbaca: {len(tabs)}",
    ]
    if tabs:
        lines.append(
            "  " + " | ".join(
                ("[aktif] " if tab.get("active") else "") + tab["title"] for tab in tabs[:8]
            )
        )
    lines.append("Semua tool browser memakai browser user ini (profil/history user).")
    return "\n".join(lines)


def stop_browser():
    # Tidak ada browser milik Nana dan tidak ada koneksi yang perlu ditutup.
    return "Nana hanya memakai browser user; tidak ada browser yang ditutup."


def _validate_url(target):
    value = str(target or "").strip()
    if not value.lower().startswith(("http://", "https://")):
        raise BrowserError("hanya URL http/https yang diizinkan")
    if is_search_url(value):
        raise BrowserError(
            "URL pencarian tidak dipakai. Gunakan browser_search(query=..., site=...) "
            "supaya Nana mengetik di kolom pencarian asli situs itu."
        )
    return value


def open_url(url, new_tab=True, browser_name=None):
    target = _validate_url(url)
    _win, title, current = _uia_open_url(target, browser_name=browser_name, new_tab=new_tab)
    return f"Dibuka: {title or target} — {current or target}"


def state_text():
    _win, wrapper = _uia_current_window()
    return _uia_state_text(wrapper)


def find_text(target):
    needle = str(target or "").strip()
    if not needle:
        raise BrowserError("target kosong")
    _win, wrapper = _uia_current_window()
    matches = _uia_find_matches(wrapper, needle, content_only=True)
    if not matches:
        return f"Tidak ada elemen yang cocok dengan '{needle}'."
    lines = [f"Cocok untuk '{needle}' (UI Automation):"]
    seen = set()
    count = 0
    for score, control in matches:
        try:
            control_type = str(control.element_info.control_type)
            name = _uia_name(control)
            key = (control_type, _normalize(name))
            if not name or key in seen:
                continue
            seen.add(key)
            count += 1
            lines.append(f"{count}. <{control_type}> {name} (skor {score})")
            if count >= 10:
                break
        except Exception:
            continue
    return "\n".join(lines)


def click_text(target, selector=None):
    if selector and not str(target or "").strip():
        raise BrowserError(
            "CSS selector tidak dipakai. Nana mengontrol browser lewat UI Automation; "
            "sebutkan teks tombol/link yang terlihat."
        )
    needle = str(target or "").strip()
    if not needle:
        raise BrowserError("target kosong")
    _win, wrapper = _uia_current_window()
    if _uia_click_text(wrapper, needle) is None:
        raise BrowserError(f"elemen '{needle}' tidak ditemukan di halaman")
    time.sleep(1.2)
    return f"Klik: {needle}\nSekarang: {_uia_document_title(wrapper)} — {_uia_address(wrapper)}"


def fill_text(target, text, submit=True, selector=None):
    if selector and not str(target or "").strip():
        raise BrowserError(
            "CSS selector tidak dipakai. Sebutkan nama kolom yang terlihat."
        )
    _win, wrapper = _uia_current_window()
    value = str(text or "")
    needle = str(target or "").strip()
    if needle:
        control = _uia_click_text(wrapper, needle, types=("edit", "combobox"))
        if control is None:
            raise BrowserError(f"kolom '{needle}' tidak ditemukan di halaman")
    else:
        control = _uia_search_input(wrapper)
        if control is None:
            raise BrowserError("kolom input tidak ditemukan")
        _uia_click(control)
    from . import keyboard

    time.sleep(0.2)
    try:
        keyboard.press_key("ctrl+a")
    except Exception:
        pass
    try:
        keyboard.type_text(value)
    except Exception as e:
        raise BrowserError(f"gagal mengetik: {str(e).splitlines()[0]}") from e
    if submit:
        try:
            keyboard.press_key("enter")
        except Exception:
            pass
        time.sleep(1.2)
    name = _uia_name(control) if control is not None else "kolom input"
    return f"Teks '{value[:80]}' dimasukkan ke: {name}"


def press(key):
    _win, wrapper = _uia_current_window()
    combo = str(key or "").strip()
    if not combo:
        raise BrowserError("tombol kosong")
    from . import keyboard

    keyboard.press_key(combo)
    time.sleep(0.4)
    return f"Tombol {combo} ditekan di browser user"


def scroll(direction="down", amount=3):
    try:
        step = max(1, min(20, int(amount or 3)))
    except (TypeError, ValueError):
        step = 3
    direction = str(direction or "down").lower()
    if direction not in ("up", "down", "left", "right"):
        raise BrowserError("arah scroll harus up/down/left/right")
    if direction in ("left", "right"):
        raise BrowserError(
            "scroll kiri/kanan belum tersedia. Gunakan browser_press dengan tombol panah."
        )
    _win, wrapper = _uia_current_window()
    from . import keyboard

    key = "pagedown" if direction == "down" else "pageup"
    for _ in range(step):
        keyboard.press_key(key)
        time.sleep(0.15)
    time.sleep(0.3)
    return f"Scroll {direction} ({step}x) di browser user"


def wait_for(target, timeout=10):
    needle = str(target or "").strip()
    if not needle:
        raise BrowserError("target kosong")
    try:
        limit = max(1, min(60, int(timeout or 10)))
    except (TypeError, ValueError):
        limit = 10
    if needle.startswith(("css=", "#", ".", "[")):
        raise BrowserError(
            "CSS selector tidak dipakai. Sebutkan teks yang terlihat di halaman."
        )
    _win, wrapper = _uia_current_window()
    deadline = time.time() + limit
    while time.time() < deadline:
        matches = _uia_find_matches(wrapper, needle, content_only=True)
        if matches:
            return f"Teks '{_uia_name(matches[0][1]) or needle}' muncul di halaman"
        time.sleep(0.4)
    raise BrowserError(f"teks '{needle}' tidak muncul dalam {limit}s")


def search_on_site(query, site=None, browser_name=None):
    q = str(query or "").strip()
    if not q:
        raise BrowserError("query kosong")

    if site:
        url = _site_url(site)
        win, _title, _current = _uia_open_url(url, browser_name=browser_name, new_tab=True)
        wrapper = _focus_browser_window(win)
    else:
        win, wrapper = _uia_current_window(browser_name)
    hint = site or _uia_address(wrapper)
    _uia_search(wrapper, q, site=hint)
    results = _uia_results(wrapper, q)
    lines = [
        f"Pencarian '{q}' dijalankan lewat kolom pencarian situs.",
        f"Halaman: {_uia_document_title(wrapper)} — {_uia_address(wrapper)}",
    ]
    if results:
        lines.append("Hasil yang terlihat:")
        for index, item in enumerate(results[:10], 1):
            lines.append(f"{index}. {item['title']}")
    else:
        lines.append("Belum ada hasil yang terbaca. Coba browser_state atau browser_wait.")
    return "\n".join(lines)


def _uia_wait_content_links(win, min_count=6, timeout=12):
    """Tunggu konten situs (bukan cuma header) selesai dimuat."""
    deadline = time.time() + timeout
    win_rect = _rect_parts(win) or (0, 0, 0, 0)
    content_top = win_rect[1] + 150
    content_bottom = win_rect[3] - 8
    while time.time() < deadline:
        visible = 0
        for control in _uia_controls(win, depth=18, control_type="Hyperlink"):
            rect = _uia_rect(control) or (0, 0, 0, 0)
            if content_top <= rect[1] < content_bottom:
                visible += 1
        if visible >= min_count:
            return True
        time.sleep(0.6)
    return False


def _uia_play(service, query, browser_name=None):
    url = _site_url(service)
    if not url:
        raise BrowserError("layanan pemutaran tidak dikenal")
    win, _title, _current = _uia_open_url(url, browser_name=browser_name, new_tab=True)
    wrapper = _focus_browser_window(win)
    _uia_dismiss_consent(wrapper)
    _uia_search(wrapper, query, site=service)
    results = _uia_results(wrapper, query)
    chosen = _pick_result(results, query)
    if not chosen:
        raise BrowserError(
            f"tidak menemukan hasil yang cocok untuk '{query}' di {service}.\n"
            + _uia_state_text(wrapper)
        )
    attempts = [chosen] + [item for item in results if item is not chosen][:3]
    clicked = None
    for item in attempts:
        before_url = _uia_address(wrapper)
        before_title = _uia_document_title(wrapper)
        if not _uia_click(item["control"]):
            continue
        deadline = time.time() + 7
        changed = False
        while time.time() < deadline:
            time.sleep(0.4)
            current = _uia_address(wrapper)
            title = _uia_document_title(wrapper)
            if (current and current != before_url) or (title and title != before_title):
                changed = True
                break
        if changed:
            clicked = item
            chosen = item
            break
    if clicked is None:
        raise BrowserError(
            f"hasil pencarian '{query}' tidak membuka halaman saat diklik. "
            "Nana tidak mengklaim berhasil; cek browser_state."
        )
    time.sleep(2.0)
    state = _uia_playing(wrapper, timeout=20)
    title = _uia_document_title(wrapper)
    current = _uia_address(wrapper)
    if not state.get("playing"):
        raise BrowserError(
            "halaman hasil sudah terbuka tetapi pemutaran belum terverifikasi.\n"
            f"Judul: {title}\nURL: {current}\n"
            "Coba browser_click(target=\"play\") atau cek browser_state."
        )
    position = state.get("time") or 0
    duration = state.get("duration") or 0
    status = f"playing ({position}s/{duration}s)" if duration else f"playing ({position}s)"
    return (
        f"{service.title()} memutar: {chosen['title']}\n"
        f"Judul halaman: {title}\nURL: {current}\n"
        f"Status: {status}"
    )


def play(service, query, browser_name=None):
    q = str(query or "").strip()
    if not q:
        raise BrowserError("query lagu/video kosong")
    name = _normalize(service or "youtube")

    target = service
    if "spotify" in name:
        target = "spotify"
    elif "youtube music" in name or "yt music" in name or "ytmusic" in name or "music.youtube" in name:
        target = "youtube music"
    elif "youtube" in name or name in ("", "auto", "musik", "music"):
        target = "youtube"
    return _uia_play(target, q, browser_name=browser_name)
