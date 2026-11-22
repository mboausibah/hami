"""Linking, clusters, pending alerts and the case brief on the synthetic test sites A, B, C."""
import uuid

import pytest

from app import services
from app.db import db
from app.linking.brief import brief_markdown, build_brief
from app.linking.clusters import cluster_of
from app.pipeline import submit_scan


@pytest.fixture(scope="module")
def sites():
    from app.testsites import make_server
    import threading

    srv = make_server(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    yield lambda name: f"http://{name}.localhost:{port}/"
    srv.shutdown()


def test_rebrand_links_and_alert_flow(sites):
    a = submit_scan(sites("site-a"), "maps", listing_name="Al Noor Manpower Services", force=True)
    assert a["tier"] == "high_risk"
    assert any(c["type"] == "identity_mismatch" for c in a["clues"])
    watcher, other = str(uuid.uuid4()), str(uuid.uuid4())
    with db() as conn:
        services.create_watch(conn, a["scan_id"], watcher)

    b = submit_scan(sites("site-b"), "manual", force=True)
    with db() as conn:
        links = [services.link_dict(l) for l in conn.execute(
            "SELECT * FROM links WHERE scan_b=? AND host_a='site-a.localhost'", (b["scan_id"],))]
        assert links, "rebrand B should be proposed as related to A"
        link = links[0]
        relations = {e["relation"]: e for e in link["evidence"]}
        assert link["strength"] == "strong" and link["review_status"] == "pending"
        assert "registration_destination" in relations and "asset_host" in relations
        assert relations["registration_destination"]["obs_ids"] and relations["asset_host"]["artifact_ids"]
        pending = conn.execute("SELECT * FROM alerts WHERE link_id=? AND watched_host='site-a.localhost'",
                               (link["link_id"],)).fetchone()
        assert pending is not None and pending["status"] == "pending"
        # Nothing reaches the watcher before review.
        assert services.alerts_for_device(conn, watcher) == []
        with pytest.raises(services.ServiceError):
            services.approve_alert(conn, pending["alert_id"], "rev")  # link not approved yet
        services.review_link(conn, link["link_id"], "approve", "rev")
        services.approve_alert(conn, pending["alert_id"], "rev")
        got = services.alerts_for_device(conn, watcher)
        assert len([g for g in got if g["alert_id"] == pending["alert_id"]]) == 1
        assert "site-b" in got[0]["reason"]["en"] and got[0]["reason"]["ar"]
        assert services.alerts_for_device(conn, other) == []
        # Withdrawal stays visible, flagged.
        services.withdraw_alert(conn, pending["alert_id"], "rev", "duplicate of an earlier alert")
        got = [g for g in services.alerts_for_device(conn, watcher) if g["alert_id"] == pending["alert_id"]][0]
        assert got["withdrawn"] and got["withdrawn_reason"]

        cid, members = cluster_of(conn, b["scan_id"])
        assert a["scan_id"] in members and b["scan_id"] in members
        brief = build_brief(conn, cid)
    hosts = {s["host"] for s in brief["sites"]}
    assert {"site-a[.]localhost", "site-b[.]localhost"} <= hosts
    assert brief["links"] and brief["links"][0]["evidence"][0]["artifacts"][0]["sha256"]
    assert brief["observations"] and brief["inferences"]
    md = brief_markdown(brief)
    assert "Direct observations" in md and "Inferences (not observations)" in md and "hxxp" in md

    c = submit_scan(sites("site-c"), "manual", force=True)
    assert c["tier"] != "high_risk"
    with db() as conn:
        common = conn.execute("SELECT host_ref FROM observations WHERE scan_id=? AND indicator_type='common_service'",
                              (c["scan_id"],)).fetchall()
        assert {r[0] for r in common} & {"cdnjs.cloudflare.com", "static.cloudflareinsights.com"}
        assert conn.execute("SELECT COUNT(*) FROM links WHERE scan_a=? OR scan_b=?",
                            (c["scan_id"], c["scan_id"])).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM alerts WHERE related_scan_id=?", (c["scan_id"],)).fetchone()[0] == 0
        cid_c, _ = cluster_of(conn, c["scan_id"])
        assert cid_c is None


def test_rejected_link_cancels_pending_alerts(sites):
    a = submit_scan(sites("site-a"), "manual", force=True)
    with db() as conn:
        services.create_watch(conn, a["scan_id"], str(uuid.uuid4()))
    b = submit_scan(sites("site-b"), "manual", force=True)
    with db() as conn:
        link = conn.execute("SELECT * FROM links WHERE scan_b=? ORDER BY link_id DESC LIMIT 1", (b["scan_id"],)).fetchone()
        assert conn.execute("SELECT COUNT(*) FROM alerts WHERE link_id=? AND status='pending'", (link["link_id"],)).fetchone()[0]
        services.review_link(conn, link["link_id"], "reject", "rev", "not related")
        assert conn.execute("SELECT COUNT(*) FROM alerts WHERE link_id=? AND status='pending'", (link["link_id"],)).fetchone()[0] == 0


def test_common_service_alone_never_links():
    from app.linking import compare, is_candidate

    a = {"host": "a.test", "site": "a.test", "reg": {}, "assets": {}, "common": {"cdnjs.cloudflare.com": []},
         "fingerprint": [], "form_signature": None, "payment_signature": None, "html_artifact": 1, "payment_obs": []}
    b = dict(a, host="b.test", site="b.test", html_artifact=2)
    sig = compare(a, b, set())
    assert [s["strength"] for s in sig] == ["weak"] and not is_candidate(sig)
    # Two medium signals backed by the same artifact pair do not make a candidate either.
    assert not is_candidate([{"strength": "medium", "artifact_ids": [1, 2]}, {"strength": "medium", "artifact_ids": [1, 2]}])
    assert is_candidate([{"strength": "medium", "artifact_ids": [1, 2]}, {"strength": "medium", "artifact_ids": [3, 4]}])
