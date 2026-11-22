"""Reviewer console (server-rendered Jinja, Arabic + English).

Auth: the reviewer token from .env, exchanged for an HttpOnly SameSite=Strict session cookie (an HMAC of
the token). Every form carries a CSRF token. Captured scam HTML is never rendered in the reviewer's
browser: HAR/HTML artifacts are served as text/plain downloads."""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app import cases, services, training_jobs
from app.api.deps import token_ok
from app.config import settings
from app.db import db, utcnow
from app.linking.brief import brief_markdown, build_brief
from app.linking.clusters import clusters_for_all
from app.pipeline import ScanError, get_scan_payload, reanalyze_stored, submit_scan
from app.review_ui.i18n import t
from app.scoring.model_store import read_registry
from app.storage import read_artifact
from app.urls import defang

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
ui = APIRouter(prefix="/review", include_in_schema=False)
COOKIE = "hami_reviewer"


def _session_value() -> str:
    return hmac.new(settings.reviewer_token.encode(), b"hami-reviewer-session", hashlib.sha256).hexdigest()


def _csrf() -> str:
    return hmac.new(settings.reviewer_token.encode(), b"hami-csrf", hashlib.sha256).hexdigest()[:32]


class NotSignedIn(Exception):
    pass


def reviewer_session(request: Request) -> str:
    if not settings.reviewer_token or not hmac.compare_digest(request.cookies.get(COOKIE, ""), _session_value()):
        raise HTTPException(303, headers={"Location": "/review/login"})
    return "reviewer"


def check_csrf(csrf: str = Form(...)) -> None:
    if not hmac.compare_digest(csrf, _csrf()):
        raise HTTPException(403, "invalid CSRF token")


def lang_of(request: Request) -> str:
    q = request.query_params.get("lang")
    if q in ("ar", "en"):
        return q
    return request.cookies.get("hami_lang", "en") if request.cookies.get("hami_lang") in ("ar", "en") else "en"


def render(request: Request, name: str, **ctx: Any) -> HTMLResponse:
    lang = lang_of(request)
    resp = templates.TemplateResponse(request, name, {
        "lang": lang, "dir": "rtl" if lang == "ar" else "ltr", "t": lambda k: t(k, lang), "csrf": _csrf(),
        "defang": defang, "path": request.url.path, **ctx})
    if request.query_params.get("lang") in ("ar", "en"):
        resp.set_cookie("hami_lang", lang, samesite="strict", max_age=3600 * 24 * 365)
    return resp


def back(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


# ---- auth ---------------------------------------------------------------------------------------------
@ui.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str | None = None) -> HTMLResponse:
    return render(request, "login.html", error=error, configured=bool(settings.reviewer_token))


@ui.post("/login")
def login(token: str = Form(...)) -> Response:
    if not token_ok(token):
        return back("/review/login?error=1")
    resp = back("/review")
    resp.set_cookie(COOKIE, _session_value(), httponly=True, samesite="strict", max_age=12 * 3600)
    return resp


@ui.post("/logout")
def logout() -> Response:
    resp = back("/review/login")
    resp.delete_cookie(COOKIE)
    return resp


# ---- scan queue ------------------------------------------------------------------------------------------
@ui.get("", response_class=HTMLResponse, dependencies=[Depends(reviewer_session)])
def scan_queue(request: Request, tier: str | None = None, unreviewed: int = 0, batch: str | None = None) -> HTMLResponse:
    with db() as conn:
        q = ("SELECT s.scan_id, s.host, s.submitted_url, s.source_type, s.batch, s.submitted_at, s.capture_mode, "
             "s.capture_status, s.listing_name, (SELECT risk_tier FROM assessments WHERE scan_id=s.scan_id ORDER BY "
             "assessment_id DESC LIMIT 1) tier, (SELECT score FROM assessments WHERE scan_id=s.scan_id ORDER BY "
             "assessment_id DESC LIMIT 1) score, (SELECT label FROM reviews WHERE scan_id=s.scan_id ORDER BY review_id "
             "DESC LIMIT 1) label FROM scans s WHERE s.status='done'")
        args: list[Any] = []
        if batch:
            q += " AND s.batch=?"
            args.append(batch)
        rows = [dict(r) for r in conn.execute(q + " ORDER BY s.scan_id DESC LIMIT 600", args)]
        batches = [r[0] for r in conn.execute("SELECT DISTINCT batch FROM scans WHERE batch IS NOT NULL")]
        counts = {r[0]: r[1] for r in conn.execute(
            "SELECT review_status, COUNT(*) FROM links GROUP BY review_status")}
        pending_alerts = conn.execute("SELECT COUNT(*) FROM alerts WHERE status='pending'").fetchone()[0]
    if tier:
        rows = [r for r in rows if r["tier"] == tier]
    if unreviewed:
        rows = [r for r in rows if not r["label"]]
    return render(request, "scans.html", rows=rows[:300], tier=tier, unreviewed=unreviewed, batch=batch,
                  batches=batches, pending_links=counts.get("pending", 0), pending_alerts=pending_alerts)


