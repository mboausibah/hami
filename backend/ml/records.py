"""Training/evaluation record format and builders shared by the importer and the trainer.

Record fields: id, source, kit_id, lang, label (fraudulent|legitimate|inconclusive), scam_type,
behavior_tags, text (redacted, normalized, hostnames removed), features (structured indicators),
url (only for real URLs; None for synthetic), html_path, hostnames, origin (private|synthetic|
public|reviewed_scan)."""
from __future__ import annotations

import email
import hashlib
import json
import sqlite3
from email import policy
from pathlib import Path
from typing import Any

from app.analyze import AnalyzerInput, analyze
from app.sanitize import sanitize_har, sanitize_html
from app.storage import read_artifact

LABELS = ("fraudulent", "legitimate", "inconclusive")


def make_record(*, rid: str, source: str, kit_id: str, label: str, origin: str, text: str,
                features: dict[str, float], lang: str = "", scam_type: str = "", behavior_tags: list[str] | None = None,
                url: str | None = None, html_path: str | None = None, hostnames: list[str] | None = None,
                fingerprint: list[int] | None = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    rec = {
        "id": rid, "source": source, "kit_id": kit_id, "lang": lang, "label": label, "scam_type": scam_type or "",
        "behavior_tags": behavior_tags or [], "text": text, "features": features, "url": url,
        "html_path": html_path, "hostnames": (hostnames or [])[:40], "origin": origin,
        "fingerprint": fingerprint or [],
    }
    if extra:
        rec.update(extra)
    return rec


def _main_html_from_har(har: dict) -> str:
    entries = har.get("log", {}).get("entries", []) or []
    for e in entries:
        c = e.get("response", {}).get("content", {}) or {}
        if "html" in (c.get("mimeType") or "") and c.get("text") and int(e.get("response", {}).get("status") or 0) < 400:
            return c["text"]
    return ""


def _html_from_mhtml(raw: bytes) -> str:
    msg = email.message_from_bytes(raw, policy=policy.default)
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            try:
                return part.get_content()
            except (LookupError, ValueError):
                payload = part.get_payload(decode=True) or b""
                return payload.decode("utf-8", "replace")
    return ""


def analyze_file(path: Path, page_url: str = "") -> dict[str, Any]:
    """Run a saved HTML/MHTML/HAR file through the same sanitizer and analyzer as live scans."""
    suffix = path.suffix.lower()
    har = None
    if suffix == ".har":
        har = sanitize_har(json.loads(path.read_text(encoding="utf-8", errors="replace")))
        html = _main_html_from_har(har)
        if not page_url:
            entries = har.get("log", {}).get("entries", [])
            page_url = entries[0]["request"]["url"] if entries else ""
    elif suffix in (".mhtml", ".mht"):
        html = sanitize_html(_html_from_mhtml(path.read_bytes()))
    else:
        html = sanitize_html(path.read_text(encoding="utf-8", errors="replace"))
    an = analyze(AnalyzerInput(page_url=page_url or f"file://{path.name}", steps=[(0, "load", html)] if html else [],
                               har=har))
    hosts = sorted(set(an.registration_destinations) | set(an.asset_hosts))
    return {"analysis": an, "hostnames": hosts, "page_url": page_url}


def scan_record_parts(conn: sqlite3.Connection, scan_id: int) -> dict[str, Any] | None:
    """Model text + features from a completed scan's stored artifacts."""
    scan = conn.execute("SELECT * FROM scans WHERE scan_id=?", (scan_id,)).fetchone()
    if scan is None or scan["status"] != "done":
        return None
    arts = {a["kind"]: a for a in conn.execute(
        "SELECT * FROM artifacts WHERE scan_id=? AND kind IN ('analysis','model_text') ORDER BY artifact_id", (scan_id,))}
    if "analysis" not in arts:
        return None
    analysis = json.loads(read_artifact(arts["analysis"]["path"]))
    text = read_artifact(arts["model_text"]["path"]).decode("utf-8") if "model_text" in arts else ""
    return {
        "scan": dict(scan), "text": text, "features": analysis.get("features", {}), "lang": analysis.get("lang", ""),
        "hostnames": sorted(set(analysis.get("registration_destinations", [])) | set(analysis.get("asset_hosts", []))),
        "fingerprint": analysis.get("fingerprint", []), "behaviors": analysis.get("behaviors", []),
        "html_path": arts["analysis"]["path"], "word_count": analysis.get("word_count", 0),
        "flags": analysis.get("flags", {}),
    }


def dataset_hash(records: list[dict[str, Any]]) -> str:
    h = hashlib.sha256()
    for r in sorted(records, key=lambda x: x["id"]):
        h.update(json.dumps([r["id"], r["label"], r["kit_id"], hashlib.sha256(r["text"].encode()).hexdigest(),
                             sorted(r["features"].items())], sort_keys=True).encode())
    return h.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
