"""Dispatcher tool: validasi, eksekusi, dan hasil untuk LLM."""

import json
import os
import re

from . import desktop, keyboard, safety, shell
from .registry import TOOLS, system_prompt  # noqa: F401 (dipakai app.py)


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
        desktop.open_url(url)
        return f"{url} dibuka"

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
        outcome = {"ok": True, "blocked": False, "message": result}
    except safety.SafetyError as e:
        outcome = {"ok": False, "blocked": True, "message": str(e)}
    except (desktop.DesktopError, keyboard.InputError, shell.ShellError, ToolError) as e:
        outcome = {"ok": False, "blocked": False, "message": str(e)}
    except Exception as e:
        outcome = {
            "ok": False,
            "blocked": False,
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
    if name == "open_folder":
        return "folder", "Membuka folder"
    if name == "open_in_vscode":
        return "app", "Membuka di VS Code"
    if name == "list_windows":
        return "list", "Melihat daftar jendela"
    if name == "wait":
        return "timer", "Menunggu sebentar"
    return "app", name or "Aksi"
