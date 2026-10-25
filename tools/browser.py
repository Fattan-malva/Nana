"""Kendali browser dinamis untuk NANA.

Dua lapis:

1. Chromium lewat Playwright (utama) — DOM asli, tab, kolom pencarian,
   klik hasil, verifikasi pemutaran. Browser yang dipakai:
   - attach ke browser user kalau ada CDP port terbuka, atau
   - browser khusus Nana (profil sendiri, login tersimpan).
2. Windows UI Automation + keyboard (fallback) — untuk tab di browser
   milik user yang tidak bisa di-attach.

Prinsip: jangan pernah menebak. Kalau tab yang diminta tidak ditemukan,
kembalikan daftar tab yang benar-benar ada, jangan menutup tab sembarangan.
"""

import difflib
import os
import re
import shutil
import threading
import time
from urllib.parse import urlparse


class BrowserError(Exception):
    pass


# --------------------------------------------------------------------------- config


def _env_flag(name, default=False):
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_float(name, default):
    try:
        return float(os.getenv(name, default) or default)
    except (TypeError, ValueError):
        return default


_profile_raw = os.getenv("NANA_BROWSER_PROFILE") or os.path.join(
    os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Nana", "browser"
)
PROFILE_DIR = os.path.expanduser(os.path.expandvars(_profile_raw))
HEADLESS = _env_flag("NANA_BROWSER_HEADLESS", False)
TIMEOUT_MS = int(_env_float("NANA_BROWSER_TIMEOUT", 20) * 1000)
CDP_PORTS = [
    int(p) for p in (os.getenv("NANA_CDP_PORTS", "9222,9223,9333").split(",")) if p.strip().isdigit()
]
DEBUG_PORT = 9333  # port milik browser Nana, supaya run berikutnya bisa attach

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

CHROMIUM_PROCESSES = ("brave.exe", "msedge.exe", "chrome.exe", "vivaldi.exe", "opera.exe", "firefox.exe")

# URL hasil "search engine" klasik. Nana sengaja menolak ini supaya selalu
# mengetik di kolom pencarian asli situs (bukan mengarang URL ?q=...).
_SEARCH_URL_RX = re.compile(
    r"(?:google\.[a-z.]+/search|bing\.com/search|search\.yahoo\.com/search|"
    r"duckduckgo\.com/(?:html/)?\?(?:[^#]*&)?q=|"
    r"youtube\.com/results\?search_query=|yandex\.[a-z.]+/search|baidu\.com/s\?)",
    re.IGNORECASE,
)


# ------------------------------------------------------------------- global state

_lock = threading.RLock()
_pw = None
_browser = None
_context = None
_owned = False

_last_page = None  # tab terakhir yang disentuh Nana (headless: semua tab "visible")


def _is_dead_error(exc) -> bool:
    text = str(exc).lower()
    return any(
        marker in text
        for marker in (
            "has been closed",
            "target closed",
            "browser closed",
            "context has been closed",
            "connection closed",
            "browser has disconnected",
            "target page, context or browser",
        )
    )


def _reset():
    global _pw, _browser, _context, _owned, _last_page
    with _lock:
        # Jangan pernah menutup browser milik user; cukup lepaskan koneksi.
        try:
            if _pw is not None:
                _pw.stop()
        except Exception:
            pass
        _pw = None
        _browser = None
        _context = None
        _owned = False
        _last_page = None


def _recoverable(fn):
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            if not _is_dead_error(e):
                raise
            _reset()
            return fn(*args, **kwargs)

    wrapper.__name__ = getattr(fn, "__name__", "wrapper")
    wrapper.__doc__ = getattr(fn, "__doc__", None)
    return wrapper


# ------------------------------------------------------------------ browser launch


def _find_chromium():
    """Cari browser Chromium yang terpasang (dinamis, tanpa path mati)."""
    preference = (os.getenv("NANA_BROWSER") or "auto").strip().lower()
    families = {
        "brave": ["brave", "brave-browser"],
        "chrome": ["chrome"],
        "edge": ["msedge"],
    }
    if preference in ("brave", "brave-browser"):
        order = ["brave"]
    elif preference in ("chrome", "google-chrome", "google chrome"):
        order = ["chrome"]
    elif preference in ("edge", "msedge", "microsoft edge"):
        order = ["edge"]
    else:
        order = ["brave", "chrome", "edge"]

    for family in order:
        for exe in families[family]:
            found = shutil.which(exe)
            if found:
                return found, family

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
    }
    for family in order:
        for root in roots:
            if not root:
                continue
            for rel in relative[family]:
                path = os.path.join(root, rel)
                if os.path.isfile(path):
                    return path, family

    # Terakhir: mapping aplikasi yang sudah dipindai desktop.py.
    try:
        from . import desktop

        for name, family in (("brave", "brave"), ("google chrome", "chrome"), ("microsoft edge", "edge")):
            target = desktop._dynamic_apps.get(name)
            if target and str(target).lower().endswith(".exe") and os.path.isfile(target):
                return target, family
    except Exception:
        pass
    return None, "edge"


def _probe_cdp():
    import httpx

    for port in CDP_PORTS:
        try:
            resp = httpx.get(f"http://127.0.0.1:{port}/json/version", timeout=0.7)
            if resp.status_code == 200:
                info = resp.json()
                if info.get("webSocketDebuggerUrl"):
                    return f"http://127.0.0.1:{port}"
        except Exception:
            continue
    return None


