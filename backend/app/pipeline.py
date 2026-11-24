"""Scan pipeline: submit -> capture -> sanitize -> store (SHA-256 every artifact) -> analyze -> score.

The analyzer and scorer read the *stored* sanitized artifacts back from the store, so a stored
capture can be re-analyzed later (e.g. when a scam site has gone offline)."""
from __future__ import annotations

import json
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from app import cases
from app.analyze import Analysis, AnalyzerInput, analyze
from app.capture import CaptureResult, capture
from app.config import settings
from app.db import db, tx, utcnow
from app.sanitize import redact_text, sanitize_har, sanitize_html, sanitize_url
from app.scoring import ReviewedContext, clue_text, decide
from app.scoring import texts as T
from app.scoring.model_store import current_model
from app.storage import artifact_url, put_artifact, read_artifact
from app.urls import UnsafeTarget, check_target, ensure_scheme, hostname, normalize_url, registrable_domain

SOURCE_TYPES = {"search", "maps", "sms", "whatsapp", "manual", "extension", "discovery", "import"}
_capture_sem = threading.BoundedSemaphore(max(1, settings.capture_concurrency))


class ScanError(ValueError):
    pass


# ------------------------------------------------------------------------------------------------
def submit_scan(url: str, source_type: str = "manual", listing_name: str | None = None, lang: str = "en",
                batch: str | None = None, parent_scan_id: int | None = None, force: bool = False,
                run_actions: bool = True, collect_nav: bool = False,
                page_signals: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run a full scan and return the result payload. Raises ScanError for invalid/unsafe input.

    page_signals: structure of the page as rendered in the user's own browser (extension), used when the server's
    capture is blocked by a bot challenge or shows little. Validated, stored as evidence, and such scans are never
    served from the cache to other checks."""
    if source_type not in SOURCE_TYPES:
        raise ScanError(f"invalid source_type: {source_type}")
    if not url or len(url) > 2048:
        raise ScanError("invalid url")
    url = ensure_scheme(url)
    lang = lang if lang in ("ar", "en") else "en"
    listing_name = (listing_name or "").strip()[:200] or None
    try:
        check_target(url, settings.capture_allow_hosts, settings.capture_allow_private)
    except UnsafeTarget as e:
        raise ScanError(f"unsafe target: {e}") from e
    norm = normalize_url(url)
    host = hostname(norm)
    clean_url = sanitize_url(url)
    signals = clean_page_signals(page_signals, host)

    if signals is not None and not force:
        cached = _recent_scan(norm)
        if cached is not None:
            # Re-use the server's recent capture of this URL; add what the user's browser saw (no new visit).
            return reanalyze_stored(cached["scan_id"], listing_name=listing_name, source_type=source_type, lang=lang,
                                    page_signals=signals)
    if not force and signals is None:
        cached = _recent_scan(norm)
        if cached is not None:
            if (cached["listing_name"] or None) == listing_name:
                payload = get_scan_payload(cached["scan_id"])
                payload["cached"] = True
                payload["capture_mode"] = "stored"
                return payload
            # Same capture, different listing name: re-analyze the stored copy (no new network visit).
            return reanalyze_stored(cached["scan_id"], listing_name=listing_name, source_type=source_type, lang=lang)

    with db() as conn:
        scan_id = conn.execute(
            "INSERT INTO scans (submitted_url, normalized_url, host, source_type, listing_name, lang, batch, "
            "parent_scan_id, submitted_at, status, access_key, client_signals) VALUES (?,?,?,?,?,?,?,?,?, 'capturing', ?, ?)",
            (clean_url, norm, host, source_type, listing_name, lang, batch, parent_scan_id, utcnow(),
             secrets.token_urlsafe(16), 1 if signals is not None else 0),
        ).lastrowid
        if signals is not None:
            put_artifact(conn, scan_id, "action_log", signals, action_name="browser_page_signals")
    t0 = time.monotonic()
    with _capture_sem:
        res = capture(url, lang=lang, run_actions=run_actions, collect_nav=collect_nav)

    if not res.ok:
        prev = _last_good_scan(norm, exclude=scan_id)
        if prev is not None:
            _store_capture(scan_id, res)  # keep the failed attempt's action log as evidence
            return _finish_from_stored(scan_id, prev["scan_id"], listing_name, res, t0)

    _store_capture(scan_id, res)
    with db() as conn:
        conn.execute("UPDATE scans SET status='analyzing', capture_status=?, capture_error=?, captured_at=?, "
                     "final_url=?, capture_mode='live' WHERE scan_id=?",
                     (res.status, res.error[:500] if res.error else None, res.finished_at,
                      sanitize_url(res.final_url) if res.final_url else None, scan_id))
    analyze_and_score(scan_id, source_scan_id=scan_id, listing_name=listing_name, http_status=res.http_status,
                      capture_status=res.status, stored=False, t0=t0, client=signals)
    payload = get_scan_payload(scan_id)
    if collect_nav:
        payload["nav_links"] = res.nav_links
    return payload


def reanalyze_stored(source_scan_id: int, listing_name: str | None = None, source_type: str = "manual",
                     lang: str = "en", page_signals: dict[str, Any] | None = None) -> dict[str, Any]:
    """New scan record that re-analyzes an earlier capture without visiting the site."""
    with db() as conn:
        src = conn.execute("SELECT * FROM scans WHERE scan_id=?", (source_scan_id,)).fetchone()
        if src is None:
            raise ScanError("unknown scan")
        origin = src["stored_from_scan_id"] or src["scan_id"]
        scan_id = conn.execute(
            "INSERT INTO scans (submitted_url, normalized_url, host, source_type, listing_name, lang, submitted_at, "
            "status, capture_mode, capture_status, captured_at, final_url, stored_from_scan_id, access_key, client_signals) "
            "SELECT submitted_url, normalized_url, host, ?, ?, ?, ?, 'analyzing', 'stored', capture_status, captured_at, "
            "final_url, ?, ?, ? FROM scans WHERE scan_id=?",
            (source_type, listing_name, lang, utcnow(), origin, secrets.token_urlsafe(16),
             1 if page_signals is not None else 0, origin)).lastrowid
        cap_status = src["capture_status"] or "ok"
        if page_signals is not None:
            put_artifact(conn, scan_id, "action_log", page_signals, action_name="browser_page_signals")
    analyze_and_score(scan_id, source_scan_id=origin, listing_name=listing_name, http_status=None,
                      capture_status=cap_status, stored=True, t0=time.monotonic(), client=page_signals)
    return get_scan_payload(scan_id)


def _finish_from_stored(scan_id: int, prev_scan_id: int, listing_name: str | None, res: CaptureResult,
                        t0: float) -> dict[str, Any]:
    with db() as conn:
        prev = conn.execute("SELECT * FROM scans WHERE scan_id=?", (prev_scan_id,)).fetchone()
        origin = prev["stored_from_scan_id"] or prev["scan_id"]
        conn.execute("UPDATE scans SET status='analyzing', capture_status=?, capture_error=?, capture_mode='stored', "
                     "stored_from_scan_id=?, captured_at=?, final_url=? WHERE scan_id=?",
                     (res.status, (res.error or "")[:500], origin, prev["captured_at"], prev["final_url"], scan_id))
    analyze_and_score(scan_id, source_scan_id=origin, listing_name=listing_name, http_status=None,
                      capture_status="ok", stored=True, t0=t0, live_failure=res.status)
    payload = get_scan_payload(scan_id)
    return payload


# ------------------------------------------------------------------------------------------------
def _store_capture(scan_id: int, res: CaptureResult) -> None:
    """Sanitize and store every artifact of a capture (HAR, HTML per step, screenshot per step, log)."""
    with db() as conn, tx(conn):
        if res.har:
            put_artifact(conn, scan_id, "har", sanitize_har(res.har, settings.capture_max_body_bytes),
                         captured_at=res.finished_at)
        for st in res.steps:
            if st.html:
                put_artifact(conn, scan_id, "html", sanitize_html(st.html), action_step=st.step,
                             action_name=st.action, captured_at=st.at)
            if st.screenshot:
                put_artifact(conn, scan_id, "screenshot", st.screenshot, action_step=st.step,
                             action_name=st.action, captured_at=st.at)
        log = {
            "requested_url": sanitize_url(res.requested_url), "final_url": sanitize_url(res.final_url or ""),
            "status": res.status, "error": redact_text(res.error or ""), "http_status": res.http_status,
            "started_at": res.started_at, "finished_at": res.finished_at, "request_count": res.request_count,
            "blocked": res.blocked,
            "actions": [{k: (sanitize_url(v) if k == "url" and isinstance(v, str) else v) for k, v in a.items()}
                        for a in res.action_log],
            "steps": [{"step": s.step, "action": s.action, "at": s.at, "url": sanitize_url(s.url), "note": s.note}
                      for s in res.steps],
        }
        put_artifact(conn, scan_id, "action_log", log, captured_at=res.finished_at or utcnow())


def load_bundle(conn: sqlite3.Connection, scan_id: int) -> tuple[list[tuple[int, str, str]], dict | None,
                                                                   dict[int, int], int | None, dict]:
    """Read a scan's stored sanitized artifacts. Returns (steps, har, step->screenshot_artifact_id,
    har_artifact_id, step->html_artifact_id)."""
    steps: list[tuple[int, str, str]] = []
    har = None
    shots: dict[int, int] = {}
    htmls: dict[int, int] = {}
    har_id = None
    for a in conn.execute("SELECT * FROM artifacts WHERE scan_id=? ORDER BY artifact_id", (scan_id,)):
        if a["kind"] == "html":
            steps.append((a["action_step"] or 0, a["action_name"] or "", read_artifact(a["path"]).decode("utf-8", "replace")))
            htmls[a["action_step"] or 0] = a["artifact_id"]
        elif a["kind"] == "har":
            har = json.loads(read_artifact(a["path"]))
            har_id = a["artifact_id"]
        elif a["kind"] == "screenshot":
            shots[a["action_step"] or 0] = a["artifact_id"]
    steps.sort(key=lambda s: s[0])
    return steps, har, shots, har_id, htmls


def analyze_and_score(scan_id: int, source_scan_id: int, listing_name: str | None, http_status: int | None,
                      capture_status: str, stored: bool, t0: float, live_failure: str | None = None,
                      asset_source: str = "capture", client: dict[str, Any] | None = None) -> None:
    with db() as conn:
        scan = conn.execute("SELECT * FROM scans WHERE scan_id=?", (scan_id,)).fetchone()
        steps, har, shots, har_id, htmls = load_bundle(conn, source_scan_id)
        src = conn.execute("SELECT final_url, submitted_url FROM scans WHERE scan_id=?", (source_scan_id,)).fetchone()
        if client is None:
            client = _stored_page_signals(conn, scan_id)
        inp = AnalyzerInput(page_url=scan["submitted_url"], final_url=src["final_url"] or "", steps=steps, har=har,
                            capture_status=capture_status if (steps or client) else "load_failed",
                            http_status=http_status, listing_name=listing_name, client=client)
        an = analyze(inp)
        _add_domain_age(an, scan["host"])
        version, model = current_model()
        score, phrases, code_score = None, [], None
        thresholds = {"threshold_agree": 0.5, "threshold_caution": 0.35}
        if model is not None and not an.flags.get("load_failed"):
            score = float(model.predict_proba([an.model_text], [an.features])[0])
            phrases = model.explain(an.model_text, an.features, k=5)
            thresholds = {k: model.settings[k] for k in ("threshold_agree", "threshold_caution")}
        if model is not None and an.code_word_count >= 40:
            # Same classifier on the site's own code strings (separate score, separate evidence source).
            code_score = float(model.predict_proba([an.code_text], [an.code_features])[0])

        from app.linking import dynamic_common_hosts

        common = dynamic_common_hosts(conn)
        ctx = ReviewedContext(
            exact_host_label=(cases.host_review(conn, an.page_host or scan["host"]) or {}).get("label"),
            strong_links=[],
        )
        decision = decide(an, score, thresholds, ctx, stored=stored)  # provisional (no link context yet)

        with tx(conn):
            analysis_art = put_artifact(conn, scan_id, "analysis", _analysis_record(an, decision, score))
            text_art = put_artifact(conn, scan_id, "model_text", an.model_text or "")
            obs_ids = _insert_observations(conn, scan_id, an, htmls, har_id)
            from app.linking.kit import store_assets

            store_assets(conn, scan_id, an.page_host or scan["host"], an.assets, asset_source)
            _store_linking_evidence(conn, scan_id, an, scan["host"])
            conn.execute(
                "UPDATE scans SET page_lang=?, fingerprint=?, form_signature=?, payment_signature=? WHERE scan_id=?",
                (an.lang, json.dumps(an.fingerprint) if an.fingerprint else None, an.form_signature or None,
                 an.payment_signature or None, scan_id))
        host = an.page_host or scan["host"]
        kit_ctx = cases.kit_context(conn, scan_id, host, common)
        ctx.strong_links = cases.strong_reviewed_links(conn, scan_id, host, an.asset_hosts, common) + kit_ctx["strong"]
        ctx.partial_links = kit_ctx["partial"]
        ctx.domain_inherited = cases.domain_inheritance(conn, host)
        decision = decide(an, score, thresholds, ctx, stored=stored, code_score=code_score)

        clues = []
        for ct in decision.clue_types:
            ob = _clue_observation(conn, scan_id, ct)
            step = ob["action_step"] if ob and ob["action_step"] is not None else 0
            shot_id = shots.get(step) or (shots.get(0) if shots else None)
            clues.append({
                "type": ct, "text": clue_text(ct, an, ctx, ob["redacted_excerpt"] if ob else None),
                "excerpt": (ob["redacted_excerpt"] if ob else None),
                "excerpt_lang": (ob["lang"] if ob else None),
                "obs_id": ob["obs_id"] if ob else None,
                "screenshot_artifact_id": shot_id,
            })
        not_checked = list(decision.not_checked)
        with tx(conn):
            conn.execute(
                "INSERT INTO assessments (scan_id, risk_tier, score, rules_fired, clues_json, identity_check, top_phrases,"
                " model_version, created_at, code_score) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (scan_id, decision.tier, score, json.dumps(decision.rules_fired),
                 json.dumps({"clues": clues, "not_checked": not_checked, "headline_key": decision.headline_key,
                             "strong_links": ctx.strong_links, "partial_links": ctx.partial_links,
                             "domain_inherited": ctx.domain_inherited, "live_failure": live_failure,
                             "code_mentions": an.code_mentions, "code_behaviors": an.code_behaviors,
                             "wall": {k: v for k, v in (an.wall or {}).items()
                                      if k not in ("paths", "images", "template_features")},
                             "redirect": an.redirect},
                            ensure_ascii=False),
                 an.identity.get("result", "not_checked"), json.dumps(phrases, ensure_ascii=False), version, utcnow(),
                 code_score))
            conn.execute("UPDATE scans SET status='done', completed_at=?, duration_ms=? WHERE scan_id=?",
                         (utcnow(), int((time.monotonic() - t0) * 1000), scan_id))
    _post_scan_hooks(scan_id)


def _post_scan_hooks(scan_id: int) -> None:
    """Related-site linking (candidate links + pending alerts for watched cases)."""
    from app.linking import process_scan

    process_scan(scan_id)


def _analysis_record(an: Analysis, decision: Any, score: float | None) -> dict[str, Any]:
    d = an.to_dict()
    d.pop("text_ar", None)
    d.pop("text_en", None)
    d.pop("model_text", None)
    d["decision"] = {"tier": decision.tier, "rules_fired": decision.rules_fired, "score": score}
    return d


def _insert_observations(conn: sqlite3.Connection, scan_id: int, an: Analysis, htmls: dict[int, int],
                         har_id: int | None) -> list[int]:
    ids = []
    now = utcnow()
    for ind in an.indicators:
        if ind.host_ref:
            art = har_id if (ind.context or "").startswith(("json:", "js:", "traffic:")) or not htmls else (
                htmls.get(0) if "html:" in (ind.context or "") else har_id)
        else:
            art = htmls.get(ind.step if ind.step is not None else 0) or (htmls.get(0) if htmls else har_id)
        cur = conn.execute(
            "INSERT INTO observations (scan_id, artifact_id, indicator_type, strength, redacted_excerpt, host_ref, "
            "host_relation, context, site_reported_time, action_step, lang, details_json, created_at, source) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (scan_id, har_id if ind.source != "visible_page" else art, ind.type, ind.strength, ind.excerpt or None,
             ind.host_ref, ind.host_relation, ind.context, ind.site_reported_time, ind.step, ind.lang or None,
             json.dumps(ind.details, ensure_ascii=False) if ind.details else None, now, ind.source))
        ids.append(cur.lastrowid)
    return ids


def _clue_observation(conn: sqlite3.Connection, scan_id: int, clue_type: str) -> sqlite3.Row | None:
    if clue_type in ("reviewed_case_exact_host", "reviewed_case_link", "classifier_score", "kit_match",
                     "kit_partial", "reviewed_domain"):
        return None
    if clue_type in ("route_vocabulary", "brand_bait"):
        return conn.execute("SELECT * FROM observations WHERE scan_id=? AND indicator_type=? ORDER BY obs_id LIMIT 1",
                            (scan_id, clue_type)).fetchone()
    if clue_type in ("registration_gate", "young_domain", "domain_shape", "no_company_identity", "bot_challenge"):
        return None
    source = "delivered_code" if clue_type == "code_behavior" else "visible_page"
    return conn.execute("SELECT * FROM observations WHERE scan_id=? AND indicator_type=? AND source=? "
                        "ORDER BY obs_id LIMIT 1", (scan_id, clue_type, source)).fetchone()


def _recent_scan(norm: str) -> sqlite3.Row | None:
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=settings.scan_cache_ttl_s)).strftime("%Y-%m-%dT%H:%M:%S")
    with db() as conn:
        return conn.execute(
            "SELECT * FROM scans WHERE normalized_url=? AND status='done' AND capture_status='ok' "
            "AND COALESCE(client_signals, 0)=0 AND submitted_at >= ? ORDER BY scan_id DESC LIMIT 1", (norm, cutoff)).fetchone()


def _last_good_scan(norm: str, exclude: int) -> sqlite3.Row | None:
    with db() as conn:
        return conn.execute(
            "SELECT * FROM scans WHERE normalized_url=? AND status='done' AND capture_status='ok' AND scan_id<>? "
            "AND COALESCE(client_signals, 0)=0 ORDER BY scan_id DESC LIMIT 1", (norm, exclude)).fetchone()


# ------------------------------------------------------------------------------------------------
def get_scan_payload(scan_id: int, include_internal: bool = False) -> dict[str, Any]:
    with db() as conn:
        s = conn.execute("SELECT * FROM scans WHERE scan_id=?", (scan_id,)).fetchone()
        if s is None:
            raise KeyError(scan_id)
        a = conn.execute("SELECT * FROM assessments WHERE scan_id=? ORDER BY assessment_id DESC LIMIT 1",
                         (scan_id,)).fetchone()
        art_scan = s["stored_from_scan_id"] or s["scan_id"]
        arts = conn.execute("SELECT artifact_id, kind, sha256, action_step, action_name, captured_at, size_bytes "
                            "FROM artifacts WHERE scan_id IN (?, ?) ORDER BY artifact_id", (art_scan, scan_id)).fetchall()
        review = cases.effective_review(conn, scan_id) or cases.host_review(conn, s["host"])
    payload: dict[str, Any] = {
        "scan_id": s["scan_id"], "url": s["submitted_url"], "final_url": s["final_url"], "host": s["host"],
        "source_type": s["source_type"], "listing_name": s["listing_name"], "status": s["status"],
        "submitted_at": s["submitted_at"], "captured_at": s["captured_at"], "completed_at": s["completed_at"],
        "duration_ms": s["duration_ms"], "page_lang": s["page_lang"],
        "capture_mode": s["capture_mode"] or "live", "capture_status": s["capture_status"],
        "stored_from_scan_id": s["stored_from_scan_id"], "cached": False, "access_key": s["access_key"],
        "artifacts": [
            {"artifact_id": r["artifact_id"], "kind": r["kind"], "sha256": r["sha256"], "action_step": r["action_step"],
             "action": r["action_name"], "captured_at": r["captured_at"], "size_bytes": r["size_bytes"],
             "url": artifact_url(r["artifact_id"], s["access_key"]) if r["kind"] == "screenshot" else None}
            for r in arts
        ],
        "review": ({"label": review["label"], "behavior_tags": review["behavior_tags"], "reviewed_at": review["created_at"]}
                   if review else None),
    }
    if a is None:
        payload.update({"tier": None, "clues": []})
        return payload
    extra = json.loads(a["clues_json"])
    tier = a["risk_tier"]
    head_key = extra.get("headline_key")
    hl = T.BEHAVIOR_HEADLINE[head_key] if tier == "high_risk" and head_key in T.BEHAVIOR_HEADLINE else T.TIER_HEADLINE[tier]
    nc = extra.get("not_checked", [])
    payload.update({
        "tier": tier,
        "tier_label": T.TIER_LABEL[tier],
        "headline": hl,
        "score": round(a["score"], 4) if a["score"] is not None else None,
        "clues": [dict(c, screenshot_url=artifact_url(c["screenshot_artifact_id"], s["access_key"])
                       if c.get("screenshot_artifact_id") else None) for c in extra.get("clues", [])],
        "what_to_do": T.WHAT_TO_DO[tier],
        "not_checked": {"en": [T.NOT_CHECKED[k]["en"] for k in nc if k in T.NOT_CHECKED],
                        "ar": [T.NOT_CHECKED[k]["ar"] for k in nc if k in T.NOT_CHECKED]},
        "identity_check": a["identity_check"],
        "model_version": a["model_version"],
        "rules_fired": json.loads(a["rules_fired"]),
        "top_phrases": json.loads(a["top_phrases"] or "[]"),
        "assessed_at": a["created_at"],
        "live_failure": extra.get("live_failure"),
        "code_score": round(a["code_score"], 4) if a["code_score"] is not None else None,
        "evidence": {
            "kit_match": next((l for l in extra.get("strong_links", []) if l.get("relation") == "same_kit"), None)
            or next((l for l in extra.get("partial_links", []) if l.get("relation") == "same_kit"), None),
            "domain_inherited": extra.get("domain_inherited"),
            "code_mentions": extra.get("code_mentions") or {},
        },
    })
    if include_internal:
        payload["strong_links"] = extra.get("strong_links", [])
    return payload


# ---- page structure from the user's browser + domain age ---------------------------------------------------------
_SIG_LIMITS = {"paths": (600, 200), "images": (200, 160)}
_FIELD_KEYS = ("type", "name", "placeholder", "label", "autocomplete")


def clean_page_signals(raw: dict[str, Any] | None, host: str) -> dict[str, Any] | None:
    """Validate and cap what the extension sent: same-host page only, paths without queries, field descriptors
    without values, image names, redacted visible text. Anything else is dropped."""
    if not isinstance(raw, dict):
        return None
    from app.sanitize import redact_text

    page_host = hostname(str(raw.get("page_url") or ""))
    if not page_host or registrable_domain(page_host) != registrable_domain(host):
        return None
    out: dict[str, Any] = {"page_url": sanitize_url(str(raw.get("page_url")))[:500]}
    for key, (n, length) in _SIG_LIMITS.items():
        out[key] = [str(x).split("?")[0].split("#")[0][:length] for x in (raw.get(key) or [])[:n] if isinstance(x, str)]
    out["fields"] = []
    for f in (raw.get("fields") or [])[:60]:
        if isinstance(f, dict):
            d = {k: redact_text(str(f.get(k) or ""))[:100] for k in _FIELD_KEYS}
            d.update({k: bool(f.get(k)) for k in ("required", "readonly", "has_value")})
            out["fields"].append(d)
    out["title"] = redact_text(str(raw.get("title") or ""))[:200]
    out["text"] = redact_text(str(raw.get("text") or ""))[:8000]
    out["identity_links"] = bool(raw.get("identity_links"))
    out["h5_shell"] = bool(raw.get("h5_shell"))
    out["lang"] = str(raw.get("lang") or "")[:8]
    return out


def _stored_page_signals(conn: Any, scan_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT path FROM artifacts WHERE scan_id=? AND kind='action_log' AND "
                       "action_name='browser_page_signals' ORDER BY artifact_id DESC LIMIT 1", (scan_id,)).fetchone()
    if row is None:
        return None
    try:
        return json.loads(read_artifact(row["path"]))
    except ValueError:
        return None


def _add_domain_age(an: Analysis, host: str) -> None:
    """First certificate of the registrable domain (certificate transparency), as evidence for the tier rules."""
    from app.analyze import Indicator
    from app.domain_age import cert_age_days

    try:
        age = cert_age_days(an.page_host or host)
    except Exception:  # noqa: BLE001 - a lookup failure must never break a scan
        age = None
    if an.wall is None:
        an.wall = {}
    an.wall["cert_age_days"] = age
    if age is not None and age < 90:
        an.indicators.append(Indicator(type="young_domain", strength="strong" if age < 30 else "medium",
                                       host_ref=registrable_domain(an.page_host or host), source="domain",
                                       excerpt=f"first certificate {age} days ago",
                                       details={"cert_age_days": age, "source": "certificate transparency"}))


def _store_linking_evidence(conn: Any, scan_id: int, an: Analysis, host: str) -> None:
    """Registration-page template (feature hashes only) and redirect/invite gateways as review candidates."""
    w = an.wall or {}
    page_host = an.page_host or host
    if w.get("template_features"):
        conn.execute("INSERT INTO page_templates (scan_id, host, site, features, n_lines, created_at) VALUES (?,?,?,?,?,?) "
                     "ON CONFLICT DO NOTHING", (scan_id, page_host, registrable_domain(page_host),
                                                json.dumps(w["template_features"]), w.get("template_lines") or 0, utcnow()))
    g = an.redirect
    if g:
        for domain, role in ((g["gateway_site"], "gateway"), (g["target_site"], "landing site")):
            conn.execute(
                "INSERT INTO discovered_domains (domain, source, first_seen_at, matched_pattern, evidence, scan_id, status, "
                "status_note, updated_at) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                (domain, "redirect_gateway", utcnow(), f"redirect_gateway:{role}",
                 json.dumps({"scan_id": scan_id, "role": role, "mechanism": g["mechanism"], "invite_code": g["invite_code"],
                             "gateway": g["gateway_host"], "target": g["target_host"]}),
                 scan_id, "scanned", f"{role} of a redirect/invitation gateway; review candidate", utcnow()))
