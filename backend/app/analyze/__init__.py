"""Offline analyzer. Reads only saved, sanitized copies (HTML per step + HAR). It never executes
scripts and never makes network requests."""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from app.analyze import patterns as P
from app.analyze.hosts import HostAnalysis, analyze_hosts, common_service_category
from app.analyze.html_features import FormInfo, claimed_names, fingerprint, form_fields, soup_of, visible_lines
from app.analyze.identity import IdentityResult, check_identity
from app.sanitize import redact_text
from app.urls import hostname, registrable_domain
from ml.arabic import detect_lang, normalize_arabic

STRONG_BEHAVIORS = ("deposit_to_unlock", "advance_fee", "commission_transfer")
OTHER_BEHAVIORS = ("credential_request", "gambling_deposit", "investment_promise")
MEDIUM_SIGNALS = ("deposit_request", "unlock_condition", "vip_table", "invitation_code", "commission_rate",
                  "withdrawal_condition", "task_earning", "off_platform_contact", "gambling", "fake_shop_discount")
JOB_CONTEXT = re.compile(r"\b(job|jobs|work|task|tasks|position|salary|hiring|vacanc|recruit|employ|career|"
                         r"part[\s-]?time)\w*|وظيف|عمل|مهام|راتب|توظيف|شاغر", re.I)

# Structured indicator features fed to the classifier (order matters; saved with each model).
STRUCT_FEATURES = [
    "deposit_request", "unlock_condition", "deposit_to_unlock", "advance_fee", "commission_transfer",
    "commission_rate", "vip_table", "invitation_code", "withdrawal_condition", "task_earning", "messaging_link",
    "off_platform_contact", "gambling", "gambling_deposit", "investment_promise", "fake_shop_discount",
    "field_card", "field_cvv", "field_otp", "field_bank_password", "field_password", "has_aed_amount",
    "log_amounts", "log_fields", "thin_content", "registration_destinations", "company_details", "log_words",
]


@dataclass
class Indicator:
    type: str
    strength: str = "info"            # strong | medium | weak | info
    excerpt: str = ""                 # original-language, redacted, <= 200 chars
    lang: str = ""
    step: int | None = None
    host_ref: str | None = None
    host_relation: str | None = None
    context: str | None = None
    site_reported_time: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class Analysis:
    page_url: str
    page_host: str
    lang: str = ""
    word_count: int = 0
    text_ar: str = ""
    text_en: str = ""
    model_text: str = ""
    indicators: list[Indicator] = field(default_factory=list)
    behaviors: list[str] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)
    amounts: list[dict[str, Any]] = field(default_factory=list)
    form_kinds: list[str] = field(default_factory=list)
    claimed_names: list[str] = field(default_factory=list)
    identity: dict[str, Any] = field(default_factory=dict)
    registration_destinations: list[str] = field(default_factory=list)
    asset_hosts: list[str] = field(default_factory=list)
    common_services: list[dict[str, str]] = field(default_factory=list)
    messaging_links: list[str] = field(default_factory=list)
    fingerprint: list[int] = field(default_factory=list)
    form_signature: str = ""
    payment_signature: str = ""
    flags: dict[str, bool] = field(default_factory=dict)
    features: dict[str, float] = field(default_factory=dict)
    site_reported_times: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    def has(self, *types: str) -> bool:
        return any(i.type in types for i in self.indicators)


@dataclass
class AnalyzerInput:
    page_url: str
    final_url: str = ""
    steps: list[tuple[int, str, str]] = field(default_factory=list)   # (step, action, html)
    har: dict | None = None
    capture_status: str = "ok"
    http_status: int | None = None
    listing_name: str | None = None


def _excerpt(line: str, limit: int = 200) -> str:
    line = redact_text(line)
    return line if len(line) <= limit else line[: limit - 1] + "…"


def _strip_hosts(text: str) -> str:
    text = re.sub(r"(?:https?:)?//\S+", " ", text)
    text = re.sub(r"\b(?:[a-z0-9-]+\.)+(?:com|net|org|ae|shop|vip|buzz|top|xyz|online|store|quest|space|cc|icu|io|co|me|app|site|info|biz|club|live|pro|test|localhost)\b",
                  " ", text, flags=re.I)
    return text


def extract_amounts(norm_line: str) -> list[tuple[str, float]]:
    out = []
    for code, rx in P.AMOUNT_RES:
        for m in rx.finditer(norm_line):
            raw = m.group(1).replace(",", "").replace(" ", "")
            try:
                val = float(raw)
            except ValueError:
                continue
            if 0 < val < 10_000_000:
                out.append((code, val))
    return out