def _ensure_context():
    global _pw, _browser, _context, _owned
    with _lock:
        if _context is not None:
            try:
                _ = _context.pages
                return _context
            except Exception:
                _reset()

        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:
            raise BrowserError(
                "Playwright belum terpasang (pip install playwright). "
                f"Detail: {str(e).splitlines()[0]}"
            ) from e

        try:
            _pw = sync_playwright().start()
        except Exception as e:
            raise BrowserError(f"Playwright tidak bisa dijalankan: {e}") from e

        errors = []
        endpoint = _probe_cdp()
        if endpoint:
            try:
                _browser = _pw.chromium.connect_over_cdp(endpoint)
                _context = _browser.contexts[0] if _browser.contexts else _browser.new_context()
                _owned = False
                print(f"[browser] attach ke browser user di {endpoint}")
            except Exception as e:
                errors.append(f"attach: {e}")
                _browser = None
                _context = None

        if _context is None:
            exe, family = _find_chromium()
            launch_args = [
                "--start-maximized",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-blink-features=AutomationControlled",
                "--disable-features=Translate",
                f"--remote-debugging-port={DEBUG_PORT}",
            ]
            kwargs = dict(
                headless=HEADLESS,
                no_viewport=True,
                args=launch_args,
                locale="id-ID",
            )
            profiles = [PROFILE_DIR, PROFILE_DIR + "-alt"]
            last_error = None
            for profile in profiles:
                try:
                    os.makedirs(profile, exist_ok=True)
                    if family in ("edge",) or exe is None:
                        _context = _pw.chromium.launch_persistent_context(
                            profile, channel="msedge", **kwargs
                        )
                    else:
                        _context = _pw.chromium.launch_persistent_context(
                            profile, executable_path=exe, **kwargs
                        )
                    _owned = True
                    print(f"[browser] membuka browser {family or 'edge'} ({profile})")
                    break
                except Exception as e:
                    last_error = e
                    errors.append(str(e))
            if _context is None:
                _reset()
                raise BrowserError("browser tidak bisa dibuka: " + " | ".join(errors or [str(last_error)]))

        _context.set_default_timeout(TIMEOUT_MS)
        _context.set_default_navigation_timeout(max(TIMEOUT_MS, 30000))
        return _context


def _pages():
    ctx = _ensure_context()
    return [p for p in ctx.pages if not p.is_closed()]


def _touch(page):
    global _last_page
    _last_page = page
    return page


def _blank_page(pages=None):
    """Halaman about:blank yang bisa dipakai ulang (biar tidak menumpuk tab)."""
    pages = pages if pages is not None else _pages()
    for page in pages:
        try:
            if (page.url or "").strip() in ("about:blank", ""):
                return page
        except Exception:
            continue
    return None


def _session_running() -> bool:
    if _context is None:
        return False
    try:
        _ = _context.pages
        return True
    except Exception:
        return False


def _active_page():
    pages = _pages()
    if not pages:
        return _touch(_ensure_context().new_page())

    # Di browser headed hanya tab depan yang visibility-nya "visible".
    visible = []
    for page in pages:
        try:
            if page.evaluate("document.visibilityState") == "visible":
                visible.append(page)
        except Exception:
            continue

    if visible:
        if _last_page is not None and _last_page in visible:
            return _last_page
        if len(visible) == 1:
            return _touch(visible[0])
        return _touch(visible[-1])
    if _last_page is not None:
        try:
            if not _last_page.is_closed():
                return _last_page
        except Exception:
            pass
    return _touch(pages[-1])


def _goto(page, url, wait="domcontentloaded"):
    try:
        page.goto(url, wait_until=wait, timeout=max(TIMEOUT_MS, 30000))
    except Exception as e:
        raise BrowserError(f"gagal membuka {url}: {str(e).splitlines()[0]}") from e
    return _touch(page)


def _settle(page, timeout=6000):
    try:
        page.wait_for_load_state("domcontentloaded", timeout=timeout)
    except Exception:
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=2500)
    except Exception:
        pass
    time.sleep(0.3)


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


# ----------------------------------------------------------------------- DOM logic

_ACT_JS = r"""
([target, action, value]) => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const t = norm(target);
  const visible = el => {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    const s = getComputedStyle(el);
    if (s.visibility === 'hidden' || s.display === 'none') return false;
    if (parseFloat(s.opacity || '1') < 0.05) return false;
    return r.bottom > -300 && r.top < (innerHeight + 500);
  };
  const nameOf = el => {
    const bits = [
      el.getAttribute('aria-label'), el.getAttribute('placeholder'), el.getAttribute('title'),
      el.getAttribute('alt'), el.getAttribute('name'), el.id, el.getAttribute('data-testid'),
      el.innerText, (el.value !== undefined && el.value !== null) ? String(el.value) : ''
    ];
    return norm(bits.filter(Boolean).join(' '));
  };
  const scoreOf = (name) => {
    if (!name) return 0;
    if (name === t) return 100;
    if (name.startsWith(t)) return 82;
    if (name.includes(t)) return 62;
    const words = t.split(' ').filter(w => w.length > 2);
    if (words.length > 1 && words.every(w => name.includes(w))) return 46;
    return 0;
  };
  const sel = 'a,button,input,textarea,select,summary,label,h1,h2,h3,[role="heading"],[role="button"],[role="link"],[role="tab"],[role="menuitem"],[role="searchbox"],[role="combobox"],[role="option"],[role="listitem"],[contenteditable="true"]';

  let best = null;
  let matches = [];

  if (t.startsWith('css=')) {
    try { best = document.querySelector(target.slice(4).trim()); } catch (e) { best = null; }
    if (best) matches = [{ score: 100, visible: visible(best), tag: best.tagName.toLowerCase(), text: norm(best.innerText || best.value || '').slice(0, 120), href: best.href || '' }];
  } else {
    let bestTotal = 0;
    for (const el of document.querySelectorAll(sel)) {
      const name = nameOf(el);
      const score = scoreOf(name);
      if (!score) continue;
      const vis = visible(el);
      matches.push({
        score: score, visible: vis, tag: el.tagName.toLowerCase(),
        text: norm(el.innerText || el.value || '').slice(0, 120),
        role: el.getAttribute('role') || '', href: el.href || ''
      });
      const total = score + (vis ? 25 : 0);
      if (vis && total > bestTotal) { bestTotal = total; best = el; }
    }
    matches.sort((a, b) => (b.visible - a.visible) || (b.score - a.score));
  }

  if (!best) {
    return { ok: false, error: 'elemen tidak ditemukan', matches: matches.slice(0, 10) };
  }

  best.scrollIntoView({ block: 'center', inline: 'center' });
  const rect = best.getBoundingClientRect();
  const info = {
    ok: true, tag: best.tagName.toLowerCase(), name: nameOf(best).slice(0, 140),
    x: rect.left + rect.width / 2, y: rect.top + rect.height / 2,
    href: best.href || '', matchCount: matches.length, matches: matches.slice(0, 10)
  };

  if (action === 'click' || action === 'focus') {
    try { best.focus({ preventScroll: true }); } catch (e) {}
    if (action === 'focus' && best.select) { try { best.select(); } catch (e) {} }
    return info;
  }
  if (action === 'fill') {
    try { best.focus({ preventScroll: true }); } catch (e) {}
    const proto = best.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const desc = Object.getOwnPropertyDescriptor(proto, 'value');
    if (desc && desc.set) { desc.set.call(best, value); } else { best.value = value; }
    best.dispatchEvent(new Event('input', { bubbles: true }));
    best.dispatchEvent(new Event('change', { bubbles: true }));
    return info;
  }
  return info;
}
"""

