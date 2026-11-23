"""Copy a Hami SQLite database into PostgreSQL and verify it.

    python tasks.py migrate-to-postgres [--to postgresql+psycopg://...] [--sqlite PATH]
    docker compose --profile postgres run --rm api python -m app.db.transfer        (inside Docker)

- The target defaults to DATABASE_URL, the source to the SQLite file (HAMI_DB_PATH / HAMI_DATA_DIR).
- The target schema is created by the normal Postgres migrations. If the target already holds data, the copy is
  refused, unless that data is only the seed indicators loaded on first start (they are copied from SQLite too).
- Rows keep their IDs (links between tables stay valid); identity sequences are moved past the copied IDs.
- Verification: row count and highest ID of every table must match. Artifact files are not touched (the DB
  stores their content-addressed keys; the store is configured separately with STORAGE_URL).
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

from sqlalchemy import MetaData, func, select, text

from app.config import settings
from app.db import get_engine, migrate

SKIP = {"schema_migrations"}
CHUNK = 1000


def transfer(sqlite_path: Path, target_url: str) -> dict[str, dict[str, int]]:
    if not target_url.startswith("postgresql"):
        raise SystemExit("target must be a postgresql+psycopg:// URL (set DATABASE_URL or pass --to)")
    if not sqlite_path.is_file():
        raise SystemExit(f"SQLite database not found: {sqlite_path}")
    migrate(path=sqlite_path)  # make sure the source has the current schema too
    os.environ["DATABASE_URL"] = target_url
    migrate()
    eng = get_engine(target_url)
    meta = MetaData()
    meta.reflect(bind=eng)
    tables = [t for t in meta.sorted_tables if t.name not in SKIP]

    src = sqlite3.connect(str(sqlite_path))
    src.row_factory = sqlite3.Row
    src_tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    with eng.begin() as c:
        scans = c.execute(text("SELECT COUNT(*) FROM scans")).scalar()
        non_seed = c.execute(text("SELECT COUNT(*) FROM scans WHERE COALESCE(batch, '') <> 'seed'")).scalar()
        if non_seed:
            raise SystemExit(f"target already has {non_seed} scans; refusing to overwrite (use an empty database)")
        if scans:  # only the seed indicators from first start: they are part of the SQLite copy as well
            names = ", ".join(t.name for t in tables)
            c.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))

    report: dict[str, dict[str, int]] = {}
    with eng.begin() as c:
        for t in tables:
            if t.name not in src_tables:
                continue
            src_cols = {r[1] for r in src.execute(f"PRAGMA table_info({t.name})")}
            cols = [col.name for col in t.columns if col.name in src_cols]
            cur = src.execute(f"SELECT {', '.join(cols)} FROM {t.name} ORDER BY rowid")
            n = 0
            while True:
                rows = cur.fetchmany(CHUNK)
                if not rows:
                    break
                c.execute(t.insert(), [dict(zip(cols, r)) for r in rows])
                n += len(rows)
            pk = [col for col in t.primary_key.columns]
            if len(pk) == 1 and n and pk[0].type.python_type is int:
                c.execute(text(f"SELECT setval(pg_get_serial_sequence('{t.name}', '{pk[0].name}'), "
                               f"(SELECT MAX({pk[0].name}) FROM {t.name}))"))
            report[t.name] = {"source": src.execute(f"SELECT COUNT(*) FROM {t.name}").fetchone()[0], "copied": n}

    # verify: counts and highest IDs
    with eng.connect() as c:
        for t in tables:
            if t.name not in report:
                continue
            report[t.name]["target"] = c.execute(select(func.count()).select_from(t)).scalar()
            pk = list(t.primary_key.columns)
            if len(pk) == 1:
                src_max = src.execute(f"SELECT MAX({pk[0].name}) FROM {t.name}").fetchone()[0]
                dst_max = c.execute(select(func.max(pk[0]))).scalar()
                report[t.name]["max_id_match"] = int(src_max == dst_max)
    src.close()
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--to", default=os.environ.get("DATABASE_URL", ""), help="target PostgreSQL URL (default DATABASE_URL)")
    ap.add_argument("--sqlite", default=str(settings.db_path), help="source SQLite file")
    args = ap.parse_args(argv)
    report = transfer(Path(args.sqlite), args.to)
    ok = True
    print(f"{'table':<22}{'sqlite':>10}{'postgres':>10}  ids")
    for name, r in report.items():
        good = r["source"] == r["target"] == r["copied"] and r.get("max_id_match", 1) == 1
        ok &= good
        print(f"{name:<22}{r['source']:>10}{r['target']:>10}  {'ok' if good else 'MISMATCH'}")
    print("verified: every table matches" if ok else "VERIFICATION FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
