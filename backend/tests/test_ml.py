import json

from ml import metrics as M


def _recs(n_kits=12, per=5):
    out = []
    for k in range(n_kits):
        label = "fraudulent" if k % 2 else "legitimate"
        for i in range(per):
            out.append({"id": f"k{k}-{i}", "kit_id": f"kit{k}", "label": label, "text": "x", "features": {}})
    return out


def test_split_keeps_kits_together_and_is_stable():
    recs = _recs()
    train, test = M.split(recs)
    assert {r["kit_id"] for r in train}.isdisjoint({r["kit_id"] for r in test})
    assert {r["label"] for r in test} == {"fraudulent", "legitimate"}
    assert {r["label"] for r in train} == {"fraudulent", "legitimate"}
    # Adding new kits never moves an existing kit across the split.
    train2, test2 = M.split(recs + _recs(20)[60:])
    old_test = {r["kit_id"] for r in test}
    assert old_test <= {r["kit_id"] for r in test2} | {"kit0", "kit1"}


def test_binary_metrics():
    m = M.binary_metrics([1, 1, 0, 0], [0.9, 0.2, 0.1, 0.7], 0.5)
    assert (m["tp"], m["fn"], m["fp"], m["tn"]) == (1, 1, 1, 1)
    assert m["recall"] == 0.5 and m["fpr_legit"] == 0.5 and m["precision"] == 0.5


def test_train_synthetic_and_promotion(tmp_path, monkeypatch):
    from app import db as dbmod
    from app.config import settings
    from ml import train as T

    monkeypatch.setattr(settings, "models_dir", tmp_path / "models")
    monkeypatch.setattr(settings, "processed_dir", tmp_path / "processed")
    monkeypatch.setenv("HAMI_DB_PATH", str(tmp_path / "ml.sqlite3"))
    dbmod.reset_init_cache()
    r1 = T.run_training("synthetic", quiet=True)
    assert r1["promotion"]["promoted"] and r1["status"] == "current"
    held = r1["metrics"]["held_out"]
    assert held["overall"]["fpr_legit"] is not None and held["overall"]["recall"] > 0.6
    assert set(held["per_language"]) >= {"ar", "en"}
    assert "task_scam" in held["per_scam_type"]
    meta = json.loads((settings.models_dir / r1["version"] / "meta.json").read_text(encoding="utf-8"))
    assert meta["dataset_hash"] == r1["dataset_hash"] and meta["feature_settings"]["word_ngram_range"] == [1, 2]
    # Second run: compared against the current model on the same held-out set.
    r2 = T.run_training("synthetic", quiet=True)
    assert "recall_not_lower" in r2["promotion"] and "fpr_not_higher" in r2["promotion"]
    with dbmod.db() as conn:
        statuses = [r["status"] for r in conn.execute("SELECT status FROM model_versions ORDER BY created_at")]
        assert statuses.count("current") == 1
    dbmod.reset_init_cache()