_SEARCH_JS = r"""
() => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const visible = el => {
    const r = el.getBoundingClientRect();
    if (r.width < 8 || r.height < 8) return false;
    const s = getComputedStyle(el);
    if (s.visibility === 'hidden' || s.display === 'none') return false;
    if (parseFloat(s.opacity || '1') < 0.05) return false;
    return r.bottom > -100 && r.top < (innerHeight + 200);
  };
  const score = el => {
    if (!visible(el)) return -1;
    const type = (el.getAttribute('type') || '').toLowerCase();
    const role = (el.getAttribute('role') || '').toLowerCase();
    const blob = norm([
      el.getAttribute('aria-label'), el.getAttribute('placeholder'), el.getAttribute('name'),
      el.id, el.getAttribute('data-testid'), el.getAttribute('data-test-id'),
      el.getAttribute('title'), el.getAttribute('class')
    ].filter(Boolean).join(' '));
    if (role === 'searchbox') return 120;
    if (type === 'search') return 115;
    if (/(^|\s)(search|telusuri|cari|pencarian|query)(\s|$)/.test(blob)) return 100;
    if (el.closest('[role="search"], form[role="search"], [data-testid*="search" i]')) return 95;
    if (el.closest('header, nav, [role="banner"]') && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) return 80;
    if ((type === 'text' || type === '') && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) return 25;
    if (el.getAttribute('contenteditable') === 'true') return 20;
    return 0;
  };
  let best = null;
  let bestScore = -1;
  for (const el of document.querySelectorAll('input, textarea, [contenteditable="true"], [role="searchbox"], [role="combobox"]')) {
    const sc = score(el);
    if (sc > bestScore) { bestScore = sc; best = el; }
  }
  if (!best || bestScore < 20) return null;
  best.scrollIntoView({ block: 'center', inline: 'center' });
  const r = best.getBoundingClientRect();
  return {
    score: bestScore,
    tag: best.tagName.toLowerCase(),
    label: norm(best.getAttribute('aria-label') || best.getAttribute('placeholder') || best.getAttribute('name') || best.id || ''),
    x: r.left + r.width / 2,
    y: r.top + r.height / 2
  };
}
"""

_STATE_JS = r"""
() => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const visible = el => {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    const s = getComputedStyle(el);
    return s.visibility !== 'hidden' && s.display !== 'none';
  };
  const label = el => norm(
    el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.getAttribute('title') ||
    el.getAttribute('alt') || el.innerText || el.value || el.getAttribute('name') || el.id || ''
  ).slice(0, 90);
  const collect = (selector, max) => {
    const out = [];
    for (const el of document.querySelectorAll(selector)) {
      if (!visible(el)) continue;
      const text = label(el);
      if (!text || out.includes(text)) continue;
      out.push(text);
      if (out.length >= max) break;
    }
    return out;
  };
  const video = document.querySelector('video');
  return {
    url: location.href,
    title: document.title,
    ready: document.readyState,
    fields: collect('input:not([type="hidden"]), textarea, [contenteditable="true"], [role="searchbox"]', 10),
    buttons: collect('button, [role="button"], input[type="submit"]', 16),
    links: collect('a[href]', 16),
    media: video ? {
      playing: !video.paused && video.readyState >= 2,
      time: Math.round(video.currentTime || 0),
      duration: Number.isFinite(video.duration) ? Math.round(video.duration) : 0,
      muted: !!video.muted
    } : null,
    scroll: { y: Math.round(scrollY), height: Math.round(document.documentElement.scrollHeight) },
    text: norm(document.body ? document.body.innerText : '').slice(0, 1200)
  };
}
"""


def _find(page, target, action="focus", value=""):
    try:
        result = page.evaluate(_ACT_JS, [str(target or ""), action, str(value or "")])
    except Exception as e:
        raise BrowserError(f"gagal mencari '{target}': {str(e).splitlines()[0]}") from e
    if not isinstance(result, dict):
        raise BrowserError(f"gagal mencari '{target}'")
    return result


# ------------------------------------------------------------------------ UI Automation


def _window_process(hwnd):
    try:
        import ctypes
        from ctypes import wintypes
        import psutil

        pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(int(hwnd), ctypes.byref(pid))
        return psutil.Process(pid.value).name().lower()
    except Exception:
        return ""


def _browser_windows():
    try:
        from . import desktop
    except Exception:
        return []
    windows = []
    for win in desktop.list_windows():
        proc = _window_process(win["hwnd"])
        # Wajib berdasarkan proses: VS Code juga memakai class Chrome_WidgetWin_1.
        if proc in CHROMIUM_PROCESSES:
            windows.append(win)
    return windows


def _uia_tabs(hwnd):
    try:
        from pywinauto import Desktop as PwDesktop

        win = PwDesktop(backend="uia").window(handle=int(hwnd))
        tabs = []
        # Jalur cepat: tab strip biasanya kontrol "Tab" dengan anak TabItem.
        try:
            strip = win.child_window(control_type="Tab", found_index=0)
            for control in strip.children():
                try:
                    name = _clean_tab_name(control.window_text())
                    if name:
                        tabs.append((name, control))
                except Exception:
                    continue
            if tabs:
                return tabs
        except Exception:
            pass
        # Fallback: telusuri descendant dengan kedalaman terbatas.
        for control in win.descendants(control_type="TabItem", depth=8):
            try:
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
    for win in _browser_windows()[:6]:
        for name, control in _uia_tabs(win["hwnd"]):
            result.append({"window": win["title"], "hwnd": win["hwnd"], "title": name, "control": control})
    return result


def _uia_find_tab(needle):
    needle = str(needle or "")
    best = None
    best_score = 0
    for tab in _uia_all_tabs():
        score = _fuzzy_score(tab["title"], needle)
        if score > best_score:
            best, best_score = tab, score
    return best if best_score >= 60 else None


def _uia_focus(tab):
    """Fokuskan tab user dan pastikan benar-benar tab itu yang aktif."""
    control = tab.get("control")
    if control is None:
        return False
    for action in ("click_input", "select"):
        try:
            getattr(control, action)()
        except Exception:
            continue
        time.sleep(0.35)
        try:
            if control.is_selected():
                return True
        except Exception:
            # Sebagian kontrol tidak mendukung is_selected; cek judul window.
            break

    try:
        from pywinauto import Desktop as PwDesktop

        win = PwDesktop(backend="uia").window(handle=int(tab["hwnd"]))
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


