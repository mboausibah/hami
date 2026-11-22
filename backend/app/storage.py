"""Content-addressed artifact store. Every artifact is SHA-256 hashed and recorded in `artifacts`."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from app.config import settings
from app.db import utcnow

EXT = {
    "har": "har.json", "html": "html", "screenshot": "png", "action_log": "log.json",
    "analysis": "analysis.json", "model_text": "txt",
}
MIME = {
    "har": "application/json", "html": "text/html", "screenshot": "image/png",
    "action_log": "application/json", "analysis": "application/json", "model_text": "text/plain",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _to_bytes(data: bytes | str | dict | list) -> bytes:
    if isinstance(data, bytes):
        return data
    if isinstance(data, str):
        return data.encode("utf-8")
    return json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")


def put_artifact(
    conn: sqlite3.Connection,
    scan_id: int,
    kind: str,
    data: bytes | str | dict | list,
    action_step: int | None = None,
    action_name: str | None = None,
    captured_at: str | None = None,
) -> dict[str, Any]:
    raw = _to_bytes(data)
    digest = sha256_bytes(raw)
    rel = Path(digest[:2]) / f"{digest}.{EXT[kind]}"
    path = settings.artifacts_dir / rel
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(raw)
        tmp.replace(path)
    cur = conn.execute(
        "INSERT INTO artifacts (scan_id, kind, sha256, path, size_bytes, mime, captured_at, action_step, action_name)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (scan_id, kind, digest, rel.as_posix(), len(raw), MIME[kind], captured_at or utcnow(), action_step, action_name),
    )
    return {"artifact_id": cur.lastrowid, "sha256": digest, "path": rel.as_posix(), "kind": kind,
            "action_step": action_step, "size_bytes": len(raw)}


def read_artifact(rel_path: str) -> bytes:
    base = settings.artifacts_dir.resolve()
    path = (base / rel_path).resolve()
    if base not in path.parents:
        raise ValueError("artifact path escapes the store")
    return path.read_bytes()


def verify_artifact(rel_path: str, expected_sha: str) -> bool:
    try:
        return sha256_bytes(read_artifact(rel_path)) == expected_sha
    except (OSError, ValueError):
        return False


def artifact_url(artifact_id: int, key: str | None = None) -> str:
    """Path relative to the API base URL; clients prefix their configured server URL. The scan's
    capability key is part of the URL so screenshots cannot be enumerated."""
    return f"/artifacts/{artifact_id}" + (f"?k={key}" if key else "")