def analyze(inp: AnalyzerInput) -> Analysis:
    page_url = inp.final_url or inp.page_url
    host = hostname(page_url)
    an = Analysis(page_url=page_url, page_host=host)

    # ---- text per step ------------------------------------------------------------------------
    lines_by_step: list[tuple[int, str]] = []
    seen_lines: set[str] = set()
    forms = FormInfo()
    names: list[str] = []
    fp: list[int] = []
    soups = []
    for step, _action, html in inp.steps:
        if not html:
            continue
        soup = soup_of(html)
        soups.append((step, soup))
        for line in visible_lines(soup):
            if line not in seen_lines:
                seen_lines.add(line)
                lines_by_step.append((step, line))
        fi = form_fields(soup)
        known = {(f.kind, f.input_type, f.hint) for f in forms.fields}
        forms.fields.extend(f for f in fi.fields if (f.kind, f.input_type, f.hint) not in known)
        for n in claimed_names(soup, [l for s, l in lines_by_step if s == step]):
            if n not in names:
                names.append(n)
        if not fp:
            fp = fingerprint(soup)

    all_text = "\n".join(l for _, l in lines_by_step)
    title_text = ""
    if soups:
        t = soups[0][1].title
        title_text = t.string.strip() if t and t.string else ""
    an.lang = detect_lang(all_text) or detect_lang(title_text, min_letters=4)
    ar_lines = [l for _, l in lines_by_step if detect_lang(l, 3) == "ar"]
    en_lines = [l for _, l in lines_by_step if detect_lang(l, 3) in ("en", "mixed")]
    an.text_ar = redact_text("\n".join(ar_lines))[:20000]
    an.text_en = redact_text("\n".join(en_lines))[:20000]
    an.word_count = len(re.findall(r"\w+", all_text))
    an.fingerprint = fp
    an.form_signature = forms.signature()
    an.form_kinds = sorted(forms.kinds)

    norm_lines = [(s, l, normalize_arabic(l)) for s, l in lines_by_step]
    norm_all = "\n".join(n for _, _, n in norm_lines)

    def first_match(rx: re.Pattern, negatable: bool = True) -> tuple[int, str] | None:
        for s, orig, norm in norm_lines:
            for m in rx.finditer(norm):
                if negatable and P.NEGATION.search(norm[max(0, m.start() - P.NEGATION_WINDOW):m.start()]):
                    continue
                return s, orig
        return None

    def window_match(rx_a: re.Pattern, rx_b: re.Pattern, width: int = 2) -> tuple[int, str] | None:
        for i, (s, orig, norm) in enumerate(norm_lines):
            m = rx_a.search(norm)
            if not m or P.NEGATION.search(norm[max(0, m.start() - P.NEGATION_WINDOW):m.start()]):
                continue
            lo, hi = max(0, i - width), min(len(norm_lines), i + width + 1)
            if any(rx_b.search(norm_lines[j][2]) for j in range(lo, hi)):
                ctx = " … ".join(norm_lines[j][1] for j in range(max(lo, i - 1), min(hi, i + 2)))
                return s, ctx
        return None

    def add(type_: str, strength: str, hit: tuple[int, str] | None, **kw: Any) -> None:
        if hit is None:
            return
        step, orig = hit
        an.indicators.append(Indicator(type=type_, strength=strength, excerpt=_excerpt(orig),
                                       lang=detect_lang(orig, 3) or an.lang, step=step, **kw))

    job_context = bool(JOB_CONTEXT.search(norm_all))

    # ---- behaviors ----------------------------------------------------------------------------
    dep = first_match(P.DEPOSIT)
    unl = first_match(P.UNLOCK)
    add("deposit_request", "medium", dep)
    add("unlock_condition", "medium", unl)
    d2u = first_match(P.DEPOSIT_TO_UNLOCK) or (window_match(P.DEPOSIT, P.UNLOCK) if dep and unl else None)
    add("deposit_to_unlock", "strong", d2u)
    adv = first_match(P.ADVANCE_FEE)
    if adv and job_context:
        add("advance_fee", "strong", adv)
    add("commission_transfer", "strong", first_match(P.COMMISSION_TRANSFER))
    add("commission_rate", "medium", first_match(P.COMMISSION_RATE))
    vip_levels = set(re.findall(r"(?:vip|level|lv\.?|المستوى|مستوى) ?(\d{1,2})", norm_all))
    if len(vip_levels) >= 2:
        add("vip_table", "medium", first_match(P.VIP), details={"levels": sorted(vip_levels, key=int)[:12]})
    add("invitation_code", "medium", first_match(P.INVITATION))
    add("withdrawal_condition", "medium", first_match(P.WITHDRAWAL))
    add("task_earning", "medium", first_match(P.TASK_EARNING))
    gam = first_match(P.GAMBLING)
    add("gambling", "medium", gam)
    if gam and (dep or first_match(P.BONUS)):
        add("gambling_deposit", "strong", dep or first_match(P.BONUS) or gam)
    inv = first_match(P.INVESTMENT)
    add("investment_promise", "strong", inv)
    add("fake_shop_discount", "medium", first_match(P.FAKE_SHOP))
    company = first_match(P.COMPANY_DETAILS)

    # ---- amounts ------------------------------------------------------------------------------
    amounts: list[dict[str, Any]] = []
    for s, orig, norm in norm_lines:
        for code, val in extract_amounts(norm):
            if len(amounts) < 40:
                amounts.append({"currency": code, "value": val, "step": s, "excerpt": _excerpt(orig, 120)})
    an.amounts = amounts
    if amounts:
        first = amounts[0]
        an.indicators.append(Indicator(type="currency_amount", strength="info", excerpt=first["excerpt"],
                                       step=first["step"], details={"count": len(amounts),
                                       "currencies": sorted({a["currency"] for a in amounts})}))

    # ---- forms --------------------------------------------------------------------------------
    kinds = forms.kinds
    sensitive = kinds & {"card", "cvv", "otp", "bank_password"}
    if sensitive:
        an.indicators.append(Indicator(type="credential_request", strength="strong" if (sensitive - {"otp"} or len(sensitive) > 1) else "medium",
                                       excerpt=", ".join(sorted(sensitive)), details={"fields": sorted(sensitive)},
                                       step=soups[0][0] if soups else 0))
    if "password" in kinds:
        an.indicators.append(Indicator(type="password_field", strength="info", excerpt="password input present"))

    # ---- hosts ----------------------------------------------------------------------------------
    ha: HostAnalysis = analyze_hosts(host, inp.har, [(s, h) for s, _a, h in inp.steps if h])
    page_site = registrable_domain(host)
    messaging = []
    for _s, html in [(s, h) for s, _a, h in inp.steps if h]:
        for m in P.MESSAGING_HOST_RE.finditer(html):
            link = redact_text(m.group(0))[:80]
            if link not in messaging:
                messaging.append(link)
    an.messaging_links = messaging[:10]
    if messaging:
        an.indicators.append(Indicator(type="messaging_link", strength="info", excerpt=", ".join(messaging[:3])))
        if not company:
            an.indicators.append(Indicator(type="off_platform_contact", strength="medium",
                                           excerpt=", ".join(messaging[:3]),
                                           details={"company_details_found": False}))

    reg_dest, assets, commons = [], [], []
    for h, ref in sorted(ha.refs.items()):
        site = registrable_domain(h)
        cat = common_service_category(h)
        if cat:
            commons.append({"host": h, "category": cat})
            an.indicators.append(Indicator(type="common_service", strength="weak", host_ref=h,
                                           host_relation=ref.relation, context=",".join(ref.contexts[:3]),
                                           details={"category": cat}))
            continue
        if site == page_site:
            continue
        if "registration_destination" in ref.roles:
            reg_dest.append(h)
            an.indicators.append(Indicator(type="registration_destination", strength="info", host_ref=h,
                                           host_relation=ref.relation, context=",".join(ref.contexts[:3]),
                                           details={"note": "referenced only; reachability not verified"
                                                    if ref.relation == "referenced" else "also observed in traffic"}))
        elif "asset" in ref.roles or any(c.startswith("traffic:image") for c in ref.contexts):
            assets.append(h)
            an.indicators.append(Indicator(type="asset_host", strength="info", host_ref=h,
                                           host_relation=ref.relation, context=",".join(ref.contexts[:3])))
        else:
            an.indicators.append(Indicator(type="host_reference", strength="info", host_ref=h,
                                           host_relation=ref.relation, context=",".join(ref.contexts[:3])))
    an.registration_destinations = reg_dest
    an.asset_hosts = assets
    an.common_services = commons
    an.site_reported_times = dict(sorted(ha.site_times.items()))
    for ts, n in list(an.site_reported_times.items())[:10]:
        an.indicators.append(Indicator(type="site_reported_time", strength="info", site_reported_time=ts,
                                       details={"records": n, "keys": sorted(ha.site_time_keys)[:5]}))

    # Brand-like hostname pattern (e.g. <word>-vip.shop): weak, for review only, never decisive.
    labels = host.split(".")
    if len(labels) >= 2 and labels[-1] in P.SCAM_HOST_TLDS and any(P.BRANDLIKE_LABEL_RE.match(l) for l in labels[:-1]):
        an.indicators.append(Indicator(type="brandlike_hostname", strength="weak", host_ref=host,
                                       details={"note": "hostname pattern common in task-scam kits; not proof of brand misuse"}))

    # ---- claimed names + identity ---------------------------------------------------------------
    for n in ha.claimed_names_json:
        if n not in names:
            names.append(n)
    an.claimed_names = [redact_text(n) for n in names[:10]]
    for n in an.claimed_names[:3]:
        an.indicators.append(Indicator(type="brand_claim", strength="info", excerpt=n))
    ident: IdentityResult = check_identity(inp.listing_name, an.claimed_names, host)
    an.identity = ident.to_dict()
    if ident.result == "mismatch":
        an.indicators.append(Indicator(type="identity_mismatch", strength="medium",
                                       excerpt=f"{ident.listing_name} ≠ {ident.best_name}"[:200],
                                       step=soups[0][0] if soups else 0, details=ident.to_dict()))

    # ---- payment script signature ---------------------------------------------------------------
    dep_amounts = sorted({a["value"] for a in amounts if a["currency"] in ("AED", "USD", "USDT")})
    if dep_amounts and (dep or d2u or adv):
        basis = "|".join(f"{v:g}" for v in dep_amounts[:12]) + "|" + ",".join(
            sorted(i.type for i in an.indicators if i.type in STRONG_BEHAVIORS + ("deposit_request", "vip_table")))
        an.payment_signature = hashlib.sha1(basis.encode()).hexdigest()[:16]

    # ---- flags ----------------------------------------------------------------------------------
    thin = an.word_count < 25
    block = bool(P.BLOCK_PAGE.search(norm_all)) and an.word_count < 150
    signin = "password" in kinds and an.word_count < 120 and not any(
        i.strength == "strong" for i in an.indicators)
    an.flags = {
        "load_failed": inp.capture_status != "ok",
        "thin_content": thin,
        "signin_wall": signin,
        "cloaking_suspected": block or (inp.http_status in (401, 403, 429, 451, 503) and an.word_count < 150),
        "company_details": bool(company),
        "job_context": job_context,
    }

    types = {i.type for i in an.indicators}
    an.behaviors = [b for b in STRONG_BEHAVIORS + OTHER_BEHAVIORS
                    if b in types and (b != "credential_request" or
                                       any(i.type == b and i.strength == "strong" for i in an.indicators))]
    if "off_platform_contact" in types:
        an.behaviors.append("off_platform_contact")
    an.signals = [s for s in MEDIUM_SIGNALS if s in types]

    # ---- model text + structured features ---------------------------------------------------------
    an.model_text = normalize_arabic(_strip_hosts(redact_text((title_text + "\n" + all_text)[:60000])))
    an.features = build_features(an, types, kinds)
    return an


