"""SQLite access: connection helper and plain-SQL migrations."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from app.config import settings

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_init_lock = threading.Lock()
_initialized: set[str] = set()


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def migrate(path: Path | None = None) -> list[str]:
    """Apply pending migrations in filename order. Returns the versions applied."""
    path = path or settings.db_path
    conn = _connect(path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
        applied = []
        for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = f.stem
            if version in done:
                continue
            conn.execute("BEGIN")
            try:
                for stmt in _split_sql(f.read_text(encoding="utf-8")):
                    conn.execute(stmt)
                conn.execute("INSERT INTO schema_migrations VALUES (?, ?)", (version, utcnow()))
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            applied.append(version)
        return applied
    finally:
        conn.close()


def _split_sql(script: str) -> list[str]:
    """Split a migration into statements, keeping CREATE TRIGGER ... END; blocks intact."""
    stmts: list[str] = []
    buf: list[str] = []
    in_trigger = False
    for line in script.splitlines():
        stripped = line.strip()
        if stripped.startswith("--") and not buf:
            continue
        buf.append(line)
        upper = stripped.upper()
        if upper.startswith("CREATE TRIGGER"):
            in_trigger = True
        if in_trigger:
            if upper.endswith("END;"):
                stmts.append("\n".join(buf))
                buf, in_trigger = [], False
        elif stripped.endswith(";"):
            stmts.append("\n".join(buf))
            buf = []
    tail = "\n".join(buf).strip()
    if tail:
        stmts.append(tail)
    return [s for s in stmts if s.strip() and not all(l.strip().startswith("--") or not l.strip() for l in s.splitlines())]


def get_conn() -> sqlite3.Connection:
    path = settings.db_path
    key = str(path)
    if key not in _initialized:
        with _init_lock:
            if key not in _initialized:
                migrate(path)
                _initialized.add(key)
    return _connect(path)


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    conn = get_conn()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def row_to_dict(row: sqlite3.Row | None, json_fields: tuple[str, ...] = ()) -> dict[str, Any] | None:
    if row is None:
        return None
    d = dict(row)
    for f in json_fields:
        if f in d and isinstance(d[f], str):
            try:
                d[f] = json.loads(d[f])
            except ValueError:
                pass
    return d


def reset_init_cache() -> None:
    """Tests switch databases; forget which ones were migrated."""
    _initialized.clear()
