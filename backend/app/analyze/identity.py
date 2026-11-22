"""Listing identity check: listing name (user or Maps panel) vs the site's claimed names."""
from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from ml.arabic import normalize_arabic

# Legal-form and filler words that should not drive a match.
STOP = {
    "llc", "l.l.c", "fze", "fzc", "fz", "fz-llc", "est", "est.", "establishment", "company", "co", "co.", "ltd",
    "limited", "inc", "group", "the", "and", "&", "services", "service", "trading", "general", "uae", "dubai",
    "abu", "dhabi", "sharjah", "official", "online", "store", "shop", "website", "branch",
    "شركه", "ش.ذ.م.م", "ذ.م.م", "مؤسسه", "موسسه", "للخدمات", "خدمات", "التجاريه", "تجاره", "العامه", "ال", "و",
    "دبي", "ابوظبي", "الشارقه", "الامارات", "فرع",
}


@dataclass
class IdentityResult:
    result: str            # match | mismatch | unclear | not_checked
    listing_name: str = ""
    best_name: str = ""
    score: float = 0.0

    def to_dict(self) -> dict:
        return {"result": self.result, "listing_name": self.listing_name, "best_name": self.best_name,
                "score": round(self.score, 1)}


def _clean(s: str) -> str:
    s = normalize_arabic(s)
    s = re.sub(r"[^\w\s؀-ۿ]", " ", s)
    toks = [t for t in s.split() if t not in STOP]
    if toks and toks[0].startswith("ال") and len(toks[0]) > 4:
        pass
    return " ".join(toks)


def check_identity(listing_name: str | None, claimed: list[str], host: str = "") -> IdentityResult:
    if not listing_name or not listing_name.strip():
        return IdentityResult("not_checked")
    ln = _clean(listing_name)
    if not ln:
        return IdentityResult("unclear", listing_name=listing_name)
    best, best_score = "", 0.0
    for name in claimed:
        cn = _clean(name)
        if not cn:
            continue
        score = max(fuzz.token_set_ratio(ln, cn), fuzz.partial_ratio(ln, cn) if min(len(ln), len(cn)) >= 5 else 0)
        if score > best_score:
            best, best_score = name, score
    # The domain itself can confirm a match (e.g. "Noor Manpower" on noormanpower.ae).
    squashed = re.sub(r"[^a-z0-9]", "", ln)
    host_label = re.sub(r"[^a-z0-9]", "", host.split(".")[0] if host else "")
    if len(squashed) >= 5 and host_label and (squashed in host_label or host_label in squashed):
        return IdentityResult("match", listing_name, host, 100.0)
    if best_score >= 80:
        return IdentityResult("match", listing_name, best, best_score)
    if not claimed:
        return IdentityResult("unclear", listing_name, "", 0.0)
    if best_score < 55:
        return IdentityResult("mismatch", listing_name, best or (claimed[0] if claimed else ""), best_score)
    return IdentityResult("unclear", listing_name, best, best_score)
