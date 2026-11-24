"""Public and reviewer API endpoints."""
from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from app import cases, services, training_jobs
from app.api.deps import rate_limit, require_reviewer, token_ok, valid_device_id
from app.config import settings
from app.db import db
from app.linking.brief import brief_markdown, build_brief
from app.pipeline import ScanError, get_scan_payload, submit_scan
from app.scoring.model_store import read_registry
from app.storage import read_artifact

router = APIRouter()

SourceType = Literal["search", "maps", "sms", "whatsapp", "manual", "extension", "discovery"]


def _err(e: services.ServiceError) -> HTTPException:
    return HTTPException(e.status, str(e))


# ---- public ---------------------------------------------------------------------------------------
class ScanIn(BaseModel):
    url: str = Field(..., max_length=2048)
    source_type: SourceType = "manual"
    listing_name: str | None = Field(default=None, max_length=200)
    lang: Literal["ar", "en"] = "en"
    device_id: str | None = Field(default=None, max_length=64)
    force: bool = False
    # Structure of the page as rendered in the user's browser (extension): same-host paths without queries,
    # image names, form-field descriptors without values, redacted visible text. Optional.
    page_signals: dict | None = None


@router.post("/scans", dependencies=[Depends(rate_limit("scans"))])
async def create_scan(body: ScanIn) -> dict:
    valid_device_id(body.device_id)
    try:
        # The device ID is used only for rate limiting; it is never stored with the scan.
        if body.page_signals is not None and len(json.dumps(body.page_signals)) > 200_000:
            raise ScanError("page_signals too large")
        return await run_in_threadpool(submit_scan, body.url, body.source_type, body.listing_name, body.lang,
                                       None, None, body.force, True, False, body.page_signals)
    except ScanError as e:
        raise HTTPException(400, str(e)) from e


