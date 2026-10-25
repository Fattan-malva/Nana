"""Web search & web fetch lewat API native Ollama.

Butuh OLLAMA_API_KEY. Kalau API Ollama tidak tersedia, pencarian memakai
fallback ringan ke DuckDuckGo dan pengambilan halaman memakai HTML biasa.
"""

import html as html_lib
import ipaddress
import os
import re
import urllib.parse

import httpx
from dotenv import load_dotenv

load_dotenv()

OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "")

# Web search/fetch hanya ada di API native Ollama (bukan endpoint OpenAI-compatible).
OLLAMA_HOST = (os.getenv("OLLAMA_HOST") or "https://ollama.com").rstrip("/")

HEADERS = {"Content-Type": "application/json"}
if OLLAMA_API_KEY:
    HEADERS["Authorization"] = f"Bearer {OLLAMA_API_KEY}"

try:
    WEB_TIMEOUT = max(5.0, min(90.0, float(os.getenv("OLLAMA_WEB_TIMEOUT", "35") or 35)))
except ValueError:
    WEB_TIMEOUT = 35.0

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class WebError(Exception):
    """Gagal mengambil data web."""


# ----------------------------------------------------------------------- helpers


def _post_native(path: str, payload: dict, timeout: float | None = None) -> dict:
    if not OLLAMA_API_KEY:
        raise WebError("OLLAMA_API_KEY belum diset di .env")
    try:
        with httpx.Client(timeout=timeout or WEB_TIMEOUT) as client:
            resp = client.post(
                f"{OLLAMA_HOST}{path}",
                headers=HEADERS,
                json=payload,
            )
    except Exception as e:
        raise WebError(f"tidak bisa menghubungi {OLLAMA_HOST}: {e}") from e

    if resp.status_code in (401, 403):
        raise WebError("API key Ollama ditolak atau kedaluwarsa")
    if resp.status_code >= 400:
        raise WebError(f"API web Ollama error HTTP {resp.status_code}")
    try:
        return resp.json()
    except Exception as e:
        raise WebError(f"respons web Ollama tidak valid: {e}") from e


def _clean_results(items) -> list[dict]:
    results = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            continue
        content = re.sub(r"\s+", " ", str(item.get("content") or "")).strip()
        results.append(
            {
                "title": re.sub(r"\s+", " ", str(item.get("title") or url)).strip()[:200],
                "url": url,
                "content": content[:1400],
            }
        )
    return results


def _ddg_url(href: str) -> str:
    """DuckDuckGo membungkus link jadi /l/?uddg=...; ambil URL aslinya."""
    href = html_lib.unescape(href or "")
    if href.startswith("//"):
        href = "https:" + href
    if "uddg=" in href:
        query = urllib.parse.urlparse(href).query
        target = urllib.parse.parse_qs(query).get("uddg", [""])[0]
        if target:
            return urllib.parse.unquote(target)
    return href


def _strip_tags(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript|svg|template)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>", "\n", raw)
    raw = re.sub(r"(?i)</(p|div|li|h[1-6]|tr|section|article)>", "\n", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html_lib.unescape(raw)
    raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
    raw = re.sub(r"\n\s*\n+", "\n\n", raw)
    return raw.strip()


def _ddg_search(query: str, max_results: int) -> list[dict]:
    """Fallback tanpa API key: DuckDuckGo HTML (tanpa dependency parser)."""
    try:
        with httpx.Client(timeout=WEB_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": _UA, "Accept-Language": "id-ID,id;q=0.9,en;q=0.8"},
            )
        if resp.status_code >= 400:
            return []
        page = resp.text
    except Exception:
        return []

    results: list[dict] = []
    pattern = re.compile(
        r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    snippets = re.findall(
        r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>',
        page,
        re.IGNORECASE | re.DOTALL,
    )
    for index, (href, title_html) in enumerate(pattern.findall(page)):
        url = _ddg_url(href)
        if not url.lower().startswith(("http://", "https://")):
            continue
        snippet = snippets[index] if index < len(snippets) else ""
        results.append(
            {
                "title": _strip_tags(title_html)[:200],
                "url": url,
                "content": _strip_tags(snippet)[:1400],
            }
        )
        if len(results) >= max_results:
            break
    return results


def _fetch_html(url: str) -> dict:
    try:
        with httpx.Client(timeout=WEB_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(
                url,
                headers={"User-Agent": _UA, "Accept-Language": "id-ID,id;q=0.9,en;q=0.8"},
            )
        if resp.status_code >= 400:
            raise WebError(f"HTTP {resp.status_code} saat mengambil {url}")
        if _private_host(resp.url.hostname or ""):
            raise WebError("redirect ke alamat lokal/privat diblokir")
        raw = resp.text
    except WebError:
        raise
    except Exception as e:
        raise WebError(f"gagal mengambil {url}: {e}") from e

    title_match = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw)
    title = _strip_tags(title_match.group(1)) if title_match else url
    links = []
    for href in re.findall(r'href=["\'](https?://[^"\']+)', raw, re.IGNORECASE):
        href = html_lib.unescape(href)
        if href not in links:
            links.append(href)
        if len(links) >= 40:
            break
    return {
        "title": title[:200] or url,
        "url": str(resp.url),
        "content": _strip_tags(raw)[:12000],
        "links": links,
    }


# --------------------------------------------------------------------- web tools


def web_search(query: str, max_results: int = 5) -> dict:
    """Cari di web. Prioritas API Ollama, fallback DuckDuckGo.

    Return: {"query", "source", "results": [{"title","url","content"}]}
    """
    q = str(query or "").strip()
    if not q:
        raise WebError("query kosong")
    if len(q) > 500:
        q = q[:500]
    try:
        limit = max(1, min(10, int(max_results or 5)))
    except (TypeError, ValueError):
        limit = 5

    errors = []
    results: list[dict] = []
    source = "ollama"
    try:
        data = _post_native("/api/web_search", {"query": q, "max_results": limit})
        results = _clean_results(data.get("results"))
    except WebError as e:
        errors.append(str(e))

    if not results:
        source = "duckduckgo"
        results = _ddg_search(q, limit)

    if not results:
        detail = "; ".join(errors) or "tidak ada hasil"
        raise WebError(f"pencarian web gagal ({detail})")

    return {"query": q, "source": source, "results": results[:limit]}


def _private_host(host: str) -> bool:
    host = (host or "").strip("[]").lower()
    if host in ("localhost", "0.0.0.0", "::1"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved


def web_fetch(url: str) -> dict:
    """Ambil isi satu halaman web (judul, teks, link)."""
    target = str(url or "").strip()
    parsed = urllib.parse.urlparse(target)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise WebError("hanya URL http/https yang diizinkan")
    if _private_host(parsed.hostname or ""):
        raise WebError("URL lokal/privat tidak diizinkan untuk web_fetch")

    try:
        data = _post_native("/api/web_fetch", {"url": target}, timeout=max(WEB_TIMEOUT, 45))
        content = str(data.get("content") or "")
        links = [str(x) for x in (data.get("links") or []) if str(x).startswith("http")]
        return {
            "url": target,
            "title": str(data.get("title") or target)[:200],
            "content": content[:12000],
            "links": links[:40],
            "source": "ollama",
        }
    except WebError:
        page = _fetch_html(target)
        page["source"] = "html"
        return page
