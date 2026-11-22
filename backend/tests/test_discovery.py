from datetime import datetime, timedelta, timezone

from app.db import db
from app.discovery import worker as W


def cfg():
    return W.load_patterns(None)


def test_name_patterns():
    c = cfg()
    assert W.match_name("*.novamart-vip.shop", c) == "brandlike_vip"
    assert W.match_name("uae2.orbitamall.buzz", c) == "country_portal"
    assert W.match_name("dubai-jobs-online.com", c) == "uae_terms"
    assert W.match_name("grab-orders-vip.top", c) == "task_order_portal"
    assert W.match_name("wazifa-now.online", c) == "arabic_transliteration"
    assert W.match_name("www.example.com", c) is None
    assert W.match_name("mail.novamart-vip.shop", c) is None  # infrastructure noise excluded
    assert W.match_name("not a host", c) is None


def test_reviewed_case_terms_added(fresh_db):
    from app import services
    from app.db import utcnow

    with db() as conn:
        sid = conn.execute("INSERT INTO scans (submitted_url, normalized_url, host, source_type, submitted_at, status) "
                           "VALUES ('https://xb.zentora-vip.shop/','https://xb.zentora-vip.shop/','xb.zentora-vip.shop',"
                           "'manual',?, 'done')", (utcnow(),)).lastrowid
        services.create_review(conn, sid, "fraudulent", "rev")
        c = W.load_patterns(conn)
    assert "zentora-vip.shop" in c["certspotter_domains"]
    assert "%zentora-vip%" in c["crtsh_queries"]
    assert W.match_name("kw.zentoravip.store", c) in ("reviewed_case_term:zentora-vip", "brandlike_vip")


def test_enqueue_only_recent_matches(fresh_db):
    now = datetime.now(timezone.utc)
    cands = [W.Candidate("om.novamart-vip.shop", now.isoformat(), "test"),
             W.Candidate("old.novamart-vip.shop", (now - timedelta(days=90)).isoformat(), "test"),
             W.Candidate("bank.example.com", now.isoformat(), "test")]
    assert W.enqueue(cands, cfg()) == 1
    assert W.enqueue(cands, cfg()) == 0  # already queued
    with db() as conn:
        rows = conn.execute("SELECT domain, status, source, matched_pattern FROM discovered_domains").fetchall()
    assert [tuple(r) for r in rows] == [("om.novamart-vip.shop", "queued", "ct", "brandlike_vip")]
