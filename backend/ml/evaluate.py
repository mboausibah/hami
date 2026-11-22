"""make eval: re-run the held-out evaluation of the current (or a given) model on the dataset
version it was trained on (same kit-grouped split)."""
from __future__ import annotations

import argparse
import json
import sys

from app.config import settings
from app.scoring.model_store import read_registry
from ml import metrics as M
from ml.model import HamiModel
from ml.records import read_jsonl
from ml.train import _fmt, trainable, y_of


def evaluate(version: str | None = None) -> dict:
    version = version or read_registry().get("current")
    if not version:
        raise SystemExit("no current model - run `make train` or `make train-synthetic` first")
    mdir = settings.models_dir / version
    meta = json.loads((mdir / "meta.json").read_text(encoding="utf-8"))
    snap = settings.processed_dir / "datasets" / f"{meta['dataset_version']}.jsonl"
    records = read_jsonl(snap)
    if not records:
        if meta["kind"] == "synthetic":
            from ml.import_private import import_synthetic
            records = import_synthetic({})
        else:
            raise SystemExit(f"dataset snapshot {snap} not found (private data snapshots are not committed)")
    _, test = M.split(trainable(records))
    model = HamiModel.load(mdir)
    scores = list(model.predict_proba([r["text"] for r in test], [r["features"] for r in test]))
    rep = M.full_report(test, scores, model.settings)
    print(f"model {version} on {meta['dataset_version']} held-out split ({len(test)} records)")
    print(f"  overall          {_fmt(rep['overall'])}")
    print(f"  High-risk rule   {_fmt(rep['tier_high_risk_rule'])}")
    for k, v in rep["per_language"].items():
        print(f"  lang {k:10s} {_fmt(v)}")
    for k, v in rep["per_source"].items():
        print(f"  source {k:8s} {_fmt(v)}")
    for k, v in rep["per_scam_type"].items():
        print(f"  scam_type {k:14s} recall {v['recall']} (n={v['n']})")
    stored = json.loads((mdir / "metrics.json").read_text(encoding="utf-8"))["held_out"]["overall"]
    same = all(stored.get(k) == rep["overall"].get(k) for k in ("tp", "fp", "fn", "tn"))
    print(f"  matches metrics saved at training time: {same}")
    _ = y_of
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None)
    args = ap.parse_args(argv)
    evaluate(args.model)
    return 0


if __name__ == "__main__":
    sys.exit(main())
