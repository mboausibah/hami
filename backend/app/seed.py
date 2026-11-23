"""Seed indicators: reviewer-confirmed cases shipped with Hami so a fresh install can already match kits and
inherit risk across registrable domains.

    python tasks.py export-indicators      writes data/seed/indicators.json from this machine's reviewed cases
    (loaded automatically by `app.cli migrate` / `python tasks.py run` / the Docker entrypoint)

What is exported, per confirmed case (registrable domain):
  label, scam type, behavior tags, kit ID, review date, reviewed hostnames, the site's *distinctive* delivered
  files (SHA-256, file name, build-chunk name, kind, size and a bottom-k shingle sketch: hashes, not content),
  and infrastructure hosts it contacted (API / CDN / support / payment hosts).
What is never exported: page text, screenshots, HTML, HARs, request URLs with paths or queries, e-mails, phone
numbers, tokens, cookies, local file paths. `validate()` enforces this before writing and before loading.

Loading creates one `scans` row per reviewed host (batch 'seed', no artifacts), the files as `asset_files`, the
infrastructure hosts as observations, and a review "seeded from team review". The normal kit matching, domain
inheritance, infrastructure signals and on-device lists then use them like any reviewed case. Loading is
idempotent: hosts already seeded are skipped.
"""
from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import REPO_DIR, settings
from app.db import db, tx, utcnow
from app.urls import hostname, registrable_domain

SEED_PATH = REPO_DIR / "data" / "seed" / "indicators.json"
SEED_BATCH = "seed"
SEED_REVIEWER = "Hami team (seeded from team review)"
SEED_NOTE = "seeded from team review (data/seed/indicators.json): indicators only, no page content"
FORMAT = 1

HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
FILE_RE = re.compile(r"^[A-Za-z0-9._~+-]{1,160}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
PATHLIKE_RE = re.compile(r"@|data[/\\]private|eyJ[A-Za-z0-9_-]{8,}")
FORBIDDEN_RE = re.compile(r"@|data[/\\]private|[A-Za-z]:\\|/home/|/Users/|eyJ[A-Za-z0-9_-]{8,}|\+?\d[\d\s-]{8,}\d")


# ---- export -------------------------------------------------------------------------------------------------
def _team_labels() -> dict[str, dict[str, Any]]:
    """registrable domain -> {kit_id, scam_type, behavior_tags} from the team's labels.csv, if this machine has it."""
    path = settings.private_dir / "datasets" / "labels.csv"
    out: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return out
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            ref = (row.get("file_or_url") or "").strip()
            if not ref.lower().startswith("http") or (row.get("label") or "").strip() != "fraudulent":
                continue
            e = out.setdefault(registrable_domain(hostname(ref)), {"kit_id": "", "scam_type": "", "behavior_tags": set()})
            e["kit_id"] = e["kit_id"] or (row.get("kit_id") or "").strip()
            e["scam_type"] = e["scam_type"] or (row.get("scam_type") or "").strip()
            e["behavior_tags"] |= {t.strip() for t in (row.get("behavior_tags") or "").split(";") if t.strip()}
    return out


def _seedable(r: Any) -> bool:
    """Images only when the build named them (content hash): generic shared images (game-provider thumbnails,
    CMS uploads) also appear on unrelated sites and would weaken a fresh install's kit matching."""
    return r["kind"] != "image" or bool(r["name_hashed"])


def export_indicators(out: Path = SEED_PATH) -> dict[str, Any]:
    from app.cases import reviewed_fraud_scans
    from app.linking.kit import _distinctive, _infra_hosts

    team = _team_labels()
    cases: dict[str, dict[str, Any]] = {}
    with db() as conn:
        latest = conn.execute(
            """WITH latest AS (SELECT s.host, MAX(r.review_id) AS rid FROM reviews r JOIN scans s ON s.scan_id=r.scan_id
                               WHERE COALESCE(s.batch, '') <> 'seed' GROUP BY s.host)
               SELECT l.host, r.label, r.scam_type, r.behavior_tags, r.created_at FROM latest l
               JOIN reviews r ON r.review_id=l.rid WHERE r.label='fraudulent' ORDER BY l.host""").fetchall()
        reviewed = {r["host"]: r for r in latest}
        scans = [s for s in reviewed_fraud_scans(conn) if s["host"] in reviewed and s["batch"] != SEED_BATCH]
        by_site: dict[str, list] = defaultdict(list)
        for s in scans:
            by_site[registrable_domain(s["host"])].append(s)
        for site, ss in sorted(by_site.items()):
            files: dict[str, dict[str, Any]] = {}
            infra: set[str] = set()
            for s in ss:
                for r in _distinctive(conn, s["scan_id"]):
                    if r["sha256"] in files or not _seedable(r):
                        continue
                    files[r["sha256"]] = {
                        "sha256": r["sha256"], "file_name": r["file_name"], "chunk_name": r["chunk_name"],
                        "name_hashed": bool(r["name_hashed"]), "kind": r["kind"], "size_bytes": r["size_bytes"],
                        "host": r["host"], "sketch": json.loads(r["sketch"]) if r["sketch"] else None}
                infra |= _infra_hosts(conn, s["scan_id"], site, set())
            hosts = sorted({s["host"] for s in ss})
            revs = [reviewed[h] for h in hosts]
            t = team.get(site, {})
            tags = sorted({x for r in revs for x in json.loads(r["behavior_tags"] or "[]")} | set(t.get("behavior_tags", ())))
            cases[site] = {
                "registrable_domain": site, "label": "fraudulent",
                "scam_type": next((r["scam_type"] for r in revs if r["scam_type"]), None) or t.get("scam_type") or None,
                "behavior_tags": tags, "kit_id": t.get("kit_id") or f"seed_{site}",
                "reviewed_at": max(r["created_at"] for r in revs)[:10], "hosts": hosts,
                "infrastructure_hosts": sorted(infra),
                "assets": sorted(files.values(), key=lambda a: (a["kind"], a["file_name"])),
            }
    doc = {"format": FORMAT, "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
           "source": "Hami team review (reviewer-confirmed cases)",
           "contents": "indicators only: domains, hostnames, kit IDs, distinctive file hashes/names, infrastructure "
                       "hosts, labels, review dates. No page text, screenshots, personal data or tokens.",
           "cases": list(cases.values())}
    validate(doc)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=1, ensure_ascii=True) + "\n", encoding="utf-8", newline="\n")
    return {"path": str(out), "cases": len(doc["cases"]), "assets": sum(len(c["assets"]) for c in doc["cases"]),
            "hosts": sum(len(c["hosts"]) for c in doc["cases"])}


