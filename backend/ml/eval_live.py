"""make eval-live: run the full product (capture + rules + model) on approved live URLs and report
the result separately from the held-out test set.

Scam set: datasets/live_urls.csv (+ PhishTank sample if a feed file is present in public_datasets).
Legitimate control: legit_urls.csv sites whose kit is in the *held-out* split (never trained on).
Each row says whether its kit was seen in training, so seen-kit results are never mistaken for
generalization."""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone

from app.config import settings
from app.pipeline import ScanError, submit_scan
from app.scoring.model_store import read_registry
from app.urls import defang, ensure_scheme, hostname, registrable_domain
from ml import metrics as M
from ml.records import read_jsonl


def _csv(name: str) -> list[dict]:
    p = settings.private_dir / "datasets" / name
    if not p.is_file():
        return []
    with p.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _train_kits(version: str | None) -> set[str]:
    if not version:
        return set()
    meta = json.loads((settings.models_dir / version / "meta.json").read_text(encoding="utf-8"))
    recs = read_jsonl(settings.processed_dir / "datasets" / f"{meta['dataset_version']}.jsonl")
    train, _ = M.split([r for r in recs if r["label"] in ("fraudulent", "legitimate") and r.get("text")])
    return {r["kit_id"] for r in train}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gap", type=float, default=settings.bulk_capture_gap_s)
    ap.add_argument("--legit-controls", type=int, default=8)
    ap.add_argument("--phishtank", type=int, default=0, help="number of PhishTank URLs to sample (needs a feed file)")
    args = ap.parse_args(argv)
    version = read_registry().get("current")
    seen = _train_kits(version)
    items = [{"url": ensure_scheme(r["url"]), "expected": "fraudulent", "kit_id": r.get("kit_id", ""), "set": "live_urls"}
             for r in _csv("live_urls.csv") if r.get("url")]
    if args.phishtank:
        for f in (settings.private_dir / "public_datasets").glob("*phishtank*.csv"):
            with f.open(encoding="utf-8", errors="replace", newline="") as fh:
                for i, row in enumerate(csv.DictReader(fh)):
                    if i >= args.phishtank:
                        break
                    items.append({"url": row["url"], "expected": "fraudulent", "kit_id": "pub_phishtank", "set": "phishtank"})
    controls = 0
    for r in _csv("legit_urls.csv"):
        kit = f"legit_{registrable_domain(hostname(r['url']))}"
        if kit not in seen and controls < args.legit_controls:
            items.append({"url": ensure_scheme(r["url"]), "expected": "legitimate", "kit_id": kit, "set": "legit_control"})
            controls += 1
    if not items:
        raise SystemExit("no approved live URLs (data/private/datasets/live_urls.csv)")
    print(f"eval-live with model {version}: {len(items)} URLs (live captures, {args.gap:.0f}s apart)")
    rows = []
    for i, it in enumerate(items):
        if i:
            time.sleep(max(2.0, args.gap))
        try:
            p = submit_scan(it["url"], "manual", batch="live_eval", force=True)
        except ScanError as e:
            p = {"tier": "refused", "score": None, "capture_status": str(e), "duration_ms": None, "capture_mode": None}
        row = {**it, "tier": p["tier"], "score": p.get("score"), "capture": p.get("capture_status"),
               "capture_mode": p.get("capture_mode"), "duration_ms": p.get("duration_ms"),
               "kit_in_training": it["kit_id"] in seen, "scan_id": p.get("scan_id")}
        rows.append(row)
        print(f"  {it['set']:13s} {defang(it['url'])[:55]:55s} -> {str(p['tier']):22s} score={p.get('score')} "
              f"{'(kit seen in training)' if row['kit_in_training'] else ''}")
    scam = [r for r in rows if r["expected"] == "fraudulent"]
    legit = [r for r in rows if r["expected"] == "legitimate"]
    loaded = lambda rs: [r for r in rs if r["capture"] == "ok"]  # noqa: E731
    summary = {
        "model": version, "at": datetime.now(timezone.utc).isoformat(),
        "scam": {"n": len(scam), "loaded": len(loaded(scam)), "tiers": dict(Counter(r["tier"] for r in scam)),
                 "high_risk": sum(r["tier"] == "high_risk" for r in scam),
                 "caution_or_high": sum(r["tier"] in ("high_risk", "caution") for r in scam),
                 "unseen_kits": sum(not r["kit_in_training"] for r in scam)},
        "legit_control": {"n": len(legit), "loaded": len(loaded(legit)), "tiers": dict(Counter(r["tier"] for r in legit)),
                          "flagged_high": sum(r["tier"] == "high_risk" for r in legit),
                          "flagged_caution_or_high": sum(r["tier"] in ("high_risk", "caution") for r in legit)},
        "median_scan_ms": sorted(r["duration_ms"] for r in rows if r["duration_ms"])[len(rows) // 2] if rows else None,
        "rows": rows,
    }
    out = settings.processed_dir / f"eval_live_{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    s, l = summary["scam"], summary["legit_control"]
    print(f"\nLIVE (reported separately from the held-out test set):")
    print(f"  scam URLs: {s['n']} ({s['loaded']} loaded) -> High risk {s['high_risk']}, Caution or High {s['caution_or_high']};"
          f" tiers {s['tiers']}; kits unseen in training: {s['unseen_kits']}")
    print(f"  legit controls (held-out kits): {l['n']} ({l['loaded']} loaded) -> flagged High {l['flagged_high']}, "
          f"Caution or High {l['flagged_caution_or_high']}; tiers {l['tiers']}")
    print(f"  median scan time {summary['median_scan_ms']} ms; report -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
