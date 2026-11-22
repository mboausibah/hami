"""Command-line entry points: python -m app.cli <command>."""
from __future__ import annotations

import argparse
import sys

from app.config import settings


def cmd_migrate(_args: argparse.Namespace) -> int:
    from app.db import migrate

    settings.ensure_dirs()
    applied = migrate()
    print(f"database: {settings.db_path}")
    print("applied migrations: " + (", ".join(applied) if applied else "none (up to date)"))
    return 0


def cmd_testsites(args: argparse.Namespace) -> int:
    from app.testsites import serve_forever

    serve_forever(args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hami")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate", help="create/upgrade the SQLite database").set_defaults(fn=cmd_migrate)
    ts = sub.add_parser("testsites", help="serve the synthetic test sites (site-a/b/c.localhost, listing)")
    ts.add_argument("--port", type=int, default=None)
    ts.set_defaults(fn=cmd_testsites)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
