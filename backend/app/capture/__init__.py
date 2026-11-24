"""Capture service: the only stage that touches the network.

A fresh Chromium context per scan (UAE locale and timezone, realistic user agent). Records a HAR
with response bodies, rendered HTML and a screenshot after each step, and a timestamped action log.
Safety: never signs in, types, submits forms, pays, downloads or follows discovered links. Runs only
predefined non-submitting actions (switch language, open a country selector) inside a ~20 s budget,
with caps on request count and response size, and refuses private-network targets.
"""
from __future__ import annotations

import asyncio
import re
import json
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

from app.config import settings
from app.urls import UnsafeTarget, check_target, registrable_domain, request_allowed

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
UNSAFE_WORDS = (
    "login|log in|sign in|signin|sign up|signup|register|logout|pay|deposit|recharge|submit|buy|order now|"
    "withdraw|checkout|cart|apply|download|install|delete|confirm|تسجيل|دخول|دفع|ادفع|إيداع|ايداع|شحن|شراء|سحب|"
    "تأكيد|اشترك|حمل|تنزيل"
)
NAV_EXCLUDE = (
    "login", "log-in", "signin", "sign-in", "signup", "sign-up", "register", "account", "cart", "checkout",
    "logout", "password", "auth", "oauth", "apply", "download", "basket", "wishlist", "my-", "profile",
    "subscribe", "payment", "pay", "wallet", "otp", "verify",
)
NAV_EXCLUDE_EXT = (".pdf", ".zip", ".apk", ".exe", ".dmg", ".doc", ".docx", ".xls", ".xlsx", ".jpg", ".png", ".mp4")

FIND_TARGET_JS = r"""
([kind, unsafeWords, currentLang]) => {
  const unsafe = new RegExp(unsafeWords, 'i');
  const patterns = kind === 'language'
    ? [/^\s*(english|eng|en)\s*$/i, /^\s*(العربية|عربي|arabic|ar)\s*$/i, /\b(language|lang)\b|اللغة/i]
    : kind === 'dismiss'
    ? [/^\s*(more on that later|later|maybe later|not now|no,? thanks|close|skip|cancel|×|✕|x|لاحقا|لاحقًا|ليس الآن|إغلاق|اغلاق|تخطي)\s*$/i]
    : [/country|countries|region|select (your )?location|الدولة|البلد|الدول|المنطقة|اختر الدولة/i];
  // Icon-only controls (globe / flag buttons): matched by class, id, aria-label, title or image alt/src.
  const attrPattern = kind === 'language' ? /(^|[-_\s])(lang|language|locale|i18n|globe)([-_\s]|$)/i
    : kind === 'country' ? /(^|[-_\s])(country|countries|flag|region|area-code|nation)([-_\s]|$)/i : null;
  const visible = el => {
    const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const ownText = el => (el.innerText || el.getAttribute('aria-label') || el.getAttribute('title') || '').trim();
  const sameOriginLink = a => {
    const href = a.getAttribute('href') || '';
    if (!href || href.startsWith('#') || href.startsWith('javascript:')) return true;
    try { const u = new URL(href, location.href); return u.origin === location.origin; } catch (e) { return false; }
  };
  const safe = el => {
    if (el.closest('form')) {
      const t = (el.getAttribute('type') || '').toLowerCase();
      if (el.tagName === 'BUTTON' && t !== 'button') return false;
      if (el.tagName === 'INPUT') return false;
    }
    if (el.tagName === 'A' && !sameOriginLink(el)) return false;
    const txt = ownText(el);
    if (unsafe.test(txt)) return false;
    return true;
  };
  const els = Array.from(document.querySelectorAll(
    'button, [role=button], a, li, span, div, uni-view, uni-text, label, p'));
  for (const pat of patterns) {
    for (const el of els) {
      const txt = ownText(el);
      if (!txt || txt.length > 40 || !pat.test(txt)) continue;
      if (kind === 'language') {
        // Pick the *other* language than the page currently shows.
        if (currentLang === 'ar' && /العربية|عربي|arabic|^\s*ar\s*$/i.test(txt)) continue;
        if (currentLang === 'en' && /^\s*(english|eng|en)\s*$/i.test(txt)) continue;
      }
      if (!visible(el) || !safe(el)) continue;
      // Prefer the innermost matching element.
      const inner = Array.from(el.querySelectorAll('*')).find(c => ownText(c) === txt && visible(c));
      const target = inner || el;
      document.querySelectorAll('[data-hami-target]').forEach(x => x.removeAttribute('data-hami-target'));
      target.setAttribute('data-hami-target', '1');
      return txt.slice(0, 40);
    }
  }
  if (attrPattern) {
    const attrsOf = el => [el.className && el.className.baseVal !== undefined ? el.className.baseVal : el.className,
      el.id, el.getAttribute('aria-label'), el.getAttribute('title'),
      ...Array.from(el.querySelectorAll('img')).slice(0, 2).map(i => (i.getAttribute('alt') || '') + ' ' + (i.getAttribute('src') || ''))
    ].filter(Boolean).join(' ');
    const cands = Array.from(document.querySelectorAll('button, [role=button], a, div, span, li, uni-view, img'));
    for (const el of cands) {
      const a = attrsOf(el);
      if (!a || !attrPattern.test(a.replace(/[A-Z]/g, m => '-' + m.toLowerCase()))) continue;
      const r = el.getBoundingClientRect();
      if (r.width > 120 || r.height > 80 || !visible(el) || !safe(el)) continue;  // small icon controls only
      document.querySelectorAll('[data-hami-target]').forEach(x => x.removeAttribute('data-hami-target'));
      el.setAttribute('data-hami-target', '1');
      return ('[' + (el.getAttribute('aria-label') || el.tagName.toLowerCase()) + ']').slice(0, 40);
    }
  }
  return null;
}
"""

