"""Investigator-mode evidence uploads: a HAR sanitized on the device, with its SHA-256 computed there.

The server verifies the hash of exactly the bytes it received, sanitizes again in strict mode (defence in
depth), stores the result as a hashed artifact on a new evidence scan and analyzes it like any capture
(kit fingerprints, delivered code, linking). Both hashes are kept in evidence_files."""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from typing import Any

from app.config import settings
from app.db import db, tx, utcnow
from app.sanitize import sanitize_har, sanitize_html
from app.storage import put_artifact
from app.urls import hostname, normalize_url

MAX_HAR_BYTES = 25_000_000


class EvidenceError(ValueError):
    pass


def _main_document(har: dict[str, Any], host: str) -> str:
    for e in har.get("log", {}).get("entries", []) or []:
        c = e.get("response", {}).get("content", {}) or {}
        if hostname(e.get("request", {}).get("url", "")) == host and "html" in (c.get("mimeType") or "") and c.get("text"):
            return c["text"]
    return ""


def ingest(page_url: str, har_text: str, client_sha256: str, entries: int, linked_scan_id: int | None) -> dict[str, Any]:
    from app.pipeline import analyze_and_score, get_scan_payload
    from app.snapshots import strip_url

    raw = har_text.encode("utf-8")
    if len(raw) > MAX_HAR_BYTES:
        raise EvidenceError("evidence file too large")
    server_sha = hashlib.sha256(raw).hexdigest()
    page = strip_url(page_url)
    if not page or not page.startswith("http"):
        raise EvidenceError("page_url must be an http(s) URL")
    try:
        har = json.loads(har_text)
        assert isinstance(har.get("log", {}).get("entries"), list)
    except (ValueError, AssertionError, AttributeError) as e:
        raise EvidenceError("not a HAR file") from e
    clean = sanitize_har(har, settings.capture_max_body_bytes, strict=True)
    host = hostname(page)
    doc = sanitize_html(_main_document(clean, host))
    now = utcnow()
    with db() as conn, tx(conn):
        scan_id = conn.execute(
            "INSERT INTO scans (submitted_url, normalized_url, host, source_type, batch, parent_scan_id, submitted_at,"
            " status, capture_mode, capture_status, captured_at, final_url, access_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (page, normalize_url(page), host, "extension", "evidence", linked_scan_id, now, "analyzing", "live", "ok",
             now, page, secrets.token_urlsafe(16))).lastrowid
        art = put_artifact(conn, scan_id, "har", clean, action_name="investigator_evidence", captured_at=now)
        if doc:
            put_artifact(conn, scan_id, "html", doc, action_step=0, action_name="evidence_document", captured_at=now)
        put_artifact(conn, scan_id, "action_log", {
            "source": "investigator mode (chrome.debugger HAR, sanitized on the device, re-sanitized on the server)",
            "entries_reported": entries, "entries_received": len(clean["log"]["entries"]),
            "client_sha256": client_sha256, "server_sha256": server_sha, "hash_match": client_sha256 == server_sha},
            captured_at=now)
        evidence_id = conn.execute(
            "INSERT INTO evidence_files (scan_id, page_host, artifact_id, client_sha256, server_sha256, entries, created_at)"
            " VALUES (?,?,?,?,?,?,?)", (scan_id, host, art["artifact_id"], client_sha256, server_sha,
                                        len(clean["log"]["entries"]), now)).lastrowid
    analyze_and_score(scan_id, scan_id, None, None, "ok", False, time.monotonic(), asset_source="snapshot")
    out = get_scan_payload(scan_id)
    out.update({"evidence_id": evidence_id, "client_sha256": client_sha256, "server_sha256": server_sha,
                "hash_match": client_sha256 == server_sha, "stored_artifact_sha256": art["sha256"]})
    return out
