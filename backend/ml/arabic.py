"""Arabic text normalization used everywhere text is matched or featurized.

- unify alef variants  أ إ آ ٱ → ا
- ى → ي ,  ة → ه   (for matching only)
- strip tatweel (ـ) and diacritics (harakat, Quranic marks)
- Arabic-Indic and Extended Arabic-Indic digits → Western digits, Arabic decimal/thousands separators
"""
from __future__ import annotations

import re
import unicodedata

_DIGITS = {ord(c): str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")}
_DIGITS.update({ord(c): str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")})
_SEPARATORS = {ord("٫"): ".", ord("٬"): ",", ord("،"): ","}
_DIGIT_TABLE = {**_DIGITS}
LETTER_TABLE = _LETTERS = {
    ord("أ"): "ا", ord("إ"): "ا", ord("آ"): "ا", ord("ٱ"): "ا",
    ord("ى"): "ي", ord("ة"): "ه",
    ord("ؤ"): "و", ord("ئ"): "ي",
}
TATWEEL = "\u0640"
# Harakat, tanween, shadda, sukun, superscript alef, Quranic annotation marks.
_DIACRITICS_RE = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06DC\u06DF-\u06E8\u06EA-\u06ED]")
_ARABIC_LETTER_RE = re.compile(r"[\u0621-\u064A\u0660-\u0669\u066E-\u06D3\u06FA-\u06FF]")
_LATIN_LETTER_RE = re.compile(r"[A-Za-z]")


def digits_to_western(text: str) -> str:
    """Map Arabic-Indic digits (and Arabic decimal separator) to Western. Length-preserving."""
    return text.translate(_DIGIT_TABLE).replace("٫", ".").replace("٬", ",")


def strip_diacritics(text: str) -> str:
    return _DIACRITICS_RE.sub("", text.replace(TATWEEL, ""))


def normalize_arabic(text: str, lower: bool = True) -> str:
    """Full normalization for matching and features."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = strip_diacritics(text)
    text = text.translate(_LETTERS)
    text = digits_to_western(text)
    if lower:
        text = text.lower()
    return re.sub(r"\s+", " ", text).strip()


def count_scripts(text: str) -> tuple[int, int]:
    return len(_ARABIC_LETTER_RE.findall(text)), len(_LATIN_LETTER_RE.findall(text))


def detect_lang(text: str, min_letters: int = 20) -> str:
    """Return 'ar', 'en', 'mixed' or '' (too little text). Script-ratio based; robust on short,
    noisy page text where statistical detectors are unreliable."""
    ar, lat = count_scripts(text or "")
    total = ar + lat
    if total < min_letters:
        return ""
    if ar / total >= 0.7:
        return "ar"
    if lat / total >= 0.7:
        return "en"
    return "mixed"


def is_arabic_char(ch: str) -> bool:
    return bool(_ARABIC_LETTER_RE.match(ch))