# Canvas-rendered apps (Flutter web): turn on the framework's accessibility tree, as a screen reader does,
# so the page's text exists in the DOM. A non-submitting action.
ENABLE_A11Y_JS = r"""
() => {
  const ph = document.querySelector('flt-semantics-placeholder, [aria-label="Enable accessibility"]');
  if (!ph) return false;
  ph.click();
  return true;
}
"""

NAV_LINKS_JS = r"""
() => {
  const out = [];
  const pick = sel => document.querySelectorAll(sel).forEach(a => {
    const href = a.getAttribute('href'); if (!href) return;
    try { out.push(new URL(href, location.href).href); } catch (e) {}
  });
  pick('nav a[href], header a[href], [role=navigation] a[href]');
  pick('footer a[href]');
  pick('a[href]');
  return out;
}
"""

PAGE_LANG_JS = r"""
() => {
  const t = (document.body && document.body.innerText || '').slice(0, 4000);
  const ar = (t.match(/[؀-ۿ]/g) || []).length;
  const en = (t.match(/[A-Za-z]/g) || []).length;
  return ar > en ? 'ar' : 'en';
}
"""


def _http_url(current: str, fallback: str) -> str:
    """The page's URL if it is a web page; pages that end on about:blank, data: or an error page keep the last
    real http(s) URL (otherwise the page would be scored as host 'about' and lose its domain context)."""
    return current if current.lower().startswith(("http://", "https://")) else fallback


@dataclass
class CaptureStep:
    step: int
    action: str
    at: str
    url: str
    html: str | None = None
    screenshot: bytes | None = None
    note: str = ""


@dataclass
class CaptureResult:
    requested_url: str
    final_url: str = ""
    status: str = "pending"          # ok | load_failed | timeout | refused
    error: str = ""
    http_status: int | None = None
    steps: list[CaptureStep] = field(default_factory=list)
    har: dict[str, Any] | None = None
    action_log: list[dict[str, Any]] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""
    request_count: int = 0
    blocked: dict[str, int] = field(default_factory=dict)
    nav_links: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class _Budget:
    def __init__(self, seconds: float):
        self.deadline = time.monotonic() + seconds

    def left(self) -> float:
        return max(0.0, self.deadline - time.monotonic())

    def ms(self, cap_s: float) -> float:
        return max(1.0, min(cap_s, self.left()) * 1000)


