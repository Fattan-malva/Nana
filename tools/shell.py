"""Jalankan perintah terminal yang aman (allowlist) dan ambil output-nya."""

import os
import shutil
import subprocess

from . import safety

CREATE_NO_WINDOW = 0x08000000

DEFAULT_ALLOWED = (
    "code,code-insiders,notepad,explorer,wt,node,npm,npx,git,"
    "where,tasklist,ipconfig,ping,curl,python,py,pip"
)


class ShellError(Exception):
    pass


def allowed_commands():
    raw = os.getenv("TOOLS_ALLOWED_COMMANDS", DEFAULT_ALLOWED)
    items = {x.strip().lower() for x in raw.split(",") if x.strip()}
    return items or {x.strip() for x in DEFAULT_ALLOWED.split(",")}


def _timeout():
    try:
        value = float(os.getenv("TOOLS_CMD_TIMEOUT", "20") or 20)
    except ValueError:
        value = 20.0
    return max(3.0, min(120.0, value))


def run_command(command, cwd=None):
    allowed = allowed_commands()
    base = safety.check_command(command, allowed)

    workdir = None
    if cwd:
        workdir = os.path.expandvars(os.path.expanduser(str(cwd)))
        if not os.path.isdir(workdir):
            raise ShellError(f"folder kerja tidak ditemukan: {workdir}")

    exe = shutil.which(base) or shutil.which(base + ".exe")
    if not exe:
        raise ShellError(f"perintah '{base}' tidak ditemukan di PATH")

    # .cmd/.bat (mis. npm, code) harus lewat cmd; isi perintah sudah divalidasi.
    if exe.lower().endswith((".cmd", ".bat")):
        argv = ["cmd", "/d", "/c", str(command)]
    else:
        argv = str(command)

    limit = _timeout()
    try:
        proc = subprocess.run(
            argv,
            cwd=workdir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=limit,
            creationflags=CREATE_NO_WINDOW,
        )
    except FileNotFoundError as e:
        raise ShellError(f"perintah tidak ditemukan: {e}")
    except subprocess.TimeoutExpired as e:
        partial = ""
        if e.stdout:
            partial = e.stdout if isinstance(e.stdout, str) else e.stdout.decode("utf-8", "replace")
        raise ShellError(
            f"perintah melebihi {limit:.0f} detik dan dihentikan. "
            f"Output sementara: {partial[:500]}"
        )

    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if len(output) > 4000:
        output = output[:4000] + "\n... [output dipotong]"

    return {"exit": proc.returncode, "output": output}
