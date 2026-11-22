"""Kit-grouped cross-validation: every scam family (kit) is held out in exactly one fold, so the scores are
for families the model has never seen. Reported overall, per scam type, per source and per view."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from ml import metrics as M
from ml.model import DEFAULT_SETTINGS, HamiModel

N_FOLDS = 5


def kit_folds(records: list[dict[str, Any]], k: int = N_FOLDS) -> list[set[str]]:
    """Deterministic, roughly balanced assignment of kits to folds (per label, by hash order)."""
    kits: dict[str, list] = defaultdict(list)
    for r in records:
        kits[r["kit_id"] or r["id"]].append(r)
    folds: list[set[str]] = [set() for _ in range(k)]
    sizes = [0] * k
    for label in ("fraudulent", "legitimate"):
        label_kits = sorted((kid for kid, rs in kits.items() if rs[0]["label"] == label), key=M.kit_bucket)
        for kid in sorted(label_kits, key=lambda x: -len(kits[x])):
            i = min(range(k), key=lambda j: sizes[j])
            folds[i].add(kid)
            sizes[i] += len(kits[kid])
    return folds


def kit_cv(records: list[dict[str, Any]], settings: dict[str, Any] | None = None, k: int = N_FOLDS) -> dict[str, Any]:
    settings = dict(settings or DEFAULT_SETTINGS)
    folds = kit_folds(records, k)
    scored: list[tuple[dict[str, Any], float]] = []
    for test_kits in folds:
        train = [r for r in records if (r["kit_id"] or r["id"]) not in test_kits]
        test = [r for r in records if (r["kit_id"] or r["id"]) in test_kits]
        if len({r["label"] for r in train}) < 2 or not test:
            continue
        model = HamiModel(settings).fit([r["text"] for r in train], [r["features"] for r in train],
                                        [1 if r["label"] == "fraudulent" else 0 for r in train])
        for r, s in zip(test, model.predict_proba([r["text"] for r in test], [r["features"] for r in test])):
            scored.append((r, float(s)))
    recs = [r for r, _ in scored]
    scores = [s for _, s in scored]
    rep = M.full_report(recs, scores, settings)
    rep["per_view"] = M.grouped(recs, scores, settings["threshold_agree"], lambda r: [r.get("view") or "page"])
    rep["folds"] = len(folds)
    rep["kits"] = len({r["kit_id"] or r["id"] for r in records})
    return rep


def oof_scores(records: list[dict[str, Any]], settings: dict[str, Any], k: int = N_FOLDS) -> list[tuple[dict[str, Any], float]]:
    """Out-of-fold scores (kit-grouped) on the given records only."""
    out: list[tuple[dict[str, Any], float]] = []
    for test_kits in kit_folds(records, k):
        train = [r for r in records if (r["kit_id"] or r["id"]) not in test_kits]
        test = [r for r in records if (r["kit_id"] or r["id"]) in test_kits]
        if len({r["label"] for r in train}) < 2 or not test:
            continue
        m = HamiModel(dict(settings)).fit([r["text"] for r in train], [r["features"] for r in train],
                                          [1 if r["label"] == "fraudulent" else 0 for r in train])
        out.extend(zip(test, (float(x) for x in m.predict_proba([r["text"] for r in test], [r["features"] for r in test]))))
    return out


def threshold_for_fpr(scored: list[tuple[dict[str, Any], float]], max_fpr: float, floor: float) -> float:
    """Smallest threshold (>= floor) whose out-of-fold FPR on legitimate records is <= max_fpr."""
    legit = sorted((s for r, s in scored if r["label"] == "legitimate"), reverse=True)
    if not legit:
        return floor
    allowed = int(max_fpr * len(legit))
    t = legit[allowed] + 1e-6 if allowed < len(legit) else floor
    return round(max(floor, min(t, 0.95)), 4)
