"""Dispatcher tool: validasi, eksekusi, dan hasil untuk LLM."""

import json
import os
import re

from core.task_engine import request_cancel

from . import (
    browser,
    desktop,
    interaction,
    keyboard,
    observation,
    safety,
    shell,
    verification,
    web,
)
from .registry import TOOLS


class ToolError(Exception):
    pass


def _text(args, key, required=True):
    value = args.get(key, "")
    value = "" if value is None else str(value).strip()
    if required and not value:
        raise ToolError(f"argumen '{key}' wajib diisi")
    return value


def _strict_vscode():
    value = os.getenv("TOOLS_STRICT_VSCODE", "false").strip().lower()
    return value in ("1", "true", "yes", "on")


def _bool(args, key, default=False):
    """Argumen boolean dari model kadang berupa string ('true'/'false')."""
    value = args.get(key, default)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "ya")
    return bool(value)


def _call(name, args):
    if name == "open_app":
        app = _text(args, "name")
        desktop.open_app(app)
        return f"{app} dibuka"

    if name == "open_terminal":
        target = _text(args, "target", required=False) or "vscode"
        opened = desktop.open_terminal(target)
        return f"Terminal {opened} dibuka"

    if name == "focus_window":
        title = _text(args, "title")
        focused = desktop.focus_window(title)
        return f"Fokus ke: {focused}"

    if name == "type_text":
        text = _text(args, "text")
        fg = desktop.foreground_info()
        if fg["is_terminal"]:
            raise safety.SafetyError(
                "jendela aktif adalah terminal; gunakan run_command untuk perintah terminal"
            )
        if _strict_vscode() and "visual studio code" in fg["title"].lower():
            raise safety.SafetyError(
                "mode ketat aktif: mengetik ke VS Code diblokir (TOOLS_STRICT_VSCODE)"
            )
        if fg["title"].strip().lower() in ("nana", "voice assistant"):
            raise ToolError("tidak ada jendela target; fokuskan aplikasi dulu")
        count = keyboard.type_text(text)
        return f"{count} karakter diketik ke: {fg['title']}"

    if name == "press_key":
        keys = _text(args, "keys")
        keyboard.press_key(keys)
        return f"Tombol {keys} ditekan"

    if name == "run_command":
        command = _text(args, "command")
        cwd = _text(args, "cwd", required=False) or None
        result = shell.run_command(command, cwd=cwd)
        output = result["output"] or "(tanpa output)"
        return f"exit={result['exit']}\n{output}"

    if name == "open_url":
        url = _text(args, "url")
        if browser.is_search_url(url):
            raise ToolError(
                "URL pencarian tidak dipakai. Gunakan browser_search(query=..., site=...) "
                "supaya Nana mengetik di kolom pencarian asli situs itu."
            )
        try:
            return browser.open_url(url)
        except browser.BrowserError:
            desktop.open_url(url)
            return f"{url} dibuka (browser default)"

    if name == "browser_open":
        url = _text(args, "url")
        new_tab = _bool(args, "new_tab")
        return browser.open_url(url, new_tab=new_tab)

    if name == "browser_tabs":
        return browser.list_tabs_text()

    if name == "browser_switch_tab":
        source = _text(args, "browser", required=False) or "auto"
        return browser.activate_tab(_text(args, "title"), source=source)

    if name == "browser_close_tab":
        title = _text(args, "title", required=False) or None
        source = _text(args, "browser", required=False) or "auto"
        return browser.close_tab(title, source=source)

    if name == "browser_state":
        return browser.state_text()

    if name == "browser_find":
        return browser.find_text(_text(args, "target"))

    if name == "browser_click":
        target = _text(args, "target", required=False) or None
        selector = _text(args, "selector", required=False) or None
        if not target and not selector:
            raise ToolError("argumen 'target' atau 'selector' wajib diisi")
        return browser.click_text(target, selector=selector)

    if name == "browser_fill":
        target = _text(args, "target", required=False) or None
        selector = _text(args, "selector", required=False) or None
        if not target and not selector:
            raise ToolError("argumen 'target' atau 'selector' wajib diisi")
        text = _text(args, "text", required=False)
        submit = _bool(args, "submit", True)
        return browser.fill_text(target, text, submit=submit, selector=selector)

    if name == "browser_press":
        return browser.press(args.get("key") or args.get("keys") or "")

    if name == "browser_scroll":
        direction = _text(args, "direction", required=False) or "down"
        return browser.scroll(direction, args.get("amount", 3))

    if name == "browser_wait":
        return browser.wait_for(_text(args, "target"), args.get("timeout", 10))

    if name == "browser_search":
        query = _text(args, "query")
        site = _text(args, "site", required=False) or None
        return browser.search_on_site(query, site=site)

    if name == "browser_play":
        service = _text(args, "service", required=False) or "youtube"
        query = _text(args, "query")
        return browser.play(service, query)

    if name == "web_search":
        query = _text(args, "query")
        return web.search_text(query, args.get("max_results", 5))

    if name == "web_fetch":
        return web.fetch_text(_text(args, "url"))

    if name == "open_folder":
        path = _text(args, "path")
        opened = desktop.open_folder(path)
        return f"Folder dibuka: {opened}"

    if name == "open_in_vscode":
        path = _text(args, "path")
        opened = desktop.open_in_vscode(path)
        return f"Dibuka di VS Code: {opened}"

    if name == "list_windows":
        windows = desktop.list_windows()
        titles = [w["title"] for w in windows][:30]
        return "\n".join(titles) if titles else "(tidak ada jendela)"

    if name == "observe_active":
        info = observation.active_window()
        return json.dumps(info, ensure_ascii=False)

    if name == "ui_controls":
        title = _text(args, "title", required=False) or None
        info = observation.control_tree(title)
        # ringkas agar tidak terlalu panjang
        controls = info.get("controls", [])[:40]
        return json.dumps({"window": info.get("window"), "controls": controls}, ensure_ascii=False)

    if name == "ui_click":
        window = _text(args, "window", required=False) or None
        namev = _text(args, "name", required=False) or None
        auto_id = _text(args, "auto_id", required=False) or None
        res = interaction.click_control(window, namev, auto_id)
        return res.get("message", "ok")

    if name == "ui_type":
        window = _text(args, "window", required=False) or None
        namev = _text(args, "name", required=False) or None
        auto_id = _text(args, "auto_id", required=False) or None
        text = _text(args, "text")
        res = interaction.type_control(window, namev, auto_id, text)
        return res.get("message", "ok")

    if name == "ui_scroll":
        direction = _text(args, "direction", required=False) or "down"
        res = interaction.scroll(direction)
        return res.get("message", "ok")

    if name == "mouse_click":
        x = args.get("x")
        y = args.get("y")
        res = interaction.click_at(x, y)
        return res.get("message", "ok")

    if name == "wait_for_control":
        window = _text(args, "window", required=False) or None
        namev = _text(args, "name", required=False) or None
        auto_id = _text(args, "auto_id", required=False) or None
        timeout = args.get("timeout", 8)
        res = interaction.wait_for_control(window, namev, auto_id, timeout)
        return res.get("message", "ok")

    if name == "dismiss_dialog":
        res = interaction.dismiss_dialog()
        return res.get("message", "ok")

    if name == "verify_window":
        title = _text(args, "title")
        res = verification.verify_window(title)
        return res.get("message", "ok") + (" " + str(res.get("matches")) if res.get("matches") else "")

    if name == "verify_file":
        path = _text(args, "path")
        res = verification.verify_file(path)
        return res.get("message", "ok")

    if name == "verify_process":
        namev = _text(args, "name")
        res = verification.verify_process(namev)
        return res.get("message", "ok")

    if name == "cancel_task":
        request_cancel()
        return "Pembatalan diminta"

    if name == "volume_up":
        steps = args.get("steps", 1)
        return desktop.volume_up(steps)

    if name == "volume_down":
        steps = args.get("steps", 1)
        return desktop.volume_down(steps)

    if name == "volume_mute":
        return desktop.volume_mute()

    if name == "close_tab":
        title = _text(args, "title", required=False) or None
        count = args.get("count", 1)
        source = _text(args, "browser", required=False) or "auto"
        return browser.close_tab(title, count, source=source)

    if name == "close_browser":
        title = _text(args, "title", required=False) or None
        closed = desktop.close_browser(title)
        return f"Browser ditutup: {closed}"

    if name == "wait":
        value = desktop.wait(args.get("ms", 500))
        return f"Menunggu {value} ms"

    raise ToolError(f"tool tidak dikenal: {name}")


