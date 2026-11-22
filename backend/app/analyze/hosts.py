"""Hostname references in saved HTML, JS and JSON bodies, labeled *referenced* vs *observed in traffic*.

Nothing here makes a network request: it reads the sanitized HAR and HTML only.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlsplit

import yaml
from bs4 import BeautifulSoup

from app.urls import registrable_domain

URL_HOST_RE = re.compile(r"(?:https?:)?//([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+)(?::\d+)?", re.I)
BARE_HOST_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}(?::\d+)?(?:/.*)?$", re.I)
FILE_EXT_TLDS = {"png", "jpg", "jpeg", "gif", "svg", "webp", "ico", "js", "css", "json", "html", "htm", "php", "txt",
                 "mp4", "mp3", "woff", "woff2", "ttf", "otf", "eot", "map", "xml", "pdf", "zip", "apk", "vue", "ts",
                 "jsx", "tsx", "md", "yml", "yaml", "lock", "wasm", "avif", "bmp", "csv", "min", "bundle", "chunk"}
IMAGE_EXT_RE = re.compile(r"\.(png|jpe?g|gif|svg|webp|ico|avif|bmp)(\?|$)", re.I)
# Only keys that name a registration/landing destination; generic "url"/"link" keys (ads, trackers)
# are recorded as plain host references.
REG_KEY_RE = re.compile(r"(domain|regist|signup|sign_up|h5_?(url|link|domain|address)|website|site_?url|web_?url|"
                        r"jump|landing|invite_?(url|link)|share_?(url|link|addr)|redirect_?url|entry_?url|portal)", re.I)
ASSET_KEY_RE = re.compile(r"(logo|icon|img|image|avatar|banner|pic|photo|oss|cdn|static|file|asset|thumb|cover|background|bg)", re.I)
DATE_KEY_RE = re.compile(r"(create|update|modif|publish|edit)[a-z_]*(time|at|date)$|^(ctime|mtime|createtime|updatetime)$", re.I)
DATE_VAL_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?|^\d{10}(\d{3})?$")

COMMON_SERVICES_FILE = Path(__file__).resolve().parent.parent / "linking" / "common_services.yaml"


def _load_common() -> tuple[set[str], dict[str, str]]:
    data = yaml.safe_load(COMMON_SERVICES_FILE.read_text(encoding="utf-8")) or {}
    domains: set[str] = set()
    category: dict[str, str] = {}
    for cat, items in data.items():
        for d in items or []:
            d = str(d).lower().strip()
            domains.add(d)
            category[d] = cat
    return domains, category


COMMON_DOMAINS, COMMON_CATEGORY = _load_common()


def common_service_category(host: str) -> str | None:
    host = host.lower()
    for cand in (host, registrable_domain(host)):
        if cand in COMMON_CATEGORY:
            return COMMON_CATEGORY[cand]
    parts = host.split(".")
    for i in range(len(parts) - 1):
        suffix = ".".join(parts[i:])
        if suffix in COMMON_CATEGORY:
            return COMMON_CATEGORY[suffix]
    return None


def _valid_host(h: str) -> bool:
    h = h.lower().strip(".")
    if "." not in h or len(h) > 253:
        return False
    tld = h.rsplit(".", 1)[-1]
    if tld in FILE_EXT_TLDS or tld.isdigit():
        return False
    if re.fullmatch(r"[\d.]+", h):
        return True  # IPv4 literal
    return bool(re.fullmatch(r"[a-z0-9.-]+", h))


@dataclass
class HostRef:
    host: str
    relation: str                     # referenced | observed | referenced_and_observed
    contexts: list[str] = field(default_factory=list)   # json:domainUrl, html:img[src], traffic:image ...
    roles: set[str] = field(default_factory=set)        # registration_destination | asset | script | link | messaging
    artifact_hint: set[str] = field(default_factory=set)  # 'har' or 'html:<step>'
    statuses: list[int] = field(default_factory=list)
    count: int = 0

    def add(self, ctx: str, role: str | None, hint: str) -> None:
        if ctx not in self.contexts and len(self.contexts) < 12:
            self.contexts.append(ctx)
        if role:
            self.roles.add(role)
        self.artifact_hint.add(hint)
        self.count += 1


def _walk_json(obj: Any, path: str = "") -> Iterator[tuple[str, str, Any]]:
    """Yield (key_path, last_key, value) for scalar leaves."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_json(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:500]):
            yield from _walk_json(v, f"{path}[]")
    else:
        last = re.split(r"[.\[\]]+", path.strip("[]."))[-1] if path else ""
        yield path, last, obj


def _hosts_in_string(s: str, allow_bare: bool) -> list[tuple[str, str]]:
    """Return (host, full_value) pairs found in a string."""
    out = []
    for m in URL_HOST_RE.finditer(s):
        out.append((m.group(1).lower(), s))
    if not out and allow_bare and BARE_HOST_RE.match(s.strip()):
        host = s.strip().split("/")[0].split(":")[0].lower()
        out.append((host, s))
    return [(h, v) for h, v in out if _valid_host(h)]


