"""Idle snapshots from the extension: what a candidate page loaded in the user's browser (metadata only).

The extension sends, after 10 s without activity on a candidate page and only with the user's consent:
resource URLs without query strings or fragments, their types, status codes, timings and sizes, and the
visible text (e-mails / phone numbers removed on the device). Never cookies, headers, form values or bodies.

The backend sanitizes again, then fetches the public static JS and CSS files listed - from its own environment,
with no cookies, through the same private-network guard as captures - hashes them for kit matching and reads
their strings. The snapshot is stored as a HAR-format artifact (user-browser metadata; JS/CSS bodies fetched by
the backend are marked `_hami_fetched_by: backend`) linked to the scan, and analyzed by the normal pipeline."""
from __future__ import annotations

import concurrent.futures
import re
import secrets
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.analyze.assets import common_file_name
from app.analyze.hosts import common_service_category
from app.capture import USER_AGENT
from app.config import settings
from app.db import db, tx, utcnow
from app.sanitize import redact_text, sanitize_html
from app.storage import put_artifact
from app.urls import UnsafeTarget, check_target, hostname, normalize_url

MAX_RESOURCES = 600
MAX_FETCH = 40
MAX_FILE_BYTES = 2_000_000
STATIC_RE = re.compile(r"\.(m?js|css)$", re.I)
TYPE_MIME = {"script": "application/javascript", "css": "text/css", "link": "text/css", "img": "image/*",
             "image": "image/*", "font": "font/*", "xmlhttprequest": "application/json", "fetch": "application/json",
             "websocket": "websocket", "main_frame": "text/html", "sub_frame": "text/html", "navigation": "text/html"}


class SnapshotError(ValueError):
    pass


def strip_url(url: str) -> str | None:
    """http(s)/ws(s) URL without query string, fragment or credentials."""
    try:
        p = urlsplit(url.strip())
    except ValueError:
        return None
    if p.scheme not in ("http", "https", "ws", "wss") or not p.hostname:
        return None
    netloc = p.hostname + (f":{p.port}" if p.port else "")
    return urlunsplit((p.scheme, netloc, p.path or "/", "", ""))


def _fetch(url: str) -> tuple[str, bytes | None, str]:
    try:
        check_target(url, settings.capture_allow_hosts, settings.capture_allow_private)
    except UnsafeTarget as e:
        return url, None, f"refused: {e}"
    headers = {"User-Agent": USER_AGENT}
    target = url
    p = urlsplit(url)
    if (p.hostname or "").endswith(".localhost"):
        # Test sites: browsers resolve *.localhost to loopback, the OS resolver may not.
        headers["Host"] = p.netloc
        target = urlunsplit((p.scheme, "127.0.0.1" + (f":{p.port}" if p.port else ""), p.path, p.query, ""))
    try:
        with httpx.Client(headers=headers, timeout=8, follow_redirects=False) as c:
            with c.stream("GET", target) as r:
                if r.status_code != 200:
                    return url, None, f"HTTP {r.status_code}"
                buf = bytearray()
                for chunk in r.iter_bytes():
                    buf += chunk
                    if len(buf) > MAX_FILE_BYTES:
                        return url, None, "too large"
                return url, bytes(buf), r.headers.get("content-type", "")
    except httpx.HTTPError as e:
        return url, None, type(e).__name__


def build_har(resources: list[dict[str, Any]], fetched: dict[str, tuple[bytes | None, str]]) -> dict[str, Any]:
    import hashlib

    entries = []
    for r in resources:
        content: dict[str, Any] = {"mimeType": TYPE_MIME.get(r["type"], "")}
        got = fetched.get(r["url"])
        if got and got[0] is not None:
            body = got[0]
            content["_hami_sha256"] = hashlib.sha256(body).hexdigest()
            content["_hami_size"] = len(body)
            content["mimeType"] = "text/css" if r["url"].lower().endswith(".css") else "application/javascript"
            content["text"] = redact_text(body.decode("utf-8", "replace"))
            content["_hami_fetched_by"] = "backend"
        entries.append({
            "startedDateTime": utcnow(), "time": r.get("duration_ms") or 0,
            "request": {"method": "GET", "url": r["url"], "headers": [], "cookies": [], "queryString": []},
            "response": {"status": int(r.get("status") or 0) or (200 if got and got[0] is not None else 0),
                         "headers": [], "cookies": [], "content": content},
            "_resourceType": r["type"], "_hami_source": "user_browser_metadata",
            "_hami_size_reported": r.get("size"),
        })
    return {"log": {"version": "1.2", "creator": {"name": "hami-idle-snapshot"}, "entries": entries}}