def run(tool, args):
    name = re.sub(r"\s*\([^)]*\)\s*$", "", str(tool or "").strip())
    payload = args if isinstance(args, dict) else {}

    if name not in TOOLS:
        return {
            "ok": False,
            "blocked": False,
            "message": f"Tool tidak dikenal: {name or '(kosong)'}",
        }

    printable = json.dumps(payload, ensure_ascii=False)
    print(f"[tool] -> {name} {printable[:300]}")

    try:
        result = _call(name, payload)
        outcome = {"ok": True, "blocked": False, "status": "success", "message": result}
    except safety.SafetyError as e:
        outcome = {"ok": False, "blocked": True, "status": "blocked", "message": str(e)}
    except (
        desktop.DesktopError,
        keyboard.InputError,
        shell.ShellError,
        browser.BrowserError,
        web.WebToolError,
        ToolError,
    ) as e:
        outcome = {"ok": False, "blocked": False, "status": "failed", "message": str(e)}
    except Exception as e:
        outcome = {
            "ok": False,
            "blocked": False,
            "status": "failed",
            "message": f"{type(e).__name__}: {e}",
        }

    status = "OK" if outcome["ok"] else ("BLOCKED" if outcome["blocked"] else "GAGAL")
    print(f"[tool] <- {name} {status}: {outcome['message'][:300]}")
    return outcome


