"""Importer: data/private (+ public datasets + synthetic corpus) -> data/processed/records.jsonl + report.

- Saved HTML/MHTML/HAR files go through the same sanitizer and analyzer as live scans.
- URL rows use captures made with the safe pipeline *after approval* (make capture-labels /
  capture-legit); URLs not captured yet are listed, never fetched here.
- Domains referenced inside HAR files are review candidates only (discovery queue, unlabeled).
- Missing labels -> listed as unlabeled, never guessed. Missing kit_id -> proposed groups by layout
  fingerprint and shared distinctive hostnames, shown for confirmation.
- Empty lang -> detected from the page text.

Usage: python -m ml.import_private [--no-synthetic] [--no-public] [--register-candidates]
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from app.analyze.html_features import fingerprint_similarity
from app.analyze.hosts import common_service_category
from app.config import REPO_DIR, settings
from app.db import db, utcnow
from app.urls import normalize_url, registrable_domain
from ml.arabic import detect_lang
from ml.records import LABELS, analyze_file, make_record, scan_record_parts, write_jsonl

SITE_EXTS = {".html", ".htm", ".mhtml", ".mht", ".har"}
CORPUS_DIR = REPO_DIR / "testsites" / "corpus"
VALID_TAGS = {"advance_fee", "deposit_to_unlock", "commission_transfer", "brand_misuse", "identity_mismatch",
              "credential_request", "off_platform_contact", "fake_shop", "investment_promise", "gambling_deposit"}
VALID_SCAM_TYPES = {"task_scam", "gambling_deposit", "fake_shop", "investment", "phishing", "parcel", "other", ""}
PUBLIC_SAMPLE_PER_CLASS = 1000


def _tags(s: str) -> tuple[list[str], list[str]]:
    tags = [t.strip() for t in (s or "").split(";") if t.strip()]
    return [t for t in tags if t in VALID_TAGS], [t for t in tags if t not in VALID_TAGS]


def _is_url(s: str) -> bool:
    return bool(re.match(r"^https?://", s.strip(), re.I))


def latest_capture(conn, url: str) -> int | None:
    row = conn.execute("SELECT scan_id FROM scans WHERE normalized_url=? AND status='done' AND capture_status='ok' "
                       "AND stored_from_scan_id IS NULL ORDER BY scan_id DESC LIMIT 1", (normalize_url(url),)).fetchone()
    return row["scan_id"] if row else None


# ------------------------------------------------------------------------------------------------
def import_private(report: dict[str, Any], register_candidates: bool) -> list[dict[str, Any]]:
    priv = settings.private_dir
    records: list[dict[str, Any]] = []
    labels_csv = priv / "datasets" / "labels.csv"
    listed_files: set[str] = set()
    report["private"] = {"labels_rows": 0, "not_captured_urls": [], "unlabeled": [], "invalid": [],
                         "har_review_candidates": 0}
    if not labels_csv.is_file():
        report["private"]["missing"] = "datasets/labels.csv not found"
        return records
    with labels_csv.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    report["private"]["labels_rows"] = len(rows)
    with db() as conn:
        for i, row in enumerate(rows, start=2):
            ref = (row.get("file_or_url") or "").strip()
            label = (row.get("label") or "").strip().lower()
            kit = (row.get("kit_id") or "").strip()
            scam_type = (row.get("scam_type") or "").strip().lower()
            tags, bad_tags = _tags(row.get("behavior_tags", ""))
            if not ref:
                continue
            if label not in LABELS:
                report["private"]["unlabeled"].append({"row": i, "ref": _short(ref), "reason": "missing or invalid label"})
                continue
            if bad_tags:
                report["private"]["invalid"].append({"row": i, "unknown_tags": bad_tags})
            if scam_type not in VALID_SCAM_TYPES:
                report["private"]["invalid"].append({"row": i, "unknown_scam_type": scam_type})
            if _is_url(ref):
                sid = latest_capture(conn, ref)
                if sid is None:
                    report["private"]["not_captured_urls"].append({"row": i, "url": _short(ref), "kit_id": kit})
                    continue
                parts = scan_record_parts(conn, sid)
                if parts is None:
                    continue
                lang = (row.get("lang") or "").strip() or parts["lang"]
                records.append(make_record(
                    rid=f"private:scan:{sid}", source="private_url", kit_id=kit, label=label, origin="private",
                    text=parts["text"], features=parts["features"], lang=lang, scam_type=scam_type, behavior_tags=tags,
                    url=parts["scan"]["normalized_url"], html_path=parts["html_path"], hostnames=parts["hostnames"],
                    fingerprint=parts["fingerprint"], extra={"scan_id": sid}))
            else:
                path = (priv / ref).resolve()
                listed_files.add(path.as_posix())
                if not path.is_file() or priv.resolve() not in path.parents:
                    report["private"]["invalid"].append({"row": i, "ref": _short(ref), "reason": "file not found"})
                    continue
                res = analyze_file(path)
                an = res["analysis"]
                lang = (row.get("lang") or "").strip() or an.lang or detect_lang(an.model_text)
                records.append(make_record(
                    rid=f"private:file:{ref}", source="private_file", kit_id=kit, label=label, origin="private",
                    text=an.model_text, features=an.features, lang=lang, scam_type=scam_type, behavior_tags=tags,
                    url=normalize_url(res["page_url"]) if _is_url(res["page_url"]) else None,
                    html_path=f"data/private/{ref}", hostnames=res["hostnames"], fingerprint=an.fingerprint))
                if path.suffix.lower() == ".har":
                    n = _har_candidates(conn, an, ref, kit, register_candidates)
                    report["private"]["har_review_candidates"] += n

    # Files in sites/ that labels.csv does not mention: unlabeled, listed for the team.
    sites = priv / "sites"
    if sites.is_dir():
        for p in sorted(sites.rglob("*")):
            if p.is_file() and p.suffix.lower() in SITE_EXTS and p.resolve().as_posix() not in listed_files:
                report["private"]["unlabeled"].append({"ref": p.relative_to(priv).as_posix(), "reason": "not in labels.csv"})
    return records


def _har_candidates(conn, an, ref: str, kit: str, register: bool) -> int:
    """Registration destinations referenced in a HAR become *review candidates* (never labeled)."""
    hosts = [h for h in an.registration_destinations if not common_service_category(h)]
    if register:
        now = utcnow()
        for h in hosts:
            conn.execute(
                "INSERT OR IGNORE INTO discovered_domains (domain, source, first_seen_at, matched_pattern, evidence, status, "
                "status_note, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (h, "har_reference", now, f"har_reference:{kit}",
                 json.dumps({"file": ref, "relation": "registration destination referenced in captured JSON",
                             "reachability": "not verified"}),
                 "awaiting_approval", "captured only after team approval (make capture-har-candidates)", now))
    return len(hosts)


def import_legit_captures(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Approved captures of datasets/legit_urls.csv (homepage + same-site nav pages)."""
    records = []
    with db() as conn:
        scans = conn.execute("SELECT scan_id, host FROM scans WHERE batch='legit_urls' AND status='done' "
                             "AND capture_status='ok' ORDER BY scan_id").fetchall()
        seen_urls = set()
        for s in scans:
            parts = scan_record_parts(conn, s["scan_id"])
            if parts is None or parts["scan"]["normalized_url"] in seen_urls:
                continue
            seen_urls.add(parts["scan"]["normalized_url"])
            if parts["word_count"] < 25:
                continue  # blocked/thin captures are not useful negatives
            site = registrable_domain(s["host"])
            records.append(make_record(
                rid=f"legit:scan:{s['scan_id']}", source="legit_urls", kit_id=f"legit_{site}", label="legitimate",
                origin="private", text=parts["text"], features=parts["features"], lang=parts["lang"],
                url=parts["scan"]["normalized_url"], html_path=parts["html_path"], hostnames=parts["hostnames"],
                fingerprint=parts["fingerprint"], extra={"scan_id": s["scan_id"]}))
    report["legit_captures"] = {"pages": len(records), "sites": len({r["kit_id"] for r in records})}
    return records


