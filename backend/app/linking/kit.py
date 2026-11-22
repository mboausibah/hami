"""Kit fingerprinting: do two sites run the same software?

Evidence is the files a page delivered (JS, CSS, fonts, images): identical SHA-256, identical content-hashed
build names, or near-identical bundles (shingle sketch). Files are weighted by distinctiveness: anything on
the common-asset list, served from a common-service host, ever delivered on a legitimate capture, or seen on
many unrelated sites is common and ignored. App-specific chunks and language packs are the strongest
evidence. Infrastructure is compared too: shared API / CDN / support-SDK / payment hosts and API host naming
patterns."""
from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from app.analyze.assets import is_vendor_chunk, sketch_similarity
from app.analyze.hosts import common_service_category
from app.db import utcnow
from app.urls import registrable_domain

COMMON_SITE_COUNT = 6          # a file on this many unrelated sites is common
MIN_FILE_BYTES = 512           # tiny files (empty JSON, 1x1 pixels) are never kit evidence
KIT_KINDS = ("js", "css", "font", "image")
NEAR_IDENTICAL = 0.8
STRONG_MIN_FILES = 3
LANG_PACK_RE = re.compile(r"^[a-z]{2}([-_][A-Za-z]{2,4})?$")


def store_assets(conn: sqlite3.Connection, scan_id: int, page_host: str, rows: list[dict[str, Any]],
                 source: str = "capture") -> int:
    site = registrable_domain(page_host)
    now = utcnow()
    for r in rows:
        conn.execute(
            "INSERT INTO asset_files (scan_id, host, site, file_name, chunk_name, name_hashed, kind, sha256, size_bytes,"
            " sketch, source, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (scan_id, r["host"], site, r["file_name"], r["chunk_name"], r["name_hashed"], r["kind"], r["sha256"],
             r["size_bytes"], json.dumps(r["sketch"]) if r.get("sketch") else None, source, now))
    return len(rows)


def _legit_sites(conn: sqlite3.Connection) -> set[str]:
    sites = {registrable_domain(r[0]) for r in conn.execute("SELECT DISTINCT host FROM scans WHERE batch='legit_urls'")}
    rows = conn.execute(
        "SELECT s.host, r.label FROM reviews r JOIN scans s ON s.scan_id=r.scan_id "
        "JOIN (SELECT s2.host h, MAX(r2.review_id) rid FROM reviews r2 JOIN scans s2 ON s2.scan_id=r2.scan_id GROUP BY s2.host) l "
        "ON l.rid=r.review_id").fetchall()
    sites |= {registrable_domain(r["host"]) for r in rows if r["label"] == "legitimate"}
    return sites


def common_shas(conn: sqlite3.Connection, shas: list[str]) -> set[str]:
    """Which of these hashes are common: on a legitimate capture, or on many unrelated sites."""
    if not shas:
        return set()
    legit = _legit_sites(conn)
    out = set()
    marks = ",".join("?" * len(shas))
    per: dict[str, set[str]] = defaultdict(set)
    for r in conn.execute(f"SELECT sha256, site FROM asset_files WHERE sha256 IN ({marks})", shas):
        per[r["sha256"]].add(r["site"])
    for sha, sites in per.items():
        if sites & legit or len(sites) >= COMMON_SITE_COUNT:
            out.add(sha)
    return out


@dataclass
class KitMatch:
    site: str
    host: str
    scan_id: int
    files: list[str] = field(default_factory=list)       # matching file names (evidence)
    scan_hosts: set[str] = field(default_factory=set)     # page hosts whose captures delivered the matching files
    app_specific: int = 0                                 # non-vendor chunks / language packs among them
    strength: str = "medium"                              # strong = same software kit, medium = partial

    def to_dict(self) -> dict[str, Any]:
        return {"site": self.site, "host": self.host, "scan_id": self.scan_id, "files": self.files[:25],
                "n_files": len(self.files), "app_specific": self.app_specific, "strength": self.strength}


def _distinctive(conn: sqlite3.Connection, scan_id: int) -> list[sqlite3.Row]:
    from app.analyze.assets import common_file_name

    rows = [r for r in conn.execute("SELECT * FROM asset_files WHERE scan_id=?", (scan_id,))
            if r["kind"] in KIT_KINDS and (r["size_bytes"] or 0) >= MIN_FILE_BYTES
            and not common_service_category(r["host"]) and not common_file_name(r["file_name"])]
    common = common_shas(conn, [r["sha256"] for r in rows])
    return [r for r in rows if r["sha256"] not in common]


