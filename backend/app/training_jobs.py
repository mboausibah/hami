"""Background training jobs started from POST /train or the reviewer console."""
from __future__ import annotations

import threading
import traceback
import uuid
from typing import Any

from app.db import utcnow

_lock = threading.Lock()
JOBS: dict[str, dict[str, Any]] = {}


def start(kind: str = "full") -> dict[str, Any]:
    with _lock:
        running = [j for j in JOBS.values() if j["status"] == "running"]
        if running:
            return running[0]
        job = {"job_id": uuid.uuid4().hex[:12], "kind": kind, "status": "running", "started_at": utcnow(),
               "finished_at": None, "result": None, "error": None}
        JOBS[job["job_id"]] = job
    threading.Thread(target=_run, args=(job,), daemon=True).start()
    return job


def _run(job: dict[str, Any]) -> None:
    from ml.train import run_training

    try:
        job["result"] = run_training(job["kind"], quiet=True)
        job["status"] = "done"
    except SystemExit as e:
        job["status"], job["error"] = "failed", str(e)
    except Exception as e:  # report, never crash the API
        job["status"], job["error"] = "failed", f"{type(e).__name__}: {e}\n{traceback.format_exc()[-800:]}"
    job["finished_at"] = utcnow()


def get(job_id: str) -> dict[str, Any] | None:
    return JOBS.get(job_id)


def latest() -> dict[str, Any] | None:
    return max(JOBS.values(), key=lambda j: j["started_at"], default=None)
