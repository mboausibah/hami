"""Database access behind SQLAlchemy, selected by DATABASE_URL.

Default: SQLite file at HAMI_DB_PATH (backend/storage/hami.sqlite3). Moving to hosted Postgres is a config change:
    DATABASE_URL=postgresql+psycopg://user:password@host:5432/hami
Migrations are plain SQL per dialect (migrations/sqlite/, migrations/postgresql/), tracked in schema_migrations.

The rest of the code uses a small, dialect-neutral API: `with db() as conn`, `conn.execute(sql, params)` with
`?` placeholders, rows readable by column name or index, `.lastrowid` after INSERT (RETURNING on Postgres),
`with tx(conn):` for multi-statement transactions. Outside `tx`, every statement is committed immediately.
"""
from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from app.config import settings

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_lock = threading.Lock()
_engines: dict[str, Engine] = {}
_initialized: set[str] = set()


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def database_url(path: Path | None = None) -> str:
    if path is not None:
        return f"sqlite:///{Path(path).as_posix()}"
    url = os.environ.get("DATABASE_URL", "").strip()
    return url or f"sqlite:///{settings.db_path.as_posix()}"


def get_engine(url: str) -> Engine:
    with _lock:
        eng = _engines.get(url)
        if eng is not None:
            return eng
        if url.startswith("sqlite"):
            Path(url.split("///", 1)[1]).parent.mkdir(parents=True, exist_ok=True)
            eng = create_engine(url, connect_args={"timeout": 30, "check_same_thread": False}, pool_pre_ping=True)

            @event.listens_for(eng, "connect")
            def _sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA foreign_keys = ON")
                cur.execute("PRAGMA journal_mode = WAL")
                cur.execute("PRAGMA busy_timeout = 30000")
                cur.close()
        else:
            eng = create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=20)
        _engines[url] = eng
        return eng


# ---- thin compatibility layer -------------------------------------------------------------------------------
class Row:
    """Row readable by index, by column name, as a mapping (dict(row)) or as a tuple."""

    __slots__ = ("_t", "_m")

    def __init__(self, sa_row: Any) -> None:
        self._t = tuple(sa_row)
        self._m = sa_row._mapping

    def __getitem__(self, k: int | slice | str) -> Any:
        return self._t[k] if isinstance(k, (int, slice)) else self._m[k]

    def keys(self) -> list[str]:
        return list(self._m.keys())

    def get(self, k: str, default: Any = None) -> Any:
        return self._m.get(k, default)

    def __iter__(self) -> Iterator[Any]:
        return iter(self._t)

    def __len__(self) -> int:
        return len(self._t)

    def __repr__(self) -> str:
        return f"Row({dict(self._m)!r})"


class Result:
    def __init__(self, rows: list[Row] | None, lastrowid: Any, rowcount: int) -> None:
        self._rows = rows or []
        self._i = 0
        self.lastrowid = lastrowid
        self.rowcount = rowcount

    def fetchone(self) -> Row | None:
        if self._i >= len(self._rows):
            return None
        r = self._rows[self._i]
        self._i += 1
        return r

    def fetchall(self) -> list[Row]:
        rest = self._rows[self._i:]
        self._i = len(self._rows)
        return rest

    def __iter__(self) -> Iterator[Row]:
        return iter(self.fetchall())


def _translate(sql: str) -> tuple[str, int]:
    """'?' placeholders -> :p0, :p1 ... (outside quoted literals)."""
    out, n, quote = [], 0, None
    for ch in sql:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            out.append(ch)
        elif ch == "?":
            out.append(f":p{n}")
            n += 1
        else:
            out.append(ch)
    return "".join(out), n


class DB:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.dialect = engine.dialect.name
        self._c = engine.connect()
        self._in_tx = False

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> Result:
        q, n = _translate(sql)
        bind = {f"p{i}": v for i, v in enumerate(params or ())}
        if len(bind) != n:
            raise ValueError(f"expected {n} parameters, got {len(bind)}")
        is_insert = q.lstrip().upper().startswith("INSERT")
        if is_insert and self.dialect == "postgresql" and "RETURNING" not in q.upper():
            q = q.rstrip().rstrip(";") + " RETURNING *"
        try:
            r = self._c.execute(text(q), bind)
            rows = [Row(x) for x in r.fetchall()] if r.returns_rows else None
            if is_insert:
                lastrowid = rows[0][0] if (self.dialect == "postgresql" and rows) else getattr(r, "lastrowid", None)
            else:
                lastrowid = None
            # With RETURNING, Postgres drivers report rowcount -1: count the returned rows instead.
            rowcount = len(rows or []) if (is_insert and self.dialect == "postgresql") else r.rowcount
            if not self._in_tx:
                self._c.commit()
            return Result(None if is_insert and self.dialect == "postgresql" else rows, lastrowid, rowcount)
        except DBAPIError as e:
            if not self._in_tx:
                self._c.rollback()
            raise (e.orig if e.orig is not None else e) from None

    def close(self) -> None:
        try:
            if self._c.in_transaction():
                self._c.rollback()
        finally:
            self._c.close()


def migrate(path: Path | None = None) -> list[str]:
    """Apply pending migrations for the database's dialect, in filename order. Returns versions applied."""
    eng = get_engine(database_url(path))
    folder = MIGRATIONS_DIR / ("postgresql" if eng.dialect.name == "postgresql" else "sqlite")
    with eng.connect() as c:
        c.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"))
        c.commit()
        done = {r[0] for r in c.execute(text("SELECT version FROM schema_migrations"))}
    applied = []
    for f in sorted(folder.glob("*.sql")):
        if f.stem in done:
            continue
        raw = eng.raw_connection()
        try:
            cur = raw.cursor()
            if eng.dialect.name == "sqlite":
                raw.driver_connection.executescript("BEGIN;\n" + f.read_text(encoding="utf-8") + "\nCOMMIT;")
            else:
                cur.execute(f.read_text(encoding="utf-8"))
            cur.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (%s, %s)"
                        if eng.dialect.name == "postgresql" else
                        "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)", (f.stem, utcnow()))
            raw.commit()
        except Exception:
            raw.rollback()
            raise
        finally:
            raw.close()
        applied.append(f.stem)
    return applied


def get_conn() -> DB:
    url = database_url()
    if url not in _initialized:
        with _lock:
            pass
        if url not in _initialized:
            migrate()
            _initialized.add(url)
    return DB(get_engine(url))


@contextmanager
def db() -> Iterator[DB]:
    conn = get_conn()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def tx(conn: DB) -> Iterator[DB]:
    """Run several statements atomically."""
    if conn._in_tx:  # nested: part of the outer transaction
        yield conn
        return
    if conn._c.in_transaction():
        conn._c.commit()
    conn._in_tx = True
    try:
        yield conn
        conn._c.commit()
    except Exception:
        conn._c.rollback()
        raise
    finally:
        conn._in_tx = False


def row_to_dict(row: Row | None, json_fields: tuple[str, ...] = ()) -> dict[str, Any] | None:
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