def build_features(an: Analysis, types: set[str], kinds: set[str]) -> dict[str, float]:
    f = {k: 0.0 for k in STRUCT_FEATURES}
    for k in ("deposit_request", "unlock_condition", "deposit_to_unlock", "advance_fee", "commission_transfer",
              "commission_rate", "vip_table", "invitation_code", "withdrawal_condition", "task_earning",
              "messaging_link", "off_platform_contact", "gambling", "gambling_deposit", "investment_promise",
              "fake_shop_discount"):
        f[k] = 1.0 if k in types else 0.0
    f["field_card"] = 1.0 if "card" in kinds else 0.0
    f["field_cvv"] = 1.0 if "cvv" in kinds else 0.0
    f["field_otp"] = 1.0 if "otp" in kinds else 0.0
    f["field_bank_password"] = 1.0 if "bank_password" in kinds else 0.0
    f["field_password"] = 1.0 if "password" in kinds else 0.0
    f["has_aed_amount"] = 1.0 if any(a["currency"] == "AED" for a in an.amounts) else 0.0
    f["log_amounts"] = math.log1p(len(an.amounts)) / 4
    f["log_fields"] = math.log1p(len(an.form_kinds)) / 3
    f["thin_content"] = 1.0 if an.word_count < 25 else 0.0
    f["registration_destinations"] = 1.0 if an.registration_destinations else 0.0
    f["company_details"] = 1.0 if an.flags.get("company_details") else 0.0
    f["log_words"] = math.log1p(an.word_count) / 10
    return f
