"""Hami detector: calibrated logistic regression on TF-IDF word 1-2 grams + char 3-5 grams of
redacted, normalized page text (hostnames removed), plus structured indicator features."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from scipy import sparse
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from app.analyze import STRUCT_FEATURES

DEFAULT_SETTINGS = {
    "word_ngram_range": [1, 2],
    "char_ngram_range": [3, 5],
    "word_max_features": 40000,
    "char_max_features": 80000,
    "struct_weight": 1.5,
    "C": 4.0,
    "class_weight": "balanced",
    "calibration": "sigmoid",
    "threshold_agree": 0.5,      # "classifier agrees" (High risk needs this + strong behavior)
    "threshold_caution": 0.35,   # score above this alone -> Caution
    "struct_features": STRUCT_FEATURES,
}


def struct_matrix(feats: list[dict[str, float]], names: list[str], weight: float) -> sparse.csr_matrix:
    arr = np.array([[float(f.get(n, 0.0)) for n in names] for f in feats], dtype=np.float64) * weight
    return sparse.csr_matrix(arr)


@dataclass
class HamiModel:
    settings: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_SETTINGS))
    word_vec: TfidfVectorizer | None = None
    char_vec: TfidfVectorizer | None = None
    clf: Any = None                  # calibrated classifier used for scores
    explainer: LogisticRegression | None = None   # plain LR on all training data, for phrase weights
    calibrated: bool = False

    def _matrix(self, texts: list[str], feats: list[dict[str, float]], fit: bool = False) -> sparse.csr_matrix:
        s = self.settings
        if fit:
            self.word_vec = TfidfVectorizer(analyzer="word", ngram_range=tuple(s["word_ngram_range"]),
                                            max_features=s["word_max_features"], sublinear_tf=True, min_df=1,
                                            token_pattern=r"(?u)\b\w\w+\b")
            self.char_vec = TfidfVectorizer(analyzer="char_wb", ngram_range=tuple(s["char_ngram_range"]),
                                            max_features=s["char_max_features"], sublinear_tf=True, min_df=1)
            w = self.word_vec.fit_transform(texts)
            c = self.char_vec.fit_transform(texts)
        else:
            w = self.word_vec.transform(texts)
            c = self.char_vec.transform(texts)
        st = struct_matrix(feats, s["struct_features"], s["struct_weight"])
        return sparse.hstack([w, c, st]).tocsr()

    def fit(self, texts: list[str], feats: list[dict[str, float]], y: list[int]) -> "HamiModel":
        X = self._matrix(texts, feats, fit=True)
        y_arr = np.asarray(y)
        base = dict(C=self.settings["C"], class_weight=self.settings["class_weight"], max_iter=3000, solver="liblinear")
        self.explainer = LogisticRegression(**base).fit(X, y_arr)
        min_class = int(min(np.bincount(y_arr, minlength=2)))
        cv = min(5, min_class)
        if cv >= 2:
            self.clf = CalibratedClassifierCV(LogisticRegression(**base), method=self.settings["calibration"], cv=cv)
            self.clf.fit(X, y_arr)
            self.calibrated = True
        else:
            self.clf = self.explainer
            self.calibrated = False
        return self

    def predict_proba(self, texts: list[str], feats: list[dict[str, float]]) -> np.ndarray:
        X = self._matrix(texts, feats)
        return self.clf.predict_proba(X)[:, 1]

    def feature_names(self) -> list[str]:
        return (list(self.word_vec.get_feature_names_out()) + [f"char:{c}" for c in self.char_vec.get_feature_names_out()]
                + [f"indicator:{n}" for n in self.settings["struct_features"]])

    def explain(self, text: str, feats: dict[str, float], k: int = 5) -> list[dict[str, Any]]:
        """Top-weighted phrases pushing this page towards 'fraudulent' (word n-grams and indicators)."""
        X = self._matrix([text], [feats])
        coef = self.explainer.coef_[0]
        contrib = X.multiply(coef).tocsr()
        names = self.feature_names()
        n_word = len(self.word_vec.vocabulary_)
        n_char = len(self.char_vec.vocabulary_)
        items = []
        for idx, val in zip(contrib.indices, contrib.data):
            if val <= 0:
                continue
            if n_word <= idx < n_word + n_char:
                continue  # char n-grams are not readable explanations
            items.append((val, names[idx]))
        items.sort(reverse=True)
        return [{"phrase": name, "weight": round(float(v), 3)} for v, name in items[:k]]

    def top_global_phrases(self, k: int = 25) -> dict[str, list[dict[str, Any]]]:
        coef = self.explainer.coef_[0]
        names = self.feature_names()
        n_word = len(self.word_vec.vocabulary_)
        n_char = len(self.char_vec.vocabulary_)
        idx = [i for i in range(len(names)) if not (n_word <= i < n_word + n_char)]
        order = sorted(idx, key=lambda i: coef[i])
        neg = [{"phrase": names[i], "weight": round(float(coef[i]), 3)} for i in order[:k]]
        pos = [{"phrase": names[i], "weight": round(float(coef[i]), 3)} for i in reversed(order[-k:])]
        return {"fraudulent": pos, "legitimate": neg}

    # ---- persistence -----------------------------------------------------------------------------
    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, directory / "model.joblib", compress=3)
        (directory / "feature_settings.json").write_text(json.dumps(self.settings, indent=2), encoding="utf-8")

    @staticmethod
    def load(directory: Path) -> "HamiModel":
        return joblib.load(directory / "model.joblib")