async def _capture_async(url: str, lang: str, run_actions: bool, collect_nav: bool) -> CaptureResult:
    from playwright.async_api import Error as PWError
    from playwright.async_api import async_playwright

    res = CaptureResult(requested_url=url, started_at=_now())
    budget = _Budget(settings.capture_timeout_s)
    allow_hosts, allow_private = settings.capture_allow_hosts, settings.capture_allow_private
    start_site = registrable_domain(urlsplit(url).hostname or "")
    state = {"phase": "initial", "requests": 0, "bytes": 0, "scripts": [], "loaded": set(), "chunk_entries": []}

    def block(reason: str) -> None:
        res.blocked[reason] = res.blocked.get(reason, 0) + 1

    def log(action: str, **kw: Any) -> None:
        res.action_log.append({"at": _now(), "action": action, **kw})

    har_dir = Path(tempfile.mkdtemp(prefix="hami-har-"))
    har_path = har_dir / "capture.har"
    locale = "ar-AE" if lang == "ar" else "en-AE"
    accept_lang = "ar-AE,ar;q=0.9,en;q=0.8" if lang == "ar" else "en-AE,en;q=0.9,ar;q=0.8"
    log("start", url=url, locale=locale, timeout_s=settings.capture_timeout_s)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-dev-shm-usage", "--disable-features=Translate", "--no-first-run"],
            **({"chromium_sandbox": False} if sys.platform != "win32" else {}),
        )
        try:
            context = await browser.new_context(
                locale=locale,
                timezone_id="Asia/Dubai",
                user_agent=USER_AGENT,
                viewport={"width": 1366, "height": 900},
                accept_downloads=False,
                service_workers="block",
                record_har_path=str(har_path),
                record_har_content="embed",
                extra_http_headers={"Accept-Language": accept_lang},
            )

            async def route_handler(route, request):  # noqa: ANN001
                state["requests"] += 1
                if state["requests"] > settings.capture_max_requests:
                    block("request_cap")
                    return await route.abort("blockedbyclient")
                if state["bytes"] > settings.capture_max_total_bytes:
                    block("size_cap")
                    return await route.abort("blockedbyclient")
                if not request_allowed(request.url, allow_hosts, allow_private):
                    block("private_network")
                    return await route.abort("blockedbyclient")
                if request.resource_type == "media":
                    block("media")
                    return await route.abort("blockedbyclient")
                if request.is_navigation_request() and request.frame.parent_frame is None:
                    if request.method != "GET":
                        block("form_submission")
                        return await route.abort("blockedbyclient")
                    if state["phase"] == "actions":
                        target_site = registrable_domain(urlsplit(request.url).hostname or "")
                        if target_site != start_site:
                            block("cross_site_navigation")
                            log("blocked_navigation", reason="cross-site link not followed")
                            return await route.abort("blockedbyclient")
                return await route.continue_()

            await context.route("**/*", route_handler)
            page = await context.new_page()

            async def on_popup(p):  # noqa: ANN001
                if p is not page:
                    block("popup")
                    try:
                        await p.close()
                    except PWError:
                        pass

            context.on("page", lambda p: asyncio.ensure_future(on_popup(p)))
            page.on("dialog", lambda d: asyncio.ensure_future(d.dismiss()))
            page.on("download", lambda d: asyncio.ensure_future(d.cancel()))

            def on_response(r):  # noqa: ANN001
                try:
                    cl = int(r.headers.get("content-length", "0") or 0)
                except ValueError:
                    cl = 0
                state["bytes"] += cl
                state["loaded"].add(r.url.split("#")[0])
                if (r.request.resource_type == "script" and len(state["scripts"]) < 60
                        and registrable_domain(urlsplit(r.url).hostname or "") == start_site):
                    state["scripts"].append(r)

            page.on("response", on_response)

            async def snapshot(step: int, action: str, note: str = "") -> None:
                html, shot = None, None
                try:
                    html = await page.content()
                except PWError as e:
                    note = (note + f" html_error={type(e).__name__}").strip()
                try:
                    shot = await page.screenshot(type="png", timeout=budget.ms(4) if budget.left() > 1 else 2000)
                except PWError as e:
                    note = (note + f" screenshot_error={type(e).__name__}").strip()
                res.steps.append(CaptureStep(step=step, action=action, at=_now(), url=page.url,
                                             html=html, screenshot=shot, note=note))
                log("snapshot", step=step, step_action=action, url=page.url, note=note)

            # Step 0: load the submitted page.
            try:
                resp = await page.goto(url, wait_until="domcontentloaded", timeout=budget.ms(15))
                res.http_status = resp.status if resp else None
                log("load", status=res.http_status, url=page.url)
                try:
                    await page.wait_for_load_state("networkidle", timeout=budget.ms(6))
                except PWError:
                    log("networkidle_timeout")
                await page.wait_for_timeout(min(1200, budget.ms(1.2)))
                res.status = "ok"
            except PWError as e:
                msg = str(e).splitlines()[0][:300]
                res.status = "timeout" if "Timeout" in msg else "load_failed"
                res.error = msg
                log("load_failed", error=msg)

            if res.status == "ok":
                res.final_url = _http_url(page.url, (resp.url if resp else "") or url)
                await snapshot(0, "load")
                state["phase"] = "actions"
                if collect_nav:
                    try:
                        res.nav_links = _filter_nav_links(await page.evaluate(NAV_LINKS_JS), page.url)
                    except PWError:
                        res.nav_links = []
                if run_actions:
                    try:
                        cur_lang = await page.evaluate(PAGE_LANG_JS)
                    except PWError:
                        cur_lang = "en"
                    step = 1
                    try:
                        enabled = await page.evaluate(ENABLE_A11Y_JS)
                    except PWError:
                        enabled = False
                    if enabled:
                        log("action", kind="enable_accessibility_tree", target_text="canvas-rendered app")
                        await page.wait_for_timeout(min(1500, budget.ms(1.5)))
                        await snapshot(step, "accessibility_tree")
                        step += 1
                    names = {"language": "language_switch", "country": "country_selector", "dismiss": "dismiss_popup"}
                    for kind in ("dismiss", "language", "country"):
                        if budget.left() < 3:
                            log("action_skipped", kind=kind, reason="time budget")
                            continue
                        try:
                            label = await page.evaluate(FIND_TARGET_JS, [kind, UNSAFE_WORDS, cur_lang])
                        except PWError:
                            label = None
                        if not label:
                            log("action_not_available", kind=kind)
                            continue
                        try:
                            await page.click("[data-hami-target='1']", timeout=budget.ms(2.5), no_wait_after=True)
                            log("action", kind=kind, target_text=label[:40])
                            try:
                                await page.wait_for_load_state("networkidle", timeout=budget.ms(3))
                            except PWError:
                                pass
                            await page.wait_for_timeout(min(900, budget.ms(0.9)))
                            await snapshot(step, names[kind])
                            step += 1
                        except PWError as e:
                            log("action_failed", kind=kind, error=str(e).splitlines()[0][:200])
                res.final_url = _http_url(page.url, res.final_url or url)
            if res.status == "ok" and budget.left() > 2:
                await _fetch_chunks(context, page, state, start_site, allow_hosts, allow_private, budget, log)
            res.request_count = state["requests"]
            await context.close()
        finally:
            await browser.close()

    try:
        if har_path.exists():
            res.har = json.loads(har_path.read_text(encoding="utf-8", errors="replace"))
            if state["chunk_entries"]:
                res.har.setdefault("log", {}).setdefault("entries", []).extend(state["chunk_entries"])
    except (OSError, ValueError) as e:
        log("har_read_failed", error=str(e)[:200])
    finally:
        try:
            for f in har_dir.iterdir():
                f.unlink()
            har_dir.rmdir()
        except OSError:
            pass
    res.finished_at = _now()
    log("finish", status=res.status, requests=res.request_count, blocked=res.blocked)
    return res