# --------------------------------------------------------------------- tab helpers


def _page_score(page, needle):
    try:
        title = page.title()
        url = page.url
    except Exception:
        return 0
    return max(_fuzzy_score(title, needle), _fuzzy_score(url, needle))


def _best_page(pages, needle):
    best = None
    best_score = 0
    for page in pages:
        try:
            score = _page_score(page, needle)
        except Exception:
            continue
        if score > best_score:
            best, best_score = page, score
    return best if best_score >= 55 else None


def _tab_line(index, page, active=False):
    try:
        return f"{index}. {'[aktif] ' if active else ''}{page.title()} — {page.url}"
    except Exception:
        return f"{index}. (tab tidak bisa dibaca)"


@_recoverable
def list_tabs_text():
    lines = ["Browser Nana (bisa dikendalikan penuh):"]
    managed_titles = set()
    if _session_running():
        try:
            pages = _pages()
        except Exception as e:
            pages = []
            lines.append(f"(error: {str(e).splitlines()[0]})")
        current = None
        try:
            current = _active_page()
        except Exception:
            current = None
        for index, page in enumerate(pages, 1):
            lines.append("  " + _tab_line(index, page, active=(page is current)))
            try:
                managed_titles.add(_normalize(page.title()))
            except Exception:
                pass
        if not pages and len(lines) == 1:
            lines.append("  (belum ada tab)")
    else:
        lines.append("  (belum aktif; akan dibuka saat dibutuhkan)")

    other_windows = []
    for win in _browser_windows()[:5]:
        title = win["title"].strip()
        if not title or _normalize(title) in managed_titles:
            continue  # ini jendela browser Nana sendiri
        tabs = [name for name, _ in _uia_tabs(win["hwnd"])][:25]
        if not tabs:
            continue
        other_windows.append((title, tabs))

    if other_windows:
        lines.append("")
        lines.append("Browser user (kontrol terbatas via UI Automation):")
        for win_title, tabs in other_windows:
            lines.append(f"  Window: {win_title}")
            for name in tabs:
                lines.append(f"    - {name}")
    if len(lines) == 1:
        lines.append("  (tidak ada tab browser)")
    return "\n".join(lines)


@_recoverable
def activate_tab(title, source="auto"):
    needle = str(title or "").strip()
    src = _normalize(source or "auto")
    if not needle:
        raise BrowserError("judul tab kosong")
    if src in ("auto", "nana", "otomatis") and _session_running():
        page = _best_page(_pages(), needle)
        if page is not None:
            try:
                page.bring_to_front()
                _touch(page)
                time.sleep(0.4)
                return f"Fokus ke tab Nana: {page.title()}"
            except Exception:
                pass
        if src in ("nana", "otomatis"):
            raise BrowserError(f"tab '{needle}' tidak ada di browser Nana.\n{list_tabs_text()}")
    if src in ("auto", "user", "pengguna"):
        activated = _uia_activate_tab(needle)
        if activated:
            return f"Fokus ke tab user: {activated}"
    raise BrowserError(f"tab '{needle}' tidak ditemukan.\n{list_tabs_text()}")


@_recoverable
def close_tab(title=None, count=1, source="auto"):
    needle = str(title or "").strip()
    src = _normalize(source or "auto")
    try:
        amount = max(1, min(10, int(count or 1)))
    except (TypeError, ValueError):
        amount = 1

    closed = []
    for index in range(amount):
        target = needle if index == 0 else ""
        result = None
        error = None

        if src in ("auto", "nana", "otomatis") and _session_running():
            try:
                pages = _pages()
                if target:
                    page = _best_page(pages, target)
                    if page is None:
                        raise BrowserError(f"tab '{target}' tidak ada di browser Nana")
                else:
                    page = _active_page()
                closed_title = page.title()
                before = len(pages)
                try:
                    page.close(run_before_unload=False)
                except TypeError:
                    page.close()
                time.sleep(0.4)
                if len(_pages()) >= before:
                    raise BrowserError("tab tidak mau tertutup")
                result = closed_title or "(tanpa judul)"
            except Exception as e:
                error = e
                if src in ("nana", "otomatis"):
                    raise BrowserError(f"{e}\n{list_tabs_text()}") from e

        if result is None and src in ("auto", "user", "pengguna"):
            try:
                if target:
                    tab = _uia_find_tab(target)
                    if tab is None:
                        raise BrowserError(f"tab '{target}' tidak ditemukan")
                    closed_title = tab["title"]
                    if not _uia_focus(tab):
                        raise BrowserError(
                            f"tab '{closed_title}' tidak bisa difokuskan. "
                            "Nana tidak menutup tab lain supaya aman."
                        )
                    from . import keyboard

                    keyboard.press_key("ctrl+w")
                    time.sleep(0.8)
                    remaining = [name for name, _ in _uia_tabs(tab["hwnd"])]
                    if any(_normalize(name) == _normalize(closed_title) for name in remaining):
                        raise BrowserError(
                            f"tab '{closed_title}' belum tertutup. "
                            "Cek kembali dengan browser_tabs."
                        )
                    result = closed_title
                else:
                    # Tanpa judul, jangan menebak tab di browser user.
                    raise BrowserError(
                        "judul tab kosong. Sebutkan tab yang mau ditutup "
                        "(lihat daftar dari browser_tabs)."
                    )
            except Exception as e:
                if error is None:
                    error = e

        if result is None:
            message = str(error) if error else "tab gagal ditutup"
            raise BrowserError(f"{message}\n{list_tabs_text()}")
        closed.append(result)

    return "Tab ditutup: " + ", ".join(closed)


# -------------------------------------------------------------------- page actions


def is_search_url(url) -> bool:
    """True untuk URL hasil search engine (yang sengaja tidak dipakai Nana)."""
    return bool(_SEARCH_URL_RX.search(str(url or "")))


