"""Delivered files: kit fingerprints and readable strings from the site's own code (never executed).

- Every delivered file is identified by SHA-256 (from the sanitizer, computed before binary bodies are
  dropped), its file name and, for content-hashed build names (Vite `en-US-DpCkNiEF.js`, webpack
  `main.e78238c7.chunk.js`), its chunk name. Text bundles also get a bottom-k shingle sketch so
  near-identical builds still match.
- String literals of the site's own JS (language packs, route and chunk names, config keys) become
  "delivered code" text for the same analyzer and classifier as visible text.
"""
from __future__ import annotations

import codecs
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

from app.analyze.hosts import common_service_category

VITE_RE = re.compile(r"^(?P<chunk>.+?)[-.](?P<hash>[A-Za-z0-9_]{8}|[A-Za-z0-9_-]{8})\.(?P<ext>m?js|css)$")
WEBPACK_RE = re.compile(r"^(?P<chunk>.+?)\.(?P<hash>[0-9a-f]{8,20})(?:\.chunk)?\.(?P<ext>m?js|css)$")
EXT_KIND = {"js": "js", "mjs": "js", "css": "css", "woff": "font", "woff2": "font", "ttf": "font", "otf": "font",
            "eot": "font", "png": "image", "jpg": "image", "jpeg": "image", "gif": "image", "webp": "image",
            "svg": "image", "ico": "image", "avif": "image", "json": "json"}
COMMON_FILE = Path(__file__).resolve().parent.parent / "linking" / "common_assets.yaml"
SKETCH_K = 128
SHINGLE = 8
STRING_RE = re.compile(r'"((?:[^"\\\n]|\\.){2,300})"|\'((?:[^\'\\\n]|\\.){2,300})\'|`([^`$\\]{2,300})`')
CAMEL_RE = re.compile(r"(?<=[a-z])(?=[A-Z])|[-_.]+")
ARABIC = re.compile(r"[؀-ۿ]")
LETTERS = re.compile(r"[A-Za-z؀-ۿ]")
CODEY = re.compile(r"(function|return|var |const |=>|\{|\}|;|</?[a-z]+[ >]|https?://|\.(js|css|png|svg)\b|^[#.][\w-]+$|"
                   r"^\w+\(|\\x|%[sd]|^[A-Z0-9_]{3,}$|^[\w-]+/[\w/-]+$)")


def _load_common() -> list[re.Pattern]:
    data = yaml.safe_load(COMMON_FILE.read_text(encoding="utf-8")) or {}
    return [re.compile(p, re.I) for p in data.get("file_name_patterns", [])]


COMMON_NAME_PATTERNS = _load_common()


def split_name(file_name: str) -> tuple[str | None, bool]:
    """(chunk name without the content hash, whether the name carries a content hash)."""
    for rx in (WEBPACK_RE, VITE_RE):
        m = rx.match(file_name)
        if m:
            h = m.group("hash")
            # A real content hash mixes character classes (not a plain word like "template").
            if rx is WEBPACK_RE or (re.search(r"\d", h) or (re.search(r"[A-Z]", h) and re.search(r"[a-z]", h))):
                return m.group("chunk"), True
    return None, False


def common_file_name(file_name: str) -> bool:
    return any(p.search(file_name) for p in COMMON_NAME_PATTERNS)


def is_vendor_chunk(chunk: str | None, file_name: str) -> bool:
    n = (chunk or file_name).lower()
    return n.startswith(("vendor", "chunk-vendors", "polyfill", "runtime", "framework", "react", "vue")) or "vendor" in n


def sketch(text: str) -> list[int]:
    """Bottom-k sketch of token 8-shingles: a Jaccard estimate for near-identical bundles, in pure Python."""
    toks = re.findall(r"[A-Za-z_$][\w$]*|\d+|\S", text[:1_500_000])
    if len(toks) < SHINGLE:
        return []
    hashes = {int.from_bytes(hashlib.blake2b(" ".join(toks[i:i + SHINGLE]).encode(), digest_size=8).digest(), "big")
              for i in range(0, len(toks) - SHINGLE + 1)}
    return sorted(hashes)[:SKETCH_K]


def sketch_similarity(a: list[int] | None, b: list[int] | None) -> float:
    if not a or not b:
        return 0.0
    union = sorted(set(a) | set(b))[:SKETCH_K]
    sa, sb = set(a), set(b)
    both = sum(1 for h in union if h in sa and h in sb)
    return both / len(union)


@dataclass
class AssetFile:
    url: str
    host: str
    file_name: str
    chunk_name: str | None
    name_hashed: bool
    kind: str
    sha256: str
    size: int | None
    sketch: list[int] = field(default_factory=list)
    text: str | None = None          # kept in memory only (code-string extraction), never stored here
    common: bool = False             # common library / common-service host


