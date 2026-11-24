"""Registration walls, referenced routes, brand bait, domain shape, bot challenges and browser page signals.

All sites are fictional (testsites/sites/site-e, site-f) or built inline; no real scam domain or invite code."""
import threading

import pytest

from app.analyze import AnalyzerInput, analyze
from app.analyze.walls import brand_bait, classify_routes, domain_shape
from app.scoring import ReviewedContext, decide

TH = {"threshold_agree": 0.77, "threshold_caution": 0.55}


def test_route_vocabulary_levels():
    task = ["/index/ctrl/recharge.html", "/index/rot_order/index.html", "/index/my/invite", "/index/user/login.html"]
    groups, strength = classify_routes(task)
    assert strength == "task" and {"recharge", "task_orders", "invite"} <= set(groups)
    exchange = ["/en/deposit", "/en/withdraw", "/en/referral", "/en/vip-program"]
    assert classify_routes(exchange)[1] == "money"
    telecom = ["/personal/recharge", "/personal/offers", "/business/login", "/support/contact"]
    assert classify_routes(telecom)[1] is None
    microtask = ["/tasks", "/withdraw", "/invite", "/profile"]  # legitimate workers never deposit
    assert classify_routes(microtask)[1] is None


def test_domain_shape_and_brand_bait():
    assert domain_shape("app.k7x2qz9m.xyz") == (True, "xyz")
    assert domain_shape("www.example-careers.com") == (False, None)
    assert domain_shape("6thstreet.com")[0] is False
    assert brand_bait(["alibaba.png", "amazon.png", "logo.png", "bg1.jpg"], "k7x2qz9m.xyz") == ["alibaba", "amazon"]
    assert brand_bait(["amazon-logo.png"], "amazon.ae") == []
    assert brand_bait(["shopifyPartner.png"], "kestrel.top") == ["shopify"]


def _decide(url: str, html: str, client=None, age=None):
    an = analyze(AnalyzerInput(page_url=url, final_url=url, steps=[(0, "load", html)], har=None, client=client))
    an.wall["cert_age_days"] = age
    return decide(an, 0.2, TH, ReviewedContext()), an


def test_referral_on_established_site_is_not_high():
    html = ("<html><head><title>Sign up</title></head><body><h1>Join ExampleRides</h1><form>"
            "<input type='tel' name='phone' placeholder='Mobile number'><input type='password' name='password'>"
            "<input name='referral' value='AB12CD'></form><a href='/terms'>Terms</a> <a href='/privacy'>Privacy</a>"
            "<p>ExampleRides FZ-LLC, Dubai</p></body></html>")
    d, an = _decide("https://www.example-rides.com/invite/AB12CD", html, age=3000)
    assert an.wall["invite_gated"] and an.wall["company_identity"]
    assert d.tier != "high_risk", d.rules_fired
    assert d.tier in ("insufficient_evidence", "no_strong_signals"), d.rules_fired


def test_login_wall_without_evidence_is_never_no_strong_signals():
    html = ("<html><head><title>Login</title></head><body><form><input name='user' placeholder='Username'>"
            "<input type='password' name='password'></form><a href='/privacy'>Privacy</a></body></html>")
    d, _ = _decide("https://portal.example-company.com/login", html, age=2000)
    assert d.tier == "insufficient_evidence" and "registration_or_login_wall" in d.rules_fired


def test_young_domain_plus_invite_gate_is_high():
    html = ("<html><head><title>Register</title></head><body><form><input type='tel' name='tel' placeholder='+971'>"
            "<input type='password' name='pwd'></form></body></html>")
    d, _ = _decide("https://m.k7x2qz9m.xyz/index/user/register/invite_code/AB12CD.html", html, age=12)
    assert d.tier == "high_risk" and any(r.startswith("registration_gate+domain_under_30_days") for r in d.rules_fired)


@pytest.fixture(scope="module")
def sites():
    from app import db as dbmod
    from app.testsites import make_server

    dbmod.reset_init_cache()
    srv = make_server(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield lambda path: f"http://{path.split('/')[0]}.localhost:{srv.server_address[1]}/" + "/".join(path.split("/")[1:])
    srv.shutdown()


def test_invite_gated_wall_with_task_routes_in_lazy_chunk(sites):
    from app.db import db
    from app.pipeline import submit_scan

    p = submit_scan(sites("site-e/index/user/register/invite_code/QV7K2M.html"), "extension", force=True)
    assert p["tier"] == "high_risk", p["rules_fired"]
    assert any(r.startswith("registration_gate+") and "task_route_vocabulary" in r for r in p["rules_fired"])
    texts = " ".join(c["text"]["en"] for c in p["clues"])
    assert "invite code and a separate security password" in texts and "rotation-order" in texts
    with db() as conn:
        log = [r["path"] for r in conn.execute("SELECT path FROM artifacts WHERE scan_id=? AND kind='action_log' "
                                                "AND action_name IS NULL", (p["scan_id"],))]
    from app.storage import read_artifact

    assert any(b"chunk_fetch" in read_artifact(x) for x in log), "the lazy route chunk was fetched"


def test_bot_challenge_then_browser_signals(sites):
    from app.db import db
    from app.pipeline import submit_scan

    url = sites("site-f/index/user/register/invite_code/ZX81PQ.html")
    server_only = submit_scan(url, "extension", force=True)
    assert server_only["tier"] != "no_strong_signals", server_only["rules_fired"]
    assert server_only["tier"] in ("caution", "insufficient_evidence")
    signals = {
        "page_url": url, "title": "Mobile phone number login", "lang": "en",
        "text": "Mobile phone number login\nPhone number +971\nPassword\nLogin Register\nCopyright (c) 2026",
        "paths": ["/index/ctrl/recharge.html", "/index/rot_order/index.html", "/index/my/invite", "/index/user/login.html"],
        "images": ["bg1.jpg", "touch.png"],
        "fields": [{"type": "tel", "name": "username", "placeholder": "Enter mobile number"},
                   {"type": "password", "name": "password", "placeholder": "your password"},
                   {"type": "password", "name": "paypassword", "placeholder": "Security password"}],
        "identity_links": False,
    }
    with_browser = submit_scan(url, "extension", page_signals=signals)
    assert with_browser["tier"] == "high_risk", with_browser["rules_fired"]
    with db() as conn:
        flag = conn.execute("SELECT client_signals FROM scans WHERE scan_id=?", (with_browser["scan_id"],)).fetchone()[0]
    assert flag == 1
    # A later check without browser signals is never served the browser-signal result from the cache.
    again = submit_scan(url, "extension")
    assert again["scan_id"] != with_browser["scan_id"] and again["tier"] == server_only["tier"]
    # Signals for a different site are ignored.
    other = submit_scan(url, "extension", page_signals=dict(signals, page_url="https://elsewhere.example/"))
    assert other["tier"] == server_only["tier"]