def _authorized_for_scan(scan_id: int, key: str | None, authorization: str | None) -> None:
    if authorization and authorization.lower().startswith("bearer ") and token_ok(authorization[7:].strip()):
        return
    with db() as conn:
        row = conn.execute("SELECT access_key FROM scans WHERE scan_id=?", (scan_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "scan not found")
    if not key or key != row["access_key"]:
        raise HTTPException(403, "scan key required")


@router.get("/scans/{scan_id}", dependencies=[Depends(rate_limit("default"))])
def read_scan(scan_id: int, k: str | None = None, authorization: str | None = Header(default=None)) -> dict:
    _authorized_for_scan(scan_id, k, authorization)
    return get_scan_payload(scan_id)


@router.get("/artifacts/{artifact_id}", dependencies=[Depends(rate_limit("default"))])
def read_screenshot(artifact_id: int, k: str | None = None, authorization: str | None = Header(default=None)) -> Response:
    """Screenshots only. Other artifacts (HAR, HTML) are for reviewers via the console."""
    with db() as conn:
        a = conn.execute("SELECT a.*, s.access_key FROM artifacts a JOIN scans s ON s.scan_id=a.scan_id "
                         "WHERE a.artifact_id=?", (artifact_id,)).fetchone()
        if a is None or a["kind"] != "screenshot":
            raise HTTPException(404, "not found")
        reviewer = bool(authorization and authorization.lower().startswith("bearer ") and token_ok(authorization[7:].strip()))
        if not reviewer:
            # The key of the capturing scan, or of any scan that re-used this stored capture.
            ok = k is not None and (k == a["access_key"] or conn.execute(
                "SELECT 1 FROM scans WHERE stored_from_scan_id=? AND access_key=?", (a["scan_id"], k)).fetchone())
            if not ok:
                raise HTTPException(403, "scan key required")
    return Response(read_artifact(a["path"]), media_type="image/png",
                    headers={"Cache-Control": "private, max-age=86400", "X-Content-SHA256": a["sha256"]})


class LookupIn(BaseModel):
    hosts: list[str] = Field(..., max_length=60)


@router.post("/lookup/hosts", dependencies=[Depends(rate_limit("lookup"))])
def lookup_hosts(body: LookupIn) -> dict:
    """What Hami already knows about each hostname (reviewed tier or latest assessment). No capture."""
    with db() as conn:
        return {"results": services.lookup_hosts(conn, body.hosts)}


class WatchIn(BaseModel):
    scan_id: int
    device_id: str = Field(..., max_length=64)
    k: str | None = None


@router.post("/watches", dependencies=[Depends(rate_limit("default"))])
def create_watch(body: WatchIn, authorization: str | None = Header(default=None)) -> dict:
    valid_device_id(body.device_id)
    _authorized_for_scan(body.scan_id, body.k, authorization)
    with db() as conn:
        try:
            return services.create_watch(conn, body.scan_id, body.device_id)
        except services.ServiceError as e:
            raise _err(e) from e


@router.delete("/watches/{watch_id}", dependencies=[Depends(rate_limit("default"))])
def delete_watch(watch_id: str, device_id: str = Query(..., max_length=64)) -> dict:
    valid_device_id(device_id)
    with db() as conn:
        if not services.delete_watch(conn, watch_id, device_id):
            raise HTTPException(404, "watch not found")
    return {"deleted": True}


@router.get("/watches", dependencies=[Depends(rate_limit("default"))])
def list_watches(device_id: str = Query(..., max_length=64)) -> dict:
    valid_device_id(device_id)
    with db() as conn:
        return {"watches": services.watches_for_device(conn, device_id)}


@router.get("/alerts", dependencies=[Depends(rate_limit("default"))])
def list_alerts(device_id: str = Query(..., max_length=64)) -> dict:
    valid_device_id(device_id)
    with db() as conn:
        return {"alerts": services.alerts_for_device(conn, device_id)}


@router.get("/indicators/high-risk-hosts", dependencies=[Depends(rate_limit("default"))])
def high_risk_hosts() -> dict:
    """Hostnames from reviewer-approved High-risk (fraudulent) cases only, with a version number."""
    with db() as conn:
        hosts, version = cases.high_risk_hosts(conn)
    from app.urls import registrable_domain

    names = [h["host"] for h in hosts]
    # Registrable domains of confirmed cases: every subdomain inherits the risk (PSL keeps shared platforms apart).
    domains = sorted({registrable_domain(h) for h in names if registrable_domain(h) and "." in registrable_domain(h)})
    return {"version": version, "count": len(names), "hosts": names, "domains": domains}


class SnapshotResource(BaseModel):
    url: str = Field(..., max_length=2048)
    type: str = Field("other", max_length=24)
    status: int | None = None
    duration_ms: float | None = None
    size: int | None = None


class SnapshotIn(BaseModel):
    page_url: str = Field(..., max_length=2048)
    resources: list[SnapshotResource] = Field(default_factory=list, max_length=1200)
    visible_text: str = Field("", max_length=40000)
    lang: str = Field("en", max_length=5)
    device_id: str = Field(..., max_length=64)
    scan_id: int | None = None
    k: str | None = None


@router.post("/snapshots", dependencies=[Depends(rate_limit("snapshots"))])
async def create_snapshot(body: SnapshotIn) -> dict:
    """Idle snapshot of a candidate page from the extension (metadata only; see app/snapshots.py)."""
    from app.snapshots import SnapshotError, ingest

    valid_device_id(body.device_id)
    linked = None
    if body.scan_id is not None:
        with db() as conn:
            row = conn.execute("SELECT access_key FROM scans WHERE scan_id=?", (body.scan_id,)).fetchone()
        if row is None or not body.k or body.k != row["access_key"]:
            raise HTTPException(403, "scan key required to link a snapshot")
        linked = body.scan_id
    try:
        return await run_in_threadpool(ingest, body.model_dump(), linked)
    except SnapshotError as e:
        raise HTTPException(400, str(e)) from e


class EvidenceIn(BaseModel):
    page_url: str = Field(..., max_length=2048)
    har_text: str
    client_sha256: str = Field(..., min_length=64, max_length=64)
    entries: int = 0
    device_id: str = Field(..., max_length=64)
    scan_id: int | None = None
    k: str | None = None


@router.post("/evidence", dependencies=[Depends(rate_limit("snapshots"))])
async def upload_evidence(body: EvidenceIn) -> dict:
    """Investigator-mode HAR (sanitized on the device), with the device-side SHA-256 verified here."""
    from app.evidence import EvidenceError, ingest

    valid_device_id(body.device_id)
    linked = None
    if body.scan_id is not None:
        with db() as conn:
            row = conn.execute("SELECT access_key FROM scans WHERE scan_id=?", (body.scan_id,)).fetchone()
        if row is None or body.k != row["access_key"]:
            raise HTTPException(403, "scan key required to link evidence")
        linked = body.scan_id
    try:
        return await run_in_threadpool(ingest, body.page_url, body.har_text, body.client_sha256, body.entries, linked)
    except EvidenceError as e:
        raise HTTPException(413 if "too large" in str(e) else 400, str(e)) from e


@router.get("/indicators/local-lists", dependencies=[Depends(rate_limit("default"))])
def local_lists() -> dict:
    """Everything the extension needs to decide on the device, without a server call per page:
    reviewer-confirmed hosts and registrable domains, recently certificate-logged look-alike domains, and
    distinctive build-file names of confirmed kits (matched against the page's own resource names)."""
    from app.analyze.assets import common_file_name
    from app.linking.kit import common_shas
    from app.urls import registrable_domain

    with db() as conn:
        hosts, version = cases.high_risk_hosts(conn)
        names = [h["host"] for h in hosts]
        domains = sorted({registrable_domain(h) for h in names if "." in registrable_domain(h)})
        from datetime import datetime, timedelta, timezone

        cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%S")
        recent = [r[0] for r in conn.execute(
            "SELECT domain FROM discovered_domains WHERE source='ct' AND first_seen_at >= ? "
            "ORDER BY first_seen_at DESC LIMIT 2000", (cutoff,))]
        fraud_sites = sorted({registrable_domain(s["host"]) for s in cases.reviewed_fraud_scans(conn)})
        kit_files: list[str] = []
        if fraud_sites:
            marks = ",".join("?" * len(fraud_sites))
            rows = conn.execute(f"SELECT file_name, sha256 FROM asset_files WHERE site IN ({marks}) AND name_hashed=1 "
                                f"AND kind IN ('js','css')", fraud_sites).fetchall()
            common = common_shas(conn, [r["sha256"] for r in rows])
            kit_files = sorted({r["file_name"] for r in rows if r["sha256"] not in common and not common_file_name(r["file_name"])})
        n_disc = conn.execute("SELECT COALESCE(MAX(id), 0) FROM discovered_domains").fetchone()[0]
    return {"version": f"{version}.{n_disc}.{len(kit_files)}", "hosts": names, "domains": domains,
            "recent_cert_domains": recent, "kit_files": kit_files[:5000]}


@router.get("/health")
def health() -> dict:
    with db() as conn:
        conn.execute("SELECT 1").fetchone()
        n = conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0]
    return {"status": "ok", "model_version": read_registry().get("current"), "scans": n,
            "reviewer_token_configured": bool(settings.reviewer_token)}


