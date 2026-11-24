"""Redacted case brief for investigators (Markdown + JSON), prepared for human review only.

Contains: the cluster's sites with defanged URLs; first/last observed (our captures) kept separate from
site-reported dates; evidence per link with artifact SHA-256 hashes and capture times; confidence and
review status per link; authorized static findings as redacted notes (never values); and a strict
split between direct observations and inferences. Never includes who submitted or watched a link."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from app import cases
from app.db import utcnow
from app.linking.clusters import cluster_of
from app.scoring import texts as T
from app.urls import defang

OBS_TYPES = ("deposit_to_unlock", "advance_fee", "commission_transfer", "credential_request", "gambling_deposit",
             "investment_promise", "vip_table", "invitation_code", "withdrawal_condition", "commission_rate",
             "off_platform_contact", "deposit_request", "identity_mismatch", "registration_destination", "asset_host",
             "brandlike_hostname")


def build_brief(conn: sqlite3.Connection, ref_id: int) -> dict[str, Any]:
    cid, scan_ids = cluster_of(conn, ref_id)
    if cid is None:
        s = conn.execute("SELECT scan_id, host FROM scans WHERE scan_id=?", (ref_id,)).fetchone()
        if s is None:
            raise KeyError(ref_id)
        scan_ids = [r["scan_id"] for r in conn.execute("SELECT scan_id FROM scans WHERE host=?", (s["host"],))]
        cid = ref_id
    scans = conn.execute(f"SELECT * FROM scans WHERE scan_id IN ({','.join('?' * len(scan_ids))}) ORDER BY scan_id",
                         tuple(scan_ids)).fetchall()
    hosts: dict[str, list[sqlite3.Row]] = {}
    for s in scans:
        hosts.setdefault(s["host"], []).append(s)

    sites, observations, inferences = [], [], []
    for host, rows in hosts.items():
        done = [r for r in rows if r["status"] == "done"]
        captured = sorted(r["captured_at"] for r in done if r["captured_at"])
        latest = done[-1] if done else rows[-1]
        ids = [r["scan_id"] for r in rows]
        marks = ",".join("?" * len(ids))
        site_times = sorted(r[0] for r in conn.execute(
            f"SELECT DISTINCT site_reported_time FROM observations WHERE scan_id IN ({marks}) AND site_reported_time IS NOT NULL",
            tuple(ids)))
        art_scan = latest["stored_from_scan_id"] or latest["scan_id"]
        arts = [dict(a) for a in conn.execute(
            "SELECT artifact_id, kind, sha256, captured_at, action_step FROM artifacts WHERE scan_id=? ORDER BY artifact_id",
            (art_scan,))]
        a = conn.execute("SELECT * FROM assessments WHERE scan_id=? ORDER BY assessment_id DESC LIMIT 1",
                         (latest["scan_id"],)).fetchone()
        review = cases.host_review(conn, host)
        sites.append({
            "host": defang(host), "url": defang(latest["final_url"] or latest["submitted_url"]),
            "first_observed": captured[0] if captured else None, "last_observed": captured[-1] if captured else None,
            "site_reported_dates": {"earliest": site_times[0] if site_times else None,
                                    "latest": site_times[-1] if site_times else None, "count": len(site_times),
                                    "note": "reported by the site itself; not our capture time"},
            "scans": ids, "artifacts": arts,
        })
        for o in conn.execute(f"SELECT * FROM observations WHERE scan_id=? AND indicator_type IN "
                              f"({','.join('?' * len(OBS_TYPES))}) ORDER BY obs_id", (latest["scan_id"], *OBS_TYPES)):
            art = conn.execute("SELECT sha256, captured_at FROM artifacts WHERE artifact_id=?", (o["artifact_id"],)).fetchone()
            observations.append({
                "site": defang(host), "obs_id": o["obs_id"], "type": o["indicator_type"],
                "excerpt": o["redacted_excerpt"], "host_ref": defang(o["host_ref"]) if o["host_ref"] else None,
                "host_relation": o["host_relation"], "context": o["context"],
                "artifact_sha256": art["sha256"] if art else None, "captured_at": art["captured_at"] if art else None,
            })
        inferences.append({
            "site": defang(host), "kind": "risk_assessment", "tier": a["risk_tier"] if a else None,
            "model_score": round(a["score"], 3) if a and a["score"] is not None else None,
            "model_version": a["model_version"] if a else None,
            "rules_fired": json.loads(a["rules_fired"]) if a else [],
            "reviewer_label": review["label"] if review else None,
            "reviewed_at": review["created_at"] if review else None,
        })

    links = []
    marks = ",".join("?" * len(scan_ids))
    for l in conn.execute(f"SELECT * FROM links WHERE scan_a IN ({marks}) OR scan_b IN ({marks}) ORDER BY link_id",
                          (*scan_ids, *scan_ids)):
        if l["scan_a"] not in scan_ids and l["scan_b"] not in scan_ids:
            continue
        evidence = []
        for sig in json.loads(l["evidence_json"]):
            art_rows = [dict(r) for r in conn.execute(
                f"SELECT artifact_id, kind, sha256, captured_at FROM artifacts WHERE artifact_id IN "
                f"({','.join('?' * len(sig['artifact_ids'])) or 'NULL'})", tuple(sig["artifact_ids"]))]
            evidence.append({"relation": sig["relation"], "strength": sig["strength"], "detail": _defang_text(sig["detail"]),
                             "observation_ids": sig["obs_ids"], "artifacts": art_rows})
        links.append({
            "link_id": l["link_id"], "between": [defang(l["host_a"]), defang(l["host_b"])],
            "relation_type": l["relation_type"], "confidence": l["strength"], "review_status": l["review_status"],
            "reviewed_at": l["reviewed_at"], "evidence": evidence,
            "inference_note": "a lead for investigation, not proof of common ownership",
        })
        inferences.append({"kind": "link", "link_id": l["link_id"], "relation_type": l["relation_type"],
                           "confidence": l["strength"], "review_status": l["review_status"]})

    host_list = list(hosts)
    findings = []
    if host_list:
        for f in conn.execute(f"SELECT * FROM static_findings WHERE related_host IN ({','.join('?' * len(host_list))})",
                              tuple(host_list)):
            findings.append({"note": f"Suspected {f['category'].replace('_', ' ')} in an authorized file (value redacted; "
                                     f"never stored or tested)", "category": f["category"], "file": f["file_path"],
                             "line": f["line"], "column": f["col"], "detected_at": f["detected_at"],
                             "review_status": f["review_status"], "site": defang(f["related_host"])})
    return {
        "brief_version": 1, "generated_at": utcnow(), "cluster_id": cid,
        "status_note": "Prepared for human review. Not sent to police automatically. Contains no reporter identities.",
        "sites": sites, "links": links, "static_findings": findings,
        "observations": observations, "inferences": inferences,
    }


def _defang_text(s: str) -> str:
    import re
    return re.sub(r"\b((?:[a-z0-9-]+\.)+[a-z]{2,24})\b", lambda m: defang(m.group(1)), s, flags=re.I)


def brief_markdown(b: dict[str, Any]) -> str:
    L = [f"# Hami case brief — cluster {b['cluster_id']}", "",
         f"_Generated {b['generated_at']}. {b['status_note']}_", "", "## Sites", "",
         "| Site | First observed (capture) | Last observed (capture) | Site-reported dates | Scans |",
         "|---|---|---|---|---|"]
    for s in b["sites"]:
        sr = s["site_reported_dates"]
        srt = f"{sr['earliest']} → {sr['latest']} ({sr['count']})" if sr["count"] else "none"
        L.append(f"| `{s['url']}` | {s['first_observed'] or '-'} | {s['last_observed'] or '-'} | {srt} | {len(s['scans'])} |")
    L += ["", "## Links between sites", ""]
    if not b["links"]:
        L.append("No proposed or approved links.")
    for l in b["links"]:
        L.append(f"### Link {l['link_id']}: `{l['between'][0]}` ↔ `{l['between'][1]}`")
        label = T.RELATION_TEXT.get(l["relation_type"], {}).get("en", "")
        L.append(f"- Relation: **{l['relation_type']}**{f' ({label})' if label else ''} · confidence **{l['confidence']}** · review status **{l['review_status']}**"
                 + (f" ({l['reviewed_at']})" if l["reviewed_at"] else ""))
        for e in l["evidence"]:
            L.append(f"- [{e['strength']}] {e['relation']}: {e['detail']} (observations {e['observation_ids'] or '-'})")
            for a in e["artifacts"]:
                L.append(f"  - artifact {a['artifact_id']} ({a['kind']}, captured {a['captured_at']}) sha256 `{a['sha256']}`")
        L.append(f"- _{l['inference_note']}_")
        L.append("")
    L += ["## Direct observations", "", "| Site | Observation | Excerpt / host | Artifact SHA-256 | Captured |", "|---|---|---|---|---|"]
    for o in b["observations"]:
        detail = (o["excerpt"] or "") if not o["host_ref"] else f"{o['host_ref']} ({o['host_relation']}, {o['context']})"
        detail = detail.replace("|", "\\|")[:140]
        L.append(f"| `{o['site']}` | {o['type']} | {detail} | `{(o['artifact_sha256'] or '')[:16]}…` | {o['captured_at'] or '-'} |")
    L += ["", "## Inferences (not observations)", ""]
    for i in b["inferences"]:
        if i["kind"] == "risk_assessment":
            L.append(f"- `{i['site']}`: tier **{i['tier']}**, model score {i['model_score']} ({i['model_version']}), "
                     f"rules {', '.join(i['rules_fired'])}; reviewer label: {i['reviewer_label'] or 'not reviewed'}")
        else:
            L.append(f"- link {i['link_id']}: {i['relation_type']} ({i['confidence']}), {i['review_status']}")
    L += ["", "## Authorized static findings (redacted)", ""]
    if not b["static_findings"]:
        L.append("None.")
    for f in b["static_findings"]:
        L.append(f"- {f['note']}: `{f['file']}` line {f['line']}, column {f['column']} · detected {f['detected_at']} · "
                 f"review status {f['review_status']}")
    L += ["", "## Full artifact list", ""]
    for s in b["sites"]:
        L.append(f"**`{s['host']}`**")
        for a in s["artifacts"]:
            L.append(f"- {a['kind']} (step {a['action_step']}) captured {a['captured_at']} · sha256 `{a['sha256']}`")
    return "\n".join(L) + "\n"
