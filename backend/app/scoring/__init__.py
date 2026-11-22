"""Rules layer + risk tiers (exactly as in the proposal).

High risk  - a strong fraud behavior (deposit to unlock / advance fee / commission for moving money,
             plus gambling deposits, guaranteed-return investment and card/OTP credential requests)
             AND the classifier agrees; or a strong reviewed-case link plus any fraud behavior;
             or the exact host was confirmed fraudulent by a reviewer.
Caution    - fraud signals without classifier agreement / a payment request, a listing-identity
             mismatch, or a classifier score above the caution threshold.
No strong signals - otherwise; wording says it is not a guarantee.
Insufficient evidence - failed load, sign-in wall, cloaking suspected or too little content.
Weak signals (common analytics, CDN, hosting, payment providers) never raise the tier alone.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.analyze import Analysis
from app.scoring import texts as T

FRAUD_BEHAVIORS = ("deposit_to_unlock", "advance_fee", "commission_transfer", "gambling_deposit",
                   "investment_promise", "credential_request")
CLUE_PRIORITY = ("identity_mismatch", "reviewed_case_exact_host", "deposit_to_unlock", "advance_fee",
                 "commission_transfer", "credential_request", "gambling_deposit", "investment_promise",
                 "reviewed_case_link", "vip_table", "withdrawal_condition", "invitation_code", "commission_rate",
                 "off_platform_contact", "deposit_request", "task_earning", "gambling", "fake_shop_discount",
                 "classifier_score")
AMOUNT_CLUES = {"deposit_to_unlock", "advance_fee", "deposit_request"}


@dataclass
class ReviewedContext:
    exact_host_label: str | None = None                     # latest reviewer label for this host
    strong_links: list[dict[str, Any]] = field(default_factory=list)  # [{relation, scan_id, host}]


@dataclass
class Decision:
    tier: str
    rules_fired: list[str]
    clue_types: list[str]
    not_checked: list[str]
    headline_key: str | None = None


def decide(an: Analysis, score: float | None, thresholds: dict[str, float], ctx: ReviewedContext,
           stored: bool = False) -> Decision:
    agree_t = thresholds.get("threshold_agree", 0.5)
    caution_t = thresholds.get("threshold_caution", 0.35)
    fired: list[str] = []
    behaviors = [b for b in an.behaviors if b in FRAUD_BEHAVIORS]
    signals = list(an.signals)
    reviewed_legit = ctx.exact_host_label == "legitimate"
    model_ok = score is not None and not reviewed_legit
    agree = model_ok and score >= agree_t
    above_caution = model_ok and score >= caution_t
    any_fraud = bool(behaviors) or bool(signals)
    flags = an.flags or {}
    not_checked = ["behind_signin", "payment_pages", "operator"]
    if score is None:
        not_checked.append("no_model")
    if stored:
        not_checked.append("stored_capture")
    if an.identity.get("result") == "unclear":
        not_checked.append("identity_unclear")

    tier = None
    headline = None
    if ctx.exact_host_label == "fraudulent":
        tier = "high_risk"
        fired.append("reviewed_case_exact_host")
    if behaviors and agree:
        tier = "high_risk"
        fired.append("strong_behavior+classifier_agrees")
        headline = behaviors[0]
    if ctx.strong_links and any_fraud:
        tier = "high_risk"
        fired.append("reviewed_case_link+fraud_behavior")
        headline = headline or (behaviors[0] if behaviors else None)

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
        if ctx.strong_links:
            caution_reasons.append("related_to_reviewed_case")
        if caution_reasons:
            tier = "caution"
            fired.extend(caution_reasons)
    elif an.identity.get("result") == "mismatch":
        fired.append("listing_identity_mismatch")

    if tier is None:
        insufficient = []
        if flags.get("load_failed"):
            insufficient.append("load_failed")
        if flags.get("signin_wall"):
            insufficient.append("signin_wall")
        if flags.get("cloaking_suspected"):
            insufficient.append("cloaking")
        if flags.get("thin_content"):
            insufficient.append("thin_content")
        if insufficient:
            tier = "insufficient_evidence"
            fired.extend(insufficient)
            not_checked.extend(insufficient)
    if tier is None:
        tier = "no_strong_signals"
        fired.append("no_fraud_behavior_low_score" if score is not None else "no_fraud_behavior_rules_only")
        if reviewed_legit:
            fired.append("reviewed_legitimate")

    # Clues: strongest observed evidence first, at most 3.
    present = set(behaviors) | set(signals)
    if an.identity.get("result") == "mismatch":
        present.add("identity_mismatch")
    if ctx.exact_host_label == "fraudulent":
        present.add("reviewed_case_exact_host")
    if ctx.strong_links:
        present.add("reviewed_case_link")
    if tier in ("high_risk", "caution") and above_caution and not behaviors:
        present.add("classifier_score")
    clue_types = [c for c in CLUE_PRIORITY if c in present]
    if tier in ("no_strong_signals", "insufficient_evidence"):
        clue_types = [c for c in clue_types if c in ("identity_mismatch",)]
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
    if clue_type == "reviewed_case_link" and ctx.strong_links:
        rel = ctx.strong_links[0]["relation"]
        fmt_en["relation"] = T.RELATION_TEXT.get(rel, {"en": rel})["en"]
        fmt_ar["relation"] = T.RELATION_TEXT.get(rel, {"ar": rel}).get("ar", rel)
    return {"en": tmpl["en"].format(**fmt_en), "ar": tmpl["ar"].format(**fmt_ar)}
