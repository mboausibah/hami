"""make tier-check: system-level tiers (rules + kits + model) on stored real captures, without visiting sites.

Re-analyzes every stored legitimate capture (legit_urls) and every stored scam capture / session kit of a
reviewer- or labels.csv-confirmed fraudulent site, on a temporary COPY of the database, and reports how many
legitimate pages get Caution/High (false alarms) and how many scam pages get Caution/High. Kits of the
same family stay linked through the real reviews, so seen-family results are reported separately.

    python -m ml.tier_check [--show]
"""
from __future__ import annotations

import argparse
import collections
import os
import shutil
import sys
import tempfile
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true", help="list every flagged legitimate page")
    ap.add_argument("--model", default=None, help="evaluate this model version instead of the current one")
    args = ap.parse_args(argv)
    if args.model:
        os.environ["HAMI_MODEL_VERSION"] = args.model
    from app.config import settings

    tmp = Path(tempfile.mkdtemp(prefix="hami-tiercheck-")) / "copy.sqlite3"
    shutil.copy(settings.db_path, tmp)
    os.environ["HAMI_DB_PATH"] = str(tmp)
    from app import db as dbmod

    dbmod.reset_init_cache()
    from app.cases import reviewed_fraud_scans
    from app.pipeline import reanalyze_stored
    from app.urls import registrable_domain

    with dbmod.db() as conn:
        legit = [r[0] for r in conn.execute("SELECT scan_id FROM scans WHERE batch='legit_urls' AND status='done' "
                                            "AND capture_status='ok'")]
        fraud_sites = {registrable_domain(s["host"]) for s in reviewed_fraud_scans(conn)}
        scam = [(r[0], r[1]) for r in conn.execute(
            "SELECT MAX(scan_id), host FROM scans WHERE batch IN ('labels','sessions','har_candidates','live_eval') "
            "AND status='done' AND capture_status='ok' GROUP BY host")]
    scam = [(sid, h) for sid, h in scam if registrable_domain(h) in fraud_sites or h in ("betnala.com", "betfugu.com")]
    out = {}
    for name, ids in (("legitimate", [(s, None) for s in legit]), ("scam (confirmed families + kit02 candidates)", scam)):
        tiers = collections.Counter()
        flagged = []
        for sid, _h in ids:
            p = reanalyze_stored(sid, source_type="import")
            tiers[p["tier"]] += 1
            if name == "legitimate" and p["tier"] in ("high_risk", "caution"):
                flagged.append((p["host"], p["tier"], p["rules_fired"]))
            if name != "legitimate" and args.show:
                print(f"   {p['host']:32s} {p['tier']:22s} {p['rules_fired']}")
        out[name] = tiers
        n = sum(tiers.values())
        alarm = tiers["high_risk"] + tiers["caution"]
        print(f"{name}: {n} pages -> {dict(tiers)}; Caution or High {alarm}/{n}")
        if args.show:
            for f in flagged:
                print("   ", f)
    shutil.rmtree(tmp.parent, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
