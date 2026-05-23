"""轻量网页抓取：拿 <title> 和 <meta description>，不依赖外部库。"""
from __future__ import annotations

import gzip
import html
import io
import re
import socket
import ssl
import zlib
from urllib.parse import urlparse
from urllib.request import Request, urlopen

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
TIMEOUT = 8
MAX_BYTES = 512 * 1024  # 最多读 512KB，head 部分早就解析完了


_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_META_RE = re.compile(
    r'<meta\s+[^>]*?(?:name|property)\s*=\s*["\']'
    r"(?:description|og:description|twitter:description)"
    r'["\'][^>]*?content\s*=\s*["\']([^"\']*)["\']',
    re.I | re.S,
)
_META_RE_REV = re.compile(
    r'<meta\s+[^>]*?content\s*=\s*["\']([^"\']*)["\'][^>]*?'
    r'(?:name|property)\s*=\s*["\']'
    r"(?:description|og:description|twitter:description)"
    r'["\']',
    re.I | re.S,
)
_CHARSET_RE = re.compile(rb'charset\s*=\s*["\']?([\w\-]+)', re.I)


def _decompress(raw: bytes, encoding: str | None) -> bytes:
    if not encoding:
        return raw
    enc = encoding.lower()
    try:
        if enc == "gzip":
            return gzip.decompress(raw)
        if enc == "deflate":
            try:
                return zlib.decompress(raw)
            except zlib.error:
                return zlib.decompress(raw, -zlib.MAX_WBITS)
        if enc == "br":
            try:
                import brotli  # 可选依赖，没有就跳过
                return brotli.decompress(raw)
            except ImportError:
                return raw
    except Exception:
        return raw
    return raw


def _detect_encoding(content_type: str, raw: bytes) -> str:
    # 优先 HTTP header
    m = re.search(r"charset=([\w\-]+)", content_type or "", re.I)
    if m:
        return m.group(1)
    # 退而求其次：HTML meta
    m2 = _CHARSET_RE.search(raw[:4096])
    if m2:
        try:
            return m2.group(1).decode("ascii", "ignore")
        except Exception:
            pass
    return "utf-8"


def _clean(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def fetch_meta(url: str) -> dict:
    """返回 {title, description, ok, error}. 任何异常都吞掉，ok=False。"""
    result = {"title": "", "description": "", "ok": False, "error": ""}
    if not url or not url.strip():
        result["error"] = "URL 为空"
        return result

    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        result["error"] = "仅支持 http/https"
        return result

    try:
        req = Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate",
            },
        )
        ctx = ssl.create_default_context()
        # 一些自签证书的站不要让整个抓取失败
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        with urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
            content_type = resp.headers.get("Content-Type", "")
            if "html" not in content_type.lower() and content_type:
                result["error"] = f"非 HTML 响应：{content_type}"
                return result
            raw = resp.read(MAX_BYTES)
            raw = _decompress(raw, resp.headers.get("Content-Encoding"))
            encoding = _detect_encoding(content_type, raw)

        try:
            text = raw.decode(encoding, errors="replace")
        except LookupError:
            text = raw.decode("utf-8", errors="replace")

        m = _TITLE_RE.search(text)
        if m:
            result["title"] = _clean(m.group(1))

        # 尝试两种顺序的 meta 描述
        m2 = _META_RE.search(text) or _META_RE_REV.search(text)
        if m2:
            result["description"] = _clean(m2.group(1))

        result["ok"] = bool(result["title"] or result["description"])
        return result
    except socket.timeout:
        result["error"] = "请求超时"
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
    return result
