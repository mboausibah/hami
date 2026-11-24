"""Redirect / invitation gateways and registration-page template fingerprints (linking evidence).

Gateway: the capture started on domain X and the scored page is on domain Y, reached through an HTTP redirect,
an HTML meta-refresh or a script redirect (e.g. a /code/<invite> page that bounces to /register/invite_code/<same
code>). Recorded only when the landing page is a registration/login wall or shows scam signals, or the same invite
code appears on both sides (legitimate cross-domain redirects and URL shorteners are not gateways).

Template: the distinctive wording (not UI boilerplate, not the site's own brand) and the form structure of a
registration / login page, reduced to integer feature hashes. Two sites sharing a template is template REUSE - a
lead for review, never proof of common ownership. No domain or wording is hardcoded.
"""
from __future__ import annotations

import re
import zlib
from typing import Any
from urllib.parse import parse_qsl, urljoin, urlsplit

from app.analyze.hosts import common_service_category
from app.urls import hostname, registrable_domain
from ml.arabic import normalize_arabic

META_REFRESH_RE = re.compile(r"""<meta[^>]+http-equiv=["']?refresh["']?[^>]*content=["']?\s*\d*\s*;?\s*url\s*=\s*([^"'>\s]+)""",
                             re.I)
JS_REDIRECT_RE = re.compile(r"""(?:window\.|document\.|top\.)?location(?:\.href)?\s*=\s*["']([^"']+)["']|"""
                            r"""location\.(?:replace|assign)\(\s*["']([^"']+)["']\s*\)""", re.I)
CODE_TOKEN_RE = re.compile(r"[A-Za-z0-9]{4,16}")

# UI boilerplate that appears on every sign-up / login page (English + Arabic, normalized).
GENERIC = set("""
a an and the of to for in on at by with your you our my me we us is are be it this that from or not no yes
login log in sign up signin signup register registration create account accounts new user username users password
passwords pwd confirm repeat enter please phone mobile number tel email e-mail mail address code verification verify
otp sms send get resend remember forgot forget reset show hide submit ok cancel close back next continue go home
menu language english arabic message messages loading copyright all rights reserved terms privacy policy contact
help support about now here click button agree accept welcome hello hi name first last full country select
login.html register.html app download
تسجيل الدخول دخول حساب جديد انشاء كلمه المرور السر رقم الهاتف الجوال البريد الالكتروني رمز التحقق ارسال تذكرني نسيت
اللغه العربيه الانجليزيه موافق الغاء الرئيسيه الشروط الخصوصيه جميع الحقوق محفوظه مرحبا اسم المستخدم
""".split())


def _codes(url: str) -> set[str]:
    u = urlsplit(url)
    parts = [re.sub(r"\.(html?|php|aspx?)$", "", seg, flags=re.I) for seg in u.path.split("/") if seg]
    parts += [v for _k, v in parse_qsl(u.query)] + [seg for seg in re.split(r"[/?&=#]", u.fragment) if seg]
    out = set()
    for p in parts:
        for t in CODE_TOKEN_RE.findall(p):
            if re.search(r"[A-Za-z]", t) and re.search(r"\d", t) and not re.fullmatch(r"v\d+|\d+px|html5", t, re.I):
                out.add(t.upper())
    return out


def detect_gateway(page_url: str, final_url: str, har: dict | None, landing_wall: bool,
                   landing_signals: bool) -> dict[str, Any] | None:
    """{gateway_host, gateway_url_path, target_host, mechanism, invite_code} when X != Y, else None."""
    if not final_url or not final_url.lower().startswith("http"):
        return None
    gx, gy = hostname(page_url), hostname(final_url)
    sx, sy = registrable_domain(gx), registrable_domain(gy)
    if not sx or not sy or sx == sy or common_service_category(gx):
        return None
    mechanism = "script_or_other"
    for e in (har or {}).get("log", {}).get("entries", []) or []:
        url = e.get("request", {}).get("url", "")
        if registrable_domain(hostname(url)) != sx:
            continue
        res = e.get("response", {}) or {}
        st = res.get("status") or 0
        if 300 <= st < 400:
            loc = next((h.get("value", "") for h in res.get("headers", []) if h.get("name", "").lower() == "location"), "")
            if registrable_domain(hostname(urljoin(url, loc))) == sy or not loc:
                mechanism = "http_redirect"
                break
        text = (res.get("content", {}) or {}).get("text") or ""
        if isinstance(text, str) and text:
            m = META_REFRESH_RE.search(text[:50_000])
            if m and registrable_domain(hostname(urljoin(url, m.group(1)))) == sy:
                mechanism = "meta_refresh"
                break
            for a, b in JS_REDIRECT_RE.findall(text[:50_000]):
                if registrable_domain(hostname(urljoin(url, a or b))) == sy:
                    mechanism = "script_redirect"
                    break
    shared = sorted(_codes(page_url) & _codes(final_url))
    if not (shared or landing_wall or landing_signals):
        return None
    return {"gateway_host": gx, "gateway_site": sx, "gateway_url_path": urlsplit(page_url).path[:200],
            "target_host": gy, "target_site": sy, "mechanism": mechanism, "invite_code": shared[0] if shared else None}


# ---- template fingerprint ----------------------------------------------------------------------------------------
def _norm_line(line: str, own_tokens: set[str]) -> list[str]:
    t = normalize_arabic(line.lower())
    t = re.sub(r"\d+", "0", t)
    words = [w for w in re.findall(r"[a-z؀-ۿ0]+", t) if w not in own_tokens]
    return words


def template_features(page_host: str, lines: list[str], fields: list[Any], form_actions: list[str]) -> tuple[list[int], int, list[str]]:
    """(feature hashes, distinctive line count, up to 3 sample lines). Empty when the page has no distinctive wording."""
    own = set(re.split(r"[^a-z0-9]+", page_host.lower())) | set(re.split(r"[^a-z0-9]+", registrable_domain(page_host)))
    feats: set[int] = set()
    kept: list[str] = []
    for line in lines[:300]:
        words = _norm_line(line, own)
        distinctive = [w for w in words if w not in GENERIC and len(w) > 1]
        if len(words) < 3 or not distinctive:
            continue
        key = " ".join(words)
        if key in kept:
            continue
        kept.append(key)
        feats.add(zlib.crc32(("L:" + key).encode()))
        for i in range(max(1, len(words) - 2)):
            feats.add(zlib.crc32(("S:" + " ".join(words[i:i + 3])).encode()))
    n_distinctive = sum(len([w for w in k.split() if w not in GENERIC and len(w) > 1]) for k in kept)
    if len(kept) < 2 or n_distinctive < 4:
        return [], len(kept), []
    seq = []
    for f in fields[:30]:
        name = re.sub(r"\d+", "0", str(getattr(f, "hint", "") or "").split(" ")[0].lower())[:30]
        typ = str(getattr(f, "type", "") or "")
        seq.append(f"{typ}:{name}")
        feats.add(zlib.crc32(("F:" + f"{typ}:{name}").encode()))
    if seq:
        feats.add(zlib.crc32(("FS:" + "|".join(seq)).encode()))
    for a in form_actions[:5]:
        path = "/".join(seg for seg in urlsplit(a).path.split("/") if seg and not re.search(r"\d", seg))
        if path:
            feats.add(zlib.crc32(("A:" + path.lower()).encode()))
    return sorted(feats)[:400], len(kept), kept[:3]


def template_similarity(a: list[int], b: list[int]) -> tuple[float, int]:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0, 0
    inter = len(sa & sb)
    return inter / len(sa | sb), inter
