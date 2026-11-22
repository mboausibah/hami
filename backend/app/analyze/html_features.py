"""Features read from saved HTML: visible text, form fields, claimed names, layout fingerprint."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Comment

from app.analyze import patterns as P
from ml.arabic import normalize_arabic

INVISIBLE_TAGS = ("script", "style", "noscript", "template", "svg", "head", "iframe", "object", "canvas")
BLOCK_SEP_TAGS = {"p", "div", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6", "br", "section",
                  "article", "header", "footer", "nav", "button", "a", "span", "label", "option", "uni-view",
                  "uni-text", "dt", "dd", "table", "form", "main", "aside"}
NAME_SPLIT_RE = re.compile(r"\s*[|\-–—:·•»/]\s*")
COPYRIGHT_RE = re.compile(r"(?:©|&copy;|copyright|حقوق (?:الطبع|النشر)[^\d]{0,20})\s*(?:\d{4}\s*[-–]?\s*\d{0,4})?\s*([^\n|.©]{2,60})", re.I)
GENERIC_NAME_WORDS = {"home", "welcome", "index", "login", "official", "website", "site", "page", "الرئيسية",
                      "الصفحة الرئيسية", "untitled", "loading", "document", "app"}


def soup_of(html: str) -> BeautifulSoup:
    return BeautifulSoup(html or "", "lxml")


def visible_lines(soup: BeautifulSoup) -> list[str]:
    """Visible text split into lines at block boundaries."""
    body = soup.body or soup
    for c in body.find_all(string=lambda s: isinstance(s, Comment)):
        c.extract()
    parts: list[str] = []

    def walk(node) -> None:  # noqa: ANN001
        for child in node.children:
            name = getattr(child, "name", None)
            if name is None:
                txt = str(child)
                if txt.strip():
                    parts.append(txt)
                continue
            if name in INVISIBLE_TAGS:
                continue
            style = (child.get("style") or "").replace(" ", "").lower() if hasattr(child, "get") else ""
            if "display:none" in style or "visibility:hidden" in style or child.get("hidden") is not None or \
                    child.get("aria-hidden") == "true":
                continue
            if name == "input":
                ph = child.get("placeholder")
                if ph:
                    parts.append(f"\n{ph}\n")
                continue
            label = child.get("aria-label")
            if label and name != "flt-semantics-placeholder" and not child.get_text(strip=True):
                # Accessibility labels carry the text of canvas-rendered apps and icon-only controls.
                parts.append(f"\n{label}\n")
            if name in BLOCK_SEP_TAGS:
                parts.append("\n")
            walk(child)
            if name in BLOCK_SEP_TAGS:
                parts.append("\n")

    walk(body)
    lines = []
    for line in "".join(parts).split("\n"):
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    return lines


@dataclass
class FormField:
    kind: str           # card | cvv | otp | bank_password | expiry | password | email | phone | text | other
    input_type: str
    hint: str           # normalized hint text (name/id/placeholder/label), redacted, truncated


@dataclass
class FormInfo:
    fields: list[FormField] = field(default_factory=list)

    @property
    def kinds(self) -> set[str]:
        return {f.kind for f in self.fields}

    def signature(self) -> str:
        sig = sorted(f"{f.kind}:{f.input_type}" for f in self.fields)
        return hashlib.sha1("|".join(sig).encode()).hexdigest()[:16] if sig else ""


def form_fields(soup: BeautifulSoup) -> FormInfo:
    info = FormInfo()
    labels = {lab.get("for"): lab.get_text(" ", strip=True) for lab in soup.find_all("label") if lab.get("for")}
    for el in soup.find_all(["input", "select", "textarea"]):
        itype = (el.get("type") or el.name or "text").lower()
        if itype in ("hidden", "submit", "button", "image", "reset", "checkbox", "radio", "file"):
            continue
        hint_raw = " ".join(filter(None, [
            el.get("name"), el.get("id"), el.get("placeholder"), el.get("autocomplete"), el.get("aria-label"),
            el.get("title"), labels.get(el.get("id")),
        ]))
        hint = normalize_arabic(hint_raw)[:80]
        ac = (el.get("autocomplete") or "").lower()
        if ac.startswith("cc-number") or P.FIELD_CARD.search(hint):
            kind = "card"
        elif ac.startswith("cc-csc") or P.FIELD_CVV.search(hint):
            kind = "cvv"
        elif ac.startswith("cc-exp") or P.FIELD_EXPIRY.search(hint):
            kind = "expiry"
        elif ac == "one-time-code" or P.FIELD_OTP.search(hint):
            kind = "otp"
        elif P.FIELD_BANK_PW.search(hint):
            kind = "bank_password"
        elif itype == "password":
            kind = "password"
        elif itype == "email" or "email" in hint or "بريد" in hint:
            kind = "email"
        elif itype == "tel" or re.search(r"phone|mobile|هاتف|جوال|موبايل", hint):
            kind = "phone"
        elif itype in ("text", "search", "number", "textarea", "select"):
            kind = "text"
        else:
            kind = "other"
        info.fields.append(FormField(kind=kind, input_type=itype, hint=hint))
    return info


def claimed_names(soup: BeautifulSoup, lines: list[str]) -> list[str]:
    """Names the site claims for itself: title, site-name metas, logo alt, h1, header/footer copyright."""
    names: list[str] = []

    def add(s: str | None) -> None:
        if not s:
            return
        s = re.sub(r"\s+", " ", s).strip()
        if 2 <= len(s) <= 70 and normalize_arabic(s) not in GENERIC_NAME_WORDS and s not in names:
            names.append(s)

    if soup.title and soup.title.string:
        title = soup.title.string.strip()
        add(title)
        for part in NAME_SPLIT_RE.split(title):
            if len(part) >= 3:
                add(part)
    for attr, val in (("property", "og:site_name"), ("name", "application-name"),
                      ("name", "apple-mobile-web-app-title"), ("property", "og:title"), ("name", "author")):
        m = soup.find("meta", attrs={attr: val})
        if m and m.get("content"):
            add(m["content"])
    for img in soup.select("header img[alt], .logo img[alt], img.logo[alt], [class*=logo] img[alt], a.navbar-brand img[alt]")[:3]:
        add(img.get("alt"))
    for el in soup.select(".logo, .brand, .navbar-brand, [class*=site-name], [class*=brand-name]")[:3]:
        add(el.get_text(" ", strip=True))
    h1 = soup.find("h1")
    if h1:
        add(h1.get_text(" ", strip=True))
    footer = soup.find("footer")
    footer_text = footer.get_text(" ", strip=True) if footer else " ".join(lines[-15:])
    for m in COPYRIGHT_RE.finditer(footer_text):
        cand = re.sub(r"(all rights reserved|جميع الحقوق محفوظة).*$", "", m.group(1), flags=re.I).strip(" .,-")
        add(cand)
    return names[:10]


# ---- layout fingerprint (DOM-structure shingles + MinHash) ---------------------------------------
_MH_N = 64
_MH_P = (1 << 61) - 1
_MH_A = [((i + 1) * 0x9E3779B97F4A7C15) % _MH_P or 1 for i in range(_MH_N)]
_MH_B = [((i + 7) * 0xC2B2AE3D27D4EB4F) % _MH_P for i in range(_MH_N)]


def _structure_tokens(soup: BeautifulSoup, limit: int = 4000) -> list[str]:
    tokens = []
    body = soup.body or soup
    for el in body.find_all(True, limit=limit):
        if el.name in ("script", "style", "noscript", "svg", "path", "br"):
            continue
        cls = el.get("class") or []
        first = re.sub(r"\d+", "", cls[0]) if cls else ""
        tokens.append(f"{el.name}.{first}")
    return tokens


def fingerprint(soup: BeautifulSoup, k: int = 4) -> list[int]:
    toks = _structure_tokens(soup)
    if len(toks) < k:
        return []
    shingles = {"|".join(toks[i:i + k]) for i in range(len(toks) - k + 1)}
    hashes = [int.from_bytes(hashlib.blake2b(s.encode(), digest_size=8).digest(), "big") for s in shingles]
    return [min((a * h + b) % _MH_P for h in hashes) for a, b in zip(_MH_A, _MH_B)]


def fingerprint_similarity(a: list[int] | str | None, b: list[int] | str | None) -> float:
    if isinstance(a, str):
        a = json.loads(a) if a else []
    if isinstance(b, str):
        b = json.loads(b) if b else []
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(1 for x, y in zip(a, b) if x == y) / len(a)