# ---- case page --------------------------------------------------------------------------------------------
@ui.get("/scans/{scan_id}", response_class=HTMLResponse, dependencies=[Depends(reviewer_session)])
def case_page(request: Request, scan_id: int, msg: str | None = None) -> HTMLResponse:
    try:
        p = get_scan_payload(scan_id, include_internal=True)
    except KeyError as e:
        raise HTTPException(404, "scan not found") from e
    with db() as conn:
        obs = [dict(o) for o in conn.execute("SELECT * FROM observations WHERE scan_id=? ORDER BY "
                                             "CASE strength WHEN 'strong' THEN 0 WHEN 'medium' THEN 1 WHEN 'weak' THEN 3 ELSE 2 END, obs_id",
                                             (scan_id,))]
        assessments = [dict(a) for a in conn.execute("SELECT * FROM assessments WHERE scan_id=? ORDER BY assessment_id",
                                                     (scan_id,))]
        history = services.review_history(conn, scan_id)
        links = [services.link_dict(l) for l in conn.execute(
            "SELECT * FROM links WHERE scan_a=? OR scan_b=? OR host_a=? OR host_b=? ORDER BY link_id DESC",
            (scan_id, scan_id, p["host"], p["host"]))]
        alerts = [services.alert_dict(conn, a) for a in conn.execute(
            "SELECT * FROM alerts WHERE watched_host=? OR related_scan_id=? ORDER BY alert_id DESC", (p["host"], scan_id))]
        watchers = conn.execute("SELECT COUNT(*) FROM watches WHERE host=? AND deleted_at IS NULL", (p["host"],)).fetchone()[0]
        other_scans = [dict(r) for r in conn.execute(
            "SELECT scan_id, submitted_at, capture_mode, (SELECT risk_tier FROM assessments WHERE scan_id=scans.scan_id "
            "ORDER BY assessment_id DESC LIMIT 1) tier FROM scans WHERE host=? AND scan_id<>? ORDER BY scan_id DESC LIMIT 20",
            (p["host"], scan_id))]
    for a in assessments:
        a["rules"] = json.loads(a["rules_fired"])
    shots = [a for a in p["artifacts"] if a["kind"] == "screenshot"]
    return render(request, "case.html", p=p, obs=obs, assessments=assessments, history=history, links=links,
                  alerts=alerts, watchers=watchers, shots=shots, other_scans=other_scans, msg=msg,
                  tags=services.BEHAVIOR_TAGS, scam_types=services.SCAM_TYPES)


@ui.post("/scans/{scan_id}/review", dependencies=[Depends(reviewer_session), Depends(check_csrf)])
async def post_review(scan_id: int, request: Request) -> Response:
    form = await request.form()
    with db() as conn:
        try:
            services.create_review(conn, scan_id, str(form.get("label", "")), str(form.get("reviewer") or "reviewer"),
                                   [str(x) for x in form.getlist("behavior_tags")], str(form.get("scam_type") or "") or None,
                                   str(form.get("notes") or ""), form.get("training_eligible") == "on")
        except services.ServiceError as e:
            return back(f"/review/scans/{scan_id}?msg={e}")
    return back(f"/review/scans/{scan_id}?msg=saved")


@ui.post("/scans/{scan_id}/reanalyze", dependencies=[Depends(reviewer_session), Depends(check_csrf)])
def post_reanalyze(scan_id: int) -> Response:
    try:
        p = reanalyze_stored(scan_id)
    except ScanError as e:
        return back(f"/review/scans/{scan_id}?msg={e}")
    return back(f"/review/scans/{p['scan_id']}?msg=re-analyzed")


@ui.get("/artifacts/{artifact_id}", dependencies=[Depends(reviewer_session)])
def reviewer_artifact(artifact_id: int) -> Response:
    with db() as conn:
        a = conn.execute("SELECT * FROM artifacts WHERE artifact_id=?", (artifact_id,)).fetchone()
    if a is None:
        raise HTTPException(404)
    data = read_artifact(a["path"])
    if a["kind"] == "screenshot":
        return Response(data, media_type="image/png")
    # Never render captured HTML/JS: plain-text download only.
    return PlainTextResponse(data.decode("utf-8", "replace"), headers={
        "Content-Disposition": f'attachment; filename="artifact-{artifact_id}-{a["kind"]}.txt"',
        "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'"})