@dataclass
class HostAnalysis:
    refs: dict[str, HostRef] = field(default_factory=dict)
    site_times: dict[str, int] = field(default_factory=dict)       # site-reported timestamps -> count
    site_time_keys: set[str] = field(default_factory=set)
    claimed_names_json: list[str] = field(default_factory=list)    # platform names found in JSON config
    json_responses: int = 0

    def ref(self, host: str) -> HostRef:
        if host not in self.refs:
            self.refs[host] = HostRef(host=host, relation="referenced")
        return self.refs[host]


NAME_KEY_RE = re.compile(r"(platform_name|site_name|sitename|app_name|appname|h5_platform_name|brand_name|company_name|shop_name|title)$", re.I)


def analyze_hosts(page_host: str, har: dict | None, html_steps: list[tuple[int, str]]) -> HostAnalysis:
    ha = HostAnalysis()
    observed: dict[str, list[tuple[str, int]]] = {}

    entries = (har or {}).get("log", {}).get("entries", []) or []
    for e in entries:
        req, resp = e.get("request", {}), e.get("response", {})
        url = req.get("url", "")
        try:
            host = (urlsplit(url).hostname or "").lower()
        except ValueError:
            continue
        status = int(resp.get("status") or 0)
        rtype = e.get("_resourceType") or _guess_type(resp.get("content", {}).get("mimeType", ""), url)
        if host and status > 0:
            observed.setdefault(host, []).append((rtype, status))
        content = resp.get("content", {}) or {}
        text = content.get("text")
        mime = (content.get("mimeType") or "").lower()
        if not text:
            continue
        if "json" in mime or (text[:1] in "{[" and "javascript" not in mime and "html" not in mime):
            try:
                data = json.loads(text)
            except ValueError:
                data = None
            if data is not None:
                ha.json_responses += 1
                _scan_json(ha, data, page_host)
                continue
        if "javascript" in mime or url.split("?")[0].endswith(".js"):
            for h, _v in _hosts_in_string(text[:800_000], allow_bare=False):
                ha.ref(h).add("js:string", None, "har")
        elif "html" in mime:
            _scan_html(ha, text, "har", page_host)

    for step, html in html_steps:
        _scan_html(ha, html, f"html:{step}", page_host)

    for host, seen in observed.items():
        r = ha.refs.get(host)
        if r is None:
            r = HostRef(host=host, relation="observed")
            ha.refs[host] = r
        elif r.relation == "referenced":
            r.relation = "referenced_and_observed"
        for rtype, status in seen[:20]:
            r.add(f"traffic:{rtype}", "asset" if rtype in ("image", "stylesheet", "font") else None, "har")
            r.statuses.append(status)
    return ha


def _guess_type(mime: str, url: str) -> str:
    mime = (mime or "").lower()
    if mime.startswith("image/") or IMAGE_EXT_RE.search(url):
        return "image"
    if "javascript" in mime:
        return "script"
    if "css" in mime:
        return "stylesheet"
    if "json" in mime:
        return "xhr"
    if "html" in mime:
        return "document"
    if "font" in mime:
        return "font"
    return "other"


def _scan_json(ha: HostAnalysis, data: Any, page_host: str) -> None:
    for path, key, val in _walk_json(data):
        if not isinstance(val, str):
            continue
        if DATE_KEY_RE.search(key or "") and DATE_VAL_RE.match(val.strip()):
            ha.site_times[val.strip()[:19]] = ha.site_times.get(val.strip()[:19], 0) + 1
            ha.site_time_keys.add(key)
            continue
        if NAME_KEY_RE.search(key or "") and 2 <= len(val) <= 60 and "/" not in val and val not in ha.claimed_names_json:
            if len(ha.claimed_names_json) < 5:
                ha.claimed_names_json.append(val)
        for host, full in _hosts_in_string(val, allow_bare=True):
            role = None
            if ASSET_KEY_RE.search(key or "") or IMAGE_EXT_RE.search(full):
                role = "asset"
            elif REG_KEY_RE.search(key or ""):
                role = "registration_destination"
            ha.ref(host).add(f"json:{key}", role, "har")


def _scan_html(ha: HostAnalysis, html: str, hint: str, page_host: str) -> None:
    if not html:
        return
    soup = BeautifulSoup(html, "lxml")
    for el in soup.find_all(True):
        for attr in ("src", "href", "srcset", "action", "data-src", "poster", "content"):
            val = el.get(attr)
            if not val or not isinstance(val, str):
                continue
            for host, full in _hosts_in_string(val, allow_bare=False):
                tag = el.name
                if tag in ("img", "source", "picture", "video") or (tag == "link" and "icon" in " ".join(el.get("rel") or [])):
                    role = "asset"
                elif tag == "script":
                    role = "script"
                elif tag == "link":
                    role = "asset"
                elif tag == "a":
                    role = "link"
                elif tag == "form":
                    role = "form_action"
                else:
                    role = None
                ha.ref(host).add(f"html:{tag}[{attr}]", role, hint)
    for script in soup.find_all("script"):
        txt = script.string or ""
        if txt:
            for host, _ in _hosts_in_string(txt[:300_000], allow_bare=False):
                ha.ref(host).add("html:inline-script", None, hint)