# ---- reviewer (token) -----------------------------------------------------------------------------
reviewer = APIRouter(dependencies=[Depends(require_reviewer), Depends(rate_limit("default"))])


class ReviewIn(BaseModel):
    scan_id: int
    label: Literal["fraudulent", "legitimate", "inconclusive"]
    behavior_tags: list[str] = []
    scam_type: str | None = None
    notes: str | None = Field(default=None, max_length=2000)
    training_eligible: bool = True
    reviewer: str = Field(default="reviewer", max_length=80)


@reviewer.post("/reviews")
def create_review(body: ReviewIn) -> dict:
    with db() as conn:
        try:
            services.create_review(conn, body.scan_id, body.label, body.reviewer, body.behavior_tags, body.scam_type,
                                   body.notes, body.training_eligible)
        except services.ServiceError as e:
            raise _err(e) from e
        return {"scan_id": body.scan_id, "history": services.review_history(conn, body.scan_id)}


@reviewer.get("/reviews")
def list_reviews(scan_id: int) -> dict:
    with db() as conn:
        return {"scan_id": scan_id, "history": services.review_history(conn, scan_id)}


class LinkReviewIn(BaseModel):
    decision: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=1000)
    reviewer: str = Field(default="reviewer", max_length=80)


@reviewer.get("/links")
def list_links(status: Literal["pending", "approved", "rejected"] | None = None, scan_id: int | None = None) -> dict:
    q, args = "SELECT * FROM links WHERE 1=1", []
    if status:
        q += " AND review_status=?"
        args.append(status)
    if scan_id:
        q += " AND (scan_a=? OR scan_b=?)"
        args += [scan_id, scan_id]
    with db() as conn:
        return {"links": [services.link_dict(r) for r in conn.execute(q + " ORDER BY link_id DESC LIMIT 500", args)]}


@reviewer.post("/links/{link_id}/review")
def review_link(link_id: int, body: LinkReviewIn) -> dict:
    with db() as conn:
        try:
            return services.review_link(conn, link_id, body.decision, body.reviewer, body.note)
        except services.ServiceError as e:
            raise _err(e) from e


class AlertActionIn(BaseModel):
    reviewer: str = Field(default="reviewer", max_length=80)
    reason: str | None = Field(default=None, max_length=500)


@reviewer.get("/alerts/review")
def alerts_for_review(status: Literal["pending", "approved", "withdrawn", "cancelled"] | None = None) -> dict:
    with db() as conn:
        q = "SELECT * FROM alerts" + (" WHERE status=?" if status else "") + " ORDER BY alert_id DESC LIMIT 500"
        rows = conn.execute(q, (status,) if status else ()).fetchall()
        return {"alerts": [services.alert_dict(conn, r) for r in rows]}


@reviewer.post("/alerts/{alert_id}/approve")
def approve_alert(alert_id: int, body: AlertActionIn | None = None) -> dict:
    with db() as conn:
        try:
            return services.approve_alert(conn, alert_id, (body or AlertActionIn()).reviewer)
        except services.ServiceError as e:
            raise _err(e) from e


