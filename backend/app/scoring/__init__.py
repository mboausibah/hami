"""Rules layer + risk tiers (scam-type agnostic).

Evidence sources: the visible page, the site's delivered code (string literals of its own JS bundles and its
build file names, read but never executed), kit fingerprints (identical / near-identical delivered files),
shared infrastructure, registrable-domain inheritance and reviewer decisions.

High risk  - a strong fraud behavior on the page AND the classifier agrees; or a strong reviewed-case link
             (registration destination, distinctive asset host, same software kit, shared infrastructure) plus
             any fraud behavior; or the host / its registrable domain was confirmed fraudulent by a reviewer;
             or the page is a sign-in wall / thin AND (several distinctive kit files match a confirmed case, OR
             strong fraud behavior is found in the delivered code and the classifier agrees on that code text).
Caution    - fraud signals without classifier agreement, a listing-identity mismatch, a page score above the
             caution threshold, a partial kit / infrastructure match with a confirmed case, or fraud behavior
             in the delivered code without a kit match.
No strong signals - otherwise; wording says it is not a guarantee.
Insufficient evidence - only when there is no usable page text, no usable code text and no kit, domain or
             infrastructure match (failed load, sign-in wall, cloaking, too little content).
Registration walls (any scam type; app/analyze/walls.py):
High risk  - invite-gated registration or a separate security/fund password AND at least one of: first certificate
             under 30 days, task-scam route vocabulary in the site's delivered pages/code, brand-bait logos, a kit
             match with a confirmed case.
Caution    - two or more registration, route or domain signals; or a registration/login wall with any scam
             registration or task-route signal.
A registration/login wall or bot-challenge page with no other evidence is Insufficient evidence, never
"No strong signals". A referral code on an established site cannot reach High on its own.
Weak signals (common analytics, CDN, hosting, payment providers, common libraries) never raise the tier alone.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.analyze import Analysis
from app.scoring import texts as T

FRAUD_BEHAVIORS = ("deposit_to_unlock", "advance_fee", "commission_transfer", "gambling_deposit",
                   "investment_promise", "credential_request")
CLUE_PRIORITY = ("identity_mismatch", "reviewed_case_exact_host", "reviewed_domain", "kit_match", "route_vocabulary",
                 "registration_gate", "young_domain", "brand_bait",
                 "deposit_to_unlock", "advance_fee", "commission_transfer", "credential_request", "gambling_deposit",
                 "investment_promise", "reviewed_case_link", "kit_partial", "code_behavior", "vip_table",
                 "withdrawal_condition", "invitation_code", "commission_rate", "off_platform_contact",
                 "deposit_request", "task_earning", "gambling", "fake_shop_discount", "no_company_identity",
                 "domain_shape", "classifier_score", "bot_challenge")
AMOUNT_CLUES = {"deposit_to_unlock", "advance_fee", "deposit_request"}
CODE_MIN_WORDS = 40


@dataclass
class ReviewedContext:
    exact_host_label: str | None = None                     # latest reviewer label for this host
    strong_links: list[dict[str, Any]] = field(default_factory=list)   # [{relation, scan_id, host, ...}]
    partial_links: list[dict[str, Any]] = field(default_factory=list)  # partial kit / infrastructure matches
    domain_inherited: dict[str, Any] | None = None          # {domain, confirmed_host, scan_id}

    @property
    def kit_strong(self) -> dict[str, Any] | None:
        return next((l for l in self.strong_links if l["relation"] == "same_kit"), None)

    @property
    def kit_partial(self) -> dict[str, Any] | None:
        return next((l for l in self.partial_links if l["relation"] == "same_kit"), None)


@dataclass
class Decision:
    tier: str
    rules_fired: list[str]
    clue_types: list[str]
    not_checked: list[str]
    headline_key: str | None = None


def decide(an: Analysis, score: float | None, thresholds: dict[str, float], ctx: ReviewedContext,
           stored: bool = False, code_score: float | None = None) -> Decision:
    agree_t = thresholds.get("threshold_agree", 0.5)
    caution_t = thresholds.get("threshold_caution", 0.35)
    fired: list[str] = []
    behaviors = [b for b in an.behaviors if b in FRAUD_BEHAVIORS]
    signals = list(an.signals)
    code_behaviors = [b for b in an.code_behaviors if b in FRAUD_BEHAVIORS]
    code_usable = an.code_word_count >= CODE_MIN_WORDS
    reviewed_legit = ctx.exact_host_label == "legitimate"
    flags = an.flags or {}
    # A classifier score on a near-empty page, a sign-in wall or a block page says nothing about the site.
    thin_page = any(flags.get(k) for k in ("load_failed", "thin_content", "signin_wall", "cloaking_suspected"))
    model_ok = score is not None and not reviewed_legit
    agree = model_ok and score >= agree_t
    above_caution = model_ok and not thin_page and score >= caution_t
    code_agree = code_score is not None and not reviewed_legit and code_score >= agree_t and code_usable
    any_fraud = bool(behaviors) or bool(signals) or bool(code_behaviors)
    not_checked = ["behind_signin", "payment_pages", "operator"]
    if score is None:
        not_checked.append("no_model")
    if stored:
        not_checked.append("stored_capture")
    if an.identity.get("result") == "unclear":
        not_checked.append("identity_unclear")
    if flags.get("bot_challenge"):
        not_checked.append("bot_challenge")

    tier = None
    headline = None
    if ctx.exact_host_label == "fraudulent":
        tier = "high_risk"
        fired.append("reviewed_case_exact_host")
    if ctx.domain_inherited and not reviewed_legit:
        tier = "high_risk"
        fired.append("reviewed_registrable_domain")
    if behaviors and agree:
        tier = "high_risk"
        fired.append("strong_behavior+classifier_agrees")
        headline = behaviors[0]
    if ctx.strong_links and any_fraud and not reviewed_legit:
        tier = "high_risk"
        fired.append("reviewed_case_link+fraud_behavior")
        headline = headline or (behaviors[0] if behaviors else None)
    # ---- registration walls / referenced routes / domain (scam-type agnostic) ----------------------------------
    from app.analyze.walls import wall_counts

    w = an.wall or {}
    ws = wall_counts(w)
    age = w.get("cert_age_days")
    gate = ws["invite_gated"] or ws["security_password"]
    route_task = w.get("route_strength") == "task"
    gate_support = [k for k, ok in (("domain_under_30_days", age is not None and age < 30),
                                    ("task_route_vocabulary", route_task),
                                    ("brand_bait_logos", ws["brand_bait"]),
                                    ("kit_match", bool(ctx.kit_strong or ctx.kit_partial))) if ok]
    if gate and gate_support and not reviewed_legit:
        tier = "high_risk"
        fired.append("registration_gate+" + "+".join(gate_support))
    if thin_page and not reviewed_legit:
        if ctx.kit_strong:
            tier = "high_risk"
            fired.append("signin_or_thin+same_kit_as_reviewed_case")
        if code_behaviors and code_agree:
            tier = "high_risk"
            fired.append("signin_or_thin+code_behavior+classifier_agrees_on_code")
            headline = headline or code_behaviors[0]

    if tier is None:
        caution_reasons = []
        if behaviors:
            caution_reasons.append("fraud_behavior_without_classifier_agreement")
        if an.identity.get("result") == "mismatch":
            caution_reasons.append("listing_identity_mismatch")
        if above_caution:
            caution_reasons.append("classifier_above_caution_threshold")
        if len(signals) >= 3:
            caution_reasons.append("multiple_fraud_signals")
        if ctx.strong_links and not reviewed_legit:
            caution_reasons.append("related_to_reviewed_case")
        if ctx.partial_links and not reviewed_legit:
            caution_reasons.append("partial_kit_or_infrastructure_match")
        # Code evidence matters most when the page itself shows little (sign-in wall / thin); on a normal content
        # page it also needs the classifier to agree on the code text.
        if code_behaviors and not reviewed_legit and (thin_page or code_agree):
            caution_reasons.append("fraud_behavior_in_delivered_code")
        wall_signals = [k for k in ("invite_gated", "security_password", "scam_register_route", "no_company_identity",
                                    "route_vocab", "brand_bait", "young_domain", "domain_shape", "h5_shell") if ws[k]]
        if len(wall_signals) >= 2 and not reviewed_legit:
            caution_reasons.append("registration_route_domain_signals:" + ",".join(wall_signals))
        elif w.get("registration_wall") and not reviewed_legit and (
                ws["security_password"] or ws["scam_register_route"] or route_task or ws["brand_bait"]
                or (ws["invite_gated"] and ws["no_company_identity"])):
            caution_reasons.append("registration_wall_with_scam_signal")
        if caution_reasons:
            tier = "caution"
            fired.extend(caution_reasons)
    elif an.identity.get("result") == "mismatch":
        fired.append("listing_identity_mismatch")

    if tier is None:
        no_match = not (ctx.strong_links or ctx.partial_links or ctx.domain_inherited)
        insufficient = []
        if not reviewed_legit and no_match and flags.get("bot_challenge"):
            insufficient.append("bot_challenge")
        elif not reviewed_legit and no_match and w.get("registration_wall") and not (behaviors or above_caution):
            insufficient.append("registration_or_login_wall")
        if not insufficient and thin_page and not code_usable and no_match:
            for k, name in (("load_failed", "load_failed"), ("signin_wall", "signin_wall"),
                            ("cloaking_suspected", "cloaking"), ("thin_content", "thin_content")):
                if flags.get(k):
                    insufficient.append(name)
        if insufficient:
            tier = "insufficient_evidence"
            fired.extend(insufficient)
            not_checked.extend(insufficient)
    if tier is None:
        tier = "no_strong_signals"
        fired.append("no_fraud_behavior_low_score" if score is not None else "no_fraud_behavior_rules_only")
        if thin_page:
            fired.append("judged_from_delivered_code")
        if reviewed_legit:
            fired.append("reviewed_legitimate")

    # Clues: strongest observed evidence first, at most 3.
    present = set(behaviors) | set(signals)
    if an.identity.get("result") == "mismatch":
        present.add("identity_mismatch")
    if ctx.exact_host_label == "fraudulent":
        present.add("reviewed_case_exact_host")
    if ctx.domain_inherited:
        present.add("reviewed_domain")
    if ctx.kit_strong:
        present.add("kit_match")
    elif ctx.kit_partial:
        present.add("kit_partial")
    if any(l["relation"] != "same_kit" for l in ctx.strong_links):
        present.add("reviewed_case_link")
    if code_behaviors or (an.code_mentions and tier in ("high_risk", "caution") and an.code_signals):
        present.add("code_behavior")
    if tier in ("high_risk", "caution") and above_caution and not behaviors:
        present.add("classifier_score")
    if tier in ("high_risk", "caution"):
        if w.get("route_strength"):
            present.add("route_vocabulary")
        if gate:
            present.add("registration_gate")
        if age is not None and age < 90:
            present.add("young_domain")
        if ws["brand_bait"]:
            present.add("brand_bait")
        if ws["no_company_identity"]:
            present.add("no_company_identity")
        if ws["domain_shape"]:
            present.add("domain_shape")
    if tier == "insufficient_evidence" and flags.get("bot_challenge"):
        present.add("bot_challenge")
    clue_types = [c for c in CLUE_PRIORITY if c in present]
    if tier in ("no_strong_signals", "insufficient_evidence"):
        clue_types = [c for c in clue_types if c in ("identity_mismatch", "bot_challenge")]
    return Decision(tier=tier, rules_fired=fired, clue_types=clue_types[:3],
                    not_checked=list(dict.fromkeys(not_checked)), headline_key=headline)


def headline(decision: Decision) -> dict[str, str]:
    if decision.tier == "high_risk" and decision.headline_key in T.BEHAVIOR_HEADLINE:
        return T.BEHAVIOR_HEADLINE[decision.headline_key]
    return T.TIER_HEADLINE[decision.tier]


def clue_text(clue_type: str, an: Analysis, ctx: ReviewedContext, excerpt: str | None = None) -> dict[str, str]:
    tmpl = T.CLUE_TEXT.get(clue_type, {"en": clue_type, "ar": clue_type})
    amount_en = amount_ar = ""
    if clue_type in AMOUNT_CLUES and an.amounts:
        # Prefer the amount stated in the cited sentence; otherwise the largest amount on the page.
        from app.analyze import extract_amounts
        from ml.arabic import normalize_arabic

        in_excerpt = [{"currency": c, "value": v} for c, v in extract_amounts(normalize_arabic(excerpt or ""))
                      if c in ("AED", "USD", "USDT")]
        a = in_excerpt[0] if in_excerpt else max(
            (x for x in an.amounts if x["currency"] in ("AED", "USD", "USDT")), key=lambda x: x["value"], default=None)
        if a:
            v = f"{a['value']:,.0f}" if a["value"] >= 10 else f"{a['value']:g}"
            amount_en = f" (amount seen: {a['currency']} {v})"
            cur_ar = {"AED": "درهم", "USD": "دولار", "USDT": "USDT"}[a["currency"]]
            amount_ar = f" (المبلغ الظاهر: {v} {cur_ar})"
    fmt_en = {"amount": amount_en, "listing": an.identity.get("listing_name", ""),
              "claimed": an.identity.get("best_name", ""), "relation": ""}
    fmt_ar = dict(fmt_en, amount=amount_ar)
    if clue_type == "kit_match" and ctx.kit_strong:
        fmt_en.update(host=ctx.kit_strong["host"], n=ctx.kit_strong["n_files"])
        fmt_ar.update(host=ctx.kit_strong["host"], n=ctx.kit_strong["n_files"])
    if clue_type == "kit_partial" and ctx.kit_partial:
        fmt_en.update(host=ctx.kit_partial["host"], n=ctx.kit_partial["n_files"])
        fmt_ar.update(host=ctx.kit_partial["host"], n=ctx.kit_partial["n_files"])
    if clue_type == "reviewed_domain" and ctx.domain_inherited:
        fmt_en.update(domain=ctx.domain_inherited["domain"])
        fmt_ar.update(domain=ctx.domain_inherited["domain"])
    if clue_type == "code_behavior":
        en, ar = T.mentions_phrase(an.code_mentions)
        fmt_en.update(things=en)
        fmt_ar.update(things=ar)
    if clue_type in ("route_vocabulary", "registration_gate", "young_domain", "brand_bait", "domain_shape"):
        from app.scoring.texts import wall_phrases

        en, ar = wall_phrases(clue_type, an.wall or {})
        fmt_en.update(things=en)
        fmt_ar.update(things=ar)
    if clue_type == "reviewed_case_link" and ctx.strong_links:
        rel = next(l for l in ctx.strong_links if l["relation"] != "same_kit")["relation"]
        fmt_en["relation"] = T.RELATION_TEXT.get(rel, {"en": rel})["en"]
        fmt_ar["relation"] = T.RELATION_TEXT.get(rel, {"ar": rel}).get("ar", rel)
    return {"en": tmpl["en"].format(**fmt_en), "ar": tmpl["ar"].format(**fmt_ar)}