def kit_matches(conn: sqlite3.Connection, scan_id: int) -> list[KitMatch]:
    """Other sites that delivered the same distinctive files as this scan."""
    scan = conn.execute("SELECT host FROM scans WHERE scan_id=?", (scan_id,)).fetchone()
    if scan is None:
        return []
    my_site = registrable_domain(scan["host"])
    mine = _distinctive(conn, scan_id)
    if not mine:
        return []
    by_site: dict[str, dict[str, Any]] = {}

    def hit(r: sqlite3.Row, mine_row: sqlite3.Row, how: str) -> None:
        if r["site"] == my_site:
            return
        if r["kind"] not in KIT_KINDS:
            return
        e = by_site.setdefault(r["site"], {"files": {}, "scan_id": r["scan_id"], "host": r["host"], "scans": set()})
        e["scan_id"] = max(e["scan_id"], r["scan_id"])
        e["scans"].add(r["scan_id"])
        label = mine_row["file_name"] + ("" if how == "identical" else f" ({how})")
        e["files"][mine_row["file_name"]] = (label, mine_row)

    shas = [r["sha256"] for r in mine]
    marks = ",".join("?" * len(shas))
    by_sha = defaultdict(list)
    for r in mine:
        by_sha[r["sha256"]].append(r)
    for r in conn.execute(f"SELECT * FROM asset_files WHERE sha256 IN ({marks})", shas):
        for m in by_sha[r["sha256"]]:
            hit(r, m, "identical")
    hashed = [r for r in mine if r["name_hashed"]]
    if hashed:
        names = {r["file_name"]: r for r in hashed}
        nm = ",".join("?" * len(names))
        for r in conn.execute(f"SELECT * FROM asset_files WHERE file_name IN ({nm})", list(names)):
            hit(r, names[r["file_name"]], "same build name")
    for m in mine:
        if not m["sketch"] or not m["chunk_name"]:
            continue
        sk = json.loads(m["sketch"])
        for r in conn.execute("SELECT * FROM asset_files WHERE chunk_name=? AND sketch IS NOT NULL AND site<>? "
                              "AND sha256<>? LIMIT 200", (m["chunk_name"], my_site, m["sha256"])):
            if sketch_similarity(sk, json.loads(r["sketch"])) >= NEAR_IDENTICAL:
                hit(r, m, "near-identical")

    out = []
    for site, e in by_site.items():
        files = [lab for lab, _ in e["files"].values()]
        app_specific = sum(1 for _, r in e["files"].values()
                           if r["kind"] in ("js", "css") and not is_vendor_chunk(r["chunk_name"], r["file_name"]))
        lang_pack = any(LANG_PACK_RE.match(r["chunk_name"] or "") for _, r in e["files"].values())
        strong = len(files) >= STRONG_MIN_FILES and (app_specific >= 1 or lang_pack)
        marks2 = ",".join("?" * len(e["scans"]))
        scan_hosts = {r[0] for r in conn.execute(f"SELECT DISTINCT host FROM scans WHERE scan_id IN ({marks2})",
                                                 tuple(e["scans"]))}
        page_host = next(iter(sorted(scan_hosts, key=len)), e["host"])
        out.append(KitMatch(site=site, host=page_host, scan_id=e["scan_id"], files=sorted(files),
                            app_specific=app_specific, strength="strong" if strong else "medium",
                            scan_hosts=scan_hosts))
    out.sort(key=lambda k: (k.strength != "strong", -len(k.files)))
    return out


# ---- infrastructure --------------------------------------------------------------------------------
def _infra_hosts(conn: sqlite3.Connection, scan_id: int, my_site: str, common: set[str]) -> set[str]:
    rows = conn.execute("SELECT DISTINCT host_ref FROM observations WHERE scan_id=? AND host_ref IS NOT NULL AND "
                        "indicator_type IN ('host_reference','asset_host','registration_destination') AND "
                        "host_relation IN ('observed','referenced_and_observed')", (scan_id,)).fetchall()
    return {r[0] for r in rows if r[0] not in common and not common_service_category(r[0])
            and registrable_domain(r[0]) != my_site}


def api_pattern(host: str) -> str | None:
    """'h5server.betnalaapi.com' -> 'h5server.*api.com': same API naming scheme on a different brand domain."""
    parts = host.split(".")
    if len(parts) < 3:
        return None
    reg = registrable_domain(host)
    label = reg.split(".")[0]
    m = re.match(r"^[a-z0-9]+?(api|server|cdn|res|resource|static|pay|cs)\d*$", label)
    if not m or parts[0] in ("www", "api", "cdn", "static", "img", "m"):
        return None
    return f"{parts[0]}.*{m.group(1)}.{reg.split('.', 1)[1]}"


def infra_signals(conn: sqlite3.Connection, scan_a: int, scan_b: int, common: set[str]) -> list[dict[str, Any]]:
    ha = conn.execute("SELECT host FROM scans WHERE scan_id=?", (scan_a,)).fetchone()["host"]
    hb = conn.execute("SELECT host FROM scans WHERE scan_id=?", (scan_b,)).fetchone()["host"]
    sa, sb = registrable_domain(ha), registrable_domain(hb)
    ia, ib = _infra_hosts(conn, scan_a, sa, common), _infra_hosts(conn, scan_b, sb, common)
    out = []
    shared = sorted(ia & ib)
    if shared:
        out.append({"relation": "shared_infrastructure", "strength": "strong",
                    "detail": "both pages contacted the same API/CDN/support/payment hosts: " + ", ".join(shared[:6]),
                    "obs_ids": [], "artifact_ids": []})
    pa = {p for p in (api_pattern(h) for h in ia) if p}
    pb = {p for p in (api_pattern(h) for h in ib) if p}
    same = sorted(pa & pb)
    if same:
        out.append({"relation": "infrastructure_pattern", "strength": "medium",
                    "detail": "same API host naming scheme on different domains: " + ", ".join(same[:4]),
                    "obs_ids": [], "artifact_ids": []})
    return out
