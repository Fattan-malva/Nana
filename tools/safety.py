"""Lapisan keamanan: NANA tidak boleh menghapus apa pun.

Aturan ini dipakai sebelum teks diketik, sebelum tombol ditekan, dan
sebelum perintah terminal dijalankan.
"""

import os
import re


class SafetyError(Exception):
    pass


# Pola aksi hapus (dipakai untuk teks yang diketik & perintah).
_DESTRUCTIVE_SOURCE = [
    r"\bdel\b",
    r"\bdelete\b",
    r"\berase\b",
    r"\brmdir\b",
    r"\brd\b",
    r"\brm\b",
    r"\bunlink\b",
    r"\bshred\b",
    r"\bsdelete\b",
    r"\bwipe\b",
    r"\btruncate\b",
    r"remove-item",
    r"clear-content",
    r"\bformat\b",
    r"diskpart",
    r"cipher\s+/w",
    r"git\s+clean",
    r"git\s+reset\s+--hard",
    r"git\s+checkout\s+--",
    r"git\s+restore",
    r"git\s+stash\s+(drop|clear)",
    r"git\s+branch\s+-D",
    r"git\s+tag\s+-d",
    r"git\s+push\b.*--delete",
    r"git\s+remote\s+remove",
    r"npm\s+(uninstall|remove|rm)\b",
    r"yarn\s+remove\b",
    r"pip\s+uninstall\b",
    r"winget\s+uninstall\b",
    r"choco\s+uninstall\b",
    r"docker\s+(rm|rmi)\b",
    r"kubectl\s+delete\b",
    r"os\.remove",
    r"os\.unlink",
    r"os\.rmdir",
    r"shutil\.rmtree",
    r"\bremove\s*\(",
    r"\.delete\s*\(",
    r"\.unlink\s*\(",
    r"deletefile",
    r"deletedirectory",
    r"removedirectory",
    r"file\.delete",
    r"directory\.delete",
    r"fs\.rm\b",
    r"recycle",
    r"/mir\b",
    r"/purge\b",
    r":>",
]

_DESTRUCTIVE = [re.compile(p, re.IGNORECASE) for p in _DESTRUCTIVE_SOURCE]

# Karakter yang membuka jalan untuk menyusun perintah hapus secara tidak langsung.
_SHELL_META = re.compile(r"[&|<>^`]")

# Executable yang tidak boleh dipakai lewat run_command, apa pun isi .env.
_NEVER_ALLOW = {
    "cmd", "powershell", "pwsh", "wsl", "bash", "sh",
    "cscript", "wscript", "mshta", "rundll32", "regsvr32",
    "certutil", "bitsadmin",
}

# Combo tombol yang dilarang (apa pun modifier-nya asal berakhir delete/backspace).
_BLOCKED_END_KEYS = {"delete", "del", "backspace", "bksp"}


def is_destructive(text):
    if not text:
        return False
    return any(rx.search(str(text)) for rx in _DESTRUCTIVE)


def check_text(text):
    """Tolak teks yang mengandung aksi hapus."""
    if is_destructive(text):
        raise SafetyError("teks mengandung perintah hapus")
    return True


def check_keys(combo):
    """Tolak Delete/Backspace dan kombinasinya."""
    parts = [p.strip().lower().replace(" ", "") for p in str(combo).split("+") if p.strip()]
    if not parts:
        raise SafetyError("tombol kosong")
    if parts[-1] in _BLOCKED_END_KEYS:
        raise SafetyError("tombol hapus tidak diizinkan")
    return True


def _first_token(command):
    m = re.match(r'^\s*(?:"([^"]+)"|\'([^\']+)\'|(\S+))', command)
    if not m:
        return ""
    return next((g for g in m.groups() if g), "")


def check_command(command, allowed):
    """Validasi perintah terminal sebelum dijalankan.

    - executable harus ada di allowlist
    - tidak boleh ada karakter shell berbahaya
    - tidak boleh mengandung pola hapus
    """
    cmd = str(command or "").strip()
    if not cmd:
        raise SafetyError("perintah kosong")

    if _SHELL_META.search(cmd):
        raise SafetyError("perintah memakai operator shell yang tidak diizinkan")

    if is_destructive(cmd):
        raise SafetyError("perintah mengandung aksi hapus")

    token = _first_token(cmd)
    if not token:
        raise SafetyError("perintah tidak valid")

    base = os.path.basename(token).lower()
    for ext in (".exe", ".cmd", ".bat", ".com"):
        if base.endswith(ext):
            base = base[: -len(ext)]
            break

    if base in _NEVER_ALLOW:
        raise SafetyError(f"{base} tidak diizinkan")

    if base not in allowed:
        raise SafetyError(
            f"{base} tidak ada di allowlist (atur TOOLS_ALLOWED_COMMANDS di .env)"
        )

    lowered = cmd.lower()
    if base in ("python", "python3", "py") and re.search(r"(^|\s)-c(\s|$)", lowered):
        raise SafetyError("python -c tidak diizinkan")
    if base in ("node", "nodejs") and re.search(r"(^|\s)(-e|--eval|-p|--print)(\s|$)", lowered):
        raise SafetyError("node --eval tidak diizinkan")

    return base


def check_user_path(path):
    """Pastikan path yang diminta user memang ada (tanpa membuka celah hapus)."""
    if not path:
        raise SafetyError("path kosong")
    p = os.path.expandvars(os.path.expanduser(str(path)))
    if not os.path.exists(p):
        raise SafetyError(f"path tidak ditemukan: {p}")
    return p
