"""Discovery worker: finds newly issued look-alike domains in public certificate transparency logs.

    python -m app.discovery.worker            # loop every DISCOVERY_POLL_S seconds
    python -m app.discovery.worker --once     # one cycle (queries + rate-limited captures)
    python -m app.discovery.worker --once --no-capture

Rate limits: DISCOVERY_QUERY_GAP_S between CT queries, DISCOVERY_CAPTURE_GAP_S between captures,
DISCOVERY_MAX_CAPTURES_PER_CYCLE captures per cycle. Only certificates issued within
DISCOVERY_MAX_AGE_DAYS are considered. Never run mass scans from the campus network."""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import httpx
import yaml

from app import cases
from app.config import settings
from app.db import db, utcnow
from app.urls import defang, registrable_domain

PATTERNS_FILE = Path(__file__).with_name("patterns.yaml")
USER_AGENT = "Hami-discovery/1.0 (hackathon research prototype; rate-limited)"
HOST_OK = re.compile(r"^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$")


@dataclass
class Candidate:
    domain: str
    cert_seen_at: str | None
    source_detail: str


def log(msg: str) -> None:
    print(f"[discovery {datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


# ---- patterns ------------------------------------------------------------------------------------
def load_patterns(conn=None) -> dict[str, Any]:  # noqa: ANN001
    cfg = yaml.safe_load(PATTERNS_FILE.read_text(encoding="utf-8")) or {}
    cfg.setdefault("crtsh_queries", [])
    cfg.setdefault("name_patterns", [])
    cfg.setdefault("exclude", [])
    cfg.setdefault("certspotter_domains", [])
    terms = list(cfg.get("extra_brand_terms") or [])
    reviewed_domains: list[str] = []
    if conn is not None:
        for s in cases.reviewed_fraud_scans(conn):
            host = s["host"]
            if host.endswith(".localhost"):
                continue
            reviewed_domains.append(registrable_domain(host))
            for label in host.split("."):
                m = re.match(r"^([a-z]{3,})-?(vip|gl|mall|shop|global|uae|task|order)\d*$", label)
                if m:
                    terms.append(m.group(1) + "-" + m.group(2))
    for term in dict.fromkeys(terms):
        safe = re.escape(term.lower())
        cfg["name_patterns"].append({"name": f"reviewed_case_term:{term}", "regex": safe.replace(r"\-", "-?")})
        cfg["crtsh_queries"].append(f"%{term}%")
    cfg["certspotter_domains"] = list(dict.fromkeys(list(cfg["certspotter_domains"]) + reviewed_domains))
    cfg["_compiled"] = [(p["name"], re.compile(p["regex"], re.I)) for p in cfg["name_patterns"]]
    cfg["_exclude"] = [re.compile(x, re.I) for x in cfg["exclude"]]
    return cfg


def match_name(name: str, cfg: dict[str, Any]) -> str | None:
    name = name.lower().strip().lstrip("*.").rstrip(".")
    if not HOST_OK.match(name) or any(x.search(name) for x in cfg["_exclude"]):
        return None
    for pname, rx in cfg["_compiled"]:
        if rx.search(name):
            return pname
    return None


def recent(ts: str | None, max_age_days: int) -> bool:
    if not ts:
        return True
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return True
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt >= datetime.now(timezone.utc) - timedelta(days=max_age_days)


# ---- sources ---------------------------------------------------------------------------------------
def crtsh(client: httpx.Client, query: str) -> list[Candidate]:
    r = client.get("https://crt.sh/", params={"q": query, "output": "json", "exclude": "expired", "deduplicate": "Y"},
                   timeout=60)
    r.raise_for_status()
    out = []
    for e in r.json():
        seen = e.get("entry_timestamp") or e.get("not_before")
        for name in str(e.get("name_value", "")).split():
            out.append(Candidate(name.lower().lstrip("*.").rstrip("."), seen, f"crt.sh:{query}"))
    return out


def certspotter(client: httpx.Client, domain: str) -> list[Candidate]:
    r = client.get("https://api.certspotter.com/v1/issuances",
                   params={"domain": domain, "include_subdomains": "true", "expand": "dns_names"}, timeout=30)
    r.raise_for_status()
    out = []
    for e in r.json():
        for name in e.get("dns_names", []):
            out.append(Candidate(name.lower().lstrip("*.").rstrip("."), e.get("not_before"), f"certspotter:{domain}"))
    return out


def certstream(seconds: float) -> list[Candidate]:
    """Listen to the public CertStream feed for a few seconds (if reachable)."""
    async def run() -> list[Candidate]:
        import websockets

        out: list[Candidate] = []
        end = time.monotonic() + seconds
        async with websockets.connect("wss://certstream.calidog.io/", open_timeout=10, max_size=2 ** 22) as ws:
            while time.monotonic() < end:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=max(1.0, end - time.monotonic())))
                if msg.get("message_type") != "certificate_update":
                    continue
                leaf = msg["data"]["leaf_cert"]
                ts = datetime.fromtimestamp(leaf.get("not_before", time.time()), timezone.utc).isoformat()
                for name in leaf.get("all_domains", []):
                    out.append(Candidate(name.lower().lstrip("*.").rstrip("."), ts, "certstream"))
        return out

    try:
        return asyncio.run(run())
    except Exception as e:  # feed unavailable or timeout: other sources still run
        log(f"certstream unavailable ({type(e).__name__})")
        return []