# ---- links & alerts ------------------------------------------------------------------------------------------
@ui.get("/links", response_class=HTMLResponse, dependencies=[Depends(reviewer_session)])
def links_page(request: Request, status: str = "pending") -> HTMLResponse:
    with db() as conn:
        rows = [services.link_dict(l) for l in conn.execute(
            "SELECT * FROM links WHERE review_status=? ORDER BY link_id DESC LIMIT 300", (status,))]
    return render(request, "links.html", links=rows, status=status)


@ui.post("/links/{link_id}/review", dependencies=[Depends(reviewer_session), Depends(check_csrf)])
def post_link_review(link_id: int, decision: str = Form(...), note: str = Form(""), next: str = Form("/review/links")) -> Response:  # noqa: A002
    with db() as conn:
        try:
            services.review_link(conn, link_id, decision, "reviewer", note)
        except services.ServiceError as e:
            raise HTTPException(e.status, str(e)) from e
    return back(next if next.startswith("/review") else "/review/links")


@ui.get("/alerts", response_class=HTMLResponse, dependencies=[Depends(reviewer_session)])
def alerts_page(request: Request, status: str = "pending") -> HTMLResponse:
    with db() as conn:
        rows = [services.alert_dict(conn, a) for a in conn.execute(
            "SELECT * FROM alerts WHERE status=? ORDER BY alert_id DESC LIMIT 300", (status,))]
        for r in rows:
            r["watchers"] = conn.execute("SELECT COUNT(*) FROM watches WHERE host=? AND deleted_at IS NULL",
                                         (r["watched_host"],)).fetchone()[0]
            r["link_status"] = conn.execute("SELECT review_status FROM links WHERE link_id=?", (r["link_id"],)).fetchone()[0]
    return render(request, "alerts.html", alerts=rows, status=status)


@ui.post("/alerts/{alert_id}/{action}", dependencies=[Depends(reviewer_session), Depends(check_csrf)])
def post_alert(alert_id: int, action: str, reason: str = Form(""), next: str = Form("/review/alerts")) -> Response:  # noqa: A002
    with db() as conn:
        try:
            if action == "approve":
                services.approve_alert(conn, alert_id, "reviewer")
            elif action == "withdraw":
                services.withdraw_alert(conn, alert_id, "reviewer", reason)
            else:
                raise HTTPException(404)
        except services.ServiceError as e:
            raise HTTPException(e.status, str(e)) from e
    return back(next if next.startswith("/review") else "/review/alerts")


# ---- discovery queue ------------------------------------------------------------------------------------------
@ui.get("/discovery", response_class=HTMLResponse, dependencies=[Depends(reviewer_session)])
def discovery_page(request: Request, show: str = "relevant") -> HTMLResponse:
    with db() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT d.*, (SELECT risk_tier FROM assessments WHERE scan_id=d.scan_id ORDER BY assessment_id DESC LIMIT 1) tier, "
            "(SELECT score FROM assessments WHERE scan_id=d.scan_id ORDER BY assessment_id DESC LIMIT 1) score "
            "FROM discovered_domains d ORDER BY d.updated_at DESC LIMIT 800")]
    for r in rows:
        r["evidence"] = json.loads(r["evidence"]) if r["evidence"] else None
    if show == "relevant":
        rows = [r for r in rows if r["status"] != "scanned" or r["tier"] in ("high_risk", "caution")]
    return render(request, "discovery.html", rows=rows, show=show)


_capture_lock = threading.Lock()


@ui.post("/discovery/{item_id}/capture", dependencies=[Depends(reviewer_session), Depends(check_csrf)])
def post_discovery_capture(item_id: int) -> Response:
    """Reviewer approval to capture one queued domain (homepage only) with the safe pipeline."""
    with db() as conn:
        d = conn.execute("SELECT * FROM discovered_domains WHERE id=?", (item_id,)).fetchone()
        if d is None:
            raise HTTPException(404)
        conn.execute("UPDATE discovered_domains SET status='scanning', status_note='approved by reviewer', updated_at=? "
                     "WHERE id=?", (utcnow(), item_id))

    def run() -> None:
        with _capture_lock:
            try:
                p = submit_scan(f"https://{d['domain']}/", "discovery", batch=f"{d['source']}_candidates", force=True)
                status, sid, note = "scanned", p["scan_id"], f"tier={p['tier']}; awaiting review"
            except ScanError as e:
                status, sid, note = "failed", None, str(e)[:200]
            with db() as conn:
                conn.execute("UPDATE discovered_domains SET status=?, scan_id=?, status_note=?, updated_at=? WHERE id=?",
                             (status, sid, note, utcnow(), item_id))

    threading.Thread(target=run, daemon=True).start()
    return back("/review/discovery?show=all")


