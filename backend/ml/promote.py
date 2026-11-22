"""Explicit reviewer promotion of a candidate model (the documented override of the automatic promotion rule).

The automatic rule (recall must not drop AND legitimate-page FPR must not rise on the same held-out set) can
never replace a current model that almost never flags anything. A reviewer may promote a candidate explicitly;
the decision, its reason and both models' held-out metrics are recorded in model_versions.promotion_json and
backend/models/registry.json, and the previous model is retired (restorable the same way).

    python -m ml.promote <version> --reason "..." [--reviewer NAME]
"""
from __future__ import annotations

import argparse
import json
import sys

from app.config import settings
from app.db import db, tx, utcnow
from app.scoring.model_store import invalidate, read_registry, write_registry


def promote(version: str, reason: str, reviewer: str) -> dict:
    mdir = settings.models_dir / version
    if not (mdir / "model.joblib").is_file():
        raise SystemExit(f"unknown model version {version}")
    if len(reason.strip()) < 15:
        raise SystemExit("give a real reason (at least 15 characters)")
    reg = read_registry()
    previous = reg.get("current")
    meta = json.loads((mdir / "meta.json").read_text(encoding="utf-8"))
    decision = {"manual": True, "reviewer": reviewer, "reason": reason, "at": utcnow(), "previous": previous,
                "automatic_rule": meta.get("promotion")}
    with db() as conn, tx(conn):
        conn.execute("UPDATE model_versions SET status='retired', retired_at=? WHERE status='current'", (utcnow(),))
        cur = conn.execute("UPDATE model_versions SET status='current', promoted_at=?, promotion_json=? WHERE version=?",
                           (utcnow(), json.dumps(decision), version))
        if cur.rowcount == 0:
            raise SystemExit(f"{version} is not recorded in model_versions")
    for v in reg.get("versions", []):
        if v["version"] == previous:
            v["status"] = "retired"
        if v["version"] == version:
            v["status"] = "current"
            v["manual_promotion"] = {"reviewer": reviewer, "reason": reason, "at": decision["at"]}
    reg["current"] = version
    write_registry(reg)
    meta["manual_promotion"] = decision
    (mdir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    invalidate()
    return decision


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("version")
    ap.add_argument("--reason", required=True)
    ap.add_argument("--reviewer", default="reviewer")
    args = ap.parse_args(argv)
    d = promote(args.version, args.reason, args.reviewer)
    print(f"promoted {args.version} (previous: {d['previous']}) by {d['reviewer']}: {d['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
