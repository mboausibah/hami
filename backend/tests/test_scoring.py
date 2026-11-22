from app.analyze import Analysis
from app.scoring import ReviewedContext, decide

T = {"threshold_agree": 0.5, "threshold_caution": 0.35}


def an(behaviors=(), signals=(), identity="not_checked", **flags):
    a = Analysis(page_url="https://x.test", page_host="x.test")
    a.behaviors = list(behaviors)
    a.signals = list(signals)
    a.identity = {"result": identity, "listing_name": "L", "best_name": "B"}
    a.flags = {"load_failed": False, "thin_content": False, "signin_wall": False, "cloaking_suspected": False, **flags}
    return a


def test_high_requires_behavior_and_classifier():
    assert decide(an(["deposit_to_unlock"]), 0.9, T, ReviewedContext()).tier == "high_risk"
    d = decide(an(["deposit_to_unlock"]), 0.2, T, ReviewedContext())
    assert d.tier == "caution" and "fraud_behavior_without_classifier_agreement" in d.rules_fired
    # no model -> never High from behavior alone
    assert decide(an(["advance_fee"]), None, T, ReviewedContext()).tier == "caution"


def test_high_from_reviewed_link_plus_fraud_behavior():
    ctx = ReviewedContext(strong_links=[{"relation": "asset_host", "scan_id": 1, "host": "cdn.x.test"}])
    assert decide(an(signals=["vip_table"]), 0.1, T, ctx).tier == "high_risk"
    # link without any fraud behavior: only Caution
    assert decide(an(), 0.1, T, ctx).tier == "caution"


def test_caution_paths():
    assert decide(an(identity="mismatch"), 0.05, T, ReviewedContext()).tier == "caution"
    assert decide(an(), 0.4, T, ReviewedContext()).tier == "caution"
    assert decide(an(signals=["vip_table", "invitation_code", "withdrawal_condition"]), 0.1, T,
                  ReviewedContext()).tier == "caution"


def test_weak_or_single_signals_do_not_raise():
    assert decide(an(signals=["task_earning"]), 0.1, T, ReviewedContext()).tier == "no_strong_signals"


def test_insufficient_evidence():
    for flag in ("load_failed", "signin_wall", "thin_content", "cloaking_suspected"):
        assert decide(an(**{flag: True}), None, T, ReviewedContext()).tier == "insufficient_evidence"
    # signals still win over thin content
    assert decide(an(["deposit_to_unlock"], thin_content=True), 0.9, T, ReviewedContext()).tier == "high_risk"


def test_reviewed_exact_host():
    assert decide(an(), 0.0, T, ReviewedContext(exact_host_label="fraudulent")).tier == "high_risk"
    d = decide(an(), 0.9, T, ReviewedContext(exact_host_label="legitimate"))
    assert d.tier == "no_strong_signals" and "reviewed_legitimate" in d.rules_fired


def test_clues_capped_at_three():
    d = decide(an(["deposit_to_unlock", "advance_fee"], ["vip_table", "invitation_code"], identity="mismatch"),
               0.9, T, ReviewedContext())
    assert len(d.clue_types) == 3 and d.clue_types[0] == "identity_mismatch"


def test_classifier_score_ignored_on_thin_or_signin_pages():
    d = decide(an(thin_content=True), 0.9, T, ReviewedContext())
    assert d.tier == "insufficient_evidence" and "classifier_above_caution_threshold" not in d.rules_fired
    assert decide(an(signin_wall=True), 0.6, T, ReviewedContext()).tier == "insufficient_evidence"