# ---- validation (export and load) ----------------------------------------------------------------------------
def validate(doc: dict[str, Any]) -> None:
    if doc.get("format") != FORMAT or not isinstance(doc.get("cases"), list):
        raise ValueError("not a Hami seed file (format 1)")
    allowed_case = {"registrable_domain", "label", "scam_type", "behavior_tags", "kit_id", "reviewed_at", "hosts",
                    "infrastructure_hosts", "assets"}
    allowed_asset = {"sha256", "file_name", "chunk_name", "name_hashed", "kind", "size_bytes", "host", "sketch"}
    for c in doc["cases"]:
        if set(c) - allowed_case:
            raise ValueError(f"unexpected case fields: {sorted(set(c) - allowed_case)}")
        if c["label"] not in ("fraudulent", "legitimate"):
            raise ValueError("label must be fraudulent or legitimate")
        for h in [c["registrable_domain"], *c["hosts"], *c["infrastructure_hosts"]]:
            if not HOST_RE.match(h or ""):
                raise ValueError(f"not a bare hostname: {h!r}")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", c["reviewed_at"] or ""):
            raise ValueError("reviewed_at must be a date")
        for a in c["assets"]:
            if set(a) - allowed_asset:
                raise ValueError(f"unexpected asset fields: {sorted(set(a) - allowed_asset)}")
            if not SHA_RE.match(a["sha256"]) or not FILE_RE.match(a["file_name"]) or not HOST_RE.match(a["host"]):
                raise ValueError(f"bad asset entry: {a.get('file_name')!r}")
            if a["sketch"] is not None and not all(isinstance(x, int) for x in a["sketch"]):
                raise ValueError("sketch must be a list of integers")
        meta = json.dumps({k: v for k, v in c.items() if k not in ("assets", "reviewed_at")})
        names = " ".join(f"{a['file_name']} {a['chunk_name'] or ''}" for a in c["assets"])
        if FORBIDDEN_RE.search(meta) or PATHLIKE_RE.search(names):
            raise ValueError(f"seed case {c['registrable_domain']} contains an e-mail, phone-like number, token or path")


# ---- load ---------------------------------------------------------------------------------------------------
def load_seed(path: Path | None = None) -> dict[str, int]:
    path = path or Path(settings.seed_path)
    if not path.is_file():
        return {"cases": 0, "hosts": 0, "assets": 0}
    doc = json.loads(path.read_text(encoding="utf-8"))
    validate(doc)
    added = {"cases": 0, "hosts": 0, "assets": 0}
    with db() as conn, tx(conn):
        seeded = {r[0] for r in conn.execute("SELECT host FROM scans WHERE batch=?", (SEED_BATCH,))}
        for c in doc["cases"]:
            new_hosts = [h for h in c["hosts"] if h not in seeded]
            if not new_hosts:
                continue
            at = c["reviewed_at"] + "T00:00:00.000000Z"
            first = None
            for h in new_hosts:
                sid = conn.execute(
                    "INSERT INTO scans (submitted_url, normalized_url, host, source_type, batch, submitted_at, status,"
                    " capture_mode, capture_status, captured_at, completed_at, final_url) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (f"https://{h}/", f"https://{h}/", h, "import", SEED_BATCH, at, "done", "stored", "seed", at, at,
                     f"https://{h}/")).lastrowid
                conn.execute("INSERT INTO reviews (scan_id, label, behavior_tags, scam_type, notes, reviewer,"
                             " training_eligible, created_at) VALUES (?,?,?,?,?,?,?,?)",
                             (sid, c["label"], json.dumps(c["behavior_tags"]), c["scam_type"], SEED_NOTE,
                              SEED_REVIEWER, 0, at))
                first = first or sid
                added["hosts"] += 1
            now = utcnow()
            for a in c["assets"]:
                conn.execute(
                    "INSERT INTO asset_files (scan_id, host, site, file_name, chunk_name, name_hashed, kind, sha256,"
                    " size_bytes, sketch, source, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (first, a["host"], c["registrable_domain"], a["file_name"], a["chunk_name"], int(a["name_hashed"]),
                     a["kind"], a["sha256"], a["size_bytes"], json.dumps(a["sketch"]) if a["sketch"] else None,
                     "seed", now))
                added["assets"] += 1
            for h in c["infrastructure_hosts"]:
                conn.execute("INSERT INTO observations (scan_id, indicator_type, strength, host_ref, host_relation,"
                             " context, created_at, source) VALUES (?,?,?,?,?,?,?,?)",
                             (first, "asset_host", "info", h, "observed", "seeded from team review", now, "seed"))
            added["cases"] += 1
    return added


def main() -> int:
    r = export_indicators()
    print(f"wrote {r['path']}: {r['cases']} confirmed cases, {r['hosts']} hosts, {r['assets']} distinctive files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
