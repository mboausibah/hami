"""Command-line entry points: python -m app.cli <command>."""
from __future__ import annotations

import argparse
import os
import sys

from app.config import settings


def cmd_migrate(_args: argparse.Namespace) -> int:
    from app.db import migrate

    settings.ensure_dirs()
    applied = migrate()
    print(f"database: {settings.db_path}")
    print("applied migrations: " + (", ".join(applied) if applied else "none (up to date)"))
    _seed()
    return 0


def _seed() -> None:
    """Load data/seed/indicators.json (reviewer-confirmed cases from the team) into an empty or older DB."""
    if not settings.load_seed:
        return
    from app.seed import load_seed

    r = load_seed()
    if r["cases"]:
        print(f"seed indicators: loaded {r['cases']} confirmed cases ({r['hosts']} hosts, {r['assets']} files) "
              "- marked 'seeded from team review'")


def cmd_export_indicators(_args: argparse.Namespace) -> int:
    from app.seed import main as export_main

    return export_main()


def cmd_testsites(args: argparse.Namespace) -> int:
    from app.testsites import serve_forever

    serve_forever(args.port)
    return 0


def _ensure_env() -> None:
    """Create .env from .env.example and generate a reviewer token if it is empty."""
    import secrets

    from app.config import REPO_DIR

    env, example = REPO_DIR / ".env", REPO_DIR / ".env.example"
    if not env.exists() and example.exists():
        env.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    lines = env.read_text(encoding="utf-8").splitlines() if env.exists() else []
    if not any(l.startswith("HAMI_REVIEWER_TOKEN=") and l.split("=", 1)[1].strip() for l in lines):
        token = secrets.token_urlsafe(32)
        lines = [l for l in lines if not l.startswith("HAMI_REVIEWER_TOKEN=")] + [f"HAMI_REVIEWER_TOKEN={token}"]
        env.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.environ["HAMI_REVIEWER_TOKEN"] = token
        settings.reviewer_token = token
        print("generated a reviewer token in .env (keep it private)")


def cmd_token(_args: argparse.Namespace) -> int:
    """Print the reviewer token (for the console login)."""
    if not settings.reviewer_token:
        print("no reviewer token configured (set HAMI_REVIEWER_TOKEN in .env)", file=sys.stderr)
        return 1
    print(settings.reviewer_token)
    return 0


def cmd_devserver(args: argparse.Namespace) -> int:
    """make run: .env + token, DB, a current model (trains on synthetic data if none), test sites, API."""
    import uvicorn

    from app.db import migrate
    from app.scoring.model_store import read_registry

    _ensure_env()
    settings.ensure_dirs()
    migrate()
    _seed()
    if not read_registry().get("current"):
        print("no current model: training one on the synthetic corpus (make train-synthetic)...")
        from ml.train import run_training

        run_training("synthetic")
    from app.testsites import start_in_thread

    start_in_thread(settings.testsite_port)
    print("")
    print(f"  Hami API          http://localhost:{args.port}   (health: /health, docs: /docs)")
    print(f"  Reviewer console  http://localhost:{args.port}/review   (token: python tasks.py token)")
    print(f"  Test sites        http://site-a.localhost:{settings.testsite_port}/  site-b, site-c, listing (automated tests only)")
    print(f"  Model             {read_registry().get('current')}")
    print("  Chrome extension  chrome://extensions -> Developer mode -> Load unpacked -> clients/extension/dist")
    print("")
    uvicorn.run("app.main:app", host=args.host, port=args.port, log_level="info")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hami")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate", help="create/upgrade the SQLite database").set_defaults(fn=cmd_migrate)
    sub.add_parser("token", help="print the reviewer token").set_defaults(fn=cmd_token)
    sub.add_parser("export-indicators", help="write data/seed/indicators.json from reviewed cases").set_defaults(
        fn=cmd_export_indicators)
    ts = sub.add_parser("testsites", help="serve the synthetic test sites (site-a/b/c.localhost, listing)")
    ts.add_argument("--port", type=int, default=None)
    ts.set_defaults(fn=cmd_testsites)
    dv = sub.add_parser("devserver", help="local development server (make run)")
    dv.add_argument("--host", default="127.0.0.1", help="0.0.0.0 to expose on the network")
    dv.add_argument("--port", type=int, default=8000)
    dv.set_defaults(fn=cmd_devserver)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