def import_synthetic(report: dict[str, Any]) -> list[dict[str, Any]]:
    labels = CORPUS_DIR / "labels.csv"
    records = []
    if not labels.is_file():
        report["synthetic"] = {"missing": "run: python testsites/generator/generate.py"}
        return records
    with labels.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            res = analyze_file(CORPUS_DIR / row["file"])
            an = res["analysis"]
            tags, _ = _tags(row["behavior_tags"])
            records.append(make_record(
                rid=f"synthetic:{row['file']}", source="synthetic", kit_id=row["kit_id"], label=row["label"],
                origin="synthetic", text=an.model_text, features=an.features, lang=row["lang"] or an.lang,
                scam_type=row["scam_type"], behavior_tags=tags, url=None,
                html_path=f"testsites/corpus/{row['file']}", hostnames=res["hostnames"], fingerprint=an.fingerprint))
    report["synthetic"] = {"pages": len(records)}
    return records


# ---- public datasets -----------------------------------------------------------------------------
def _find(base: Path, patterns: tuple[str, ...]) -> list[Path]:
    out = []
    for pat in patterns:
        out.extend(sorted(base.rglob(pat)))
    return out


def _label_from(value: str) -> str | None:
    v = str(value).strip().lower()
    if v in {"1", "phishing", "phish", "fraud", "fraudulent", "fake", "malicious", "bad", "scam", "illegitimate"}:
        return "fraudulent"
    if v in {"0", "legitimate", "legit", "benign", "good", "safe", "genuine", "real", "-1"}:
        return "legitimate"
    return None


