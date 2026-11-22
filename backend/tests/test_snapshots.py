"""Idle snapshots: metadata-only HAR artifact, backend fetch of public bundles, kit match to a confirmed case."""
import json
import os
import threading
import uuid

import pytest
from fastapi.testclient import TestClient

from app import services
from app.db import db
from app.pipeline import submit_scan
from app.storage import read_artifact

TOKEN = os.environ["HAMI_REVIEWER_TOKEN"]


@pytest.fixture(scope="module")
def env():
    from app import db as dbmod
    from app.main import create_app
    from app.testsites import make_server

    dbmod.reset_init_cache()
    srv = make_server(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    yield TestClient(create_app()), (lambda n: f"http://{n}.localhost:{port}/")
    srv.shutdown()


def test_snapshot_kit_match_and_privacy(env):
    client, site = env
    names = json.loads((__import__("pathlib").Path(__file__).resolve().parents[2] / "testsites/sites/bundles.json").read_text())
    a = submit_scan(site("site-a"), "manual", force=True)
    with db() as conn:
        services.create_review(conn, a["scan_id"], "fraudulent", "rev", ["deposit_to_unlock"], "task_scam")
    base = site("site-d")
    dev = str(uuid.uuid4())
    payload = {
        "page_url": base + "?session=SECRET123#frag", "device_id": dev, "lang": "en",
        "visible_text": "Quorvia\nSign in\nCreate account\ncontact me@example.com",
        "resources": [{"url": base + "assets/" + n + "?v=SECRET123", "type": "script" if n.endswith(".js") else "css",
                       "status": 200, "duration_ms": 12.5, "size": 900} for n in names.values()]
                     + [{"url": "wss://chat.quorvia-support.test/socket?token=SECRET123", "type": "websocket", "status": 101},
                        {"url": "https://api.quorvia-pay.test/v1/user?uid=SECRET123", "type": "xmlhttprequest", "status": 200}],
    }
    r = client.post("/snapshots", json=payload, headers={"X-Device-Id": dev})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["snapshot_id"] and p["tier"] == "high_risk", (p["tier"], p["rules_fired"])
    assert "signin_or_thin+same_kit_as_reviewed_case" in p["rules_fired"]
    kit_clue = next(c for c in p["clues"] if c["type"] == "kit_match")
    assert "site-a.localhost" in kit_clue["text"]["en"] and "identical files" in kit_clue["text"]["en"]
    with db() as conn:
        art = conn.execute("SELECT path FROM artifacts WHERE scan_id=? AND kind='har'", (p["scan_id"],)).fetchone()
        html = conn.execute("SELECT path FROM artifacts WHERE scan_id=? AND kind='html'", (p["scan_id"],)).fetchone()
    har = json.loads(read_artifact(art["path"]))
    dump = json.dumps(har) + read_artifact(html["path"]).decode()
    assert "SECRET123" not in dump and "me@example.com" not in dump
    types = {e["_resourceType"] for e in har["log"]["entries"]}
    assert {"websocket", "xmlhttprequest", "script"} <= types
    fetched = [e for e in har["log"]["entries"] if e["response"]["content"].get("_hami_fetched_by") == "backend"]
    assert len(fetched) == len(names) and all(len(e["response"]["content"]["_hami_sha256"]) == 64 for e in fetched)
    assert all(e["request"]["headers"] == [] and e["request"]["cookies"] == [] for e in har["log"]["entries"])


def test_snapshot_validation(env):
    client, _ = env
    dev = str(uuid.uuid4())
    assert client.post("/snapshots", json={"page_url": "file:///etc/passwd", "device_id": dev}).status_code == 400
    assert client.post("/snapshots", json={"page_url": "https://x.test/", "device_id": dev, "scan_id": 1, "k": "bad"},
                       headers={"X-Device-Id": dev}).status_code == 403


def test_evidence_upload_hash_and_sanitize(env):
    import hashlib

    client, site = env
    dev = str(uuid.uuid4())
    har = {"log": {"version": "1.2", "creator": {"name": "t", "version": "1"}, "entries": [{
        "startedDateTime": "2026-11-22T10:00:00Z", "time": 5,
        "request": {"method": "GET", "url": site("site-d") + "?token=LEFTOVER", "cookies": [], "queryString": [],
                    "headers": [{"name": "Authorization-Cid", "value": "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.zzzzzzzzzz"}]},
        "response": {"status": 200, "headers": [], "cookies": [], "content": {"mimeType": "text/html",
                     "text": "<html><body><h1>Quorvia</h1><p>mail me@example.com</p></body></html>"}}}]}}
    text = json.dumps(har)
    good = hashlib.sha256(text.encode()).hexdigest()
    r = client.post("/evidence", json={"page_url": site("site-d"), "har_text": text, "client_sha256": good,
                                       "entries": 1, "device_id": dev}, headers={"X-Device-Id": dev})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["hash_match"] is True and p["evidence_id"] and len(p["stored_artifact_sha256"]) == 64
    with db() as conn:
        art = conn.execute("SELECT path FROM artifacts WHERE scan_id=? AND kind='har'", (p["scan_id"],)).fetchone()
    stored = read_artifact(art["path"]).decode()
    assert "LEFTOVER" not in stored and "eyJhbGci" not in stored and "me@example.com" not in stored
    bad = client.post("/evidence", json={"page_url": site("site-d"), "har_text": text, "client_sha256": "0" * 64,
                                         "entries": 1, "device_id": dev}, headers={"X-Device-Id": dev}).json()
    assert bad["hash_match"] is False
