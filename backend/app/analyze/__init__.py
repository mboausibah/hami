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
JOB_NEAR = re.compile(r"\b(job|jobs|position|salary|hiring|vacanc\w*|recruit\w*|employ\w*|candidate|interview|"
                      r"tasks?|work permit|visa|offer letter)\b|وظيف|توظيف|راتب|شاغر|مهام|مقابله|تاشيره", re.I)
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
    source: str = "visible_page"      # visible_page | delivered_code | asset_name | traffic


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
    # Delivered files and the site's own code (read, never executed).
    assets: list[dict[str, Any]] = field(default_factory=list)
    code_text: str = ""
    code_word_count: int = 0
    code_behaviors: list[str] = field(default_factory=list)
    code_signals: list[str] = field(default_factory=list)
    code_mentions: dict[str, int] = field(default_factory=dict)
    code_features: dict[str, float] = field(default_factory=dict)
    wall: dict[str, Any] = field(default_factory=dict)     # registration wall, routes, brand bait, domain shape

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
    client: dict | None = None        # page as rendered in the user's browser (extension; structure only)


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


def detect_behaviors(norm_lines: list[tuple[int, str, str]], lang: str, source: str,
                     combine: bool = True) -> tuple[list[Indicator], dict[str, Any]]:
    """Scam-type agnostic behavior detection over (step, original line, normalized line) tuples. Used for the
    visible page, the site's delivered code strings and its build file names alike."""
    out: list[Indicator] = []
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
        out.append(Indicator(type=type_, strength=strength, excerpt=_excerpt(orig),
                                 lang=detect_lang(orig, 3) or lang, step=step, source=source, **kw))

    job_context = bool(JOB_CONTEXT.search(norm_all))

    # ---- behaviors ----------------------------------------------------------------------------
    dep = first_match(P.DEPOSIT)
    unl = first_match(P.UNLOCK)
    add("deposit_request", "medium", dep)
    add("unlock_condition", "medium", unl)
    # combine=False (delivered code: unrelated strings in arbitrary order) -> only single-string phrases count.
    d2u = first_match(P.DEPOSIT_TO_UNLOCK) or (window_match(P.DEPOSIT, P.UNLOCK) if dep and unl and combine else None)
    add("deposit_to_unlock", "strong", d2u)
    # The fee and the job/task wording must appear in the same passage (not a fee anywhere + "jobs" in a footer).
    adv = window_match(P.ADVANCE_FEE, JOB_NEAR, width=1) if first_match(P.ADVANCE_FEE) else None
    if adv and job_context:
        add("advance_fee", "strong", adv)
    elif P.PARCEL_CONTEXT.search(norm_all):
        adv = first_match(P.PARCEL_FEE)
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
    if gam and combine and (dep or first_match(P.BONUS)):
        add("gambling_deposit", "strong", dep or first_match(P.BONUS) or gam)
    inv = first_match(P.INVESTMENT)
    add("investment_promise", "strong", inv)
    add("fake_shop_discount", "medium", first_match(P.FAKE_SHOP))
    company = first_match(P.COMPANY_DETAILS)

    return out, {"job_context": job_context, "company": company, "dep": dep, "d2u": d2u, "adv": adv}


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

    # Bot-challenge / block page (e.g. "Just a moment..." interstitials): the server never saw the site itself.
    server_text = normalize_arabic("\n".join(l for _, l in lines_by_step))
    server_words = len(re.findall(r"\w+", server_text))
    challenge_traffic = any("/cdn-cgi/challenge-platform/" in (e.get("request", {}).get("url", "") or "")
                            for e in ((inp.har or {}).get("log", {}).get("entries", []) or [])[:60])
    bot_challenge = (bool(P.BLOCK_PAGE.search(server_text)) and server_words < 150) or (
        challenge_traffic and server_words < 150)
    client = inp.client if isinstance(inp.client, dict) else None
    if client:
        # The page the user's own browser rendered. When the server only saw a challenge or a near-empty page, its
        # text replaces the server text; otherwise new lines are added. Structure only arrives redacted.
        client_lines = [l.strip()[:400] for l in str(client.get("text") or "").splitlines() if l.strip()][:400]
        if bot_challenge or server_words < 40:
            lines_by_step, seen_lines = [], set()
        for line in client_lines:
            if line not in seen_lines:
                seen_lines.add(line)
                lines_by_step.append((0, line))
        if client.get("fields"):
            from html import escape

            snippet = "".join(
                f'<input type="{escape(str(f.get("type") or "text")[:20])}" name="{escape(str(f.get("name") or "")[:80])}" '
                f'placeholder="{escape(str(f.get("placeholder") or "")[:80])}" aria-label="{escape(str(f.get("label") or "")[:80])}">'
                for f in client.get("fields", [])[:60] if isinstance(f, dict))
            fi = form_fields(soup_of(f"<form>{snippet}</form>"))
            known = {(f.kind, f.input_type, f.hint) for f in forms.fields}
            forms.fields.extend(f for f in fi.fields if (f.kind, f.input_type, f.hint) not in known)
        if client.get("title") and not names:
            names.append(str(client["title"])[:120])

    all_text = "\n".join(l for _, l in lines_by_step)
    title_text = ""
    if soups:
        t = soups[0][1].title
        title_text = t.string.strip() if t and t.string else ""
    if client and (bot_challenge or not title_text):
        title_text = str(client.get("title") or "")[:200]
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
    page_inds, ctx_flags = detect_behaviors(norm_lines, an.lang, "visible_page")
    an.indicators.extend(page_inds)
    job_context, company, dep, d2u, adv = (ctx_flags["job_context"], ctx_flags["company"], ctx_flags["dep"],
                                           ctx_flags["d2u"], ctx_flags["adv"])

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
        "bot_challenge": bot_challenge and not client,
        "user_browser": bool(client),
    }
    if client and an.word_count >= 25:
        # The user's browser saw the real page: a server-side block is no longer the whole story.
        an.flags["cloaking_suspected"] = False
        an.flags["thin_content"] = False
    _wall_indicators(an, inp, soups, lines_by_step, bool(company), client, bot_challenge)

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
    analyze_code(an, inp.har)
    return an