def import_public(report: dict[str, Any]) -> list[dict[str, Any]]:
    base = settings.private_dir / "public_datasets"
    rep: dict[str, Any] = {"present": base.is_dir()}
    report["public"] = rep
    records: list[dict[str, Any]] = []
    if not base.is_dir():
        return records
    rng = random.Random(42)

    # 1) Fraudulent/legitimate online shops (URL list, Mendeley) -> URL features + captured ones.
    shop_rows = []
    for f in _find(base, ("*shop*/*.csv", "*shop*.csv")):
        shop_rows.extend(_url_label_rows(f))
    with db() as conn:
        for url, label in shop_rows:
            site = registrable_domain(_host(url))
            rec = {"url": normalize_url(url), "label": label}
            sid = latest_capture(conn, url)
            parts = scan_record_parts(conn, sid) if sid else None
            records.append(make_record(
                rid=f"pub_shop:{rec['url']}", source="pub_shop", kit_id=f"pub_shop_{site}", label=label, origin="public",
                text=parts["text"] if parts else "", features=parts["features"] if parts else {},
                lang=parts["lang"] if parts else "", scam_type="fake_shop" if label == "fraudulent" else "",
                behavior_tags=["fake_shop"] if label == "fraudulent" else [], url=rec["url"],
                extra={"url_only": parts is None}))
    rep["shops"] = {"rows": len(shop_rows), "with_capture": sum(1 for r in records if r["source"] == "pub_shop" and not r.get("url_only"))}

    # 2) Phishing websites with HTML (Putra 2023): balanced sample of HTML pages.
    phish = _putra_rows(base)
    by_label: dict[str, list] = defaultdict(list)
    for item in phish:
        by_label[item["label"]].append(item)
    sample = []
    for lab, items in by_label.items():
        rng.shuffle(items)
        sample.extend(items[:PUBLIC_SAMPLE_PER_CLASS])
    for item in sample:
        try:
            res = analyze_file(item["path"], page_url=item.get("url") or "")
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        an = res["analysis"]
        site = registrable_domain(_host(item.get("url") or "")) or item["path"].stem
        records.append(make_record(
            rid=f"pub_phish:{item['path'].name}", source="pub_phish", kit_id=f"pub_phish_{site}", label=item["label"],
            origin="public", text=an.model_text, features=an.features, lang=an.lang,
            scam_type="phishing" if item["label"] == "fraudulent" else "",
            behavior_tags=["credential_request"] if item["label"] == "fraudulent" else [],
            url=normalize_url(item["url"]) if item.get("url") else None, html_path=None, hostnames=res["hostnames"]))
    rep["phishing_html"] = {"found": len(phish), "sampled": len(sample)}

    # 3) Tranco top sites: legitimate domains for the URL-only baseline (rank is not proof of safety).
    tranco = _find(base, ("*tranco*/*.csv", "*tranco*.csv", "top-1m.csv"))
    n = 0
    for f in tranco[:1]:
        with f.open(encoding="utf-8", errors="replace", newline="") as fh:
            for row in csv.reader(fh):
                if len(row) >= 2 and row[0].isdigit():
                    dom = row[1].strip().lower()
                    records.append(make_record(rid=f"pub_tranco:{dom}", source="pub_tranco", kit_id=f"pub_tranco_{dom}",
                                               label="legitimate", origin="public", text="", features={},
                                               url=f"https://{dom}/", extra={"url_only": True}))
                    n += 1
                    if n >= 2000:
                        break
    rep["tranco"] = {"domains": n}
    # 4) PhishTank feed is a live-evaluation source only (make eval-live), never training data.
    rep["phishtank"] = {"files": [p.name for p in _find(base, ("*phishtank*", "online-valid*.csv"))]}
    return records


