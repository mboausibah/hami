"""Sanitizer: runs on every capture bundle before anything is stored.

Removes cookies, Authorization/Set-Cookie (and similar) headers, request bodies, token-like
query parameters, e-mail addresses and phone numbers. Binary response bodies are dropped
(metadata kept); text bodies are capped in size.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import re
from typing import Any
from urllib.parse import urlsplit

from app.urls import TOKEN_PARAM_RE, strip_token_params
from ml.arabic import digits_to_western

SENSITIVE_HEADERS = {
    "cookie", "set-cookie", "authorization", "proxy-authorization", "x-api-key", "x-auth-token",
    "x-csrf-token", "x-xsrf-token", "x-access-token", "x-refresh-token", "x-session-id", "token",
    "access-token", "x-amz-security-token", "x-goog-api-key",
}
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,253}\.[A-Za-z]{2,24}")
# Phone numbers: international (+ / 00 prefix), UAE mobile/landline, or digits inside tel:/wa.me links.
PHONE_RES = [
    re.compile(r"(?<![\w/])(?:\+|00)\d[\d\s\-().]{6,18}\d(?!\w)"),
    re.compile(r"(?<![\w.])0?5[024568][\s\-]?\d{3}[\s\-]?\d{4}(?!\w)"),
    re.compile(r"(?<![\w.])0[2-79][\s\-]?\d{3}[\s\-]?\d{4}(?!\w)"),
]
LINK_PHONE_RE = re.compile(r"((?:wa\.me|api\.whatsapp\.com/send\?phone=|whatsapp://send\?phone=|tel:|sms:|viber://chat\?number=)/?)(\+?\d[\d\-]{5,})", re.I)
JWT_RE = re.compile(r"eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")
TEXT_MIME_RE = re.compile(r"(text/|json|javascript|ecmascript|xml|svg|x-www-form-urlencoded)", re.I)

REDACTED_EMAIL = "[email]"
REDACTED_PHONE = "[phone]"


def redact_text(text: str) -> str:
    """Redact e-mails, phone numbers and JWT-like tokens. Arabic-Indic digits are handled by
    matching on a length-preserving Western-digit copy."""
    if not text:
        return text
    text = LINK_PHONE_RE.sub(lambda m: m.group(1) + REDACTED_PHONE, text)
    text = EMAIL_RE.sub(REDACTED_EMAIL, text)
    text = JWT_RE.sub("[token]", text)
    western = digits_to_western(text)
    if len(western) != len(text):  # defensive; translation is 1:1
        western = text
    spans: list[tuple[int, int]] = []
    for rx in PHONE_RES:
        for m in rx.finditer(western):
            digits = sum(c.isdigit() for c in m.group(0))
            if 8 <= digits <= 15:
                spans.append(m.span())
    if not spans:
        return text
    spans.sort()
    out, last = [], 0
    for s, e in spans:
        if s < last:
            continue
        out.append(text[last:s])
        out.append(REDACTED_PHONE)
        last = e
    out.append(text[last:])
    return "".join(out)


def sanitize_url(url: str) -> str:
    try:
        return redact_text(strip_token_params(url))
    except ValueError:
        return "[unparseable-url]"


SENSITIVE_HEADER_NAME_RE = re.compile(r"(auth|token|session|cookie|sign|secret|api[-_]?key|csrf|xsrf|jwt|credential|"
                                      r"password|visitor[-_]?id|device[-_]?id|client[-_]?id|\bcid\b)", re.I)
BEARER_RE = re.compile(r"^\s*(bearer|basic|token|digest)\s+\S+|eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}", re.I)


def is_sensitive_header(name: str, value: str) -> bool:
    """Known secret headers, any header *named* like a credential, or any value that looks like one."""
    n = name.lower()
    return n in SENSITIVE_HEADERS or bool(SENSITIVE_HEADER_NAME_RE.search(n)) or bool(BEARER_RE.search(value or ""))


def _clean_headers(headers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for h in headers or []:
        name = str(h.get("name", ""))
        if name.startswith(":") or is_sensitive_header(name, str(h.get("value", ""))):
            continue
        value = str(h.get("value", ""))
        if name.lower() in ("referer", "location", "origin", "content-location"):
            value = sanitize_url(value)
        out.append({"name": name, "value": value})
    return out


# JSON keys whose values are personal or account data (tokens, invite/referral codes, contact details,
# balances, identities). Their values are replaced in every stored JSON body.
SENSITIVE_JSON_KEY_RE = re.compile(
    r"(token|secret|password|passwd|pwd|session|sid|auth|cookie|sign(ature)?|invite|invit|referr|refer_?code|"
    r"promo_?code|share_?code|phone|mobile|tel|email|mail|whatsapp|telegram|uid|user_?id|member_?id|account|"
    r"username|user_?name|nick|real_?name|full_?name|id_?card|passport|bank|card_?no|iban|balance|amount_?left|"
    r"wallet|address|ip|device_?id|imei|otp|captcha|verify_?code)", re.I)
AUTH_HEADER_NAMES = {"authorization", "cookie", "token", "x-token", "x-auth-token", "x-access-token", "accesstoken",
                     "access-token", "x-session-id", "proxy-authorization"}
STATIC_MIME_RE = re.compile(r"(javascript|ecmascript|text/css|font/|application/font|woff|svg|image/)", re.I)


def _redact_json(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: ("[redacted]" if SENSITIVE_JSON_KEY_RE.search(str(k)) and not isinstance(v, (dict, list))
                    else _redact_json(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_json(v) for v in obj]
    if isinstance(obj, str):
        return redact_text(obj)
    return obj


def _body_bytes(content: dict[str, Any]) -> bytes | None:
    text = content.get("text")
    if text is None:
        return None
    if content.get("encoding") == "base64":
        try:
            return base64.b64decode(text)
        except (ValueError, TypeError):
            return None
    return text.encode("utf-8", "surrogatepass") if isinstance(text, str) else None


def sanitize_har(har: dict[str, Any], max_body_bytes: int = 1_500_000, strict: bool = False) -> dict[str, Any]:
    """Return a sanitized deep copy of a HAR document.

    Every response body is SHA-256 hashed *before* anything is dropped (`content._hami_sha256`), so delivered
    JS/CSS/fonts/images can be fingerprinted without keeping binary bodies. `strict=True` (user-recorded
    sessions) additionally drops every non-static response body of requests that carried credentials, and all
    WebSocket messages."""
    har = copy.deepcopy(har)
    log = har.get("log", {})
    for page in log.get("pages", []) or []:
        if "title" in page:
            page["title"] = sanitize_url(str(page["title"]))
    for e in log.get("entries", []) or []:
        req = e.get("request", {})
        had_auth = (
            any(is_sensitive_header(str(h.get("name", "")), str(h.get("value", ""))) for h in req.get("headers", []) or [])
            or bool(req.get("cookies"))
            or any(TOKEN_PARAM_RE.search(str(q.get("name", ""))) for q in req.get("queryString", []) or [])
        )
        req["url"] = sanitize_url(req.get("url", ""))
        req["headers"] = _clean_headers(req.get("headers", []))
        req["cookies"] = []
        req["queryString"] = [
            {"name": q.get("name", ""), "value": redact_text(str(q.get("value", "")))}
            for q in req.get("queryString", []) or []
            if not TOKEN_PARAM_RE.search(str(q.get("name", "")))
        ]
        if req.get("postData"):
            # Request bodies may hold credentials or personal data: never stored.
            req["postData"] = {"mimeType": req["postData"].get("mimeType", ""), "text": "[removed by sanitizer]"}
        res = e.get("response", {})
        res["headers"] = _clean_headers(res.get("headers", []))
        res["cookies"] = []
        if res.get("redirectURL"):
            res["redirectURL"] = sanitize_url(res["redirectURL"])
        content = res.get("content", {}) or {}
        mime = str(content.get("mimeType", ""))
        raw = _body_bytes(content)
        if raw is not None:
            content["_hami_sha256"] = hashlib.sha256(raw).hexdigest()
            content["_hami_size"] = len(raw)
        text = content.get("text")
        if text is not None:
            if content.get("encoding") == "base64" or not TEXT_MIME_RE.search(mime):
                content["text"] = None
                content["_hami_body"] = "binary-dropped"
                content.pop("encoding", None)
            elif strict and had_auth and not STATIC_MIME_RE.search(mime):
                content["text"] = None
                content["_hami_body"] = "authenticated-response-dropped"
            elif len(text.encode("utf-8", "ignore")) > max_body_bytes:
                content["text"] = None
                content["_hami_body"] = "oversize-dropped"
            elif "json" in mime.lower() or (text[:1] in "{[" and "javascript" not in mime.lower()):
                try:
                    content["text"] = json.dumps(_redact_json(json.loads(text)), ensure_ascii=False)
                except ValueError:
                    content["text"] = redact_text(text)
            else:
                content["text"] = redact_text(text)
        res["content"] = content
        # Remove fields that can carry connection identifiers or message contents.
        for k in ("_initiator", "serverIPAddress", "connection", "_securityDetails", "_webSocketMessages"):
            e.pop(k, None)
    return har


_INPUT_VALUE_RE = re.compile(r'(<input\b[^>]*?\bvalue\s*=\s*)("[^"]*"|\'[^\']*\')', re.I)


def sanitize_html(html: str) -> str:
    """Redact personal data in rendered HTML and drop pre-filled input values."""
    if not html:
        return html
    html = _INPUT_VALUE_RE.sub(lambda m: m.group(1) + '""', html)
    return redact_text(html)


def host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""