@_recoverable
def open_url(url, new_tab=False):
    target = str(url or "").strip()
    if not target.lower().startswith(("http://", "https://")):
        raise BrowserError("hanya URL http/https yang diizinkan")
    if is_search_url(target):
        raise BrowserError(
            "URL pencarian tidak dipakai. Gunakan browser_search(query=..., site=...) "
            "supaya Nana mengetik di kolom pencarian asli situs itu."
        )

    ctx = _ensure_context()
    host = urlparse(target).netloc.lower().replace("www.", "")
    page = None
    if not new_tab:
        for candidate in _pages():
            try:
                if host and host in candidate.url.lower():
                    page = candidate
                    page.bring_to_front()
                    break
            except Exception:
                continue
    if page is None:
        pages = _pages()
        page = _blank_page(pages)
        if page is None:
            page = ctx.new_page()
    _goto(page, target)
    try:
        page.bring_to_front()
    except Exception:
        pass
    try:
        title = page.title()
    except Exception:
        title = target
    return f"Dibuka: {title} — {page.url}"


@_recoverable
def state_text():
    page = _active_page()
    try:
        data = page.evaluate(_STATE_JS)
    except Exception as e:
        raise BrowserError(f"gagal membaca halaman: {str(e).splitlines()[0]}") from e

    lines = [
        f"URL: {data.get('url')}",
        f"Judul: {data.get('title')}",
        f"Status: {data.get('ready')}",
    ]
    media = data.get("media")
    if media:
        status = "playing" if media.get("playing") else "paused"
        duration = media.get("duration") or 0
        extra = " (mute)" if media.get("muted") else ""
        where = f"{duration}s" if duration else "live/stream"
        lines.append(f"Media: {status} ({media.get('time')}s/{where}){extra}")
    scroll = data.get("scroll") or {}
    lines.append(f"Scroll: {scroll.get('y', 0)}/{scroll.get('height', 0)}")

    fields = data.get("fields") or []
    if fields:
        lines.append("Kolom input: " + " | ".join(fields[:8]))
    buttons = data.get("buttons") or []
    if buttons:
        lines.append("Tombol: " + " | ".join(buttons[:12]))
    links = data.get("links") or []
    if links:
        lines.append("Link: " + " | ".join(links[:12]))
    text = data.get("text") or ""
    if text:
        lines.append("Teks: " + text[:700])
    return "\n".join(lines)


@_recoverable
def find_text(target):
    needle = str(target or "").strip()
    if not needle:
        raise BrowserError("target kosong")
    page = _active_page()
    result = _find(page, needle, action="none")
    matches = result.get("matches") or []
    if not matches:
        return f"Tidak ada elemen yang cocok dengan '{needle}'."
    lines = [f"Cocok untuk '{needle}':"]
    for index, item in enumerate(matches[:10], 1):
        flag = "" if item.get("visible") else " (tersembunyi)"
        href = f" -> {item['href']}" if item.get("href") else ""
        lines.append(
            f"{index}. <{item.get('tag')}> {item.get('text')}{flag}{href} "
            f"(skor {item.get('score')})"
        )
    return "\n".join(lines)


def _click_page(page, target, selector=None):
    query = f"css={selector}" if selector else str(target or "")
    result = _find(page, query, action="click")
    if not result.get("ok"):
        matches = result.get("matches") or []
        hint = ""
        if matches:
            hint = "\nKandidat: " + " | ".join(m.get("text", "")[:60] for m in matches[:6] if m.get("text"))
        raise BrowserError(f"elemen '{target or selector}' tidak ditemukan.{hint}")

    x, y = result.get("x"), result.get("y")
    href = result.get("href") or ""
    pages_before = set(id(p) for p in _pages())
    try:
        url_before = page.url
    except Exception:
        url_before = ""
    clicked = False
    if x is not None and y is not None:
        try:
            page.mouse.click(float(x), float(y))
            clicked = True
        except Exception:
            clicked = False

    if not clicked:
        # Fallback: klik lewat DOM.
        try:
            page.evaluate(_ACT_JS, [query, "click", ""])
            page.evaluate(
                """(t) => { const el = document.querySelector(t); if (el) el.click(); }""",
                selector or "",
            )
        except Exception:
            pass

    time.sleep(0.5)
    try:
        page.wait_for_load_state("domcontentloaded", timeout=5000)
    except Exception:
        pass
    time.sleep(0.3)

    # Tab baru (mis. target=_blank) -> pindah ke tab itu.
    new_pages = [p for p in _pages() if id(p) not in pages_before]
    if new_pages:
        page = new_pages[-1]
        try:
            page.bring_to_front()
        except Exception:
            pass
        _touch(page)
        return page, result

    # Klik tidak berpindah halaman walau ada href -> buka langsung.
    if href and href.startswith("http"):
        try:
            if page.url == url_before:
                _goto(page, href)
        except Exception:
            pass
    return page, result


@_recoverable
def click_text(target, selector=None):
    page = _active_page()
    page, result = _click_page(page, target, selector)
    try:
        title = page.title()
        url = page.url
    except Exception:
        title, url = "(tidak diketahui)", ""
    return f"Klik: {result.get('name') or target}\nSekarang: {title} — {url}"


@_recoverable
def fill_text(target, text, submit=True, selector=None):
    value = str(text or "")
    page = _active_page()
    query = f"css={selector}" if selector else str(target or "")
    result = _find(page, query, action="focus")
    if not result.get("ok"):
        raise BrowserError(f"kolom '{target or selector}' tidak ditemukan")

    x, y = result.get("x"), result.get("y")
    if x is not None and y is not None:
        try:
            page.mouse.click(float(x), float(y))
        except Exception:
            pass
    try:
        page.keyboard.press("Control+A")
    except Exception:
        pass
    try:
        page.keyboard.type(value, delay=18)
    except Exception as e:
        raise BrowserError(f"gagal mengetik: {str(e).splitlines()[0]}") from e

    if submit:
        page.keyboard.press("Enter")
        _settle(page)

    return f"Teks '{value[:80]}' dimasukkan ke: {result.get('name') or target}"


_PW_KEYS = {
    "enter": "Enter",
    "return": "Enter",
    "esc": "Escape",
    "escape": "Escape",
    "tab": "Tab",
    "space": " ",
    "backspace": "Backspace",
    "delete": "Delete",
    "up": "ArrowUp",
    "down": "ArrowDown",
    "left": "ArrowLeft",
    "right": "ArrowRight",
    "pageup": "PageUp",
    "pagedown": "PageDown",
    "home": "Home",
    "end": "End",
}
_MODIFIERS = {
    "ctrl": "Control",
    "control": "Control",
    "shift": "Shift",
    "alt": "Alt",
    "win": "Meta",
    "meta": "Meta",
}


