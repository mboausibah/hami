"""False-alarm rate on legitimate pages that were NOT in training.

    python -m ml.eval_holdout [--target 50] [--gap 6] [--rescore]

Reads ml/holdout_legit_urls.csv (UAE job boards, shops, gig and micro-task platforms). Drops every site whose
registrable domain appears anywhere in the training records (pages, URL-only rows, hostnames inside pages),
in the legit_urls captures or in any review. Captures the homepage of the rest with the normal safe pipeline
(no sign-in, no forms), rate-limited, into batch 'holdout_legit', which the importer never reads, until
--target pages were captured successfully. --rescore re-scores the stored captures with the current model
instead of visiting the sites again.

A false alarm is a legitimate page rated High risk (the tier that shows a full-page warning). Caution is
reported separately. Pages that could not be captured (blocked, timeouts, insufficient_evidence) are counted
but excluded from the rate. Report: data/processed/holdout_report.json.
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter
from pathlib import Path

from app.config import settings
from app.db import db
from app.pipeline import ScanError, reanalyze_stored, submit_scan
from app.urls import hostname, registrable_domain

HERE = Path(__file__).parent
LIST = HERE / "holdout_legit_urls.csv"
INSUFFICIENT = "insufficient_evidence"
WELL_KNOWN = HERE.parents[1] / "clients/extension/src/data/well_known.json"


def training_domains() -> set[str]:
    out: set[str] = set()
    rec = settings.processed_dir / "records.jsonl"
    if rec.is_file():
        with rec.open(encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                for h in [hostname(r.get("url") or "")] + list(r.get("hostnames") or []):
                    if h:
                        out.add(registrable_domain(h))
    with db() as conn:
        for (h,) in conn.execute("SELECT DISTINCT host FROM scans WHERE batch IN ('legit_urls', 'labels', 'sessions')"):
            out.add(registrable_domain(h))
        for (h,) in conn.execute("SELECT DISTINCT s.host FROM reviews r JOIN scans s ON s.scan_id = r.scan_id"):
            out.add(registrable_domain(h))
    out.discard("")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=50)
    ap.add_argument("--gap", type=float, default=6.0, help="seconds between captures")
    ap.add_argument("--rescore", action="store_true")
    ap.add_argument("--list", default=str(LIST), help="CSV with category,url")
    ap.add_argument("--batch", default="holdout_legit", help="scan batch name (never read by the importer)")
    ap.add_argument("--keep-trained", action="store_true",
                    help="keep sites whose domain appears in training (reported per row) instead of dropping them")
    ap.add_argument("--report", default="holdout_report.json")
    args = ap.parse_args(argv)

    rows = list(csv.DictReader(Path(args.list).open(encoding="utf-8")))
    seen = training_domains()
    well_known = set(json.loads(WELL_KNOWN.read_text(encoding="utf-8"))["domains"]) if WELL_KNOWN.is_file() else set()
    trained = {r["url"] for r in rows if registrable_domain(hostname(r["url"])) in seen}
    excluded = [] if args.keep_trained else sorted(trained)
    todo = [r for r in rows if r["url"] not in excluded]
    print(f"{len(rows)} candidates, {len(excluded)} excluded (domain already in training), {len(todo)} eligible")

    results = []
    if args.rescore:
        with db() as conn:
            stored = conn.execute("SELECT MAX(scan_id) AS sid, submitted_url FROM scans WHERE batch=?"
                                  " GROUP BY submitted_url", (args.batch,)).fetchall()
        cat = {r["url"]: r["category"] for r in rows}
        for s in stored:
            if s["submitted_url"] in excluded:
                continue
            p = reanalyze_stored(s["sid"])
            results.append((cat.get(s["submitted_url"], "?"), s["submitted_url"], p))
    else:
        # Reuse earlier captures of this hold-out set (re-scored with the current model); visit only new sites.
        with db() as conn:
            stored = {r["submitted_url"]: r["sid"] for r in conn.execute(
                "SELECT MAX(scan_id) AS sid, submitted_url FROM scans WHERE batch=? GROUP BY submitted_url",
                (args.batch,))}
        ok = 0
        for r in todo:
            if ok >= args.target:
                break
            if r["url"] in stored:
                p = reanalyze_stored(stored[r["url"]])
                results.append((r["category"], r["url"], p))
                ok += p["capture_status"] == "ok" and p["tier"] != INSUFFICIENT
                continue
            try:
                p = submit_scan(r["url"], "manual", batch=args.batch, force=True)
            except ScanError as e:
                print(f"  refused {r['url']}: {e}")
                continue
            results.append((r["category"], r["url"], p))
            good = p["capture_status"] == "ok" and p["tier"] != INSUFFICIENT
            ok += good
            print(f"  [{ok:>2}] {r['category']:<9} {p['tier'] or '-':<18} {p['capture_status']:<10} {r['url']}")
            time.sleep(args.gap)

    # Pages that loaded: every tier counts (Insufficient evidence is the honest answer for many sign-up walls).
    loaded = [(c, u, p) for c, u, p in results if p["capture_status"] == "ok"]
    evaluated = [(c, u, p) for c, u, p in loaded if p["tier"] != INSUFFICIENT]
    failed = [(c, u, p["capture_status"], p["tier"]) for c, u, p in results if p["capture_status"] != "ok"]
    tiers = Counter(p["tier"] for _, _, p in evaluated)
    n = len(evaluated)
    by_cat: dict[str, Counter] = {}
    for c, _, p in evaluated:
        by_cat.setdefault(c, Counter())[p["tier"]] += 1
    flagged = [{"category": c, "url": u, "tier": p["tier"], "rules_fired": p["rules_fired"], "score": p.get("score"),
                "clues": [cl["text"]["en"] for cl in p.get("clues", [])][:4],
                "skipped_by_extension": registrable_domain(hostname(u)) in well_known}
               for c, u, p in evaluated if p["tier"] in ("high_risk", "caution")]
    loaded_tiers = Counter(p["tier"] for _, _, p in loaded)
    rows_out = [{"category": c, "url": u, "tier": p["tier"], "capture_status": p["capture_status"],
                 "rules_fired": p["rules_fired"], "domain_in_training": u in trained} for c, u, p in results]
    report = {
        "list": Path(args.list).name, "batch": args.batch,
        "loaded_pages": len(loaded), "loaded_tiers": dict(loaded_tiers),
        "high_on_loaded": loaded_tiers["high_risk"], "caution_on_loaded": loaded_tiers["caution"],
        "rows": rows_out,
        "model_version": evaluated[0][2].get("model_version") if evaluated else None,
        "evaluated_pages": n, "capture_failed_or_insufficient": len(failed),
        "excluded_in_training": len(excluded), "tiers": dict(tiers), "by_category": {k: dict(v) for k, v in by_cat.items()},
        "false_alarm_rate_high": round(tiers["high_risk"] / n, 4) if n else None,
        "caution_or_high_rate": round((tiers["high_risk"] + tiers["caution"]) / n, 4) if n else None,
        "flagged": flagged, "failed": [{"category": c, "url": u, "capture_status": s, "tier": t} for c, u, s, t in failed],
        "in_extension_skip_list": sum(registrable_domain(hostname(u)) in well_known for _, u, _ in evaluated),
    }
    out = settings.processed_dir / args.report
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("failed", "rows")}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
