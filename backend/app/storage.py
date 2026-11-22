"""Content-addressed artifact store behind a small interface. Every artifact is SHA-256 hashed and recorded in
the `artifacts` table; the bytes live in an ArtifactStore selected by STORAGE_URL.

    STORAGE_URL=                     -> local folder (HAMI_DATA_DIR/artifacts), the default
    STORAGE_URL=file:///srv/hami/artifacts

An S3-compatible store (AWS S3, MinIO, Cloudflare R2) is a new ArtifactStore implementation of put/get/exists
selected by `s3://bucket/prefix`; see docs/architecture.md. It is not implemented in this MVP.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit
from urllib.request import url2pathname

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


class ArtifactStore(Protocol):
    """Where artifact bytes live. Keys are content-addressed relative paths (ab/<sha256>.<ext>)."""

    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...


class LocalStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        base = self.root.resolve()
        path = (base / key).resolve()
        if base not in path.parents:
            raise ValueError("artifact key escapes the store")
        return path

    def put(self, key: str, data: bytes, content_type: str) -> None:  # noqa: ARG002
        path = self._path(key)
        if path.exists():
            return  # content-addressed: same key, same bytes
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()


def get_store() -> ArtifactStore:
    url = os.environ.get("STORAGE_URL", "").strip()
    if not url:
        return LocalStore(settings.artifacts_dir)
    parts = urlsplit(url)
    if parts.scheme == "file":
        return LocalStore(Path(url2pathname(parts.path)))
    raise RuntimeError(f"STORAGE_URL scheme not supported in this build: {parts.scheme}:// "
                       "(implement ArtifactStore for it; see docs/architecture.md)")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _to_bytes(data: bytes | str | dict | list) -> bytes:
    if isinstance(data, bytes):
        return data
    if isinstance(data, str):
        return data.encode("utf-8", "replace")
    return json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8", "replace")


def put_artifact(conn: Any, scan_id: int, kind: str, data: bytes | str | dict | list, action_step: int | None = None,
                 action_name: str | None = None, captured_at: str | None = None) -> dict[str, Any]:
    raw = _to_bytes(data)
    digest = sha256_bytes(raw)
    key = f"{digest[:2]}/{digest}.{EXT[kind]}"
    get_store().put(key, raw, MIME[kind])
    cur = conn.execute(
        "INSERT INTO artifacts (scan_id, kind, sha256, path, size_bytes, mime, captured_at, action_step, action_name)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (scan_id, kind, digest, key, len(raw), MIME[kind], captured_at or utcnow(), action_step, action_name),
    )
    return {"artifact_id": cur.lastrowid, "sha256": digest, "path": key, "kind": kind,
            "action_step": action_step, "size_bytes": len(raw)}


def read_artifact(rel_path: str) -> bytes:
    return get_store().get(rel_path)


def verify_artifact(rel_path: str, expected_sha: str) -> bool:
    try:
        return sha256_bytes(read_artifact(rel_path)) == expected_sha
    except (OSError, ValueError):
        return False


def artifact_url(artifact_id: int, key: str | None = None) -> str:
    """Path relative to the API base URL; clients prefix their configured server URL. The scan's
    capability key is part of the URL so screenshots cannot be enumerated."""
    return f"/artifacts/{artifact_id}" + (f"?k={key}" if key else "")
