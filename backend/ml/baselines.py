"""Baselines compared on the same held-out examples: URL only, and URL + page text."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import numpy as np
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression


def url_string(url: str) -> str:
    p = urlsplit(url)
    return f"{(p.hostname or '').lower()} {p.path.lower()}"


class UrlModel:
    """Character n-grams of hostname + path, plus simple lexical counts."""

    def __init__(self, with_text: bool = False):
        self.with_text = with_text
        self.url_vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), sublinear_tf=True, min_df=1)
        self.text_vec = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), sublinear_tf=True, min_df=1,
                                        token_pattern=r"(?u)\b\w\w+\b") if with_text else None
        self.clf = LogisticRegression(C=4.0, class_weight="balanced", max_iter=3000, solver="liblinear")

    @staticmethod
    def _lex(urls: list[str]) -> sparse.csr_matrix:
        rows = []
        for u in urls:
            h = urlsplit(u).hostname or ""
            rows.append([len(h) / 30, h.count("-") / 3, sum(c.isdigit() for c in h) / 5, h.count(".") / 4])
        return sparse.csr_matrix(np.array(rows, dtype=float))

    def _X(self, recs: list[dict[str, Any]], fit: bool) -> sparse.csr_matrix:
        urls = [r["url"] for r in recs]
        us = [url_string(u) for u in urls]
        parts = [self.url_vec.fit_transform(us) if fit else self.url_vec.transform(us), self._lex(urls)]
        if self.with_text:
            texts = [r["text"] for r in recs]
            parts.append(self.text_vec.fit_transform(texts) if fit else self.text_vec.transform(texts))
        return sparse.hstack(parts).tocsr()

    def fit(self, recs: list[dict[str, Any]]) -> "UrlModel":
        y = [1 if r["label"] == "fraudulent" else 0 for r in recs]
        self.clf.fit(self._X(recs, True), y)
        return self

    def predict_proba(self, recs: list[dict[str, Any]]) -> list[float]:
        return list(self.clf.predict_proba(self._X(recs, False))[:, 1])
