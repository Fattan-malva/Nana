"""Tool web realtime untuk NANA.

`web_search` memakai API web search Ollama (butuh internet + OLLAMA_API_KEY),
dengan fallback DuckDuckGo. `web_fetch` membaca isi satu halaman.

Modul ini juga menyediakan deteksi "pertanyaan butuh info terbaru" supaya
konteks web bisa disuntikkan otomatis sebelum model menjawab.
"""

import os
import re
import time

from services import ollama

_CACHE: dict[tuple, tuple[float, str]] = {}
try:
    _CACHE_TTL = max(30.0, float(os.getenv("WEB_CACHE_SECONDS", "600") or 600))
except (TypeError, ValueError):
    _CACHE_TTL = 600.0


class WebToolError(Exception):
    pass


def _auto_enabled() -> bool:
    raw = os.getenv("WEB_AUTO_SEARCH", "true").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _cache_get(key):
    hit = _CACHE.get(key)
    if not hit:
        return None
    created, value = hit
    if time.time() - created > _CACHE_TTL:
        _CACHE.pop(key, None)
        return None
    return value


def _cache_put(key, value):
    _CACHE[key] = (time.time(), value)
    if len(_CACHE) > 80:
        for old in sorted(_CACHE, key=lambda k: _CACHE[k][0])[:20]:
            _CACHE.pop(old, None)


def search_text(query: str, max_results=5) -> str:
    """Format hasil pencarian menjadi teks ringkas untuk model."""
    q = str(query or "").strip()
    if not q:
        raise WebToolError("query kosong")
    try:
        limit = max(1, min(10, int(max_results or 5)))
    except (TypeError, ValueError):
        limit = 5

    key = ("search", q.lower(), limit)
    cached = _cache_get(key)
    if cached:
        return cached

    try:
        data = ollama.web_search(q, limit)
    except ollama.WebError as e:
        raise WebToolError(str(e)) from e

    lines = [f'Hasil web untuk "{q}" ({data.get("source")}):']
    for index, item in enumerate(data.get("results") or [], 1):
        snippet = re.sub(r"\s+", " ", item.get("content") or "").strip()
        lines.append(f"{index}. {item['title']}")
        lines.append(f"   URL: {item['url']}")
        if snippet:
            lines.append(f"   {snippet[:600]}")
    if len(lines) == 1:
        lines.append("(tidak ada hasil)")
    text = "\n".join(lines)
    _cache_put(key, text)
    return text


def fetch_text(url: str) -> str:
    """Ambil halaman web dan kembalikan teksnya."""
    target = str(url or "").strip()
    if not target:
        raise WebToolError("url kosong")

    key = ("fetch", target.lower())
    cached = _cache_get(key)
    if cached:
        return cached

    try:
        data = ollama.web_fetch(target)
    except ollama.WebError as e:
        raise WebToolError(str(e)) from e

    content = re.sub(r"\n{3,}", "\n\n", str(data.get("content") or "")).strip()
    if len(content) > 6000:
        content = content[:6000] + "\n... [isi dipotong]"
    links = data.get("links") or []
    lines = [
        f"Judul: {data.get('title')}",
        f"URL: {data.get('url')}",
        f"Sumber: {data.get('source')}",
        "",
        content or "(halaman tidak punya teks yang bisa dibaca)",
    ]
    if links:
        lines.append("")
        lines.append("Link penting:")
        lines.extend(f"- {u}" for u in links[:12])
    text = "\n".join(lines)
    _cache_put(key, text)
    return text


# Pertanyaan yang biasanya butuh data terbaru. Sengaja tidak terlalu agresif
# supaya obrolan biasa tidak menambah latensi.
_REALTIME_RX = re.compile(
    r"("
    r"hari ini|sekarang|saat ini|terbaru|terkini|terakhir|berita|kabar|harga|kurs|"
    r"cuaca|prakiraan|ramalan|jadwal|skor|hasil pertandingan|klasemen|rilis|dirilis|"
    r"peluncuran|update|pembaruan|versi|presiden|menteri|gubernur|kebijakan|"
    r"saham|bitcoin|kripto|inflasi|pemilu|pilkada|gempa|banjir|kecelakaan|"
    r"who is|what is the latest|latest|breaking|current|today|tonight|news|"
    r"price|weather|forecast|score|release|released|stock|crypto|election"
    r")\b",
    re.IGNORECASE,
)
_YEAR_RX = re.compile(r"\b20(2[5-9]|3\d)\b")


def needs_realtime(text: str) -> bool:
    if not _auto_enabled():
        return False
    value = str(text or "")
    return bool(_REALTIME_RX.search(value) or _YEAR_RX.search(value))


def realtime_context(text: str) -> str:
    """Blok konteks web untuk disisipkan ke system prompt (string kosong jika tidak perlu)."""
    value = str(text or "").strip()
    if not value or not needs_realtime(value):
        return ""
    try:
        block = search_text(value, 4)
    except WebToolError:
        return ""
    stamp = time.strftime("%d %b %Y %H:%M")
    return (
        f"[INFO WEB REALTIME — diambil {stamp}]\n"
        f"{block}\n\n"
        "Gunakan informasi di atas sebagai data terbaru. Jangan mengarang angka/tanggal. "
        "Kalau butuh detail, panggil web_fetch dengan salah satu URL di atas."
    )