@reviewer.post("/alerts/{alert_id}/withdraw")
def withdraw_alert(alert_id: int, body: AlertActionIn | None = None) -> dict:
    b = body or AlertActionIn()
    with db() as conn:
        try:
            return services.withdraw_alert(conn, alert_id, b.reviewer, b.reason)
        except services.ServiceError as e:
            raise _err(e) from e


class TrainIn(BaseModel):
    kind: Literal["full", "synthetic"] = "full"
    wait: bool = False


@reviewer.post("/train")
async def train(body: TrainIn | None = None) -> dict:
    b = body or TrainIn()
    job = training_jobs.start(b.kind)
    if b.wait:
        import asyncio
        while job["status"] == "running":
            await asyncio.sleep(0.5)
    return _job_view(job)


@reviewer.get("/train/{job_id}")
def train_status(job_id: str) -> dict:
    job = training_jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "unknown job")
    return _job_view(job)


def _job_view(job: dict) -> dict:
    out = {k: job[k] for k in ("job_id", "kind", "status", "started_at", "finished_at", "error")}
    r = job.get("result")
    if r:
        out.update({"version": r["version"], "model_status": r["status"], "dataset_version": r["dataset_version"],
                    "dataset_hash": r["dataset_hash"], "held_out": r["metrics"]["held_out"],
                    "baselines": r["metrics"]["baselines"], "split": r["metrics"]["split"], "promotion": r["promotion"],
                    "dataset_info": r.get("dataset_info")})
    return out


@reviewer.get("/clusters/{cluster_id}/brief")
def cluster_brief(cluster_id: int, format: Literal["json", "md"] = "json"):  # noqa: A002, ANN201
    with db() as conn:
        try:
            b = build_brief(conn, cluster_id)
        except KeyError as e:
            raise HTTPException(404, "unknown cluster or scan") from e
    if format == "md":
        return PlainTextResponse(brief_markdown(b), media_type="text/markdown; charset=utf-8",
                                 headers={"Content-Disposition": f'attachment; filename="hami-brief-{cluster_id}.md"'})
    return JSONResponse(b, headers={"Content-Disposition": f'inline; filename="hami-brief-{cluster_id}.json"'})


@reviewer.get("/discovery/queue")
def discovery_queue(status: str | None = None, all_tiers: bool = False) -> dict:
    """Discovered domains (CT logs, HAR references). By default only High risk / Caution results and
    items awaiting capture or approval."""
    with db() as conn:
        rows = conn.execute(
            "SELECT d.*, (SELECT risk_tier FROM assessments WHERE scan_id=d.scan_id ORDER BY assessment_id DESC LIMIT 1) tier, "
            "(SELECT score FROM assessments WHERE scan_id=d.scan_id ORDER BY assessment_id DESC LIMIT 1) score "
            "FROM discovered_domains d ORDER BY d.updated_at DESC LIMIT 1000").fetchall()
    items = []
    for r in rows:
        d = dict(r)
        d["evidence"] = json.loads(d["evidence"]) if d["evidence"] else None
        if status and d["status"] != status:
            continue
        if not all_tiers and d["status"] == "scanned" and d["tier"] not in ("high_risk", "caution"):
            continue
        items.append(d)
    return {"items": items, "count": len(items)}


@reviewer.get("/scans")
def list_scans(limit: int = Query(100, le=500), tier: str | None = None, unreviewed: bool = False) -> dict:
    with db() as conn:
        rows = conn.execute(
            "SELECT s.scan_id, s.host, s.submitted_url, s.source_type, s.batch, s.submitted_at, s.capture_mode, "
            "s.capture_status, (SELECT risk_tier FROM assessments WHERE scan_id=s.scan_id ORDER BY assessment_id DESC "
            "LIMIT 1) tier, (SELECT label FROM reviews WHERE scan_id=s.scan_id ORDER BY review_id DESC LIMIT 1) label "
            "FROM scans s ORDER BY s.scan_id DESC LIMIT ?", (limit * 3,)).fetchall()
    out = [dict(r) for r in rows if (not tier or r["tier"] == tier) and (not unreviewed or r["label"] is None)]
    return {"scans": out[:limit]}


@reviewer.get("/scans/{scan_id}/internal")
def scan_internal(scan_id: int, request: Request) -> dict:
    p = get_scan_payload(scan_id, include_internal=True)
    with db() as conn:
        p["observations"] = [dict(o) for o in conn.execute("SELECT * FROM observations WHERE scan_id=? ORDER BY obs_id",
                                                           (scan_id,))]
        p["reviews"] = services.review_history(conn, scan_id)
    return p