def _playwright_key(combo):
    raw = str(combo or "").strip()
    if not raw:
        raise BrowserError("tombol kosong")
    parts = [p.strip() for p in raw.split("+") if p.strip()]
    lowered = [p.lower() for p in parts]
    if "ctrl" in lowered or "control" in lowered:
        if lowered[-1] in ("w", "t", "n", "shift+w"):
            raise BrowserError("gunakan browser_close_tab untuk menutup/membuka tab")
    if lowered in (["alt", "f4"],):
        raise BrowserError("alt+f4 tidak diizinkan")
    mapped = []
    for index, part in enumerate(parts):
        low = part.lower()
        if low in _MODIFIERS:
            mapped.append(_MODIFIERS[low])
        elif low in _PW_KEYS:
            mapped.append(_PW_KEYS[low])
        elif len(part) == 1:
            mapped.append(part.upper() if index < len(parts) - 1 else part)
        else:
            mapped.append(part)
    return "+".join(mapped)


@_recoverable
def press(key):
    page = _active_page()
    combo = _playwright_key(key)
    page.keyboard.press(combo)
    time.sleep(0.3)
    return f"Tombol {combo} ditekan di halaman"


@_recoverable
def scroll(direction="down", amount=3):
    page = _active_page()
    try:
        step = max(1, min(20, int(amount or 3)))
    except (TypeError, ValueError):
        step = 3
    dx, dy = 0, 0
    direction = str(direction or "down").lower()
    if direction == "down":
        dy = 480 * step
    elif direction == "up":
        dy = -480 * step
    elif direction == "right":
        dx = 480 * step
    elif direction == "left":
        dx = -480 * step
    else:
        raise BrowserError("arah scroll harus up/down/left/right")

    try:
        size = page.evaluate("() => [innerWidth, innerHeight]") or [1200, 800]
    except Exception:
        size = [1200, 800]
    width, height = size[0] or 1200, size[1] or 800
    try:
        page.mouse.move(width / 2, height / 2)
    except Exception:
        pass
    page.mouse.wheel(dx, dy)
    time.sleep(0.5)
    try:
        position = page.evaluate("() => Math.round(scrollY)")
    except Exception:
        position = "?"
    return f"Scroll {direction} ({step}x). Posisi: {position}"


@_recoverable
def wait_for(target, timeout=10):
    needle = str(target or "").strip()
    if not needle:
        raise BrowserError("target kosong")
    try:
        limit = max(1, min(60, int(timeout or 10)))
    except (TypeError, ValueError):
        limit = 10
    page = _active_page()
    deadline = time.time() + limit

    if needle.startswith("css=") or needle.startswith(("#", ".", "[")):
        selector = needle[4:] if needle.startswith("css=") else needle
        try:
            page.wait_for_selector(selector, state="visible", timeout=limit * 1000)
            return f"Elemen '{selector}' muncul"
        except Exception as e:
            raise BrowserError(f"elemen '{selector}' tidak muncul dalam {limit}s: {str(e).splitlines()[0]}") from e

    lowered = needle.lower()
    while time.time() < deadline:
        try:
            found = page.evaluate("(t) => (document.body ? document.body.innerText : '').toLowerCase().includes(t)", lowered)
        except Exception:
            found = False
        if found:
            return f"Teks '{needle}' muncul di halaman"
        time.sleep(0.4)
    raise BrowserError(f"teks '{needle}' tidak muncul dalam {limit}s")


# ------------------------------------------------------------------- site helpers


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


def _page_for_site(site):
    url = _site_url(site)
    if not url:
        return _active_page()
    host = urlparse(url).netloc.lower().replace("www.", "")
    for page in _pages():
        try:
            if host and host in page.url.lower():
                page.bring_to_front()
                return _touch(page)
        except Exception:
            continue
    pages = _pages()
    page = _blank_page(pages)
    if page is None:
        page = _ensure_context().new_page()
    _goto(page, url)
    _settle(page)
    try:
        page.bring_to_front()
    except Exception:
        pass
    return page


def _dismiss_consent(page):
    for label in ("Accept all", "Terima semua", "I agree", "Setuju", "Accept", "Terima"):
        try:
            button = page.get_by_role("button", name=re.compile(rf"^{re.escape(label)}$", re.IGNORECASE))
            if button.count() > 0 and button.first.is_visible():
                button.first.click(timeout=1200)
                time.sleep(0.4)
                return True
        except Exception:
            continue
    return False


def _fill_search_box(page, query):
    info = page.evaluate(_SEARCH_JS)
    if not info:
        raise BrowserError("kolom pencarian tidak ditemukan di halaman ini")
    try:
        page.mouse.click(float(info["x"]), float(info["y"]))
    except Exception:
        pass
    try:
        page.keyboard.press("Control+A")
    except Exception:
        pass
    page.keyboard.type(str(query), delay=18)
    page.keyboard.press("Enter")
    _settle(page)
    return info


def _extract_links(page, limit=12):
    try:
        return page.evaluate(
            """(limit) => {
              const seen = new Set();
              const out = [];
              for (const a of document.querySelectorAll('a[href]')) {
                const r = a.getBoundingClientRect();
                if (r.width < 2 || r.height < 2) continue;
                const text = (a.innerText || a.textContent || '').replace(/\\s+/g, ' ').trim();
                if (text.length < 3) continue;
                if (!/^https?:/i.test(a.href)) continue;
                if (seen.has(a.href)) continue;
                seen.add(a.href);
                out.push({ title: text.slice(0, 160), href: a.href });
                if (out.length >= limit) break;
              }
              return out;
            }""",
            limit,
        )
    except Exception:
        return []


_NAV_MARKERS = (
    "/settings",
    "/preferences",
    "/account",
    "/login",
    "/signin",
    "/about",
    "/privacy",
    "/terms",
    "/help",
    "/advertis",
    "/careers",
    "/contact",
    "/cookies",
    "start.duckduckgo.com",
    "duckduckgo-help-pages",
    "?ia=",
    "&ia=",
    "javascript:",
)


