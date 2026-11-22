"""Related-site linking.

Signals (proposal, Part 4):
  registration destination in captured JSON  -> strong
  distinctive asset host                     -> strong
  same page template (layout + form fields)  -> medium
  same payment script (amounts + steps)      -> medium
  shared common service                      -> weak, never links alone
A pair becomes a candidate with one strong signal, or two medium signals from different artifacts.
Hostnames shared by many unrelated sites are treated as common services. A candidate link touching
a watched case where the other side shows a fraud behavior creates a *pending* alert; nothing is
sent without reviewer approval. Links never follow a referenced URL."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.analyze.hosts import common_service_category
from app.analyze.html_features import fingerprint_similarity
from app.db import db, tx, utcnow
from app.scoring import texts as T
from app.urls import defang, registrable_domain

TEMPLATE_SIM = 0.85
DYNAMIC_COMMON_MIN_SITES = 8
MAX_COMPARE_HOSTS = 3000
FRAUD_INDICATORS = ("deposit_to_unlock", "advance_fee", "commission_transfer", "gambling_deposit", "investment_promise",
                    "credential_request", "deposit_request", "vip_table", "invitation_code", "withdrawal_condition",
                    "commission_rate", "off_platform_contact", "code_behavior")
RELATION_ORDER = ("same_kit", "registration_destination", "asset_host", "shared_infrastructure", "same_template",
                  "same_payment_script", "infrastructure_pattern")


def dynamic_common_hosts(conn: sqlite3.Connection, min_sites: int = DYNAMIC_COMMON_MIN_SITES) -> set[str]:
    rows = conn.execute(
        "SELECT o.host_ref FROM observations o JOIN scans s ON s.scan_id=o.scan_id "
        "WHERE o.indicator_type IN ('asset_host','host_reference','registration_destination') AND o.host_ref IS NOT NULL "
        "GROUP BY o.host_ref HAVING COUNT(DISTINCT s.host) >= ?", (min_sites,)).fetchall()
    return {r[0] for r in rows}


def _scan_profile(conn: sqlite3.Connection, scan_id: int) -> dict[str, Any] | None:
    s = conn.execute("SELECT * FROM scans WHERE scan_id=?", (scan_id,)).fetchone()
    if s is None or s["status"] != "done":
        return None
    obs = conn.execute("SELECT * FROM observations WHERE scan_id=?", (scan_id,)).fetchall()
    html0 = conn.execute("SELECT artifact_id FROM artifacts WHERE scan_id=? AND kind='html' ORDER BY action_step, "
                         "artifact_id LIMIT 1", (s["stored_from_scan_id"] or scan_id,)).fetchone()
    prof = {
        "scan_id": scan_id, "host": s["host"], "site": registrable_domain(s["host"]),
        "fingerprint": json.loads(s["fingerprint"]) if s["fingerprint"] else [],
        "form_signature": s["form_signature"], "payment_signature": s["payment_signature"],
        "html_artifact": html0["artifact_id"] if html0 else None,
        "reg": {}, "assets": {}, "common": {}, "fraud": [], "payment_obs": [],
    }
    for o in obs:
        t = o["indicator_type"]
        if t == "registration_destination":
            prof["reg"].setdefault(o["host_ref"], []).append(o)
        elif t == "asset_host":
            prof["assets"].setdefault(o["host_ref"], []).append(o)
        elif t == "common_service":
            prof["common"].setdefault(o["host_ref"], []).append(o)
        if t in FRAUD_INDICATORS and o["strength"] in ("strong", "medium"):
            prof["fraud"].append(t)
        if t in ("deposit_to_unlock", "deposit_request", "advance_fee", "currency_amount"):
            prof["payment_obs"].append(o)
    return prof


def compare(a: dict[str, Any], b: dict[str, Any], common: set[str]) -> list[dict[str, Any]]:
    """Signals linking two scans (b is the new scan). Each signal cites observation and artifact ids."""
    signals: list[dict[str, Any]] = []
    for src, dst in ((a, b), (b, a)):
        if dst["host"] in src["reg"]:
            obs = src["reg"][dst["host"]]
            signals.append({"relation": "registration_destination", "strength": "strong",
                            "detail": f"{src['host']} references {dst['host']} as a registration destination "
                                      f"({obs[0]['context']}; {obs[0]['host_relation']})",
                            "obs_ids": [o["obs_id"] for o in obs], "artifact_ids": sorted({o["artifact_id"] for o in obs if o["artifact_id"]})})
    shared_assets = [h for h in set(a["assets"]) & set(b["assets"])
                     if h not in common and not common_service_category(h)
                     and registrable_domain(h) not in (a["site"], b["site"])]
    for h in sorted(shared_assets):
        obs = a["assets"][h] + b["assets"][h]
        signals.append({"relation": "asset_host", "strength": "strong",
                        "detail": f"both load or reference assets from {h}",
                        "obs_ids": [o["obs_id"] for o in obs], "artifact_ids": sorted({o["artifact_id"] for o in obs if o["artifact_id"]})})
    sim = fingerprint_similarity(a["fingerprint"], b["fingerprint"])
    if sim >= TEMPLATE_SIM and a["form_signature"] and a["form_signature"] == b["form_signature"]:
        signals.append({"relation": "same_template", "strength": "medium",
                        "detail": f"layout fingerprint similarity {sim:.2f} and identical form fields",
                        "obs_ids": [], "artifact_ids": sorted(x for x in (a["html_artifact"], b["html_artifact"]) if x)})
    if a["payment_signature"] and a["payment_signature"] == b["payment_signature"]:
        obs = a["payment_obs"] + b["payment_obs"]
        signals.append({"relation": "same_payment_script", "strength": "medium",
                        "detail": "identical deposit amounts and payment steps",
                        "obs_ids": [o["obs_id"] for o in obs], "artifact_ids": sorted({o["artifact_id"] for o in obs if o["artifact_id"]})})
    shared_common = sorted(set(a["common"]) & set(b["common"]))
    if shared_common:
        signals.append({"relation": "shared_common_service", "strength": "weak",
                        "detail": "shared common services (never links alone): " + ", ".join(shared_common[:5]),
                        "obs_ids": [], "artifact_ids": []})
    return signals


def is_candidate(signals: list[dict[str, Any]]) -> bool:
    if any(s["strength"] == "strong" for s in signals):
        return True
    medium = [s for s in signals if s["strength"] == "medium"]
    if len(medium) >= 2:
        arts = [frozenset(m["artifact_ids"]) for m in medium]
        return len(set(arts)) >= 2  # backed by different artifacts
    return False


def process_scan(scan_id: int) -> list[int]:
    """Compare a finished scan with the latest scan of every other site; create pending candidate links
    and pending alerts. Returns new link ids."""
    created: list[int] = []
    with db() as conn:
        new = _scan_profile(conn, scan_id)
        if new is None:
            return created
        scan = conn.execute("SELECT capture_status, batch FROM scans WHERE scan_id=?", (scan_id,)).fetchone()
        if scan["capture_status"] not in ("ok",) and not new["fingerprint"]:
            return created
        if common_service_category(new["host"]):
            return created
        common = dynamic_common_hosts(conn)
        from app.linking.kit import infra_signals, kit_matches

        kits = {k.site: k for k in kit_matches(conn, scan_id)}
        others = conn.execute(
            "SELECT MAX(scan_id) AS scan_id, host FROM scans WHERE status='done' AND host<>? AND capture_status='ok' "
            "GROUP BY host ORDER BY MAX(scan_id) DESC LIMIT ?", (new["host"], MAX_COMPARE_HOSTS)).fetchall()
        for o in others:
            other = _scan_profile(conn, o["scan_id"])
            if other is None:
                continue
            signals = compare(other, new, common)
            km = kits.get(other["site"])
            if km is not None and other["host"] in km.scan_hosts:
                signals.insert(0, {"relation": "same_kit", "strength": km.strength,
                                   "detail": (f"same software kit: {len(km.files)} identical delivered files"
                                              if km.strength == "strong" else
                                              f"partial kit match: {len(km.files)} shared distinctive files")
                                   + " (" + ", ".join(km.files[:8]) + ")",
                                   "obs_ids": [], "artifact_ids": _har_artifacts(conn, other["scan_id"], scan_id),
                                   "files": km.files})
            signals += [x for x in infra_signals(conn, other["scan_id"], scan_id, common)
                        if not any(y["relation"] == x["relation"] for y in signals)]
            if not is_candidate(signals):
                continue
            # One open link per pair of sites: a re-scan of either site does not re-propose it.
            exists = conn.execute(
                "SELECT 1 FROM links WHERE review_status IN ('pending','approved') AND "
                "((host_a=? AND host_b=?) OR (host_a=? AND host_b=?))",
                (other["host"], new["host"], new["host"], other["host"])).fetchone()
            if exists:
                continue
            strong = [s for s in signals if s["strength"] == "strong"]
            primary = sorted(strong or [s for s in signals if s["strength"] == "medium"],
                             key=lambda s: RELATION_ORDER.index(s["relation"]))[0]
            obs_ids = sorted({i for s in signals for i in s["obs_ids"]})
            with tx(conn):
                lid = conn.execute(
                    "INSERT INTO links (scan_a, scan_b, host_a, host_b, relation_type, strength, evidence_obs_ids, "
                    "evidence_json, review_status, created_at) VALUES (?,?,?,?,?,?,?,?, 'pending', ?)",
                    (other["scan_id"], scan_id, other["host"], new["host"], primary["relation"],
                     "strong" if strong else "medium", json.dumps(obs_ids), json.dumps(signals), utcnow())).lastrowid
            created.append(lid)
            _pending_alerts_for_link(conn, lid)
    return created


def _har_artifacts(conn: sqlite3.Connection, *scan_ids: int) -> list[int]:
    out = []
    for sid in scan_ids:
        row = conn.execute("SELECT a.artifact_id FROM artifacts a JOIN scans s ON a.scan_id=COALESCE(s.stored_from_scan_id, s.scan_id) "
                           "WHERE s.scan_id=? AND a.kind='har' ORDER BY a.artifact_id LIMIT 1", (sid,)).fetchone()
        if row:
            out.append(row[0])
    return out


def _has_fraud(conn: sqlite3.Connection, scan_id: int) -> bool:
    marks = ",".join("?" * len(FRAUD_INDICATORS))
    row = conn.execute(f"SELECT 1 FROM observations WHERE scan_id=? AND strength IN ('strong','medium') "
                       f"AND indicator_type IN ({marks}) LIMIT 1", (scan_id, *FRAUD_INDICATORS)).fetchone()
    return row is not None


def _fraud_summary(conn: sqlite3.Connection, scan_id: int) -> tuple[str, str]:
    rows = conn.execute("SELECT DISTINCT indicator_type FROM observations WHERE scan_id=? AND strength='strong'",
                        (scan_id,)).fetchall()
    types = [r[0] for r in rows if r[0] in T.CLUE_TEXT] or ["deposit_request"]
    t = T.CLUE_TEXT[types[0]]
    return t["en"].format(amount="", listing="", claimed="", relation=""), t["ar"].format(amount="", listing="", claimed="", relation="")


def _pending_alerts_for_link(conn: sqlite3.Connection, link_id: int) -> list[int]:
    link = conn.execute("SELECT * FROM links WHERE link_id=?", (link_id,)).fetchone()
    if link is None or link["review_status"] == "rejected":
        return []
    out = []
    for watched_host, watched_scan, related_scan, related_host in (
            (link["host_a"], link["scan_a"], link["scan_b"], link["host_b"]),
            (link["host_b"], link["scan_b"], link["scan_a"], link["host_a"])):
        watchers = conn.execute("SELECT COUNT(*) FROM watches WHERE host=? AND deleted_at IS NULL", (watched_host,)).fetchone()[0]
        if not watchers or not _has_fraud(conn, related_scan):
            continue
        rel = T.RELATION_TEXT.get(link["relation_type"], {"en": link["relation_type"], "ar": link["relation_type"]})
        fen, far = _fraud_summary(conn, related_scan)
        reason_en = (f"A related site ({defang(related_host)}) was found, connected to the site you watched by "
                     f"{rel['en']}. {fen} Do not pay.")
        reason_ar = (f"تم العثور على موقع مرتبط ({defang(related_host)}) بالموقع الذي تتابعه عبر {rel['ar']}. {far} لا تدفع.")
        with tx(conn):
            cur = conn.execute(
                "INSERT INTO alerts (link_id, watched_host, watched_scan_id, related_scan_id, reason_en, reason_ar,"
                " status, created_at) VALUES (?,?,?,?,?,?, 'pending', ?) ON CONFLICT DO NOTHING",
                (link_id, watched_host, watched_scan, related_scan, reason_en, reason_ar, utcnow()))
        if cur.rowcount:
            out.append(cur.lastrowid)
    return out


def alerts_for_new_watch(conn: sqlite3.Connection, host: str) -> list[int]:
    """A new watch on a case with existing (non-rejected) links gets pending alerts too."""
    out = []
    for l in conn.execute("SELECT link_id FROM links WHERE review_status<>'rejected' AND (host_a=? OR host_b=?)",
                          (host, host)).fetchall():
        out.extend(_pending_alerts_for_link(conn, l["link_id"]))
    return out

