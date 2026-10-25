"""Kirim teks dan tombol ke jendela aktif memakai SendInput (ctypes).

Tidak butuh pyautogui/Pillow. Delete & Backspace selalu diblokir oleh
lapisan safety sebelum sampai ke sini.
"""

import ctypes
import time
from ctypes import wintypes

from . import safety

user32 = ctypes.WinDLL("user32", use_last_error=True)

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

ULONG_PTR = ctypes.c_size_t


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT


VK = {
    "enter": 0x0D, "return": 0x0D,
    "tab": 0x09,
    "esc": 0x1B, "escape": 0x1B,
    "space": 0x20,
    "backspace": 0x08, "bksp": 0x08,
    "delete": 0x2E, "del": 0x2E,
    "insert": 0x2D,
    "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "printscreen": 0x2C, "pause": 0x13,
    "capslock": 0x14, "numlock": 0x90, "scrolllock": 0x91,
    "menu": 0x5D,
    ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE,
    "/": 0xBF, "`": 0xC0, "[": 0xDB, "\\": 0xDC, "]": 0xDD, "'": 0xDE,
}
for _i in range(1, 13):
    VK[f"f{_i}"] = 0x6F + _i

MODIFIERS = {
    "ctrl": 0x11, "control": 0x11,
    "shift": 0x10,
    "alt": 0x12,
    "win": 0x5B, "windows": 0x5B,
}


class InputError(Exception):
    pass


def _event(vk=0, scan=0, flags=0):
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.ki = KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0)
    return inp


def _send(events):
    if not events:
        return
    arr = (INPUT * len(events))(*events)
    sent = user32.SendInput(len(events), arr, ctypes.sizeof(INPUT))
    if sent != len(events):
        raise InputError(f"SendInput gagal (kode {ctypes.get_last_error()})")


def _tap(vk):
    _send([_event(vk=vk), _event(vk=vk, flags=KEYEVENTF_KEYUP)])


def _unicode_char(ch):
    units = []
    code = ord(ch)
    if code > 0xFFFF:
        code -= 0x10000
        units = [0xD800 + (code >> 10), 0xDC00 + (code & 0x3FF)]
    else:
        units = [code]
    events = []
    for unit in units:
        events.append(_event(scan=unit, flags=KEYEVENTF_UNICODE))
        events.append(_event(scan=unit, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
    _send(events)


def type_text(text):
    """Ketik teks (Unicode) ke jendela aktif."""
    safety.check_text(text)
    payload = str(text)
    if not payload:
        return 0

    count = 0
    for ch in payload:
        if ch == "\r":
            continue
        if ch == "\n":
            _tap(VK["enter"])
        elif ch == "\t":
            _tap(VK["tab"])
        else:
            _unicode_char(ch)
        count += 1
        time.sleep(0.002)
    return count


def _resolve_key(name):
    key = name.strip().lower()
    if key in VK:
        return VK[key]
    if len(key) == 1:
        if key.isalpha() or key.isdigit():
            return ord(key.upper())
    raise InputError(f"tombol tidak dikenal: {name}")


def press_key(combo):
    """Tekan satu tombol atau kombinasi, mis. 'enter' atau 'ctrl+shift+s'."""
    safety.check_keys(combo)
    raw = str(combo).strip()
    if not raw:
        raise InputError("tombol kosong")

    parts = [p for p in raw.split("+") if p.strip()]
    mods = [MODIFIERS[p.strip().lower()] for p in parts[:-1]]
    key_name = parts[-1].strip()

    for mod in mods:
        _send([_event(vk=mod)])
    _tap(_resolve_key(key_name))
    for mod in reversed(mods):
        _send([_event(vk=mod, flags=KEYEVENTF_KEYUP)])