# Keyword groups counted in the site's own code (for plain-language clues and code-only behaviors).
MENTION_GROUPS: dict[str, re.Pattern] = {
    "deposits": re.compile(r"\b(deposit|deposits|recharge|top ?up|topup)\b|ايداع|شحن", re.I),
    "withdrawals": re.compile(r"\b(withdraw|withdrawal|withdrawals|cash ?out)\b|سحب", re.I),
    "vip": re.compile(r"\bvip\d*\b", re.I),
    "bonuses": re.compile(r"\b(bonus|bonuses|cashback|rebate)\b|مكافاه|بونص", re.I),
    "betting": re.compile(r"\b(bet|bets|betting|casino|slot games?|slot machines?|jackpot|roulette|baccarat|lucky ?spin|sportsbook)\b"
                          r"|رهان|كازينو", re.I),
    "invitations": re.compile(r"\b(invite|invitation|referral|inviter|agent)\b|دعوه|احاله", re.I),
    "commissions": re.compile(r"\b(commission|commissions)\b|عموله", re.I),
    "tasks": re.compile(r"\b(task|tasks|grab order|daily orders|mission)\b|مهام|مهمه", re.I),
    "returns": re.compile(r"\b(daily (profit|income|return)s?|guaranteed (profit|return|income)s?|profit rate)\b"
                          r"|ارباح (يوميه|مضمونه)|عائد (يومي|مضمون)", re.I),
    "card_or_otp": re.compile(r"\b(card number|cvv|cvc|otp|one-time password|expiry date)\b|رقم البطاقه|رمز التحقق", re.I),
}


CODE_EXCLUDED_BEHAVIORS = ("credential_request", "advance_fee")


def analyze_code(an: Analysis, har: dict | None) -> None:
    """Fingerprint delivered files and read the site's own code strings (never executed)."""
    from app.analyze.assets import asset_rows, code_strings, extract_assets

    assets = extract_assets(har)
    an.assets = asset_rows(assets)
    strings, names = code_strings(assets)
    norm_code = [(0, x, normalize_arabic(x)) for x in strings]
    norm_names = [(0, x, normalize_arabic(x)) for x in names]
    code_inds, _ = detect_behaviors(norm_code, an.lang, "delivered_code", combine=False)
    name_inds, _ = detect_behaviors(norm_names, an.lang, "asset_name", combine=False)
    seen = set()
    for ind in code_inds + name_inds:
        if ind.type not in seen:
            seen.add(ind.type)
            an.indicators.append(ind)
    blob = "\n".join(n for _, _, n in norm_code + norm_names)
    mentions = {k: len(rx.findall(blob)) for k, rx in MENTION_GROUPS.items()}
    an.code_mentions = {k: v for k, v in mentions.items() if v}
    behaviors = [b for b in STRONG_BEHAVIORS + OTHER_BEHAVIORS if b in seen]
    # Combinations of what the code talks about, mapped onto the existing behavior tags.
    m = mentions
    # Thresholds need scam-specific vocabulary: legitimate shops, wallets and investment apps also mention
    # deposits, VIP tiers or returns, but not VIP levels together with paid tasks / invite codes.
    if m["deposits"] >= 3 and m["betting"] >= 3:
        behaviors.append("gambling_deposit")
    if m["deposits"] >= 3 and ((m["vip"] >= 3 and (m["tasks"] >= 2 or m["invitations"] >= 3)) or m["tasks"] >= 3):
        behaviors.append("deposit_to_unlock")
    if m["deposits"] >= 2 and m["returns"] >= 2:
        behaviors.append("investment_promise")
    # Card/OTP wording and generic "fee" text are normal in legitimate checkout and payment code: only an actual
    # form on the page counts for those. Code evidence is limited to platform behaviors.
    an.code_behaviors = [b for b in dict.fromkeys(behaviors) if b not in CODE_EXCLUDED_BEHAVIORS]
    an.code_signals = [x for x in MEDIUM_SIGNALS if x in seen]
    if an.code_behaviors:
        an.indicators.append(Indicator(
            type="code_behavior", strength="medium", source="delivered_code",
            excerpt=", ".join(f"{k} x{v}" for k, v in sorted(an.code_mentions.items(), key=lambda kv: -kv[1])[:6]),
            details={"behaviors": an.code_behaviors, "mentions": an.code_mentions}))
    an.code_text = normalize_arabic(_strip_hosts(redact_text("\n".join(strings + names))))[:80000]
    an.code_word_count = len(re.findall(r"\w+", an.code_text))
    ctypes = seen | set(an.code_behaviors)
    f = build_features(an, ctypes, set())
    f["thin_content"] = 0.0
    f["log_words"] = math.log1p(an.code_word_count) / 10
    f["company_details"] = 0.0
    an.code_features = f



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