# ---- extra delivered code: same-origin JS/JSON chunks referenced by bundles the page already loaded -------------
CHUNK_REF_RE = re.compile(r"""["'`]((?:\.{1,2}/|/)?[A-Za-z0-9_\-][A-Za-z0-9_\-./]{0,180}\.(?:m?js|json))["'`]""")
CHUNK_SKIP_RE = re.compile(r"/(api|admin|cdn-cgi|login|logout|user|users|account|auth|oauth|pay|payment|order|orders)(/|$)"
                           r"|\.\./\.\./", re.I)
CHUNK_JSON_DIR_RE = re.compile(r"/(static|assets|locales?|i18n|lang|langs|js|dist|build|_next|_nuxt)/", re.I)


def _chunk_candidates(text: str, script_url: str, start_site: str) -> list[str]:
    from urllib.parse import urljoin

    out = []
    parts = urlsplit(script_url)
    origin = f"{parts.scheme}://{parts.netloc}"
    for ref in CHUNK_REF_RE.findall(text[:3_000_000]):
        if ref.startswith(("/", "./", "../")):
            full = origin + ref if ref.startswith("/") else urljoin(script_url, ref)
        elif "/" in ref:
            full = origin + "/" + ref
        else:
            full = urljoin(script_url, ref)
        u = urlsplit(full)
        if registrable_domain(u.hostname or "") != start_site or CHUNK_SKIP_RE.search(u.path):
            continue
        if u.path.endswith(".json") and not CHUNK_JSON_DIR_RE.search(u.path):
            continue
        out.append(f"{u.scheme}://{u.netloc}{u.path}")
    return list(dict.fromkeys(out))


