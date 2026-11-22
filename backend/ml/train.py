"""make train / make train-synthetic

1. Build a dataset version: private + public + synthetic records (data/processed/records.jsonl) plus
   reviewer-labelled, training-eligible scans from the evidence log (inconclusive never trains).
2. Kit-grouped, version-stable train/test split.
3. Train a candidate (calibrated LR on TF-IDF word+char n-grams + structured indicators).
4. Held-out metrics: precision, recall, FPR on legitimate pages, PR-AUC, per language / source /
   scam type / behavior tag; baselines URL-only and URL+text on the same URL-bearing examples.
5. Promotion rule: the candidate replaces the current model only if, on the same held-out set,
   recall does not drop and the false-positive rate on legitimate pages does not rise.
6. Save backend/models/<version>/ (model, metrics.json, meta.json with dataset hash + settings).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings
from app.db import db, tx, utcnow
from app.scoring.model_store import invalidate, read_registry, write_registry
from app.urls import registrable_domain
from ml import metrics as M
from ml.baselines import UrlModel
from ml.model import DEFAULT_SETTINGS, HamiModel
from ml.records import dataset_hash, read_jsonl, scan_record_parts, write_jsonl


# ---- dataset ------------------------------------------------------------------------------------
def reviewed_records(conn) -> list[dict[str, Any]]:  # noqa: ANN001
    """Effective (newest) review per scan, training-eligible, fraudulent/legitimate only."""
    rows = conn.execute(
        """SELECT r.* FROM reviews r
           JOIN (SELECT scan_id, MAX(review_id) rid FROM reviews GROUP BY scan_id) l ON l.rid=r.review_id
           WHERE r.training_eligible=1 AND r.label IN ('fraudulent','legitimate')""").fetchall()
    out = []
    clusters = _cluster_map(conn)
    for r in rows:
        parts = scan_record_parts(conn, r["scan_id"])
        if parts is None or not parts["text"]:
            continue
        host = parts["scan"]["host"]
        kit = clusters.get(r["scan_id"]) or f"reviewed_{registrable_domain(host)}"
        out.append({
            "id": f"reviewed:scan:{r['scan_id']}", "source": "reviewed", "kit_id": kit, "lang": parts["lang"],
            "label": r["label"], "scam_type": r["scam_type"] or "", "behavior_tags": json.loads(r["behavior_tags"] or "[]"),
            "text": parts["text"], "features": parts["features"], "url": parts["scan"]["normalized_url"],
            "html_path": parts["html_path"], "hostnames": parts["hostnames"], "origin": "reviewed_scan",
            "fingerprint": parts["fingerprint"], "scan_id": r["scan_id"], "review_id": r["review_id"],
        })
    return out


def _cluster_map(conn) -> dict[int, str]:  # noqa: ANN001
    """scan_id -> 'cluster_<min scan id>' for reviewer-approved link clusters (keeps rebrands in one split)."""
    from app.linking.clusters import clusters_for_all

    out = {}
    for cid, scan_ids in clusters_for_all(conn).items():
        for s in scan_ids:
            out[s] = f"cluster_{cid}"
    return out


def build_dataset(kind: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if kind == "synthetic":
        from ml.import_private import import_synthetic

        rep: dict[str, Any] = {}
        records = import_synthetic(rep)
    else:
        path = settings.processed_dir / "records.jsonl"
        records = read_jsonl(path)
        if not records:
            raise SystemExit(f"{path} is missing or empty - run `make import` first (or `make train-synthetic`).")
        with db() as conn:
            reviewed = reviewed_records(conn)
        # A reviewer label wins over an imported label for the same capture.
        reviewed_scans = {r["scan_id"] for r in reviewed}
        records = [r for r in records if r.get("scan_id") not in reviewed_scans] + reviewed
    info = {"kind": kind, "counts": dict(Counter(r["label"] for r in records)),
            "sources": dict(Counter(r["source"] for r in records))}
    return records, info


def trainable(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in records if r["label"] in ("fraudulent", "legitimate") and r.get("text")]


# ---- training -----------------------------------------------------------------------------------
def y_of(recs: list[dict[str, Any]]) -> list[int]:
    return [1 if r["label"] == "fraudulent" else 0 for r in recs]


def run_training(kind: str = "full", quiet: bool = False) -> dict[str, Any]:
    t0 = time.monotonic()
    settings.ensure_dirs()
    all_records, info = build_dataset(kind)
    records = trainable(all_records)
    train, test = M.split(records)
    if len({r["label"] for r in train}) < 2 or len({r["label"] for r in test}) < 2:
        raise SystemExit("not enough labelled data: both classes are needed in train and test splits")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    ds_hash = dataset_hash(records)
    ds_version = f"ds-{stamp}-{kind}"
    snap = settings.processed_dir / "datasets" / f"{ds_version}.jsonl"
    write_jsonl(snap, all_records)

    model = HamiModel(dict(DEFAULT_SETTINGS))
    model.fit([r["text"] for r in train], [r["features"] for r in train], y_of(train))
    scores = list(model.predict_proba([r["text"] for r in test], [r["features"] for r in test]))
    report = M.full_report(test, scores, model.settings)

    # Baselines on the same held-out examples that have a real URL.
    test_kits = {r["kit_id"] for r in test}
    url_train = [r for r in all_records if r.get("url") and r["label"] in ("fraudulent", "legitimate")
                 and r["kit_id"] not in test_kits]
    url_test = [r for r in test if r.get("url")]
    baselines: dict[str, Any] = {"n_test_with_url": len(url_test)}
    if len({r["label"] for r in url_train}) == 2 and len({r["label"] for r in url_test}) == 2:
        thr = model.settings["threshold_agree"]
        u = UrlModel(False).fit(url_train)
        baselines["url_only"] = M.binary_metrics(y_of(url_test), u.predict_proba(url_test), thr)
        ut_train = [r for r in url_train if r.get("text")]
        if len({r["label"] for r in ut_train}) == 2:
            ut = UrlModel(True).fit(ut_train)
            baselines["url_plus_text"] = M.binary_metrics(y_of(url_test), ut.predict_proba(url_test), thr)
        full_s = list(model.predict_proba([r["text"] for r in url_test], [r["features"] for r in url_test]))
        baselines["full_model"] = M.binary_metrics(y_of(url_test), full_s, thr)
    else:
        baselines["note"] = ("not enough URL-bearing records with both labels in train and test; capture the approved "
                             "URL lists / public datasets to enable URL baselines")

    # Promotion rule against the current model, on the same held-out set.
    reg = read_registry()
    current = reg.get("current")
    decision: dict[str, Any] = {"current": current, "candidate_metrics": report["overall"]}
    if current and (settings.models_dir / current / "model.joblib").is_file():
        cur_model = HamiModel.load(settings.models_dir / current)
        cur_scores = list(cur_model.predict_proba([r["text"] for r in test], [r["features"] for r in test]))
        cur = M.binary_metrics(y_of(test), cur_scores, cur_model.settings["threshold_agree"])
        cand = report["overall"]
        recall_ok = (cand["recall"] or 0) >= (cur["recall"] or 0)
        fpr_ok = (cand["fpr_legit"] or 0) <= (cur["fpr_legit"] or 0)
        decision.update({"current_metrics": cur, "recall_not_lower": recall_ok, "fpr_not_higher": fpr_ok,
                         "promoted": recall_ok and fpr_ok})
    else:
        decision.update({"promoted": True, "reason": "no current model"})

    version = f"m{stamp}-{kind}"
    out_dir = settings.models_dir / version
    model.save(out_dir)
    metrics = {"held_out": report, "baselines": baselines, "split": {
        "train": len(train), "test": len(test), "train_kits": len({r["kit_id"] for r in train}),
        "test_kits": sorted({r["kit_id"] for r in test})}, "calibrated": model.calibrated}
    meta = {"version": version, "kind": kind, "created_at": utcnow(), "dataset_version": ds_version,
            "dataset_hash": ds_hash, "dataset_info": info, "feature_settings": model.settings,
            "promotion": decision, "top_phrases": model.top_global_phrases(20),
            "train_seconds": round(time.monotonic() - t0, 1)}
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    status = "current" if decision["promoted"] else "candidate"
    with db() as conn, tx(conn):
        conn.execute("INSERT INTO dataset_versions (version, created_at, kind, record_count, label_counts, sources, "
                     "dataset_hash, snapshot_path) VALUES (?,?,?,?,?,?,?,?)",
                     (ds_version, utcnow(), kind, len(all_records), json.dumps(info["counts"]),
                      json.dumps(info["sources"]), ds_hash, str(snap)))
        if decision["promoted"]:
            conn.execute("UPDATE model_versions SET status='retired', retired_at=? WHERE status='current'", (utcnow(),))
        conn.execute("INSERT INTO model_versions (version, created_at, status, dataset_version, dataset_hash, "
                     "metrics_json, feature_settings, promotion_json, path, promoted_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (version, utcnow(), status, ds_version, ds_hash, json.dumps(metrics, ensure_ascii=False),
                      json.dumps(model.settings), json.dumps(decision), str(out_dir),
                      utcnow() if decision["promoted"] else None))
    versions = reg.get("versions", [])
    versions.append({"version": version, "status": status, "dataset_hash": ds_hash, "created_at": meta["created_at"]})
    if decision["promoted"]:
        for v in versions:
            if v["version"] == current:
                v["status"] = "retired"
        reg["current"] = version
    reg["versions"] = versions
    write_registry(reg)
    invalidate()
    result = {"version": version, "status": status, "dataset_version": ds_version, "dataset_hash": ds_hash,
              "metrics": metrics, "promotion": decision}
    if not quiet:
        print_result(result)
    return result


def _fmt(m: dict[str, Any] | None) -> str:
    if not m:
        return "-"
    f = lambda v: "n/a" if v is None else f"{v:.3f}"  # noqa: E731
    return (f"P {f(m.get('precision'))}  R {f(m.get('recall'))}  FPR(legit) {f(m.get('fpr_legit'))}  "
            f"PR-AUC {f(m.get('pr_auc'))}  (n={m.get('n')}, fraud={m.get('n_fraudulent')})")


def print_result(res: dict[str, Any]) -> None:
    m = res["metrics"]
    h = m["held_out"]
    print(f"\n=== candidate {res['version']} | dataset {res['dataset_version']} (hash {res['dataset_hash'][:12]}) ===")
    sp = m["split"]
    print(f"split: train {sp['train']} records / {sp['train_kits']} kits; test {sp['test']} records / "
          f"{len(sp['test_kits'])} kits (kit-grouped, stable)")
    print(f"held-out overall      {_fmt(h['overall'])}")
    print(f"High-risk rule        {_fmt(h['tier_high_risk_rule'])}")
    print(f"Caution or above      {_fmt(h['caution_or_above'])}")
    for title, key in (("per language", "per_language"), ("per source", "per_source")):
        print(f"{title}:")
        for k, v in h[key].items():
            print(f"  {k:14s} {_fmt(v)}")
    print("per scam type (recall on held-out fraudulent pages):")
    for k, v in h["per_scam_type"].items():
        print(f"  {k:18s} recall {v['recall']}  (n={v['n']})")
    print("per behavior tag (recall):")
    for k, v in h["per_behavior_tag"].items():
        print(f"  {k:22s} recall {v['recall']}  (n={v['n']})")
    b = m["baselines"]
    print(f"baselines on the same URL-bearing held-out examples (n={b.get('n_test_with_url')}):")
    if "note" in b:
        print(f"  {b['note']}")
    for k in ("url_only", "url_plus_text", "full_model"):
        if k in b:
            print(f"  {k:14s} {_fmt(b[k])}")
    p = res["promotion"]
    if p.get("current_metrics"):
        print(f"current {p['current']}: {_fmt(p['current_metrics'])}")
        print(f"promotion rule: recall not lower={p['recall_not_lower']}, FPR not higher={p['fpr_not_higher']}"
              f" -> {'PROMOTED' if p['promoted'] else 'kept as candidate'}")
    else:
        print(f"promotion rule: {p.get('reason')} -> PROMOTED")
    print(f"saved backend/models/{res['version']}/ ({res['status']})")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["full", "synthetic"], default="full")
    args = ap.parse_args(argv)
    run_training(args.kind)
    return 0


if __name__ == "__main__":
    sys.exit(main())
