"""Import user-recorded browser sessions (HTTP Toolkit / DevTools HAR, optionally .gz/.xz) safely.

- Every file goes through the sanitizer in strict mode: cookies, auth headers, tokens, request bodies,
  WebSocket messages, invite codes, phone numbers and e-mails are removed; response bodies of requests that
  carried credentials are dropped (static JS/CSS/fonts are kept and every body is SHA-256 hashed first).
- Entries are split into one kit per site: the registrable domain of the page that loaded each request
  (Referer / Origin), else of the request host for top-level documents.
- Each site becomes a *stored scan* (batch 'sessions', capture_mode 'stored') analyzed by the same pipeline:
  delivered-file fingerprints, delivered-code strings, linking. Requests are never replayed and no token is
  ever reused; the capture pipeline never signs in.

    python -m ml.import_sessions [--dir data/private/sessions]
"""
from __future__ import annotations

import argparse
import gzip
import json
import lzma
import secrets
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.analyze.hosts import common_service_category
from app.config import settings
from app.db import db, tx, utcnow
from app.sanitize import sanitize_har, sanitize_html
from app.storage import put_artifact
from app.urls import defang, normalize_url, registrable_domain

SKIP_SITES = {"httptoolkit.tech", "httptoolkit.com", "localhost", "chrome.com", "mozilla.net", "mozilla.org",
              "windowsupdate.com", "msftconnecttest.com", "live.com", "office.com", "bing.com"}
MIN_ENTRIES = 3


def load_har(path: Path) -> dict[str, Any]:
    opener = lzma.open if path.suffix == ".xz" else gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as f:  # type: ignore[operator]
        return json.load(f)


def _header(entry: dict, name: str) -> str:
    for h in entry.get("request", {}).get("headers", []) or []:
        if str(h.get("name", "")).lower() == name:
            return str(h.get("value", ""))
    return ""


def loader_host(entry: dict) -> str:
    """Host of the page that loaded this request (Referer / Origin), else the request host itself."""
    for name in ("referer", "origin"):
        v = _header(entry, name)
        if v:
            try:
                host = urlsplit(v).hostname
            except ValueError:
                host = None
            if host:
                return host.lower()
    return (urlsplit(entry.get("request", {}).get("url", "")).hostname or "").lower()


def split_by_host(har: dict[str, Any]) -> dict[str, list[dict]]:
    """One kit per page host; API / CDN / support calls fold into the page that made them."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for e in har.get("log", {}).get("entries", []) or []:
        host = loader_host(e)
        if not host or "." not in host or registrable_domain(host) in SKIP_SITES or common_service_category(host):
            continue
        groups[host].append(e)
    def has_document(entries: list[dict]) -> bool:
        return any("html" in (e.get("response", {}).get("content", {}).get("mimeType") or "") for e in entries)

    # Pages only: a group needs an HTML document or enough traffic; pure API hosts fold into their pages.
    return {k: v for k, v in groups.items() if len(v) >= MIN_ENTRIES and (has_document(v) or len(v) >= 10)}


def _main_document(entries: list[dict], host: str) -> str:
    for e in entries:
        c = e.get("response", {}).get("content", {}) or {}
        if (urlsplit(e["request"]["url"]).hostname or "").lower() == host and "html" in (c.get("mimeType") or "") \
                and c.get("text") and int(e.get("response", {}).get("status") or 0) < 400:
            return c["text"]
    return ""


def import_file(path: Path, report: dict[str, Any]) -> list[int]:
    from app.pipeline import analyze_and_score

    har = load_har(path)
    created = []
    for host, entries in sorted(split_by_host(har).items()):
        site = registrable_domain(host)
        started = min((e.get("startedDateTime") or "" for e in entries), default="") or utcnow()
        url = f"https://{host}/"
        with db() as conn:
            dup = conn.execute("SELECT scan_id FROM scans WHERE batch='sessions' AND host=? AND captured_at=? "
                               "AND submitted_url=?", (host, started, url)).fetchone()
        if dup:
            report["skipped_existing"] += 1
            continue
        clean = sanitize_har({"log": {"version": "1.2", "creator": {"name": "hami-session-import"}, "entries": entries}},
                             settings.capture_max_body_bytes, strict=True)
        doc = sanitize_html(_main_document(clean["log"]["entries"], host))
        dropped = Counter(e["response"]["content"].get("_hami_body") for e in clean["log"]["entries"]
                          if e["response"]["content"].get("_hami_body"))
        with db() as conn, tx(conn):
            scan_id = conn.execute(
                "INSERT INTO scans (submitted_url, normalized_url, host, source_type, batch, submitted_at, status, "
                "capture_mode, capture_status, captured_at, final_url, access_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (url, normalize_url(url), host, "import", "sessions", utcnow(), "analyzing", "stored", "ok", started,
                 url, secrets.token_urlsafe(16))).lastrowid
            put_artifact(conn, scan_id, "har", clean, captured_at=started)
            if doc:
                put_artifact(conn, scan_id, "html", doc, action_step=0, action_name="session_document", captured_at=started)
            put_artifact(conn, scan_id, "action_log", {
                "imported_from": path.name, "site": site, "entries": len(entries),
                "note": "user-recorded session imported offline; requests were never replayed and no token reused",
                "sanitizer": "strict", "bodies_dropped": dict(dropped)}, captured_at=started)
        analyze_and_score(scan_id, scan_id, None, None, "ok", True, time.monotonic(), asset_source="session")
        created.append(scan_id)
        report["sites"][host] = {"file": path.name, "entries": len(entries), "scan_id": scan_id,
                                 "bodies_dropped": dict(dropped)}
    return created


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(settings.private_dir / "sessions"))
    args = ap.parse_args(argv)
    d = Path(args.dir)
    if not d.is_dir():
        print(f"no sessions folder at {d}")
        return 0
    settings.ensure_dirs()
    report: dict[str, Any] = {"sites": {}, "skipped_existing": 0, "files": []}
    for path in sorted(d.iterdir()):
        if path.name.endswith((".har", ".har.gz", ".har.xz")):
            report["files"].append(path.name)
            ids = import_file(path, report)
            print(f"{path.name}: {len(ids)} site kits imported")
    with db() as conn:
        for host, info in report["sites"].items():
            a = conn.execute("SELECT risk_tier FROM assessments WHERE scan_id=? ORDER BY assessment_id DESC LIMIT 1",
                             (info["scan_id"],)).fetchone()
            n_assets = conn.execute("SELECT COUNT(*) FROM asset_files WHERE scan_id=?", (info["scan_id"],)).fetchone()[0]
            info["tier"] = a["risk_tier"] if a else None
            print(f"  {defang(host):40s} entries={info['entries']:5d} files={n_assets:4d} tier={info['tier']}")
    print(f"skipped (already imported): {report['skipped_existing']}")
    (settings.processed_dir).mkdir(parents=True, exist_ok=True)
    (settings.processed_dir / "sessions_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