def _host(url: str) -> str:
    from app.urls import hostname
    return hostname(url) if url else ""


def _url_label_rows(path: Path) -> list[tuple[str, str]]:
    out = []
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            return out
        cols = {c.lower().strip(): c for c in reader.fieldnames}
        ucol = next((cols[c] for c in cols if c in ("url", "urls", "website", "domain", "link", "site")), None)
        lcol = next((cols[c] for c in cols if c in ("label", "class", "type", "status", "result", "category", "fraud")), None)
        if not ucol or not lcol:
            return out
        for row in reader:
            lab = _label_from(row.get(lcol, ""))
            url = (row.get(ucol) or "").strip()
            if lab and url:
                out.append((url if _is_url(url) else "https://" + url, lab))
    return out


def _putra_rows(base: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    roots = [p for p in base.iterdir() if p.is_dir() and re.search(r"phish", p.name, re.I)] if base.is_dir() else []
    for root in roots:
        index = None
        for f in root.rglob("*.csv"):
            index = f
            break
        html_files = {p.name: p for p in root.rglob("*") if p.suffix.lower() in (".html", ".htm", ".txt")}
        if index is not None:
            with index.open(encoding="utf-8-sig", errors="replace", newline="") as fh:
                reader = csv.DictReader(fh)
                cols = {c.lower().strip(): c for c in (reader.fieldnames or [])}
                fcol = next((cols[c] for c in cols if c in ("website", "file", "filename", "html", "path")), None)
                lcol = next((cols[c] for c in cols if c in ("result", "label", "class", "status")), None)
                ucol = next((cols[c] for c in cols if c in ("url", "urls", "domain")), None)
                if fcol and lcol:
                    for row in reader:
                        name = Path(row.get(fcol, "")).name
                        lab = _label_from(row.get(lcol, ""))
                        if lab and name in html_files:
                            items.append({"path": html_files[name], "label": lab, "url": row.get(ucol) if ucol else None})
        if not items:
            for name, p in html_files.items():
                parent = p.parent.name.lower()
                lab = "fraudulent" if "phish" in parent else ("legitimate" if "legit" in parent or "benign" in parent else None)
                if lab:
                    items.append({"path": p, "label": lab, "url": None})
    return items


# ---- kit grouping for records without kit_id -------------------------------------------------------
def propose_groups(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    missing = [r for r in records if not r["kit_id"]]
    if not missing:
        return []
    parent = list(range(len(missing)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(missing)):
        for j in range(i + 1, len(missing)):
            a, b = missing[i], missing[j]
            shared = set(a["hostnames"]) & set(b["hostnames"])
            if fingerprint_similarity(a["fingerprint"], b["fingerprint"]) >= 0.8 or shared:
                parent[find(i)] = find(j)
    groups: dict[int, list[str]] = defaultdict(list)
    for i, r in enumerate(missing):
        groups[find(i)].append(r["id"])
    proposals = []
    for n, (_, ids) in enumerate(sorted(groups.items()), start=1):
        gid = f"auto_grp_{n:02d}"
        for r in missing:
            if r["id"] in ids:
                r["kit_id"] = gid
                r["kit_auto"] = True
        proposals.append({"proposed_kit_id": gid, "members": ids})
    return proposals


def _short(s: str, n: int = 80) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    trainable = [r for r in records if r["text"] and r["label"] in ("fraudulent", "legitimate")]
    return {
        "total_records": len(records),
        "trainable_text_records": len(trainable),
        "url_only_records": sum(1 for r in records if not r["text"]),
        "by_label": dict(Counter(r["label"] for r in records)),
        "by_origin": dict(Counter(r["origin"] for r in records)),
        "by_source": dict(Counter(r["source"] for r in records)),
        "by_lang": dict(Counter(r["lang"] or "unknown" for r in records if r["text"])),
        "by_scam_type": dict(Counter(r["scam_type"] or "-" for r in records if r["label"] == "fraudulent")),
        "by_behavior_tag": dict(Counter(t for r in records for t in r["behavior_tags"])),
        "kits": {"count": len({r["kit_id"] for r in records}),
                 "private": dict(Counter(r["kit_id"] for r in records if r["origin"] == "private"))},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-synthetic", action="store_true")
    ap.add_argument("--no-public", action="store_true")
    ap.add_argument("--register-candidates", action="store_true", default=True,
                    help="add HAR-referenced registration destinations to the discovery queue (awaiting approval)")
    args = ap.parse_args(argv)
    settings.ensure_dirs()
    report: dict[str, Any] = {"generated_at": utcnow()}
    records = import_private(report, register_candidates=args.register_candidates)
    records += import_legit_captures(report)
    if not args.no_public:
        records += import_public(report)
    if not args.no_synthetic:
        records += import_synthetic(report)
    report["proposed_kit_groups"] = propose_groups(records)
    report["summary"] = summarize(records)
    out = settings.processed_dir / "records.jsonl"
    write_jsonl(out, records)
    (settings.processed_dir / "import_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False),
                                                               encoding="utf-8")
    _print_report(report, out)
    return 0


def _print_report(rep: dict[str, Any], out: Path) -> None:
    s = rep["summary"]
    print(f"records -> {out}")
    print(f"  total {s['total_records']}  trainable(text) {s['trainable_text_records']}  url-only {s['url_only_records']}")
    for key in ("by_label", "by_origin", "by_source", "by_lang", "by_scam_type", "by_behavior_tag"):
        print(f"  {key:16s} {json.dumps(s[key], ensure_ascii=False)}")
    print(f"  kits             {s['kits']['count']} total; private: {json.dumps(s['kits']['private'])}")
    pv = rep.get("private", {})
    print(f"private labels.csv rows: {pv.get('labels_rows', 0)}; HAR review candidates: {pv.get('har_review_candidates', 0)}"
          " (discovery queue, awaiting approval, unlabeled)")
    if pv.get("not_captured_urls"):
        print(f"  URL rows not captured yet ({len(pv['not_captured_urls'])}) -> after approval run: make capture-labels")
        for u in pv["not_captured_urls"]:
            print(f"    row {u['row']}: {u['url']} ({u['kit_id']})")
    if pv.get("unlabeled"):
        print(f"  UNLABELED ({len(pv['unlabeled'])}) - add them to labels.csv or tell us to skip:")
        for u in pv["unlabeled"]:
            print(f"    {u}")
    if pv.get("invalid"):
        print(f"  invalid entries: {pv['invalid']}")
    lc = rep.get("legit_captures", {})
    print(f"legit_urls captures: {lc.get('pages', 0)} pages from {lc.get('sites', 0)} sites"
          + ("" if lc.get("pages") else " -> after approval run: make capture-legit"))
    pub = rep.get("public", {})
    print(f"public datasets: {'present' if pub.get('present') else 'not found (data/private/public_datasets/)'} "
          + json.dumps({k: v for k, v in pub.items() if k != 'present'}))
    print(f"synthetic: {rep.get('synthetic')}")
    if rep["proposed_kit_groups"]:
        print("PROPOSED KIT GROUPS (records without kit_id) - please confirm:")
        for g in rep["proposed_kit_groups"]:
            print(f"  {g['proposed_kit_id']}: {g['members']}")


if __name__ == "__main__":
    sys.exit(main())