def _kind(file_name: str, mime: str) -> str:
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    if ext in EXT_KIND:
        return EXT_KIND[ext]
    mime = (mime or "").lower()
    if "javascript" in mime or "ecmascript" in mime:
        return "js"
    if "css" in mime:
        return "css"
    if "font" in mime or "woff" in mime:
        return "font"
    if mime.startswith("image/"):
        return "image"
    if "json" in mime:
        return "json"
    return "other"


def extract_assets(har: dict | None) -> list[AssetFile]:
    out: list[AssetFile] = []
    seen: set[tuple[str, str]] = set()
    for e in (har or {}).get("log", {}).get("entries", []) or []:
        content = e.get("response", {}).get("content", {}) or {}
        sha = content.get("_hami_sha256")
        if not sha and isinstance(content.get("text"), str) and content.get("encoding") != "base64":
            # Captures stored before per-file hashing kept text bodies: hash what was stored.
            sha = hashlib.sha256(content["text"].encode("utf-8", "replace")).hexdigest()
        if not sha:
            continue
        url = e.get("request", {}).get("url", "")
        try:
            u = urlsplit(url)
        except ValueError:
            continue
        name = (u.path.rsplit("/", 1)[-1] or "").strip()
        kind = _kind(name, content.get("mimeType", ""))
        if kind == "other" or (kind == "json" and not name) or not name:
            continue
        if (sha, name) in seen:
            continue
        seen.add((sha, name))
        chunk, hashed = split_name(name)
        host = (u.hostname or "").lower()
        text = content.get("text") if kind in ("js", "css") else None
        a = AssetFile(url=f"{u.scheme}://{host}{u.path}", host=host, file_name=name[:200], chunk_name=chunk,
                      name_hashed=hashed, kind=kind, sha256=sha, size=content.get("_hami_size"), text=text,
                      common=bool(common_service_category(host)) or common_file_name(name) or "/cdn-cgi/" in u.path)
        if text and len(text) > 2000 and not a.common:
            a.sketch = sketch(text)
        out.append(a)
    return out


# ---- readable strings from the site's own code -----------------------------------------------------
def _unescape(s: str) -> str:
    if "\\" not in s:
        return s
    try:
        out = codecs.decode(s.encode("latin-1", "backslashreplace"), "unicode_escape")
    except (UnicodeDecodeError, ValueError):
        return s
    # Re-pair UTF-16 surrogates (emoji written as two escapes) and drop any that stay unpaired.
    return out.encode("utf-16", "surrogatepass").decode("utf-16", "replace")


def _readable(s: str) -> bool:
    s = s.strip()
    if len(s) < 3 or CODEY.search(s):
        return False
    letters = len(LETTERS.findall(s))
    if letters < 3 or letters / len(s) < 0.55:
        return False
    return " " in s or bool(ARABIC.search(s)) or (len(s) >= 5 and s.isalpha())


def name_words(chunk_or_name: str) -> str:
    """'views-vipNew' -> 'views vip new'; 'homeDepositTab' -> 'home deposit tab'."""
    base = re.sub(r"\.(m?js|css)$", "", chunk_or_name)
    return " ".join(w.lower() for w in CAMEL_RE.split(base) if w and not w.isdigit())


def code_strings(assets: list[AssetFile], max_chars: int = 150_000) -> tuple[list[str], list[str]]:
    """(readable string literals from the site's own JS, words from its build file names)."""
    lines: list[str] = []
    seen: set[str] = set()
    total = 0
    own_js = [a for a in assets if a.kind == "js" and a.text and not a.common and "/cdn-cgi/" not in a.url
              and not is_vendor_chunk(a.chunk_name, a.file_name)]
    # Language packs and app chunks first (most informative), then the rest.
    own_js.sort(key=lambda a: (0 if re.match(r"^[a-z]{2}(-[A-Za-z]{2})?$", a.chunk_name or "") else 1, -(a.size or 0)))
    for a in own_js:
        for m in STRING_RE.finditer(a.text or ""):
            raw = m.group(1) or m.group(2) or m.group(3) or ""
            s = re.sub(r"\s+", " ", _unescape(raw)).strip()
            if s in seen or not _readable(s):
                continue
            seen.add(s)
            lines.append(s)
            total += len(s)
            if total > max_chars:
                return lines, _names(assets)
    return lines, _names(assets)


def _names(assets: list[AssetFile]) -> list[str]:
    out = []
    for a in assets:
        if a.common or a.kind not in ("js", "css"):
            continue
        w = name_words(a.chunk_name or a.file_name)
        if w and w not in out and len(w) > 2:
            out.append(w)
    return out[:300]


def asset_rows(assets: list[AssetFile]) -> list[dict[str, Any]]:
    return [{"host": a.host, "file_name": a.file_name, "chunk_name": a.chunk_name, "name_hashed": int(a.name_hashed),
             "kind": a.kind, "sha256": a.sha256, "size_bytes": a.size, "sketch": a.sketch} for a in assets]