def _search_results(page, limit=12, query=""):
    """Tunggu hasil pencarian muncul dan urutkan yang paling relevan."""
    deadline = time.time() + 8
    links = []
    while time.time() < deadline:
        try:
            page.wait_for_load_state("domcontentloaded", timeout=2500)
        except Exception:
            pass
        links = _extract_links(page, 300)
        if len(links) >= 3:
            break
        time.sleep(0.45)

    words = [w for w in re.split(r"[^a-z0-9]+", _normalize(query)) if len(w) > 2]
    scored = []
    for item in links:
        title = item.get("title") or ""
        href = (item.get("href") or "").lower()
        if any(marker in href for marker in _NAV_MARKERS):
            continue
        lowered = title.lower()
        hits = sum(1 for word in words if word in lowered)
        score = 0.0
        for word in words:
            if word in lowered:
                score += 12
            if word in href:
                score += 4
        score += min(len(title), 120) / 30.0
        if words and hits == 0:
            score -= 18  # biasanya link navigasi/footer, bukan hasil
        scored.append((score, item))

    scored.sort(key=lambda pair: -pair[0])
    if words:
        relevant = [item for score, item in scored if score > 0]
        if relevant:
            return relevant[:limit]
    return [item for _, item in scored[:limit]]


def _pick_result(candidates, query):
    words = [w for w in re.split(r"[^a-z0-9]+", _normalize(query)) if len(w) > 2]
    best = None
    best_score = -1.0
    for item in candidates or []:
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
        score += ratio * 40
        if "youtube.com/watch" in href:
            score += 8
        if score > best_score:
            best, best_score = item, score
    return best if best_score >= 18 else None


@_recoverable
def search_on_site(query, site=None):
    q = str(query or "").strip()
    if not q:
        raise BrowserError("query kosong")

    page = _page_for_site(site) if site else _active_page()
    _dismiss_consent(page)
    box = _fill_search_box(page, q)
    time.sleep(0.4)
    try:
        title = page.title()
    except Exception:
        title = ""
    results = _search_results(page, 10, q)
    lines = [
        f"Pencarian '{q}' dijalankan lewat kolom pencarian situs ({box.get('label') or box.get('tag')}).",
        f"Halaman: {title} — {page.url}",
    ]
    if results:
        lines.append("Hasil yang terlihat:")
        for index, item in enumerate(results[:8], 1):
            lines.append(f"{index}. {item['title']} -> {item['href']}")
    else:
        lines.append("Belum ada hasil yang terbaca. Coba browser_state atau browser_wait.")
    return "\n".join(lines)


def _verify_media(page, timeout=15):
    deadline = time.time() + timeout
    state = None
    while time.time() < deadline:
        try:
            state = page.evaluate(
                """() => { const v = document.querySelector('video, audio');
                   if (!v) return null;
                   const dur = Number.isFinite(v.duration) ? Math.round(v.duration) : 0;
                   return {playing: !v.paused && v.readyState >= 2,
                           muted: !!v.muted,
                           time: Math.round(v.currentTime || 0),
                           duration: dur}; }"""
            )
        except Exception:
            state = None
        if state and state.get("playing") and state.get("time", 0) > 0:
            return state
        time.sleep(0.5)

    # Beberapa situs menahan autoplay / memulai dalam keadaan mute.
    try:
        page.evaluate(
            """() => { const v = document.querySelector('video, audio');
               if (!v) return;
               if (v.muted) v.muted = false;
               v.play().catch(() => {}); }"""
        )
        time.sleep(2)
        state = page.evaluate(
            """() => { const v = document.querySelector('video, audio');
               if (!v) return null;
               const dur = Number.isFinite(v.duration) ? Math.round(v.duration) : 0;
               return {playing: !v.paused && v.readyState >= 2,
                       muted: !!v.muted,
                       time: Math.round(v.currentTime || 0),
                       duration: dur}; }"""
        )
    except Exception:
        pass
    return state


def _wait_youtube_ad(page, timeout=60):
    """Tunggu iklan selesai supaya durasi yang dilaporkan adalah durasi
    lagu/video, bukan iklan."""
    time.sleep(2.0)  # beri kesempatan preroll menempel
    deadline = time.time() + timeout
    quiet = 0
    while time.time() < deadline:
        try:
            showing = page.evaluate(
                """() => {
                  if (document.querySelector('.html5-video-player.ad-showing')) return true;
                  if (document.querySelector('.ytp-ad-player-overlay, .ytp-ad-preview-container')) return true;
                  const module = document.querySelector('.ytp-ad-module');
                  return !!(module && module.offsetHeight > 0 && (module.innerText || '').trim());
                }"""
            )
        except Exception:
            return
        if showing:
            quiet = 0
            try:
                page.evaluate(
                    """() => {
                      const b = document.querySelector(
                        '.ytp-ad-skip-button, .ytp-ad-skip-button-modern, button.ytp-skip-ad-button'
                      );
                      if (b) { b.click(); return true; }
                      return false;
                    }"""
                )
            except Exception:
                pass
            time.sleep(1.0)
        else:
            quiet += 1
            if quiet >= 3:
                return
            time.sleep(1.0)


def _play_youtube(query):
    page = _page_for_site("youtube")
    _dismiss_consent(page)
    _fill_search_box(page, query)
    try:
        page.wait_for_selector("ytd-video-renderer a#video-title, a#video-title", timeout=15000)
    except Exception:
        pass
    time.sleep(0.5)

    candidates = []
    try:
        candidates = page.evaluate(
            """() => Array.from(document.querySelectorAll('ytd-video-renderer a#video-title, a#video-title'))
                 .map(a => ({title: (a.innerText || a.textContent || '').trim(), href: a.href}))
                 .filter(x => x.title && x.href)"""
        )
    except Exception:
        candidates = []

    if not candidates:
        candidates = [c for c in _search_results(page, 20, query) if "/watch" in (c.get("href") or "")]

    chosen = _pick_result(candidates, query)
    if not chosen:
        raise BrowserError(
            f"tidak menemukan video yang cocok untuk '{query}'.\n{state_text()}"
        )

    href = chosen["href"]
    clicked = None
    try:
        coords = page.evaluate(
            """(href) => { const a = Array.from(document.querySelectorAll('a[href]')).find(x => x.href === href);
                 if (!a) return null; a.scrollIntoView({block: 'center'}); const r = a.getBoundingClientRect();
                 return [r.left + r.width / 2, r.top + r.height / 2]; }""",
            href,
        )
        if coords:
            page.mouse.click(float(coords[0]), float(coords[1]))
            clicked = True
    except Exception:
        clicked = False

    if not clicked:
        _goto(page, href)
    else:
        try:
            page.wait_for_url(re.compile(r"/watch"), timeout=7000)
        except Exception:
            _goto(page, href)

    _wait_youtube_ad(page)
    state = _verify_media(page, timeout=18)
    try:
        title = page.title()
        url = page.url
    except Exception:
        title, url = chosen["title"], href

    if not state or not state.get("playing"):
        raise BrowserError(
            f"halaman video sudah terbuka tapi belum terverifikasi berputar.\n"
            f"Judul: {title}\nURL: {url}\n"
            "Coba browser_click(target=\"play\") atau cek dengan browser_state."
        )

    duration = state.get("duration") or 0
    status = (
        f"playing ({state.get('time')}s/{duration}s)"
        if duration
        else f"playing (live/stream, {state.get('time')}s)"
    )
    return (
        f"YouTube memutar: {chosen['title']}\n"
        f"Judul halaman: {title}\nURL: {url}\n"
        f"Status: {status}"
    )


