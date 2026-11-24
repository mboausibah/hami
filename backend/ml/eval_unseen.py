"""Honest unseen-scam evaluation: brand-new scam sites from families Hami has never seen.

    python tasks.py eval-unseen [--rescore]

Reads data/private/datasets/unseen_scams.csv (private, never committed, NEVER used for training: the importer does
not read batch 'unseen_scams' and no review is created). Each URL is captured with the normal safe pipeline (no
sign-in, no forms) and scored exactly as a user's check from the server would be - without the page structure the
extension adds from the user's own browser. Reports how many were flagged (High or Caution) next to the legitimate
hold-out false-alarm numbers. Report: data/processed/unseen_report.json.
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter

from app.config import settings
from app.db import db
from app.pipeline import ScanError, reanalyze_stored, submit_scan

BATCH = "unseen_scams"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rescore", action="store_true", help="re-score earlier captures instead of visiting again")
    ap.add_argument("--gap", type=float, default=6.0)
    args = ap.parse_args(argv)
    path = settings.private_dir / "datasets" / "unseen_scams.csv"
    if not path.is_file():
        raise SystemExit(f"{path} not found (one URL per row, column 'url')")
    urls = [r["url"].strip() for r in csv.DictReader(path.open(encoding="utf-8-sig")) if (r.get("url") or "").strip()]
    with db() as conn:
        stored = {r["submitted_url"]: r["sid"] for r in conn.execute(
            "SELECT MAX(scan_id) AS sid, submitted_url FROM scans WHERE batch=? GROUP BY submitted_url", (BATCH,))}
    rows = []
    for url in urls:
        try:
            if args.rescore and url in stored:
                p = reanalyze_stored(stored[url])
            else:
                p = submit_scan(url, "manual", batch=BATCH, force=True)
                time.sleep(args.gap)
        except ScanError as e:
            rows.append({"url": url, "tier": None, "error": str(e)})
            continue
        rows.append({"url": url, "tier": p["tier"], "capture_status": p["capture_status"], "rules_fired": p["rules_fired"],
                     "clues": [c["text"]["en"] for c in p.get("clues", [])]})
        print(f"  {p['tier']:<22} {p['capture_status']:<10} {url[:90]}")
        for c in p.get("clues", []):
            print(f"      - {c['text']['en']}")
    tiers = Counter(r["tier"] for r in rows if r["tier"])
    flagged = tiers["high_risk"] + tiers["caution"]
    report = {"sites": len(rows), "flagged_high_or_caution": flagged, "high_risk": tiers["high_risk"],
              "caution": tiers["caution"], "tiers": dict(tiers), "evidence": "server-side capture only (no page structure "
              "from a user's browser)", "rows": rows}
    out = settings.processed_dir / "unseen_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n{flagged} of {len(rows)} brand-new scam sites flagged (High {tiers['high_risk']}, Caution {tiers['caution']})"
          f" from the server alone. Report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