async def _fetch_chunks(context, page, state: dict, start_site: str, allow_hosts, allow_private, budget, log) -> None:  # noqa: ANN001
    """Fetch same-origin static .js/.json files that already-loaded bundles reference but the page did not request
    (lazy route chunks, language packs). GET only, no HTML, no API paths, no form submits, no redirects followed;
    capped at CHUNK_FETCH_MAX_FILES files / CHUNK_FETCH_MAX_BYTES bytes and spaced CHUNK_FETCH_GAP_S apart.
    The bodies go through the normal sanitizer, delivered-code reading and kit fingerprinting."""
    from playwright.async_api import Error as PWError

    max_files, max_bytes, gap = settings.chunk_fetch_max_files, settings.chunk_fetch_max_bytes, settings.chunk_fetch_gap_s
    queue: list[str] = []
    for r in state["scripts"]:
        try:
            body = await r.text()
        except PWError:
            continue
        queue.extend(_chunk_candidates(body, r.url, start_site))
    seen, fetched, total = set(state["loaded"]), 0, 0
    while queue and fetched < max_files and total < max_bytes and budget.left() > 1.5:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        if not request_allowed(url, allow_hosts, allow_private):
            continue
        target, headers = url, {"Referer": page.url}
        u = urlsplit(url)
        if (u.hostname or "").endswith(".localhost"):
            # Chromium resolves *.localhost itself; the request API does not (local test sites only).
            target = url.replace(u.netloc, "127.0.0.1" + (f":{u.port}" if u.port else ""), 1)
            headers["Host"] = u.netloc
        try:
            resp = await context.request.get(target, headers=headers, max_redirects=0,
                                             timeout=min(4000, budget.ms(4)))
        except PWError as e:
            log("chunk_fetch_failed", url=url[:160], error=str(e).splitlines()[0][:120])
            continue
        ctype = (resp.headers.get("content-type") or "").lower()
        if resp.status != 200 or not re.search(r"javascript|ecmascript|json", ctype) or "html" in ctype:
            await asyncio.sleep(gap)
            continue
        body = await resp.body()
        if total + len(body) > max_bytes:
            break
        total += len(body)
        fetched += 1
        text = body.decode("utf-8", "replace")
        state["chunk_entries"].append({
            "startedDateTime": _now(), "time": 0, "cache": {}, "timings": {"send": 0, "wait": 0, "receive": 0},
            "request": {"method": "GET", "url": url, "httpVersion": "HTTP/1.1", "headers": [], "cookies": [],
                        "queryString": [], "headersSize": -1, "bodySize": 0},
            "response": {"status": 200, "statusText": "OK", "httpVersion": "HTTP/1.1",
                         "headers": [{"name": "content-type", "value": ctype}], "cookies": [], "redirectURL": "",
                         "headersSize": -1, "bodySize": len(body),
                         "content": {"size": len(body), "mimeType": ctype, "text": text}},
            "_hami_fetched_by": "capture_chunk_fetch",
        })
        if ctype.find("javascript") >= 0 or url.endswith((".js", ".mjs")):
            queue.extend(c for c in _chunk_candidates(text, url, start_site) if c not in seen)
        await asyncio.sleep(gap)
    if fetched or queue:
        log("chunk_fetch", files=fetched, bytes=total, not_fetched=max(0, len(set(queue) - seen)))