def _play_spotify(query):
    page = _page_for_site("spotify")
    _dismiss_consent(page)
    time.sleep(0.6)

    if "login" in (page.url or "").lower():
        raise BrowserError(
            "Spotify Web meminta login. Silakan login sekali di jendela browser Nana, lalu ulangi."
        )

    try:
        _fill_search_box(page, query)
    except BrowserError:
        raise BrowserError(
            "kolom pencarian Spotify tidak ditemukan. Mungkin halaman login atau layout berubah.\n"
            + state_text()
        )

    time.sleep(1.5)
    try:
        page.wait_for_selector('[data-testid="tracklist-row"], [role="row"]', timeout=12000)
    except Exception:
        pass

    clicked = page.evaluate(
        """(query) => {
          const rows = Array.from(document.querySelectorAll('[data-testid="tracklist-row"], [role="row"]'))
            .filter(r => (r.innerText || '').trim().length > 3);
          if (!rows.length) return {ok: false};
          const words = query.toLowerCase().split(/\\s+/).filter(w => w.length > 2);
          let pick = rows[0];
          let bestScore = -1;
          for (const row of rows) {
            const t = (row.innerText || '').toLowerCase();
            let score = 0;
            for (const w of words) { if (t.includes(w)) score += 10; }
            score += Math.min(t.length, 120) / 300;
            if (score > bestScore) { bestScore = score; pick = row; }
          }
          const text = (pick.innerText || '').replace(/\\s+/g, ' ').slice(0, 160);
          const btn = pick.querySelector('[data-testid="play-button"], button[aria-label^="Play"], button[aria-label^="Putar"]');
          if (btn) { btn.click(); return {ok: true, via: 'play-button', text}; }
          pick.click();
          return {ok: true, via: 'row', text};
        }""",
        str(query),
    )

    time.sleep(2.5)
    status = page.evaluate(
        """() => {
          const widget = document.querySelector('[data-testid="now-playing-widget"]');
          const btn = document.querySelector('[data-testid="control-button-playpause"]');
          const label = btn ? (btn.getAttribute('aria-label') || '') : '';
          const login = document.querySelector('[data-testid="login-button"], a[href*="/login"]');
          return {now: widget ? widget.innerText.replace(/\\s+/g, ' ').slice(0, 160) : '',
                  playing: /pause|jeda/i.test(label),
                  loggedOut: !!login};
        }"""
    ) or {}

    try:
        title = page.title()
    except Exception:
        title = "Spotify"

    if clicked and clicked.get("ok"):
        state = _verify_media(page, timeout=10)
        playing = bool((state and state.get("playing")) or status.get("playing"))
        if not playing:
            raise BrowserError(
                "Spotify sudah diklik tetapi pemutaran belum terverifikasi. "
                "Bisa jadi perlu login/Premium atau hasil belum siap.\n"
                f"Judul: {title}\nLagu terpilih: {clicked.get('text')}"
            )
        note = ""
        if status.get("loggedOut"):
            note = (
                "\nCatatan: Spotify terdeteksi belum login, jadi yang berputar bisa berupa "
                "preview pendek. Minta user login di jendela browser Nana untuk pemutaran penuh."
            )
        return (
            f"Spotify memutar: {clicked.get('text')}\n"
            f"Judul halaman: {title}\n"
            f"Now playing: {status.get('now') or '(tidak terbaca)'}"
            f"{note}"
        )

    raise BrowserError(
        "tidak ada hasil Spotify yang bisa dipilih. Coba browser_state untuk melihat halaman.\n"
        + state_text()
    )


def _play_generic(service, query):
    site = service or ""
    page = _page_for_site(site)
    _dismiss_consent(page)
    _fill_search_box(page, query)
    time.sleep(0.5)
    results = _search_results(page, 20, query)
    chosen = _pick_result(results, query)
    if not chosen:
        raise BrowserError(f"tidak ada hasil yang cocok untuk '{query}' di {service}")
    page, _ = _click_page(page, chosen["title"])
    state = _verify_media(page, timeout=15)
    try:
        title, url = page.title(), page.url
    except Exception:
        title, url = chosen["title"], chosen["href"]
    if state and state.get("playing"):
        duration = state.get("duration") or 0
        status = (
            f"playing ({state.get('time')}s/{duration}s)"
            if duration
            else f"playing (live/stream, {state.get('time')}s)"
        )
        return (
            f"{service} memutar: {chosen['title']}\n"
            f"Halaman: {title} — {url}\n"
            f"Status: {status}"
        )
    raise BrowserError(
        f"hasil '{chosen['title']}' sudah dibuka tetapi media belum terverifikasi berputar.\n"
        f"Halaman: {title} — {url}\n"
        "Cek dengan browser_state, lalu klik tombol play secara manual bila perlu."
    )


@_recoverable
def play(service, query):
    q = str(query or "").strip()
    if not q:
        raise BrowserError("query lagu/video kosong")
    name = _normalize(service or "youtube")
    if "spotify" in name:
        return _play_spotify(q)
    if "youtube music" in name or "yt music" in name or "ytmusic" in name or "music.youtube" in name:
        return _play_generic("youtube music", q)
    if "youtube" in name or name in ("", "auto", "musik", "music"):
        return _play_youtube(q)
    return _play_generic(service, q)


@_recoverable
def stop_browser():
    global _pw, _browser, _context, _owned
    if not _session_running():
        return "Browser otomatis sedang tidak aktif"
    if not _owned:
        raise BrowserError(
            "Nana menempel ke browser milik user; menutup seluruhnya tidak diizinkan. "
            "Gunakan browser_close_tab atau close_browser."
        )
    try:
        _context.close()
    finally:
        _reset()
    return "Browser otomatis ditutup"