# ---- training ----------------------------------------------------------------------------------------------------
@ui.get("/train", response_class=HTMLResponse, dependencies=[Depends(reviewer_session)])
def train_page(request: Request) -> HTMLResponse:
    job = training_jobs.latest()
    with db() as conn:
        versions = [dict(v) for v in conn.execute("SELECT * FROM model_versions ORDER BY created_at DESC LIMIT 30")]
        datasets = {d["version"]: dict(d) for d in conn.execute("SELECT * FROM dataset_versions")}
    for v in versions:
        v["metrics"] = json.loads(v["metrics_json"])
        v["promotion"] = json.loads(v["promotion_json"] or "{}")
        v["dataset"] = datasets.get(v["dataset_version"])
    result = None
    if job and job.get("result"):
        result = job["result"]
    elif versions:
        v = versions[0]
        result = {"version": v["version"], "status": v["status"], "dataset_version": v["dataset_version"],
                  "dataset_hash": v["dataset_hash"], "metrics": v["metrics"], "promotion": v["promotion"]}
    return render(request, "train.html", job=job, result=result, versions=versions,
                  current=read_registry().get("current"))


@ui.post("/train", dependencies=[Depends(reviewer_session), Depends(check_csrf)])
def post_train(kind: str = Form("full")) -> Response:
    training_jobs.start("synthetic" if kind == "synthetic" else "full")
    return back("/review/train")


# ---- clusters & brief ---------------------------------------------------------------------------------------------
@ui.get("/clusters", response_class=HTMLResponse, dependencies=[Depends(reviewer_session)])
def clusters_page(request: Request) -> HTMLResponse:
    with db() as conn:
        clusters = []
        for cid, scan_ids in sorted(clusters_for_all(conn).items()):
            marks = ",".join("?" * len(scan_ids))
            hosts = sorted({r[0] for r in conn.execute(f"SELECT host FROM scans WHERE scan_id IN ({marks})", tuple(scan_ids))})
            clusters.append({"id": cid, "hosts": hosts, "scans": len(scan_ids)})
    return render(request, "clusters.html", clusters=clusters)


@ui.get("/clusters/{cluster_id}/brief", dependencies=[Depends(reviewer_session)])
def brief_export(cluster_id: int, format: str = "md") -> Response:  # noqa: A002
    with db() as conn:
        try:
            b = build_brief(conn, cluster_id)
        except KeyError as e:
            raise HTTPException(404) from e
    if format == "json":
        return Response(json.dumps(b, indent=2, ensure_ascii=False), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="hami-brief-{cluster_id}.json"'})
    return PlainTextResponse(brief_markdown(b), media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="hami-brief-{cluster_id}.md"'})


_ = cases


# ---- static findings ---------------------------------------------------------------------------------------------
@ui.get("/static", response_class=HTMLResponse, dependencies=[Depends(reviewer_session)])
def static_page(request: Request, msg: str | None = None) -> HTMLResponse:
    with db() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM static_findings ORDER BY finding_id DESC LIMIT 500")]
    return render(request, "static.html", rows=rows, roots=settings.static_authorized_dirs, msg=msg)


@ui.post("/static/run", dependencies=[Depends(reviewer_session), Depends(check_csrf)])
def post_static_run() -> Response:
    from app.static_check import scan_roots

    found = scan_roots([Path(r) for r in settings.static_authorized_dirs])
    return back(f"/review/static?msg={len(found)} suspected secrets found (values never stored)")


@ui.post("/static/{finding_id}/{action}", dependencies=[Depends(reviewer_session), Depends(check_csrf)])
def post_static_review(finding_id: int, action: str) -> Response:
    status = {"confirm": "confirmed", "dismiss": "dismissed"}.get(action)
    if not status:
        raise HTTPException(404)
    with db() as conn:
        conn.execute("UPDATE static_findings SET review_status=?, reviewed_by='reviewer', reviewed_at=? WHERE finding_id=?",
                     (status, utcnow(), finding_id))
    return back("/review/static")