def _wall_indicators(an: Analysis, inp: AnalyzerInput, soups: list, lines_by_step: list, company: bool,
                     client: dict | None, bot_challenge: bool) -> None:
    """Registration wall, referenced routes, brand-bait images and domain shape (see app/analyze/walls.py)."""
    from app.analyze.walls import ROUTE_LABEL, analyze_wall

    htmls = [h for _s, _a, h in inp.steps if h]
    w = analyze_wall(an.page_url or inp.page_url, [s for _st, s in soups], htmls, inp.har,
                     [l for _s, l in lines_by_step], company, client, bot_challenge)
    an.wall = w.to_dict()
    src = "user_browser" if client and not w.path_sources.get("capture") else "referenced_routes"
    if w.route_strength:
        groups = [g for g in ROUTE_LABEL if g in w.route_groups]
        an.indicators.append(Indicator(
            type="route_vocabulary", strength="strong" if w.route_strength == "task" else "medium",
            excerpt=", ".join(w.route_groups[g] for g in groups[:5])[:200], source=src,
            details={"groups": groups, "strength": w.route_strength, "paths_seen": len(w.paths),
                     "from": w.path_sources}))
    if w.brand_bait:
        an.indicators.append(Indicator(type="brand_bait", strength="medium", excerpt=", ".join(w.brand_bait[:6]),
                                       source="asset_name", details={"brands": w.brand_bait[:10]}))
    if w.invite_gated:
        an.indicators.append(Indicator(type="invite_gated_registration", strength="medium",
                                       excerpt="invite code in the address" if w.invite_gated == "url"
                                       else "required or pre-filled invitation-code field",
                                       source="page_structure", details={"how": w.invite_gated}))
    if w.security_password:
        an.indicators.append(Indicator(type="security_password", strength="medium",
                                       excerpt={"field": "separate security/fund password field",
                                                "text": "page asks for a security/fund password",
                                                "route": "security-password route referenced"}[w.security_password],
                                       source="page_structure", details={"how": w.security_password}))
    if w.phone_only:
        an.indicators.append(Indicator(type="phone_only_signup", strength="weak",
                                       excerpt=f"phone number only{(' (' + w.country_code + ')') if w.country_code else ''}, no e-mail",
                                       source="page_structure"))
    if w.registration_wall and not w.company_identity:
        an.indicators.append(Indicator(type="no_company_identity", strength="weak",
                                       excerpt="no company name, address, terms, privacy or contact link",
                                       source="page_structure"))
    if w.scam_register_route:
        an.indicators.append(Indicator(type="scam_register_route", strength="medium",
                                       excerpt=urlsplit_path(an.page_url)[:120], source="page_structure"))
    if w.h5_shell:
        an.indicators.append(Indicator(type="h5_app_shell", strength="weak", excerpt="uni-app / H5 app shell",
                                       source="page_structure"))
    if w.random_label or w.abused_tld:
        an.indicators.append(Indicator(type="domain_shape", strength="weak", host_ref=an.page_host,
                                       details={"random_label": w.random_label, "abused_tld": w.abused_tld},
                                       source="domain"))
    if bot_challenge and not client:
        an.indicators.append(Indicator(type="bot_challenge", strength="info",
                                       excerpt="bot-challenge page instead of the site", source="visible_page"))


def urlsplit_path(url: str) -> str:
    from urllib.parse import urlsplit

    return urlsplit(url).path
