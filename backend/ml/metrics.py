"""Evaluation metrics and the kit-grouped, version-stable train/test split."""
from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Any

import numpy as np
from sklearn.metrics import average_precision_score

TEST_FRACTION = 0.25
STRONG = ("deposit_to_unlock", "advance_fee", "commission_transfer", "gambling_deposit", "investment_promise",
          "field_card", "field_cvv", "field_otp", "field_bank_password")


def kit_bucket(kit_id: str) -> float:
    return int(hashlib.sha256(kit_id.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def split(records: list[dict[str, Any]], test_fraction: float = TEST_FRACTION) -> tuple[list, list]:
    """All variants of a kit stay on one side. The side depends only on a hash of the kit id, so the
    held-out kits stay held out across dataset versions (fair candidate-vs-current comparison)."""
    kits: dict[str, list] = defaultdict(list)
    for r in records:
        kits[r["kit_id"] or r["id"]].append(r)
    test_kits = {k for k in kits if kit_bucket(k) < test_fraction}
    # Both classes must be present on both sides; move the lowest-bucket kit of a missing class.
    for label in ("fraudulent", "legitimate"):
        label_kits = sorted((k for k, rs in kits.items() if any(r["label"] == label for r in rs)), key=kit_bucket)
        if not label_kits:
            continue
        if not any(k in test_kits for k in label_kits) and len(label_kits) > 1:
            test_kits.add(label_kits[0])
        if all(k in test_kits for k in label_kits) and len(label_kits) > 1:
            test_kits.discard(label_kits[-1])
    train = [r for k, rs in kits.items() if k not in test_kits for r in rs]
    test = [r for k, rs in kits.items() if k in test_kits for r in rs]
    return train, test


def binary_metrics(y_true: list[int], scores: list[float], threshold: float) -> dict[str, Any]:
    y = np.asarray(y_true, dtype=int)
    s = np.asarray(scores, dtype=float)
    pred = (s >= threshold).astype(int)
    tp = int(((pred == 1) & (y == 1)).sum())
    fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    tn = int(((pred == 0) & (y == 0)).sum())
    out: dict[str, Any] = {
        "n": int(len(y)), "n_fraudulent": int(y.sum()), "n_legitimate": int((y == 0).sum()),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(tp / (tp + fp), 4) if tp + fp else None,
        "recall": round(tp / (tp + fn), 4) if tp + fn else None,
        "fpr_legit": round(fp / (fp + tn), 4) if fp + tn else None,
    }
    out["pr_auc"] = round(float(average_precision_score(y, s)), 4) if 0 < y.sum() < len(y) else None
    return out


def flag_metrics(y_true: list[int], flags: list[bool]) -> dict[str, Any]:
    return binary_metrics(y_true, [1.0 if f else 0.0 for f in flags], 0.5) | {"pr_auc": None}


def grouped(records: list[dict[str, Any]], scores: list[float], threshold: float, key) -> dict[str, Any]:  # noqa: ANN001
    groups: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(records):
        for g in key(r):
            groups[g].append(i)
    out = {}
    for g, idx in sorted(groups.items()):
        y = [1 if records[i]["label"] == "fraudulent" else 0 for i in idx]
        out[g] = binary_metrics(y, [scores[i] for i in idx], threshold)
    return out


def high_risk_flag(rec: dict[str, Any], score: float, agree: float) -> bool:
    f = rec.get("features", {})
    return score >= agree and any(f.get(k, 0) > 0 for k in STRONG)


def full_report(records: list[dict[str, Any]], scores: list[float], settings: dict[str, Any]) -> dict[str, Any]:
    agree, caution = settings["threshold_agree"], settings["threshold_caution"]
    y = [1 if r["label"] == "fraudulent" else 0 for r in records]
    return {
        "overall": binary_metrics(y, scores, agree),
        "per_language": grouped(records, scores, agree, lambda r: [r["lang"] or "unknown"]),
        "per_source": grouped(records, scores, agree, lambda r: [r["source"]]),
        "per_scam_type": {k: {"n": v["n_fraudulent"], "recall": v["recall"], "tp": v["tp"], "fn": v["fn"]}
                          for k, v in grouped([r for r in records if r["label"] == "fraudulent"],
                                              [s for r, s in zip(records, scores) if r["label"] == "fraudulent"],
                                              agree, lambda r: [r["scam_type"] or "unspecified"]).items()},
        "per_behavior_tag": {k: {"n": v["n_fraudulent"], "recall": v["recall"]}
                             for k, v in grouped([r for r in records if r["label"] == "fraudulent"],
                                                 [s for r, s in zip(records, scores) if r["label"] == "fraudulent"],
                                                 agree, lambda r: r["behavior_tags"] or ["untagged"]).items()},
        "tier_high_risk_rule": flag_metrics(y, [high_risk_flag(r, s, agree) for r, s in zip(records, scores)]),
        "caution_or_above": binary_metrics(y, scores, caution),
    }