def _filter_nav_links(links: list[str], base_url: str, limit: int = 12) -> list[str]:
    base_host = urlsplit(base_url).hostname or ""
    base_site = registrable_domain(base_host)
    seen: set[str] = set()
    out: list[str] = []
    base_norm = base_url.split("#")[0].rstrip("/")
    for href in links:
        try:
            u = urlsplit(urljoin(base_url, href))
        except ValueError:
            continue
        if u.scheme not in ("http", "https") or not u.hostname:
            continue
        if registrable_domain(u.hostname) != base_site:
            continue
        path = (u.path or "/").lower()
        if any(x in path for x in NAV_EXCLUDE) or path.endswith(NAV_EXCLUDE_EXT):
            continue
        if u.query and any(x in u.query.lower() for x in ("login", "token", "session", "logout")):
            continue
        clean = f"{u.scheme}://{u.netloc}{u.path or '/'}"
        if clean.rstrip("/") == base_norm or clean in seen or path in ("", "/"):
            continue
        seen.add(clean)
        out.append(clean)
        if len(out) >= limit:
            break
    return out


def capture(url: str, lang: str = "en", run_actions: bool = True, collect_nav: bool = False) -> CaptureResult:
    """Blocking capture. Runs Playwright on a private event loop so it is safe to call from worker
    threads (FastAPI threadpool, discovery worker, CLI)."""
    try:
        check_target(url, settings.capture_allow_hosts, settings.capture_allow_private)
    except UnsafeTarget as e:
        r = CaptureResult(requested_url=url, status="refused", error=str(e), started_at=_now(), finished_at=_now())
        r.action_log.append({"at": _now(), "action": "refused", "reason": str(e)})
        return r
    if sys.platform == "win32":
        loop: asyncio.AbstractEventLoop = asyncio.ProactorEventLoop()
    else:
        loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            asyncio.wait_for(_capture_async(url, lang, run_actions, collect_nav), settings.capture_timeout_s + 25)
        )
    except asyncio.TimeoutError:
        r = CaptureResult(requested_url=url, status="timeout", error="capture exceeded hard limit",
                          started_at=_now(), finished_at=_now())
        return r
    except Exception as e:  # Playwright/browser crash: report, never raise into the API
        r = CaptureResult(requested_url=url, status="load_failed", error=f"{type(e).__name__}: {str(e)[:200]}",
                          started_at=_now(), finished_at=_now())
        return r
    finally:
        loop.close()

