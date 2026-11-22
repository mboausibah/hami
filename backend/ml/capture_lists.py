"""Capture approved URL lists with the safe pipeline, rate-limited and sequential.

    python -m ml.capture_lists labels          # URL rows of datasets/labels.csv
    python -m ml.capture_lists legit           # datasets/legit_urls.csv: homepage + up to 3 same-site nav pages
    python -m ml.capture_lists har-candidates  # registration destinations referenced in HAR files (homepage only)
    python -m ml.capture_lists live            # datasets/live_urls.csv (real-world evaluation set)

Nothing runs without --yes: running the command with --yes is the team's approval. Captures never
submit forms, sign in or follow links beyond the explicit same-site navigation pages."""
from __future__ import annotations

import argparse
import csv
import sys
import time

from app.config import settings
from app.db import db, utcnow
from app.pipeline import ScanError, submit_scan
from app.urls import defang, ensure_scheme

NAV_PAGES = 3


def _rows(name: str) -> list[dict]:
    path = settings.private_dir / "datasets" / name
    if not path.is_file():
        raise SystemExit(f"{path} not found")
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _scan(url: str, batch: str, source: str = "import", **kw) -> dict | None:
    try:
        p = submit_scan(url, source, batch=batch, force=True, **kw)
    except ScanError as e:
        print(f"    refused: {e}")
        return None
    print(f"    #{p['scan_id']} {p['capture_status']:<11} tier={p['tier']:<22} {p.get('duration_ms') or 0:>6} ms  "
          f"{defang(p['final_url'] or url)[:70]}")
    return p


def capture_labels(gap: float) -> None:
    urls = [r["file_or_url"].strip() for r in _rows("labels.csv") if r.get("file_or_url", "").strip().lower().startswith("http")]
    print(f"labels.csv: {len(urls)} URLs")
    for i, u in enumerate(urls):
        if i:
            time.sleep(gap)
        print(f"  [{i + 1}/{len(urls)}] {defang(u)}")
        _scan(u, "labels")


def capture_live(gap: float) -> None:
    urls = [r["url"].strip() for r in _rows("live_urls.csv") if r.get("url", "").strip()]
    print(f"live_urls.csv: {len(urls)} URLs")
    for i, u in enumerate(urls):
        if i:
            time.sleep(gap)
        print(f"  [{i + 1}/{len(urls)}] {defang(u)}")
        _scan(u, "live_eval")


def capture_legit(gap: float, limit: int | None) -> None:
    rows = _rows("legit_urls.csv")[: limit or None]
    print(f"legit_urls.csv: {len(rows)} sites (homepage + up to {NAV_PAGES} same-site navigation pages each)")
    for i, r in enumerate(rows):
        url = ensure_scheme(r["url"].strip())
        print(f"  [{i + 1}/{len(rows)}] {url} ({r.get('category', '')})")
        home = _scan(url, "legit_urls", collect_nav=True)
        time.sleep(gap)
        if not home or home.get("capture_status") != "ok":
            continue
        for link in (home.get("nav_links") or [])[:NAV_PAGES]:
            _scan(link, "legit_urls", parent_scan_id=home["scan_id"], run_actions=False)
            time.sleep(gap)


def capture_har_candidates(gap: float) -> None:
    with db() as conn:
        rows = conn.execute("SELECT id, domain FROM discovered_domains WHERE source='har_reference' "
                            "AND status IN ('awaiting_approval','queued','failed') ORDER BY id").fetchall()
        conn.execute("UPDATE discovered_domains SET status='queued', status_note='approved for capture', updated_at=? "
                     "WHERE source='har_reference' AND status='awaiting_approval'", (utcnow(),))
    print(f"HAR review candidates: {len(rows)} domains (homepage only; results go to the reviewer discovery queue)")
    for i, r in enumerate(rows):
        if i:
            time.sleep(gap)
        print(f"  [{i + 1}/{len(rows)}] {defang(r['domain'])}")
        with db() as conn:
            conn.execute("UPDATE discovered_domains SET status='scanning', updated_at=? WHERE id=?", (utcnow(), r["id"]))
        p = _scan(f"https://{r['domain']}/", "har_candidates", source="discovery")
        with db() as conn:
            if p:
                conn.execute("UPDATE discovered_domains SET status='scanned', scan_id=?, status_note=?, updated_at=? WHERE id=?",
                             (p["scan_id"], f"tier={p['tier']}; awaiting review (never labeled automatically)", utcnow(), r["id"]))
            else:
                conn.execute("UPDATE discovered_domains SET status='failed', updated_at=? WHERE id=?", (utcnow(), r["id"]))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("which", choices=["labels", "legit", "har-candidates", "live"])
    ap.add_argument("--yes", action="store_true", help="confirm the team approved this capture")
    ap.add_argument("--gap", type=float, default=settings.bulk_capture_gap_s, help="seconds between page loads")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)
    if not args.yes:
        print("This visits real public websites with the safe capture pipeline. Re-run with --yes once the team has "
              "approved this list (run it from your own connection, not campus Wi-Fi).")
        return 2
    gap = max(2.0, args.gap)
    {"labels": lambda: capture_labels(gap), "live": lambda: capture_live(gap),
     "legit": lambda: capture_legit(gap, args.limit), "har-candidates": lambda: capture_har_candidates(gap)}[args.which]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
