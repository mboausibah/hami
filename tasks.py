#!/usr/bin/env python3
"""Hami task runner - works the same on Windows, macOS and Linux (no make needed).

    python tasks.py run                 API + reviewer console on http://localhost:8000, synthetic test sites
    python tasks.py check               backend tests + e2e checks + extension type-check/lint/build + extension checks
    python tasks.py extension           build the Chrome extension -> clients/extension/dist + hami-extension.zip
    python tasks.py import              private + sessions + public + synthetic data -> data/processed (needs data/private)
    python tasks.py train               dataset version + candidate model + metrics + promotion rule
    python tasks.py train-synthetic     same, synthetic data only (no private data needed)
    python tasks.py help                all tasks

The first run creates .venv, installs backend/requirements-dev.txt and Playwright Chromium. Requires Python 3.11+.
Extra arguments after the task name are passed through, e.g. `python tasks.py promote m2026... --reason "..."`.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
CLIENTS = ROOT / "clients"
VENV = ROOT / ".venv"
VPY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
MARKER = VENV / ".deps"
REQS = [BACKEND / "requirements.txt", BACKEND / "requirements-dev.txt"]


def say(msg: str) -> None:
    print(f"[hami] {msg}", flush=True)


def env() -> dict[str, str]:
    e = dict(os.environ)
    e["PYTHONUTF8"] = "1"
    e.setdefault("PYTHONIOENCODING", "utf-8")
    return e


def sh(cmd: list[str], cwd: Path = ROOT, check: bool = True, extra_env: dict[str, str] | None = None) -> int:
    e = env()
    e.update(extra_env or {})
    rc = subprocess.call(cmd, cwd=str(cwd), env=e)
    if check and rc != 0:
        say(f"failed ({rc}): {' '.join(cmd)}")
        sys.exit(rc)
    return rc


def deps() -> None:
    if sys.version_info < (3, 11):
        sys.exit("Python 3.11 or newer is required")
    if not VPY.exists():
        say("creating .venv")
        venv.EnvBuilder(with_pip=True).create(VENV)
    newest = max(p.stat().st_mtime for p in REQS)
    if not MARKER.exists() or MARKER.stat().st_mtime < newest:
        say("installing backend dependencies")
        sh([str(VPY), "-m", "pip", "install", "-r", str(BACKEND / "requirements-dev.txt")])
        say("installing Playwright Chromium (capture browser)")
        sh([str(VPY), "-m", "playwright", "install", "chromium"])
        MARKER.write_text("ok\n", encoding="utf-8")


def py(*args: str, cwd: Path = BACKEND, check: bool = True, extra_env: dict[str, str] | None = None) -> int:
    deps()
    return sh([str(VPY), *args], cwd=cwd, check=check, extra_env=extra_env)


def npm(*args: str) -> None:
    exe = shutil.which("npm")
    if not exe:
        sys.exit("Node.js 20+ (npm) is needed to build the extension: https://nodejs.org")
    sh([exe, *args], cwd=CLIENTS)


# ---- tasks ---------------------------------------------------------------------------------------------------
def t_run(a: list[str]) -> None:
    """start API (http://localhost:8000) + reviewer console + synthetic test sites"""
    py("-m", "app.cli", "devserver", *a)


def t_api(a: list[str]) -> None:
    """API only (no test sites)"""
    py("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", *a)


def t_token(_a: list[str]) -> None:
    """print the reviewer-console token (Docker: docker compose exec api python -m app.cli token)"""
    py("-m", "app.cli", "token")


def t_export_indicators(_a: list[str]) -> None:
    """write data/seed/indicators.json from reviewer-confirmed cases (indicators only, no page content)"""
    py("-m", "app.cli", "export-indicators")


def t_migrate_to_postgres(a: list[str]) -> None:
    """copy the SQLite DB into PostgreSQL and verify counts: migrate-to-postgres [--to URL] [--sqlite PATH]"""
    py("-m", "app.db.transfer", *a)


def t_migrate(a: list[str]) -> None:
    """create / upgrade the database (DATABASE_URL or SQLite)"""
    py("-m", "app.cli", "migrate", *a)


def t_testsites(a: list[str]) -> None:
    """serve the synthetic test sites only"""
    py("-m", "app.cli", "testsites", *a)


def t_corpus(a: list[str]) -> None:
    """regenerate the synthetic training corpus"""
    py(str(ROOT / "testsites/generator/generate.py"), *a, cwd=ROOT)


def t_import(a: list[str]) -> None:
    """private + sessions + public + synthetic data -> data/processed/records.jsonl (needs data/private)"""
    py("-m", "ml.import_sessions", *a)
    py("-m", "ml.import_private", *a)


def t_import_sessions(a: list[str]) -> None:
    """import data/private/sessions only (strict sanitizer)"""
    py("-m", "ml.import_sessions", *a)


def t_train(a: list[str]) -> None:
    """dataset version + candidate model + held-out metrics + kit-grouped CV + promotion rule"""
    py("-m", "ml.train", "--kind", "full", *a)


def t_train_synthetic(a: list[str]) -> None:
    """same as train, synthetic data only (no private data needed)"""
    py("-m", "ml.train", "--kind", "synthetic", *a)


def t_eval(a: list[str]) -> None:
    """re-run the held-out evaluation of the current model"""
    py("-m", "ml.evaluate", *a)


def t_eval_live(a: list[str]) -> None:
    """evaluate on approved live scam URLs (seen-kit vs unseen-kit)"""
    py("-m", "ml.eval_live", *a)


def t_eval_holdout(a: list[str]) -> None:
    """false-alarm rate on legitimate pages not in training (captures public homepages)"""
    py("-m", "ml.eval_holdout", *a)


def t_tier_check(a: list[str]) -> None:
    """system-level tiers on a copy of the database"""
    py("-m", "ml.tier_check", "--show", *a)


def t_promote(a: list[str]) -> None:
    """manual promotion: promote VERSION --reason "..." --reviewer NAME"""
    py("-m", "ml.promote", *a)


def t_capture_labels(a: list[str]) -> None:
    """capture labeled URLs from data/private/datasets/labels.csv (safe pipeline)"""
    py("-m", "ml.capture_lists", "labels", "--yes", *a)


def t_capture_legit(a: list[str]) -> None:
    """capture data/private/datasets/legit_urls.csv (homepage + up to 3 nav pages, rate-limited)"""
    py("-m", "ml.capture_lists", "legit", "--yes", *a)


def t_capture_har_candidates(a: list[str]) -> None:
    """capture approved review candidates referenced inside private HAR files"""
    py("-m", "ml.capture_lists", "har-candidates", "--yes", *a)


def t_capture_live(a: list[str]) -> None:
    """capture data/private/datasets/live_urls.csv"""
    py("-m", "ml.capture_lists", "live", "--yes", *a)


def t_discovery(a: list[str]) -> None:
    """certificate-transparency discovery worker (loop, rate-limited)"""
    py("-m", "app.discovery.worker", *a)


def t_static_check(a: list[str]) -> None:
    """scan authorized files for suspected secrets (values never stored)"""
    py("-m", "app.static_check", *a)


def t_test(a: list[str]) -> None:
    """backend tests"""
    py("-m", "pytest", "-q", "tests", *a)


def t_test_postgres(a: list[str]) -> None:
    """backend tests against PostgreSQL: test-postgres postgresql+psycopg://user:pw@host:5432/empty_db"""
    if not a:
        sys.exit("usage: python tasks.py test-postgres postgresql+psycopg://user:pw@host:5432/empty_db")
    py("-m", "pytest", "-q", "tests", *a[1:], extra_env={"DATABASE_URL": a[0]})


def t_e2e(a: list[str]) -> None:
    """end-to-end checks against a local API with the synthetic test sites"""
    py(str(ROOT / "scripts/e2e_check.py"), *(a or ["--start-local"]), cwd=ROOT)


def t_clients(_a: list[str]) -> None:
    """npm install for the TypeScript clients"""
    npm("install", "--no-audit", "--no-fund")


def t_extension(_a: list[str]) -> None:
    """build the Chrome extension -> clients/extension/dist + clients/extension/hami-extension.zip"""
    t_clients([])
    py(str(ROOT / "scripts/make_icons.py"), cwd=ROOT)
    npm("run", "build", "-w", "@hami/extension")


def t_check(_a: list[str]) -> None:
    """backend tests + e2e + extension build, type-check, lint + extension checks in Chromium"""
    t_test([])
    t_e2e([])
    t_extension([])
    npm("run", "typecheck")
    npm("run", "lint")
    py(str(ROOT / "scripts/extension_check.py"), cwd=ROOT)
    say("check passed")


def t_docker_up(a: list[str]) -> None:
    """docker compose up -d --build"""
    sh(["docker", "compose", "up", "-d", "--build", *a])


def t_docker_down(a: list[str]) -> None:
    """docker compose down"""
    sh(["docker", "compose", "down", *a])


TASKS = {name[2:].replace("_", "-"): fn for name, fn in sorted(globals().items()) if name.startswith("t_")}


def t_help(_a: list[str]) -> None:
    print(__doc__.split("\n\n")[0])
    for name, fn in TASKS.items():
        print(f"  {name:<24} {(fn.__doc__ or '').strip()}")


TASKS["help"] = t_help


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in TASKS:
        t_help([])
        sys.exit(0 if len(sys.argv) < 2 else 2)
    TASKS[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    main()
