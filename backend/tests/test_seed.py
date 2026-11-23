"""Seed indicators: a fresh install (no data/private) already knows the team's confirmed cases.

- data/seed/indicators.json loads into an empty DB, idempotently, marked "seeded from team review"
- a support subdomain of a seeded confirmed domain is High risk (registrable-domain inheritance)
- a login wall on a fictional brand that delivers the seeded kit's files is High risk (kit match), with the
  plain-language clue naming the confirmed site. Only file hashes/names from the seed file are used: no scam
  code or page content is in the repository.
"""
import hashlib
import json

import pytest

from app.config import REPO_DIR

SEED = REPO_DIR / "data" / "seed" / "indicators.json"


def _har(page_url: str, html: str, assets: list[dict]) -> str:
    entries = [{"startedDateTime": "2026-11-23T10:00:00Z", "time": 5,
                "request": {"method": "GET", "url": page_url, "headers": [], "cookies": [], "queryString": []},
                "response": {"status": 200, "headers": [], "cookies": [],
                             "content": {"mimeType": "text/html", "text": html}}}]
    base = page_url.rstrip("/")
    for a in assets:
        mime = {"js": "application/javascript", "css": "text/css", "font": "font/woff2"}[a["kind"]]
        entries.append({"startedDateTime": "2026-11-23T10:00:01Z", "time": 5,
                        "request": {"method": "GET", "url": f"{base}/assets/{a['file_name']}", "headers": [],
                                    "cookies": [], "queryString": []},
                        "response": {"status": 200, "headers": [], "cookies": [],
                                     "content": {"mimeType": mime, "_hami_sha256": a["sha256"],
                                                 "_hami_size": a["size_bytes"]}}})
    return json.dumps({"log": {"version": "1.2", "creator": {"name": "test", "version": "1"}, "entries": entries}})


def _ingest(page_url: str, html: str, assets: list[dict]) -> dict:
    from app.evidence import ingest

    text = _har(page_url, html, assets)
    return ingest(page_url, text, hashlib.sha256(text.encode()).hexdigest(), 1 + len(assets), None)


@pytest.fixture
def seeded(fresh_db):
    from app.seed import load_seed

    assert SEED.is_file(), "data/seed/indicators.json must be committed"
    first = load_seed(SEED)
    assert first["cases"] >= 1 and first["assets"] >= 3
    assert load_seed(SEED) == {"cases": 0, "hosts": 0, "assets": 0}  # idempotent
    return json.loads(SEED.read_text(encoding="utf-8"))


def test_seed_loads_as_team_reviewed_cases(seeded):
    from app.cases import high_risk_hosts, reviewed_fraud_scans
    from app.db import db

    with db() as conn:
        hosts = {s["host"] for s in reviewed_fraud_scans(conn)}
        notes = {r[0] for r in conn.execute("SELECT notes FROM reviews")}
        listed = {h["host"] for h in high_risk_hosts(conn)[0]}
    expected = {h for c in seeded["cases"] if c["label"] == "fraudulent" for h in c["hosts"]}
    assert expected <= hosts and expected <= listed  # also on the extension's local list
    assert all("seeded from team review" in n for n in notes)


def test_subdomain_of_seeded_domain_is_high(seeded):
    case = next(c for c in seeded["cases"] if c["registrable_domain"] == "aed99.com")
    assert "cs.aed99.com" not in case["hosts"]
    p = _ingest("https://cs.aed99.com/support/chat", "<html><body><h1>Customer service</h1>"
                "<p>How can we help you today?</p></body></html>", [])
    assert p["tier"] == "high_risk", p["rules_fired"]
    assert "reviewed_registrable_domain" in p["rules_fired"]


def test_login_wall_with_seeded_kit_is_high(seeded):
    case = next(c for c in seeded["cases"] if c["registrable_domain"] == "aed99.com")
    app_chunks = [a for a in case["assets"] if a["kind"] in ("js", "css")
                  and (a["chunk_name"] or "").startswith(("en-US", "views-"))][:6]
    assert len(app_chunks) >= 3
    html = ("<html><head><title>Quorvia</title></head><body><h1>Quorvia</h1><form><label>Phone number</label>"
            "<input name='phone'><label>Password</label><input type='password'><button>Log in</button></form>"
            "<a href='#'>Create account</a></body></html>")
    p = _ingest("https://www.quorvia-play.com/", html, app_chunks)
    assert p["tier"] == "high_risk", p["rules_fired"]
    assert "signin_or_thin+same_kit_as_reviewed_case" in p["rules_fired"]
    clue = next(c for c in p["clues"] if c["type"] == "kit_match")
    assert "aed99.com" in clue["text"]["en"] and "identical files" in clue["text"]["en"]


def test_seed_file_has_no_private_content():
    from app.seed import validate

    doc = json.loads(SEED.read_text(encoding="utf-8"))
    validate(doc)
    raw = SEED.read_text(encoding="utf-8")
    for bad in ("data/private", "data\\\\private", "Users\\\\", "@", "eyJhbGci", "<html", "password"):
        assert bad not in raw, bad
    bad = json.loads(json.dumps(doc))
    bad["cases"][0]["hosts"] = ["me@example.com"]
    with pytest.raises(ValueError):
        validate(bad)
