"""Domain operations shared by the API and the reviewer console."""
from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from app import cases
from app.db import tx, utcnow
from app.urls import defang

LABELS = ("fraudulent", "legitimate", "inconclusive")
BEHAVIOR_TAGS = ("advance_fee", "deposit_to_unlock", "commission_transfer", "brand_misuse", "identity_mismatch",
                 "credential_request", "off_platform_contact", "fake_shop", "investment_promise", "gambling_deposit")
SCAM_TYPES = ("task_scam", "gambling_deposit", "fake_shop", "investment", "phishing", "parcel", "other")


class ServiceError(ValueError):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


# ---- reviews (append-only; a new review supersedes the scan's previous one) -----------------------
def create_review(conn: sqlite3.Connection, scan_id: int, label: str, reviewer: str, behavior_tags: list[str] | None = None,
                  scam_type: str | None = None, notes: str | None = None, training_eligible: bool = True) -> dict[str, Any]:
    if label not in LABELS:
        raise ServiceError("label must be fraudulent, legitimate or inconclusive")
    tags = [t for t in (behavior_tags or []) if t]
    bad = [t for t in tags if t not in BEHAVIOR_TAGS]
    if bad:
        raise ServiceError(f"unknown behavior tags: {bad}")
    if scam_type and scam_type not in SCAM_TYPES:
        raise ServiceError(f"unknown scam_type: {scam_type}")
    if label != "fraudulent":
        scam_type = None
    scan = conn.execute("SELECT scan_id, status FROM scans WHERE scan_id=?", (scan_id,)).fetchone()
    if scan is None:
        raise ServiceError("unknown scan", 404)
    if scan["status"] != "done":
        raise ServiceError("scan is not finished", 409)
    prev = cases.effective_review(conn, scan_id)
    eligible = 1 if (training_eligible and label in ("fraudulent", "legitimate")) else 0  # inconclusive never trains
    with tx(conn):
        rid = conn.execute(
            "INSERT INTO reviews (scan_id, label, behavior_tags, scam_type, notes, reviewer, supersedes, training_eligible,"
            " created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (scan_id, label, json.dumps(tags), scam_type, (notes or "")[:2000] or None, reviewer[:80],
             prev["review_id"] if prev else None, eligible, utcnow())).lastrowid
    return review_history(conn, scan_id)[-1] | {"review_id": rid}


def review_history(conn: sqlite3.Connection, scan_id: int) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM reviews WHERE scan_id=? ORDER BY review_id", (scan_id,)).fetchall()
    out = []
    superseded = {r["supersedes"] for r in rows if r["supersedes"]}
    for r in rows:
        d = dict(r)
        d["behavior_tags"] = json.loads(d["behavior_tags"] or "[]")
        d["training_eligible"] = bool(d["training_eligible"])
        d["superseded"] = r["review_id"] in superseded
        out.append(d)
    return out


# ---- links ----------------------------------------------------------------------------------------
def review_link(conn: sqlite3.Connection, link_id: int, decision: str, reviewer: str, note: str | None = None) -> dict[str, Any]:
    if decision not in ("approve", "reject"):
        raise ServiceError("decision must be approve or reject")
    link = conn.execute("SELECT * FROM links WHERE link_id=?", (link_id,)).fetchone()
    if link is None:
        raise ServiceError("unknown link", 404)
    status = "approved" if decision == "approve" else "rejected"
    with tx(conn):
        conn.execute("UPDATE links SET review_status=?, reviewed_by=?, reviewed_at=?, review_note=? WHERE link_id=?",
                     (status, reviewer[:80], utcnow(), (note or "")[:1000] or None, link_id))
        if status == "rejected":
            conn.execute("UPDATE alerts SET status='cancelled' WHERE link_id=? AND status='pending'", (link_id,))
    return link_dict(conn.execute("SELECT * FROM links WHERE link_id=?", (link_id,)).fetchone())


def link_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["evidence_obs_ids"] = json.loads(d["evidence_obs_ids"] or "[]")
    d["evidence"] = json.loads(d.pop("evidence_json") or "[]")
    return d


# ---- alerts (pending until a reviewer approves; withdrawals stay visible) ---------------------------
def approve_alert(conn: sqlite3.Connection, alert_id: int, reviewer: str) -> dict[str, Any]:
    a = conn.execute("SELECT * FROM alerts WHERE alert_id=?", (alert_id,)).fetchone()
    if a is None:
        raise ServiceError("unknown alert", 404)
    if a["status"] != "pending":
        raise ServiceError(f"alert is {a['status']}", 409)
    link = conn.execute("SELECT review_status FROM links WHERE link_id=?", (a["link_id"],)).fetchone()
    if link["review_status"] != "approved":
        raise ServiceError("approve the underlying link first", 409)
    now = utcnow()
    with tx(conn):
        conn.execute("UPDATE alerts SET status='approved', approved_by=?, approved_at=?, sent_at=? WHERE alert_id=?",
                     (reviewer[:80], now, now, alert_id))
    return alert_dict(conn, conn.execute("SELECT * FROM alerts WHERE alert_id=?", (alert_id,)).fetchone())


def withdraw_alert(conn: sqlite3.Connection, alert_id: int, reviewer: str, reason: str | None) -> dict[str, Any]:
    a = conn.execute("SELECT * FROM alerts WHERE alert_id=?", (alert_id,)).fetchone()
    if a is None:
        raise ServiceError("unknown alert", 404)
    if a["status"] not in ("approved", "pending"):
        raise ServiceError(f"alert is {a['status']}", 409)
    with tx(conn):
        conn.execute("UPDATE alerts SET status='withdrawn', withdrawn_at=?, withdrawn_by=?, withdrawn_reason=? "
                     "WHERE alert_id=?", (utcnow(), reviewer[:80], (reason or "")[:500] or None, alert_id))
    return alert_dict(conn, conn.execute("SELECT * FROM alerts WHERE alert_id=?", (alert_id,)).fetchone())


