import json

from app.analyze import AnalyzerInput, analyze
from app.analyze.html_features import fingerprint, fingerprint_similarity, soup_of
from app.analyze.identity import check_identity

SCAM_AR = """<html><head><title>نوفا مارت VIP | مهام يومية</title></head><body>
<header><img class="logo" alt="NovaMart VIP" src="https://cdn.novalogo-assets.test/logo.png"></header>
<h1>NovaMart VIP</h1>
<p>اربح يوميًا من إكمال المهام اليومية وتقييم المنتجات</p>
<table><tr><td>VIP 1</td><td>عمولة 0.5%</td></tr><tr><td>VIP 2</td><td>عمولة 1%</td></tr></table>
<p>اشحن ٥٠٠ درهم لفتح المهام المدفوعة</p>
<p>الحد الأدنى للسحب 100 درهم بعد إكمال 30 مهمة</p>
<label for="inv">رمز الدعوة</label><input id="inv" name="invite_code">
<a href="https://wa.me/971501234567">خدمة العملاء</a>
<script src="https://cdnjs.cloudflare.com/ajax/libs/jquery/3.7.1/jquery.min.js"></script>
</body></html>"""

LEGIT_EN = """<html><head><title>Example Careers - Jobs at Example Logistics</title></head><body>
<nav><a href="/about">About us</a><a href="/jobs">Jobs</a></nav>
<h1>Join Example Logistics</h1><p>We are hiring warehouse supervisors in Dubai. Competitive salary,
health insurance and annual leave. We never ask candidates for any payment.</p>
<p>Apply through our careers portal. Trade licence 123456. Privacy policy. Terms and conditions.</p>
<footer>© 2026 Example Logistics LLC. All rights reserved.</footer></body></html>"""


def run(html, listing=None, har=None):
    return analyze(AnalyzerInput(page_url="https://novamart-vip.shop/", steps=[(0, "load", html)], har=har,
                                 listing_name=listing))


def test_scam_page_behaviors_ar():
    an = run(SCAM_AR)
    types = {i.type for i in an.indicators}
    assert "deposit_to_unlock" in an.behaviors
    for t in ("vip_table", "invitation_code", "withdrawal_condition", "commission_rate", "task_earning",
              "off_platform_contact"):
        assert t in types, t
    assert any(a["currency"] == "AED" and a["value"] == 500 for a in an.amounts)
    assert an.lang == "ar"
    assert "cdn.novalogo-assets.test" in an.asset_hosts
    assert any(c["host"] == "cdnjs.cloudflare.com" for c in an.common_services)
    assert an.payment_signature
    # Hostnames never reach the model text; phone numbers are redacted.
    assert "novalogo" not in an.model_text and "971501234567" not in json.dumps(an.to_dict(), ensure_ascii=False)


def test_legit_page_no_behaviors():
    an = run(LEGIT_EN)
    assert an.behaviors == []
    assert len(an.signals) < 2
    assert an.flags["company_details"]
    assert "Example Logistics" in " ".join(an.claimed_names)


def test_identity_mismatch_flagged():
    an = run(SCAM_AR, listing="Al Noor Manpower Services")
    assert an.identity["result"] == "mismatch"
    assert any(i.type == "identity_mismatch" for i in an.indicators)


def test_identity_match_arabic_normalized():
    r = check_identity("مؤسسة النور للتوظيف", ["النُّور للتوظيف | الرئيسية"])
    assert r.result == "match"
    assert check_identity("Example Logistics", ["Example Logistics LLC"]).result == "match"
    assert check_identity(None, ["x"]).result == "not_checked"


def test_registration_destinations_from_json():
    har = {"log": {"entries": [{
        "request": {"method": "GET", "url": "https://novamart-vip.shop/api/countries.json"},
        "response": {"status": 200, "content": {"mimeType": "application/json", "text": json.dumps({"data": [
            {"name": "UAE", "domainUrl": "https://orbita-mall.shop/register", "logoUrl": "https://cdn.novalogo-assets.test/l.png",
             "updateTime": "2026-11-03 10:00:00"}]})}}}]}}
    an = run(SCAM_AR, har=har)
    assert "orbita-mall.shop" in an.registration_destinations
    assert an.site_reported_times == {"2026-11-03 10:00:00": 1}
    rd = [i for i in an.indicators if i.type == "registration_destination"][0]
    assert rd.host_relation == "referenced" and rd.context == "json:domainUrl"


def test_thin_and_failed():
    an = analyze(AnalyzerInput(page_url="https://x.test/", steps=[], capture_status="load_failed"))
    assert an.flags["load_failed"] and an.flags["thin_content"]


def test_fingerprint_similarity():
    a = fingerprint(soup_of(SCAM_AR))
    b = fingerprint(soup_of(SCAM_AR.replace("NovaMart", "OrbitaMall")))
    c = fingerprint(soup_of(LEGIT_EN))
    assert fingerprint_similarity(a, b) == 1.0
    assert fingerprint_similarity(a, c) < 0.5
