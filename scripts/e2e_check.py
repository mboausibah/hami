#!/usr/bin/env python3
"""End-to-end checks against the Hami API (local or hosted) using the synthetic test sites.

  1. Site A with the listing name -> High risk, identity-mismatch clue, hashed artifacts stored.
  2. Site B -> proposed link to A; reviewer approves; a watcher of A gets the alert; a non-watcher doesn't.
  3. Approve B for training; retrain -> new dataset + model version; metrics printed; promotion rule applied.
  4. Site C -> common service recorded, not High risk, no alert.
  5. Site D (login wall sharing app bundles + language pack with confirmed Site A) -> High risk through the kit
     match, with the matched files as clues; Site C (common libraries only) never kit-matches.

Usage:
  python scripts/e2e_check.py --start-local            # isolated API + test sites in a temp data dir
  python scripts/e2e_check.py --api http://localhost:8000 [--token T] [--testsite-port 8100]

The API's capture browser must reach the test sites at http://site-{a,b,c}.localhost:<port>/ (run the
API with RUN_TESTSITES=true, as docker-compose and `make run` do). These synthetic sites exist only for
automated tests; they are never presented as real-world results.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' - ' + detail) if detail else ''}")
    return ok


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def token_from_env_file() -> str | None:
    env = REPO / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("HAMI_REVIEWER_TOKEN="):
                return line.split("=", 1)[1].strip() or None
    return os.environ.get("HAMI_REVIEWER_TOKEN")


def start_local() -> tuple[subprocess.Popen, str, str, int, Path]:
    tmp = Path(tempfile.mkdtemp(prefix="hami-e2e-"))
    models = tmp / "models"
    shutil.copytree(BACKEND / "models", models)
    processed = tmp / "processed"
    processed.mkdir()
    rec = REPO / "data" / "processed" / "records.jsonl"
    if rec.is_file():
        shutil.copy(rec, processed / "records.jsonl")
    api_port, ts_port = free_port(), free_port()
    token = uuid.uuid4().hex
    env = dict(os.environ, HAMI_DATA_DIR=str(tmp / "storage"), HAMI_MODELS_DIR=str(models),
               HAMI_PROCESSED_DIR=str(processed), HAMI_REVIEWER_TOKEN=token, RUN_TESTSITES="true",
               TESTSITE_PORT=str(ts_port), RATE_SCANS_PER_MIN="1000", RATE_DEFAULT_PER_MIN="1000",
               RATE_LOOKUP_PER_MIN="1000", PYTHONUTF8="1", HAMI_PUBLIC_BASE_URL=f"http://127.0.0.1:{api_port}")
    env.pop("HAMI_DB_PATH", None)
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port",
                             str(api_port), "--log-level", "warning"], cwd=BACKEND, env=env)
    base = f"http://127.0.0.1:{api_port}"
    for _ in range(60):
        try:
            if httpx.get(base + "/health", timeout=2).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.5)
    else:
        proc.terminate()
        raise SystemExit("local API did not start")
    return proc, base, token, ts_port, tmp


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default=os.environ.get("HAMI_API", "http://localhost:8000"))
    ap.add_argument("--token", default=None)
    ap.add_argument("--testsite-port", type=int, default=int(os.environ.get("TESTSITE_PORT", "8100")))
    ap.add_argument("--start-local", action="store_true")
    args = ap.parse_args()

    proc = tmp = None
    if args.start_local:
        proc, api, token, ts_port, tmp = start_local()
        print(f"local API {api} (temp data dir), test sites on port {ts_port}")
    else:
        api, token, ts_port = args.api.rstrip("/"), args.token or token_from_env_file(), args.testsite_port
        if not token:
            raise SystemExit("reviewer token needed (--token or HAMI_REVIEWER_TOKEN in .env)")
    site = lambda n: f"http://{n}.localhost:{ts_port}/"  # noqa: E731
    auth = {"Authorization": f"Bearer {token}"}
    c = httpx.Client(base_url=api, timeout=120)
    try:
        run(c, site, auth)
    finally:
        c.close()
        if proc:
            proc.terminate()
            proc.wait(timeout=15)
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} assertions passed")
    return 1 if failed else 0


def run(c: httpx.Client, site, auth: dict) -> None:  # noqa: ANN001
    watcher, bystander = str(uuid.uuid4()), str(uuid.uuid4())

    print("\nCheck 1: Site A with the listing name")
    a = c.post("/scans", json={"url": site("site-a"), "source_type": "maps", "listing_name": "Al Noor Manpower Services",
                               "lang": "en", "force": True}, headers={"X-Device-Id": watcher}).json()
    check("1a Site A is High risk", a.get("tier") == "high_risk", f"tier={a.get('tier')} rules={a.get('rules_fired')}")
    check("1b identity-mismatch clue", any(cl["type"] == "identity_mismatch" for cl in a.get("clues", [])),
          str([cl["type"] for cl in a.get("clues", [])]))
    arts = a.get("artifacts", [])
    kinds = {x["kind"] for x in arts}
    check("1c hashed artifacts stored", {"har", "html", "screenshot", "action_log"} <= kinds
          and all(len(x["sha256"]) == 64 for x in arts), f"{len(arts)} artifacts {sorted(kinds)}")
    shot = next((x for x in arts if x["kind"] == "screenshot"), None)
    if shot:
        img = c.get(shot["url"])
        check("1d screenshot bytes match recorded SHA-256",
              img.status_code == 200 and hashlib.sha256(img.content).hexdigest() == shot["sha256"])
    check("1e country-selector step captured", any(x.get("action") == "country_selector" for x in arts))

    print("\nCheck 2: Site B rebrand, reviewer approval, opt-in alert")
    w = c.post("/watches", json={"scan_id": a["scan_id"], "device_id": watcher, "k": a["access_key"]})
    check("2a watcher watches Site A", w.status_code == 200, w.text[:120] if w.status_code != 200 else "")
    b = c.post("/scans", json={"url": site("site-b"), "source_type": "manual", "force": True}).json()
    links = c.get("/links", params={"scan_id": b["scan_id"]}, headers=auth).json()["links"]
    link = next((l for l in links if l["host_a"] == "site-a.localhost" or l["host_b"] == "site-a.localhost"), None)
    check("2b B proposed as related to A", link is not None and link["review_status"] == "pending",
          f"{link['relation_type']} ({link['strength']})" if link else "no link")
    if link is None:
        return
    pend = [x for x in c.get("/alerts/review", params={"status": "pending"}, headers=auth).json()["alerts"]
            if x["link_id"] == link["link_id"] and x["watched_host"] == "site-a.localhost"]
    check("2c pending alert created (not sent)", len(pend) == 1 and pend[0]["sent_at"] is None)
    check("2d watcher sees nothing before approval", c.get("/alerts", params={"device_id": watcher}).json()["alerts"] == [])
    r = c.post(f"/links/{link['link_id']}/review", json={"decision": "approve", "reviewer": "e2e"}, headers=auth)
    check("2e reviewer approves link", r.status_code == 200 and r.json()["review_status"] == "approved")
    if pend:
        r = c.post(f"/alerts/{pend[0]['alert_id']}/approve", json={"reviewer": "e2e"}, headers=auth)
        check("2f reviewer approves alert", r.status_code == 200 and r.json()["status"] == "approved")
    got = c.get("/alerts", params={"device_id": watcher}).json()["alerts"]
    mine = [x for x in got if pend and x["alert_id"] == pend[0]["alert_id"]]
    check("2g watcher of A gets the alert with its reason", len(mine) == 1 and "site-b" in mine[0]["reason"]["en"],
          mine[0]["reason"]["en"][:110] if mine else "")
    check("2h non-watcher does not", c.get("/alerts", params={"device_id": bystander}).json()["alerts"] == [])

    print("\nCheck 3: approve B for training, retrain, promotion rule")
    for sid in (a["scan_id"], b["scan_id"]):
        r = c.post("/reviews", json={"scan_id": sid, "label": "fraudulent", "behavior_tags": ["deposit_to_unlock"],
                                     "scam_type": "task_scam", "training_eligible": True, "reviewer": "e2e"}, headers=auth)
        check(f"3a review saved for scan {sid}", r.status_code == 200)
    before = c.get("/health").json()["model_version"]
    t0 = time.monotonic()
    job = c.post("/train", json={"kind": "full", "wait": True}, headers=auth, timeout=600).json()
    ok = job.get("status") == "done"
    check("3b training finished", ok, job.get("error") or f"{time.monotonic() - t0:.1f}s")
    if ok:
        info = job.get("dataset_info") or {}
        check("3c new dataset version includes reviewed records", (info.get("sources") or {}).get("reviewed", 0) >= 1,
              f"{job['dataset_version']} sources={info.get('sources')}")
        check("3d new model version saved", bool(job.get("version")) and job["version"] != before, job.get("version"))
        o = job["held_out"]["overall"]
        print(f"      held-out: precision {o['precision']} recall {o['recall']} FPR(legit) {o['fpr_legit']} "
              f"PR-AUC {o['pr_auc']} (n={o['n']}); per language: "
              + ", ".join(f"{k} R={v['recall']}" for k, v in job["held_out"]["per_language"].items()))
        p = job["promotion"]
        applied = "promoted" in p and (p.get("reason") == "no current model" or
                                       {"recall_not_lower", "fpr_not_higher"} <= set(p))
        check("3e promotion rule applied", applied,
              f"recall_not_lower={p.get('recall_not_lower')} fpr_not_higher={p.get('fpr_not_higher')} -> "
              f"{'promoted' if p.get('promoted') else 'kept as candidate'}")

    print("\nCheck 4: Site C legitimate look-alike")
    cc = c.post("/scans", json={"url": site("site-c"), "source_type": "manual", "force": True}).json()
    internal = c.get(f"/scans/{cc['scan_id']}/internal", headers=auth).json()
    commons = {o["host_ref"] for o in internal["observations"] if o["indicator_type"] == "common_service"}
    check("4a common service recorded", bool(commons & {"cdnjs.cloudflare.com", "static.cloudflareinsights.com"}),
          ", ".join(sorted(commons)))
    check("4b not High risk", cc.get("tier") != "high_risk", f"tier={cc.get('tier')}")
    c_links = c.get("/links", params={"scan_id": cc["scan_id"]}, headers=auth).json()["links"]
    check("4c no link proposed", c_links == [])
    alerts = c.get("/alerts/review", headers=auth).json()["alerts"]
    check("4d no alert", not any(x["related_scan_id"] == cc["scan_id"] for x in alerts))
    check("4e no kit (same software) match for a site sharing only common libraries",
          not any(l["relation_type"] == "same_kit" for l in c_links))
    check("4f watcher still has exactly the approved A/B alert",
          len([x for x in c.get("/alerts", params={"device_id": watcher}).json()["alerts"]
               if x["related_host"] == "site-c.localhost"]) == 0)

    print("\nCheck 5: Site D, a login wall running the same software as confirmed Site A")
    dd = c.post("/scans", json={"url": site("site-d"), "source_type": "manual", "force": True}).json()
    check("5a Site D is High risk", dd.get("tier") == "high_risk", f"tier={dd.get('tier')} rules={dd.get('rules_fired')}")
    check("5b decided by the kit match (page itself is a sign-in wall)",
          "signin_or_thin+same_kit_as_reviewed_case" in dd.get("rules_fired", []), str(dd.get("rules_fired")))
    kit = next((cl for cl in dd.get("clues", []) if cl["type"] == "kit_match"), None)
    check("5c clue names the confirmed site and the identical files",
          kit is not None and "site-a.localhost" in kit["text"]["en"], kit["text"]["en"] if kit else "no kit clue")
    files = (dd.get("evidence") or {}).get("kit_match") or {}
    check("5d matched files listed as evidence (content-hashed build names)",
          len(files.get("files", [])) >= 3 and any(f.startswith("en-US-") for f in files.get("files", [])),
          ", ".join(files.get("files", [])[:4]))


if __name__ == "__main__":
    sys.exit(main())
