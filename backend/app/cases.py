"""Case-level queries shared by scoring, linking, lookups and indicators.

A *case* is a site (normalized host). Reviews are append-only; the effective review of a scan is
its newest review (each new review supersedes the previous one)."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.urls import registrable_domain


def effective_review(conn: sqlite3.Connection, scan_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM reviews WHERE scan_id=? ORDER BY review_id DESC LIMIT 1", (scan_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["behavior_tags"] = json.loads(d["behavior_tags"] or "[]")
    return d


def host_review(conn: sqlite3.Connection, host: str) -> dict[str, Any] | None:
    """Newest review of any scan of this host."""
    row = conn.execute(
        "SELECT r.* FROM reviews r JOIN scans s ON s.scan_id=r.scan_id WHERE s.host=? "
        "ORDER BY r.review_id DESC LIMIT 1", (host,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["behavior_tags"] = json.loads(d["behavior_tags"] or "[]")
    return d


def reviewed_fraud_scans(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Scans whose host's newest review is 'fraudulent'."""
    return conn.execute(
        """
        WITH latest AS (
          SELECT s.host, MAX(r.review_id) AS rid FROM reviews r JOIN scans s ON s.scan_id=r.scan_id GROUP BY s.host
        )
        SELECT s.* FROM scans s JOIN latest l ON l.host=s.host JOIN reviews r ON r.review_id=l.rid
        WHERE r.label='fraudulent' AND s.status='done'
        """).fetchall()


def high_risk_hosts(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], int]:
    """Hosts from reviewer-approved fraudulent cases whose assessment is High risk (or confirmed
    fraudulent by the reviewer). Returns (hosts, version)."""
    rows = conn.execute(
        """
        WITH latest AS (
          SELECT s.host, MAX(r.review_id) AS rid FROM reviews r JOIN scans s ON s.scan_id=r.scan_id GROUP BY s.host
        )
        SELECT l.host, r.created_at, r.behavior_tags FROM latest l JOIN reviews r ON r.review_id=l.rid
        WHERE r.label='fraudulent' ORDER BY l.host
        """).fetchall()
    version = conn.execute("SELECT COALESCE(MAX(review_id),0) FROM reviews").fetchone()[0]
    return [{"host": r["host"], "reviewed_at": r["created_at"],
             "behavior_tags": json.loads(r["behavior_tags"] or "[]")} for r in rows], int(version)


def strong_reviewed_links(conn: sqlite3.Connection, scan_id: int, host: str,
                          asset_hosts: list[str], common: set[str]) -> list[dict[str, Any]]:
    """Strong signals tying this page to a reviewer-confirmed fraudulent case:
    - this host is a registration destination referenced by a reviewed fraudulent scan, or
    - a reviewed fraudulent scan references this host's registration destinations, or
    - a distinctive (non-common, other-site) asset host is shared with a reviewed fraudulent scan."""
    out: list[dict[str, Any]] = []
    fraud = [r for r in reviewed_fraud_scans(conn) if r["host"] != host]
    if not fraud:
        return out
    fraud_ids = [r["scan_id"] for r in fraud]
    marks = ",".join("?" * len(fraud_ids))
    my_site = registrable_domain(host)
    rows = conn.execute(
        f"SELECT scan_id, host_ref FROM observations WHERE indicator_type='registration_destination' "
        f"AND scan_id IN ({marks}) AND host_ref=?", (*fraud_ids, host)).fetchall()
    for r in rows:
        out.append({"relation": "registration_destination", "scan_id": r["scan_id"], "host": host})
    fraud_hosts = {r["host"]: r["scan_id"] for r in fraud}
    my_regs = conn.execute(
        "SELECT host_ref FROM observations WHERE scan_id=? AND indicator_type='registration_destination'",
        (scan_id,)).fetchall()
    for r in my_regs:
        if r["host_ref"] in fraud_hosts:
            out.append({"relation": "registration_destination", "scan_id": fraud_hosts[r["host_ref"]], "host": r["host_ref"]})
    distinctive = [h for h in asset_hosts if h not in common and registrable_domain(h) != my_site]
    if distinctive:
        m2 = ",".join("?" * len(distinctive))
        rows = conn.execute(
            f"SELECT DISTINCT scan_id, host_ref FROM observations WHERE indicator_type='asset_host' "
            f"AND scan_id IN ({marks}) AND host_ref IN ({m2})", (*fraud_ids, *distinctive)).fetchall()
        for r in rows:
            out.append({"relation": "asset_host", "scan_id": r["scan_id"], "host": r["host_ref"]})
    approved = conn.execute(
        "SELECT * FROM links WHERE review_status='approved' AND strength='strong' AND (host_a=? OR host_b=?)",
        (host, host)).fetchall()
    fraud_host_set = set(fraud_hosts)
    for l in approved:
        other = l["host_b"] if l["host_a"] == host else l["host_a"]
        if other in fraud_host_set:
            out.append({"relation": l["relation_type"], "scan_id": l["scan_b"] if l["host_a"] == host else l["scan_a"],
                        "host": other, "link_id": l["link_id"]})
    seen, dedup = set(), []
    for o in out:
        k = (o["relation"], o["host"])
        if k not in seen:
            seen.add(k)
            dedup.append(o)
    return dedup


def domain_inheritance(conn: sqlite3.Connection, host: str) -> dict[str, Any] | None:
    """A subdomain (or sibling host) of a reviewer-confirmed fraudulent registrable domain inherits the risk.
    The Public Suffix List (private section included) keeps shared platforms like *.github.io separate."""
    site = registrable_domain(host)
    if not site or site == host and "." not in site:
        return None
    for s in reviewed_fraud_scans(conn):
        if s["host"] != host and registrable_domain(s["host"]) == site:
            return {"domain": site, "confirmed_host": s["host"], "scan_id": s["scan_id"]}
    return None


def kit_context(conn: sqlite3.Connection, scan_id: int, host: str, common: set[str]) -> dict[str, Any]:
    """Kit and infrastructure matches between this scan and reviewer-confirmed fraudulent cases."""
    from app.linking.kit import infra_signals, kit_matches

    fraud = {}
    for s in reviewed_fraud_scans(conn):
        if registrable_domain(s["host"]) != registrable_domain(host):
            fraud.setdefault(registrable_domain(s["host"]), s)
    strong, partial = [], []
    for k in kit_matches(conn, scan_id):
        if k.site in fraud:
            entry = {"relation": "same_kit", "scan_id": fraud[k.site]["scan_id"], "host": fraud[k.site]["host"],
                     "files": k.files[:25], "n_files": len(k.files)}
            (strong if k.strength == "strong" else partial).append(entry)
    for site, s in list(fraud.items())[:200]:
        for sig in infra_signals(conn, s["scan_id"], scan_id, common):
            entry = {"relation": sig["relation"], "scan_id": s["scan_id"], "host": s["host"], "detail": sig["detail"]}
            (strong if sig["strength"] == "strong" else partial).append(entry)
    return {"strong": strong, "partial": partial}