def alert_dict(conn: sqlite3.Connection, a: sqlite3.Row, public: bool = False) -> dict[str, Any]:
    rel = conn.execute("SELECT host, final_url FROM scans WHERE scan_id=?", (a["related_scan_id"],)).fetchone()
    tier = conn.execute("SELECT risk_tier FROM assessments WHERE scan_id=? ORDER BY assessment_id DESC LIMIT 1",
                        (a["related_scan_id"],)).fetchone()
    d = {
        "alert_id": a["alert_id"], "watched_host": a["watched_host"], "related_host": rel["host"] if rel else None,
        "related_host_defanged": defang(rel["host"]) if rel else None,
        "related_tier": tier["risk_tier"] if tier else None,
        "reason": {"en": a["reason_en"], "ar": a["reason_ar"]},
        "status": a["status"], "created_at": a["created_at"], "sent_at": a["sent_at"],
        "withdrawn": a["status"] == "withdrawn", "withdrawn_at": a["withdrawn_at"],
        "withdrawn_reason": a["withdrawn_reason"],
    }
    if not public:
        d.update({"link_id": a["link_id"], "watched_scan_id": a["watched_scan_id"], "related_scan_id": a["related_scan_id"],
                  "approved_by": a["approved_by"], "approved_at": a["approved_at"], "withdrawn_by": a["withdrawn_by"]})
    return d


def alerts_for_device(conn: sqlite3.Connection, device_id: str) -> list[dict[str, Any]]:
    """Approved (sent) alerts for hosts this device watches; withdrawn alerts stay listed, flagged."""
    rows = conn.execute(
        "SELECT DISTINCT a.* FROM alerts a JOIN watches w ON w.host=a.watched_host "
        "WHERE w.device_id=? AND w.deleted_at IS NULL AND a.sent_at IS NOT NULL AND a.status IN ('approved','withdrawn') "
        "ORDER BY a.sent_at DESC", (device_id,)).fetchall()
    return [alert_dict(conn, r, public=True) for r in rows]


# ---- watches ----------------------------------------------------------------------------------------
def create_watch(conn: sqlite3.Connection, scan_id: int, device_id: str) -> dict[str, Any]:
    scan = conn.execute("SELECT scan_id, host FROM scans WHERE scan_id=?", (scan_id,)).fetchone()
    if scan is None:
        raise ServiceError("unknown scan", 404)
    existing = conn.execute("SELECT * FROM watches WHERE device_id=? AND host=? AND deleted_at IS NULL",
                            (device_id, scan["host"])).fetchone()
    if existing:
        return dict(existing)
    wid = str(uuid.uuid4())
    with tx(conn):
        conn.execute("INSERT INTO watches (watch_id, scan_id, host, device_id, created_at) VALUES (?,?,?,?,?)",
                     (wid, scan_id, scan["host"], device_id, utcnow()))
    from app.linking import alerts_for_new_watch

    alerts_for_new_watch(conn, scan["host"])
    return dict(conn.execute("SELECT * FROM watches WHERE watch_id=?", (wid,)).fetchone())


def delete_watch(conn: sqlite3.Connection, watch_id: str, device_id: str | None) -> bool:
    w = conn.execute("SELECT * FROM watches WHERE watch_id=? AND deleted_at IS NULL", (watch_id,)).fetchone()
    if w is None or (device_id and w["device_id"] != device_id):
        return False
    with tx(conn):
        conn.execute("UPDATE watches SET deleted_at=? WHERE watch_id=?", (utcnow(), watch_id))
    return True


def watches_for_device(conn: sqlite3.Connection, device_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT w.watch_id, w.scan_id, w.host, w.created_at, "
        "(SELECT risk_tier FROM assessments WHERE scan_id=w.scan_id ORDER BY assessment_id DESC LIMIT 1) AS tier "
        "FROM watches w WHERE w.device_id=? AND w.deleted_at IS NULL ORDER BY w.created_at DESC", (device_id,)).fetchall()
    return [dict(r) for r in rows]


# ---- host lookups (Search shields): no new capture ----------------------------------------------------
def lookup_hosts(conn: sqlite3.Connection, hosts: list[str]) -> dict[str, Any]:
    out = {}
    for raw in hosts[:60]:
        h = (raw or "").strip().lower().rstrip(".")
        if h.startswith("www."):
            h = h[4:]
        if not h or len(h) > 253:
            continue
        rev = cases.host_review(conn, h)
        if rev and rev["label"] in ("fraudulent", "legitimate"):
            out[raw] = {"known": True, "source": "reviewed",
                        "tier": "high_risk" if rev["label"] == "fraudulent" else "no_strong_signals",
                        "reviewed_at": rev["created_at"]}
            continue
        a = conn.execute(
            "SELECT a.risk_tier, a.created_at FROM assessments a JOIN scans s ON s.scan_id=a.scan_id "
            "WHERE s.host=? ORDER BY a.assessment_id DESC LIMIT 1", (h,)).fetchone()
        if a:
            out[raw] = {"known": True, "source": "assessment", "tier": a["risk_tier"], "assessed_at": a["created_at"]}
        else:
            out[raw] = {"known": False, "tier": None}
    return out