def status(tool, args):
    """Label + ikon untuk baris status di UI."""
    name = re.sub(r"\s*\([^)]*\)\s*$", "", str(tool or "").strip())
    a = args if isinstance(args, dict) else {}
    arg = lambda key, default="": str(a.get(key) or default).strip()

    if name == "open_app":
        return "app", f"Membuka {arg('name', 'aplikasi')}"
    if name == "open_terminal":
        return "terminal", f"Membuka terminal {arg('target', 'vscode')}"
    if name == "focus_window":
        return "focus", f"Fokus ke {arg('title', 'jendela')}"
    if name == "type_text":
        return "keyboard", "Mengetik teks"
    if name == "press_key":
        return "key", f"Menekan {arg('keys', 'tombol')}"
    if name == "run_command":
        return "command", f"Menjalankan {arg('command', 'perintah')[:60]}"
    if name == "open_url":
        return "globe", f"Membuka {arg('url', 'tautan')[:60]}"
    if name == "browser_open":
        return "globe", f"Membuka {arg('url', 'tautan')[:60]}"
    if name == "browser_tabs":
        return "list", "Melihat tab browser"
    if name == "browser_switch_tab":
        return "focus", f"Pindah ke tab {arg('title', '')[:40]}"
    if name == "browser_close_tab" or name == "close_tab":
        return "blocked", f"Menutup tab {arg('title', 'aktif')[:40]}"
    if name == "browser_state":
        return "list", "Membaca halaman"
    if name == "browser_find":
        return "list", f"Mencari {arg('target', 'elemen')[:40]}"
    if name == "browser_click":
        return "app", f"Mengklik {arg('target', arg('selector', 'elemen'))[:40]}"
    if name == "browser_fill":
        return "keyboard", "Mengisi kolom"
    if name == "browser_press":
        return "key", f"Menekan {arg('key', 'tombol')}"
    if name == "browser_scroll":
        return "list", f"Scroll {arg('direction', 'down')}"
    if name == "browser_wait":
        return "timer", "Menunggu halaman"
    if name == "browser_search":
        return "globe", f"Mencari {arg('query', '')[:40]} di {arg('site', 'situs')}"
    if name == "browser_play":
        return "globe", f"Memutar {arg('query', 'media')[:40]}"
    if name == "web_search":
        return "globe", f"Cari web: {arg('query', '')[:40]}"
    if name == "web_fetch":
        return "globe", f"Membaca {arg('url', 'halaman')[:50]}"
    if name == "open_folder":
        return "folder", "Membuka folder"
    if name == "open_in_vscode":
        return "app", "Membuka di VS Code"
    if name == "list_windows":
        return "list", "Melihat daftar jendela"
    if name == "observe_active":
        return "list", "Mengamati window aktif"
    if name == "ui_controls":
        return "list", "Membaca kontrol UI"
    if name == "ui_click":
        return "app", "Mengklik kontrol UI"
    if name == "ui_type":
        return "keyboard", "Mengisi kontrol UI"
    if name == "ui_scroll":
        return "list", f"Scroll {arg('direction', 'down')}"
    if name == "mouse_click":
        return "app", "Klik mouse"
    if name == "wait_for_control":
        return "list", "Menunggu kontrol"
    if name == "dismiss_dialog":
        return "app", "Menutup dialog"
    if name == "verify_window":
        return "list", "Memverifikasi window"
    if name == "verify_file":
        return "folder", "Memverifikasi file"
    if name == "verify_process":
        return "app", "Memverifikasi proses"
    if name == "cancel_task":
        return "blocked", "Membatalkan tugas"
    if name == "volume_up":
        return "key", "Volume naik"
    if name == "volume_down":
        return "key", "Volume turun"
    if name == "volume_mute":
        return "key", "Mute volume"
    if name == "close_browser":
        return "app", "Menutup browser"
    if name == "wait":
        return "timer", "Menunggu sebentar"
    return "app", name or "Aksi"