# ---- queue -----------------------------------------------------------------------------------------
def enqueue(candidates: Iterable[Candidate], cfg: dict[str, Any]) -> int:
    added = 0
    now = utcnow()
    with db() as conn:
        for c in candidates:
            if not recent(c.cert_seen_at, settings.discovery_max_age_days):
                continue
            pname = match_name(c.domain, cfg)
            if not pname:
                continue
            cur = conn.execute(
                "INSERT OR IGNORE INTO discovered_domains (domain, source, cert_seen_at, first_seen_at, matched_pattern, "
                "evidence, status, updated_at) VALUES (?,?,?,?,?,?, 'queued', ?)",
                (c.domain, "ct", c.cert_seen_at, now, pname, json.dumps({"source": c.source_detail}), now))
            if cur.rowcount:
                added += 1
                log(f"new match {defang(c.domain)} ({pname}; {c.source_detail})")
    return added


def capture_queued(max_captures: int, gap: float) -> int:
    from app.pipeline import ScanError, submit_scan

    with db() as conn:
        rows = conn.execute("SELECT id, domain FROM discovered_domains WHERE source='ct' AND status='queued' "
                            "ORDER BY cert_seen_at DESC LIMIT ?", (max_captures,)).fetchall()
    done = 0
    for i, r in enumerate(rows):
        if i:
            time.sleep(gap)
        with db() as conn:
            conn.execute("UPDATE discovered_domains SET status='scanning', updated_at=? WHERE id=?", (utcnow(), r["id"]))
        try:
            p = submit_scan(f"https://{r['domain']}/", "discovery", batch="discovery", force=True)
            status, sid, note = "scanned", p["scan_id"], f"tier={p['tier']}"
            log(f"captured {defang(r['domain'])} -> {p['tier']}")
        except ScanError as e:
            status, sid, note = "skipped", None, str(e)[:200]
        with db() as conn:
            conn.execute("UPDATE discovered_domains SET status=?, scan_id=?, status_note=?, updated_at=? WHERE id=?",
                         (status, sid, note, utcnow(), r["id"]))
        done += 1
    return done


def cycle(capture: bool = True, certstream_seconds: float = 20.0, extra_domains: list[str] | None = None,
          skip_crtsh: bool = False) -> dict[str, int]:
    with db() as conn:
        cfg = load_patterns(conn)
    cfg["certspotter_domains"] = list(dict.fromkeys(cfg["certspotter_domains"] + (extra_domains or [])))
    if skip_crtsh:
        cfg["crtsh_queries"] = []
    stats = {"queries": 0, "errors": 0, "candidates": 0, "queued": 0, "captured": 0}
    with httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        jobs = [("crt.sh", q) for q in cfg["crtsh_queries"]] + [("certspotter", d) for d in cfg["certspotter_domains"]]
        for i, (src, arg) in enumerate(jobs):
            if i:
                time.sleep(settings.discovery_query_gap_s)
            try:
                cands = crtsh(client, arg) if src == "crt.sh" else certspotter(client, arg)
                stats["queries"] += 1
                stats["candidates"] += len(cands)
                stats["queued"] += enqueue(cands, cfg)
            except (httpx.HTTPError, ValueError) as e:
                stats["errors"] += 1
                log(f"{src} {arg!r} failed: {type(e).__name__} {str(e)[:80]}")
    if certstream_seconds > 0:
        cands = certstream(certstream_seconds)
        stats["candidates"] += len(cands)
        stats["queued"] += enqueue(cands, cfg)
    if capture:
        stats["captured"] = capture_queued(settings.discovery_max_captures_per_cycle, settings.discovery_capture_gap_s)
    log(f"cycle done: {stats}")
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--no-capture", action="store_true")
    ap.add_argument("--certstream-seconds", type=float, default=20.0)
    ap.add_argument("--domain", action="append", default=[], help="extra registrable domain to monitor (Cert Spotter)")
    ap.add_argument("--skip-crtsh", action="store_true")
    args = ap.parse_args(argv)
    settings.ensure_dirs()
    if not settings.discovery_enabled:
        log("DISCOVERY_ENABLED=false; exiting")
        return 0
    while True:
        cycle(capture=not args.no_capture, certstream_seconds=args.certstream_seconds, extra_domains=args.domain,
              skip_crtsh=args.skip_crtsh)
        if args.once:
            return 0
        time.sleep(max(60, settings.discovery_poll_s))


if __name__ == "__main__":
    sys.exit(main())
