import os
import uuid

import pytest
from fastapi.testclient import TestClient

from tests.helpers import REPO, serve_dir

TOKEN = os.environ["HAMI_REVIEWER_TOKEN"]
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(scope="module")
def client():
    from app import db as dbmod
    from app.main import create_app

    dbmod.reset_init_cache()
    return TestClient(create_app())


@pytest.fixture(scope="module")
def corpus():
    base, srv = serve_dir(REPO / "testsites" / "corpus")
    port = base.rsplit(":", 1)[1]
    yield lambda name: f"http://{name}.localhost:{port}"
    srv.shutdown()


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_scan_flow(client, corpus):
    dev = str(uuid.uuid4())
    r = client.post("/scans", json={"url": f"{corpus('taskscam')}/syn_task01/01.html", "source_type": "extension", "lang": "en",
                                    "device_id": dev}, headers={"X-Device-Id": dev})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["tier"] == "high_risk", p["rules_fired"]
    assert p["capture_mode"] == "live" and p["clues"] and len(p["clues"]) <= 3
    assert {"en", "ar"} <= set(p["headline"]) and p["what_to_do"]["ar"]
    shots = [a for a in p["artifacts"] if a["kind"] == "screenshot"]
    assert shots and all(len(a["sha256"]) == 64 for a in p["artifacts"])
    sid, key = p["scan_id"], p["access_key"]

    assert client.get(f"/scans/{sid}").status_code == 403
    assert client.get(f"/scans/{sid}?k={key}").json()["scan_id"] == sid
    assert client.get(f"/scans/{sid}", headers=AUTH).status_code == 200
    img = client.get(shots[0]["url"])
    assert img.status_code == 200 and img.content[:4] == b"\x89PNG"
    assert client.get(f"/artifacts/{shots[0]['artifact_id']}").status_code == 403

    # Repeated check is served from the stored capture.
    again = client.post("/scans", json={"url": f"{corpus('taskscam')}/syn_task01/01.html", "source_type": "extension"}).json()
    assert again["cached"] and again["capture_mode"] == "stored" and again["scan_id"] == sid

    # Watches + alerts (none approved yet).
    w = client.post("/watches", json={"scan_id": sid, "device_id": dev, "k": key})
    assert w.status_code == 200
    assert client.get(f"/alerts?device_id={dev}").json() == {"alerts": []}
    assert client.get(f"/watches?device_id={dev}").json()["watches"][0]["scan_id"] == sid

    # Reviewer endpoints need the token; corrections supersede, never overwrite.
    assert client.post("/reviews", json={"scan_id": sid, "label": "legitimate"}).status_code == 401
    r1 = client.post("/reviews", json={"scan_id": sid, "label": "legitimate"}, headers=AUTH).json()
    r2 = client.post("/reviews", json={"scan_id": sid, "label": "fraudulent", "behavior_tags": ["deposit_to_unlock"],
                                       "scam_type": "task_scam"}, headers=AUTH).json()
    hist = r2["history"]
    assert [h["label"] for h in hist] == ["legitimate", "fraudulent"]
    assert hist[1]["supersedes"] == hist[0]["review_id"] and hist[0]["superseded"]
    assert r1["history"][0]["label"] == "legitimate"

    host = p["host"]
    look = client.post("/lookup/hosts", json={"hosts": [host, "never-seen.example"]}).json()["results"]
    assert look[host]["tier"] == "high_risk" and look[host]["source"] == "reviewed"
    assert look["never-seen.example"]["known"] is False
    ind = client.get("/indicators/high-risk-hosts").json()
    assert host in ind["hosts"] and ind["version"] >= 2

    brief = client.get(f"/clusters/{sid}/brief", headers=AUTH)
    assert brief.status_code == 200 and brief.json()["sites"]
    md = client.get(f"/clusters/{sid}/brief?format=md", headers=AUTH).text
    assert "hxxp" in md and "sha256" in md and "Direct observations" in md
    assert client.delete(f"/watches/{w.json()['watch_id']}?device_id={dev}").json() == {"deleted": True}


def test_legit_page_not_flagged(client, corpus):
    p = client.post("/scans", json={"url": f"{corpus('gigplatform')}/syn_legit_gig01/01.html"}).json()
    assert p["tier"] in ("no_strong_signals",), (p["tier"], p["rules_fired"])


def test_inconclusive_review_never_trains(client, corpus):
    p = client.post("/scans", json={"url": f"{corpus('ambiguous')}/syn_ambig01/02.html"}).json()
    h = client.post("/reviews", json={"scan_id": p["scan_id"], "label": "inconclusive", "training_eligible": True},
                    headers=AUTH).json()["history"]
    assert h[-1]["training_eligible"] is False


def test_unsafe_targets_refused(client):
    for u in ("http://127.0.0.1:22/", "file:///etc/passwd", "http://169.254.169.254/"):
        assert client.post("/scans", json={"url": u}).status_code == 400


def test_rate_limit():
    from app.api.deps import RateLimiter

    rl = RateLimiter()
    assert all(rl.check("t", "dev", 3)[0] for _ in range(3))
    ok, retry = rl.check("t", "dev", 3)
    assert not ok and retry > 0


def test_bad_device_id(client):
    assert client.get("/alerts?device_id=x").status_code == 400