def ingest(payload: dict[str, Any], linked_scan_id: int | None) -> dict[str, Any]:
    from app.pipeline import analyze_and_score, get_scan_payload

    page = strip_url(str(payload.get("page_url", "")))
    if not page or not page.startswith("http"):
        raise SnapshotError("page_url must be an http(s) URL")
    try:
        check_target(page, settings.capture_allow_hosts, settings.capture_allow_private, resolve=False)
    except UnsafeTarget as e:
        raise SnapshotError(f"unsafe page: {e}") from e
    resources: list[dict[str, Any]] = []
    seen = set()
    for r in (payload.get("resources") or [])[:MAX_RESOURCES * 2]:
        u = strip_url(str(r.get("url", "")))
        if not u or u in seen:
            continue
        seen.add(u)
        resources.append({"url": u, "type": str(r.get("type") or "other")[:24],
                          "status": r.get("status") if isinstance(r.get("status"), int) else None,
                          "duration_ms": round(float(r["duration_ms"]), 1) if isinstance(r.get("duration_ms"), (int, float)) else None,
                          "size": r.get("size") if isinstance(r.get("size"), int) else None})
        if len(resources) >= MAX_RESOURCES:
            break
    text = redact_text(str(payload.get("visible_text") or ""))[:20000]
    # Public static files to fetch from the backend (never the user's cookies): own JS/CSS only.
    wanted = [r["url"] for r in resources if r["url"].startswith("http") and STATIC_RE.search(urlsplit(r["url"]).path)
              and not common_service_category(hostname(r["url"]))
              and not common_file_name(urlsplit(r["url"]).path.rsplit("/", 1)[-1])][:MAX_FETCH]
    fetched: dict[str, tuple[bytes | None, str]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for url, body, info in pool.map(_fetch, wanted):
            fetched[url] = (body, info)
    har = build_har(resources, fetched)
    host = hostname(page)
    html = "<html><body>" + "".join(f"<p>{line}</p>" for line in text.splitlines() if line.strip()) + "</body></html>"
    now = utcnow()
    with db() as conn, tx(conn):
        scan_id = conn.execute(
            "INSERT INTO scans (submitted_url, normalized_url, host, source_type, lang, batch, parent_scan_id, submitted_at,"
            " status, capture_mode, capture_status, captured_at, final_url, access_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (page, normalize_url(page), host, "extension", (payload.get("lang") or "en")[:2], "snapshot", linked_scan_id,
             now, "analyzing", "live", "ok", now, page, secrets.token_urlsafe(16))).lastrowid
        put_artifact(conn, scan_id, "har", har, action_name="idle_snapshot", captured_at=now)
        put_artifact(conn, scan_id, "html", sanitize_html(html), action_step=0, action_name="snapshot_visible_text",
                     captured_at=now)
        put_artifact(conn, scan_id, "action_log", {
            "source": "extension idle snapshot (user's browser, metadata only)", "resources": len(resources),
            "hosts": len({hostname(r['url']) for r in resources}), "backend_fetched": sum(1 for v in fetched.values() if v[0]),
            "fetch_results": {u: (len(b) if b else info) for u, (b, info) in fetched.items()},
            "never_sent": "cookies, headers, form values, request/response bodies, query strings"}, captured_at=now)
        snap_id = conn.execute(
            "INSERT INTO snapshots (scan_id, page_host, resource_count, host_count, fetched_count, created_at) "
            "VALUES (?,?,?,?,?,?)", (scan_id, host, len(resources), len({hostname(r['url']) for r in resources}),
                                     sum(1 for v in fetched.values() if v[0]), now)).lastrowid
    analyze_and_score(scan_id, scan_id, None, None, "ok", False, time.monotonic(), asset_source="snapshot")
    out = get_scan_payload(scan_id)
    out["snapshot_id"] = snap_id
    out["linked_scan_id"] = linked_scan_id
    return out
