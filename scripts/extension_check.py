#!/usr/bin/env python3
"""Automated check of the built Chrome extension (clients/extension/dist) in real Chromium.

Starts an isolated Hami API + synthetic test sites (like e2e_check.py --start-local), loads the unpacked
extension and verifies: popup check + bilingual result card (EN and AR/RTL), full result page (the
right-click path), watch toggle, reviewer-approved alert -> unread badge -> Updates tab, Google Maps
business check (on the synthetic listing page), local high-risk list banner after a reviewer label and
sync (no server call), Search shields on an original Google-like fixture served via request interception
(nothing is fetched from Google). Screenshots go to --shots (default: a temp dir).

    python scripts/extension_check.py [--shots DIR] [--headed]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from e2e_check import check, start_local  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
DIST = REPO / "clients" / "extension" / "dist"
RESULTS = __import__("e2e_check").RESULTS

SEARCH_FIXTURE = """<!doctype html><html><head><meta charset="utf-8"><title>part time job dubai - Search</title></head>
<body><div id="search"><div id="rso">
<div class="g"><a href="{a}"><h3>NovaMart VIP part-time jobs</h3></a><cite>site-a.localhost</cite></div>
<div class="g"><a href="{c}"><h3>Al Waha Careers - licensed recruitment</h3></a><cite>site-c.localhost</cite></div>
<div class="g"><a href="https://jobs.example.org/"><h3>Example job board</h3></a></div>
</div></div></body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default=None)
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    if not (DIST / "manifest.json").is_file():
        raise SystemExit("build the extension first: make extension")
    shots = Path(args.shots or tempfile.mkdtemp(prefix="hami-ext-shots-"))
    shots.mkdir(parents=True, exist_ok=True)
    proc, api, token, ts_port, tmp = start_local()
    auth = {"Authorization": f"Bearer {token}"}
    site = lambda n: f"http://{n}.localhost:{ts_port}/"  # noqa: E731
    print(f"local API {api}; screenshots -> {shots}")
    try:
        with sync_playwright() as p:
            # Main flow: the shipped build exactly as users load it (optional permissions NOT granted).
            test_dist = Path(tmp) / "ext"
            shutil.copytree(DIST, test_dist)
            ctx = p.chromium.launch_persistent_context(
                str(Path(tmp) / "chrome-profile"), channel="chromium", headless=not args.headed,
                args=[f"--disable-extensions-except={test_dist}", f"--load-extension={test_dist}"],
                viewport={"width": 1280, "height": 860}, accept_downloads=True)
            sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker", timeout=20000)
            ext_id = sw.url.split("/")[2]
            base = f"chrome-extension://{ext_id}"
            check("extension loaded (MV3 service worker running)", bool(ext_id), ext_id)
            check("shipped build runs without the optional permissions (no chrome.debugger)",
                  sw.evaluate("() => typeof chrome.debugger === 'undefined' && typeof chrome.downloads === 'undefined'"))
            sw.evaluate("cfg => chrome.storage.sync.set(cfg)", {"serverUrl": api, "lang": "en", "localList": True,
                                                                 "checkSearchResults": True})
            # PART 2: one-time consent screen on install; automatic checking only after agreeing.
            opened = []
            for _ in range(40):
                opened = sw.evaluate("async () => (await chrome.tabs.query({})).map(t => t.url || '')"
                                     ".filter(u => u.includes('consent/consent.html'))")
                if opened:
                    break
                time.sleep(0.25)
            consent = ctx.new_page()
            consent.goto(f"{base}/consent/consent.html")
            check("consent screen opened on install (Arabic + English)", bool(opened) and
                  "الفحص التلقائي" in consent.inner_text("body") and "Automatic checking" in consent.inner_text("body"),
                  str(opened[:1]))
            before = sw.evaluate("() => chrome.storage.sync.get(['autoCheck','consentAt'])")
            check("automatic checking off before consent", not before.get("autoCheck"))
            consent.click("#agree")
            consent.wait_for_selector("#done:not([hidden])")
            after = sw.evaluate("() => chrome.storage.sync.get(['autoCheck','consentAt'])")
            check("agreeing turns automatic checking on (consent recorded)", after.get("autoCheck") is True and bool(after.get("consentAt")))
            consent.close()
            # A skipped (sensitive) site sends nothing: a bank page served locally by request interception.
            bank_html = "<html><body><h1>Online banking</h1><p>Deposit, withdraw, part-time job offers, VIP 2</p></body></html>"
            ctx.route("https://www.emiratesnbd.com/**", lambda route: route.fulfill(status=200, content_type="text/html", body=bank_html))
            bank = ctx.new_page()
            bank.goto("https://www.emiratesnbd.com/en/")
            bank.wait_for_timeout(3000)
            c0 = httpx.Client(base_url=api, headers=auth, timeout=60)
            bank_scans = [x for x in c0.get("/scans", params={"limit": 200}).json()["scans"] if "emiratesnbd" in x["host"]]
            cls = bank.evaluate("1")  # page loaded
            check("banking site skipped on the device: nothing sent", bank_scans == [], str(bank_scans[:1]))
            bank.close()
            # A candidate page gets a badge without clicking; High risk also shows the full-page banner.
            cand = ctx.new_page()
            cand.goto(site("site-c"))
            badge = ""
            for _ in range(120):
                badge = "".join(sw.evaluate("async () => { const ts = await chrome.tabs.query({}); "
                                            "return Promise.all(ts.map(t => chrome.action.getBadgeText({tabId: t.id}))); }"))
                if badge.strip("0123456789"):
                    break
                time.sleep(0.5)
            check("candidate page (Site C) gets a toolbar badge without clicking", "✓" in badge, repr(badge))
            cand.goto(site("site-a"))
            cand.wait_for_selector("#hami-banner", timeout=90000)
            btxt = cand.evaluate("document.querySelector('#hami-banner').shadowRoot.textContent")
            check("High-risk candidate (Site A) shows the full-page banner automatically", "High risk" in btxt, btxt[:80])
            cand.close()

            # Popup check of Site A (popup page opened as a tab with ?target=).
            page = ctx.new_page()
            page.set_viewport_size({"width": 390, "height": 860})
            page.goto(f"{base}/popup/popup.html?target={site('site-a')}")
            page.click("#check-btn")
            page.wait_for_selector(".hami-card", timeout=90000)
            text = page.inner_text("#result")
            check("popup: Site A shows High risk with clues", "High risk" in text and "why" in text.lower(), text[:80].replace("\n", " "))
            # "Stored capture" when the automatic check above already scanned Site A moments ago (served from cache).
            check("popup: what to do + live/stored label", "what to do now" in text.lower()
                  and ("Live check" in text or "Stored capture" in text))
            check("clue quotes the amount from the cited sentence", "AED 500" in text, "")
            page.screenshot(path=str(shots / "popup_en.png"), full_page=True)
            # Watch toggle.
            page.check(".hami-watch input")
            page.wait_for_timeout(800)
            watches = sw.evaluate("() => chrome.storage.local.get('watches').then(x => x.watches || {})")
            check("watch toggle created a watch", len(watches) == 1, str(list(watches.values())[:1]))

            # Arabic / RTL rendering of the same card.
            sw.evaluate("() => chrome.storage.sync.set({lang: 'ar'})")
            page.goto(f"{base}/popup/popup.html?target={site('site-a')}")
            page.wait_for_selector(".hami-card", timeout=30000)
            ar_text = page.inner_text("#result")
            check("popup in Arabic is RTL", page.evaluate("document.documentElement.dir") == "rtl" and "خطر مرتفع" in ar_text)
            page.screenshot(path=str(shots / "popup_ar.png"), full_page=True)
            sw.evaluate("() => chrome.storage.sync.set({lang: 'en'})")

            # Full result page (the right-click "Check this link" path) for Site B -> pending link to A.
            page.set_viewport_size({"width": 900, "height": 900})
            page.goto(f"{base}/result/result.html?url={site('site-b')}&source=extension")
            page.wait_for_selector(".hami-card", timeout=90000)
            check("result page (right-click path) renders Site B", "OrbitaMall" in page.title() or "site-b" in page.inner_text("body"))
            page.screenshot(path=str(shots / "result_page.png"), full_page=True)

            # Reviewer approves the link + alert -> unread badge and Updates tab.
            c = httpx.Client(base_url=api, headers=auth, timeout=60)
            links = c.get("/links", params={"status": "pending"}).json()["links"]
            link = next(l for l in links if {l["host_a"], l["host_b"]} == {"site-a.localhost", "site-b.localhost"})
            c.post(f"/links/{link['link_id']}/review", json={"decision": "approve"})
            alert = next(a for a in c.get("/alerts/review", params={"status": "pending"}).json()["alerts"]
                         if a["link_id"] == link["link_id"])
            c.post(f"/alerts/{alert['alert_id']}/approve", json={})
            sw.evaluate("() => chrome.runtime.onMessage.hasListeners()")
            page.goto(f"{base}/popup/popup.html?target={site('site-c')}")
            page.wait_for_timeout(1500)
            badge = sw.evaluate("() => chrome.action.getBadgeText({})")
            check("unread-alerts badge shows 1", badge == "1", f"badge={badge!r}")
            page.click("#tab-updates")
            page.wait_for_selector(".alert", timeout=10000)
            upd = page.inner_text("#view-updates")
            check("Updates tab explains the approved alert", "site-b" in upd and "related site" in upd.lower(), upd[:100].replace("\n", " "))
            page.screenshot(path=str(shots / "updates.png"), full_page=True)
            page.wait_for_timeout(500)
            check("badge cleared after reading", sw.evaluate("() => chrome.action.getBadgeText({})") == "")

            # Maps business check on the synthetic listing page (content script matches listing.localhost).
            page.goto(site("listing"))
            page.wait_for_selector("#hami-maps-check", timeout=15000)
            page.evaluate("document.querySelector('#hami-maps-check').shadowRoot.querySelector('button.btn').click()")
            page.wait_for_function("document.querySelector('#hami-maps-check').shadowRoot.querySelector('.hami-card')",
                                   timeout=90000)
            maps_text = page.evaluate("document.querySelector('#hami-maps-check').shadowRoot.querySelector('.panel').innerText")
            check("Maps check flags the listing-name mismatch", "does not match" in maps_text and "Al Noor" in maps_text,
                  maps_text[maps_text.find("listing name"):][:90] if "listing name" in maps_text else maps_text[:90])
            page.screenshot(path=str(shots / "maps_check.png"))

            # Reviewer confirms Site A -> list sync -> banner on Site A with no server call.
            scans = c.get("/scans", params={"limit": 50}).json()["scans"]
            a_scan = next(s for s in scans if s["host"] == "site-a.localhost")
            c.post("/reviews", json={"scan_id": a_scan["scan_id"], "label": "fraudulent", "behavior_tags": ["deposit_to_unlock"]})
            opts = ctx.new_page()
            opts.goto(f"{base}/options/options.html")
            synced = opts.evaluate("""() => new Promise(r => chrome.runtime.sendMessage({type: 'syncNow'}, r))""")
            check("on-device classification marks a bank as sensitive (no network)",
                  opts.evaluate("""() => new Promise(r => chrome.runtime.sendMessage({type: 'classify', url: 'https://www.adcb.com/'}, r))""")["data"]["reason"] == "sensitive")
            opts.close()
            hosts = sw.evaluate("() => chrome.storage.local.get('lists').then(x => x.lists.hosts)")
            check("high-risk list synced to the device", "site-a.localhost" in hosts, f"{hosts} v{synced.get('data', {}).get('version')}")
            api_hits: list[str] = []
            page.on("request", lambda r: api_hits.append(r.url) if r.url.startswith(api) else None)
            page.goto(site("site-a"))
            page.wait_for_selector("#hami-banner", timeout=15000)
            banner = page.evaluate("document.querySelector('#hami-banner').shadowRoot.textContent")
            check("banner shown on the confirmed site", "reviewer-confirmed" in banner)
            check("banner needed no server call from the page", api_hits == [], str(api_hits[:2]))
            page.screenshot(path=str(shots / "banner.png"))

            # PART 3: idle snapshot on a candidate page (Site D, a login wall running Site A's bundles).
            d_page = ctx.new_page()
            d_page.goto(site("site-d"))
            snap_ok = d_page.evaluate("""() => new Promise(r => { document.addEventListener('hami-snapshot', e => r(e.detail.ok));
                                         setTimeout(() => r(null), 40000); })""")
            check("idle snapshot sent after 10 s without activity", snap_ok is True, str(snap_ok))
            snaps = [x for x in c.get("/scans", params={"limit": 100}).json()["scans"]
                     if x["host"] == "site-d.localhost" and x["batch"] == "snapshot"]
            if snaps:
                internal = c.get(f"/scans/{snaps[0]['scan_id']}/internal").json()
                har_arts = [a for a in internal["artifacts"] if a["kind"] == "har" and a["action"] == "idle_snapshot"]
                check("snapshot stored as a HAR-format artifact (metadata) with SHA-256", bool(har_arts) and len(har_arts[0]["sha256"]) == 64)
                check("snapshot finds the kit match with confirmed Site A", internal["tier"] == "high_risk" and
                      any(cl["type"] == "kit_match" for cl in internal["clues"]),
                      next((cl["text"]["en"] for cl in internal["clues"] if cl["type"] == "kit_match"), str(internal["rules_fired"])))
            else:
                check("snapshot stored as a HAR-format artifact (metadata) with SHA-256", False, "no snapshot scan")
            d_page.close()

            # Search shields on an original Google-like fixture (request interception; Google is not contacted).
            c.post("/scans", json={"url": site("site-c"), "source_type": "manual"})  # make Site C known to the server
            html = SEARCH_FIXTURE.format(a=site("site-a"), c=site("site-c"))
            ctx.route("https://www.google.com/search*", lambda route: route.fulfill(status=200, content_type="text/html", body=html))
            page.goto("https://www.google.com/search?q=part+time+job+dubai")
            page.wait_for_function("document.querySelectorAll('[data-hami-done]').length >= 3", timeout=15000)
            page.wait_for_timeout(1500)
            tiers = page.evaluate("""() => [...document.querySelectorAll('#rso .g')].map(g => {
                const host = g.querySelector('span'); const b = host && host.shadowRoot && host.shadowRoot.querySelector('button');
                return b ? b.dataset.tier : null; })""")
            check("Search shields added to every result", len(tiers) == 3 and all(t is not None for t in tiers), str(tiers))
            check("Site A shield red from the local list", tiers[0] == "high_risk", str(tiers))
            check("Site C shield from hostname lookup: no strong signals", tiers[1] == "no_strong_signals", str(tiers))
            check("unknown site gets a neutral shield", tiers[2] == "", str(tiers))
            page.screenshot(path=str(shots / "search_shields.png"))

            # Automatic check and "Check this page" agree on the same URL (no stale-cache difference).
            reg_url = site("site-e") + "index/user/register/invite_code/QV7K2M.html"
            auto_tab = ctx.new_page()
            auto_tab.goto(reg_url)
            auto_tier = None
            for _ in range(120):
                got = sw.evaluate("k => chrome.storage.session.get(k).then(x => x[k] ? x[k].result.tier : null)", f"result:{reg_url}")
                if got:
                    auto_tier = got
                    break
                time.sleep(0.5)
            pop2 = ctx.new_page()
            pop2.goto(f"{base}/popup/popup.html?target={reg_url}")
            pop2.click("#check-btn")
            pop2.wait_for_selector(".hami-card", timeout=90000)
            manual_tier = sw.evaluate("k => chrome.storage.session.get(k).then(x => x[k] ? x[k].result.tier : null)", f"result:{reg_url}")
            check("automatic check and 'Check this page' give the same tier", auto_tier is not None and auto_tier == manual_tier,
                  f"auto={auto_tier} manual={manual_tier}")
            pop2.close()
            auto_tab.close()

            # Public check page at "/" (no extension, no login): same result card.
            web = ctx.new_page()
            web.goto(f"{api}/")
            web.fill("#url", site("site-d"))
            web.click("#check-btn")
            web.wait_for_selector("#result .hami-card", timeout=90000)
            wtext = web.inner_text("#result")
            check("public check page: Site D is High risk with the kit-match clue",
                  "High risk" in wtext and "same software" in wtext, " ".join(wtext[:80].split()))
            check("public check page shows clue screenshots", web.locator("#result .hami-clue img").count() >= 1)
            web.click("#lang-btn")
            web.wait_for_timeout(300)
            check("public check page switches to Arabic (RTL)", web.evaluate("document.documentElement.dir") == "rtl"
                  and "خطر مرتفع" in web.inner_text("#result"))
            web.screenshot(path=str(shots / "public_check_page.png"), full_page=True)
            web.close()

            # Unseen scam behind a bot challenge: the server's capture only gets the challenge page (site-f), while the
            # user's browser gets the real registration page (served here to the extension's browser only). The
            # popup sends the page STRUCTURE computed on the device; field values never leave it.
            blocked_url = site("site-f") + "index/user/register/invite_code/ZX81PQ.html"
            real_html = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Mobile phone number login</title></head>
<body><h2>Nimbara Orders</h2><form action="/index/user/do_register" method="post">
<span>+971</span><input type="tel" name="username" placeholder="Enter mobile number" maxlength="11">
<input type="password" name="password" placeholder="Login password">
<input type="password" name="paypassword" placeholder="Security password">
<input type="text" name="invite_code" value="PLANTEDVALUE42" readonly required>
<button>Register</button></form>
<a href="/index/user/login.html">Login</a>
<script>var nav = ["/index/ctrl/recharge.html", "/index/rot_order/index.html", "/index/my/invite"];</script>
<p>Copyright (c) 2026</p></body></html>"""
            ctx.route(blocked_url, lambda route: route.fulfill(status=200, content_type="text/html", body=real_html))
            tab = ctx.new_page()
            tab.goto(blocked_url)
            tab.fill("input[name=password]", "TypedSecret!9")
            tab.fill("input[name=username]", "0501234567")
            pop = ctx.new_page()
            pop.set_viewport_size({"width": 400, "height": 900})
            pop.goto(f"{base}/popup/popup.html?target={blocked_url}")
            pop.click("#check-btn")
            pop.wait_for_selector(".hami-card", timeout=90000)
            card = pop.inner_text("#result")
            check("page blocked for the server, seen by the browser: High risk from on-device page structure",
                  "High risk" in card and "invite code and a separate security password" in card, card[:120].replace("\n", " "))
            check("clue names the task-scam routes the page links to", "rotation-order" in card and "recharge" in card)
            sig_files = list((Path(tmp) / "storage").rglob("*.log.json"))
            sent = [f.read_text(encoding="utf-8") for f in sig_files if "paypassword" in f.read_text(encoding="utf-8")]
            check("page structure stored as evidence; no field values, typed password or phone number sent",
                  bool(sent) and not any(x in t for t in sent for x in ("PLANTEDVALUE42", "TypedSecret", "0501234567")),
                  f"{len(sent)} signal artifact(s)")
            pop.screenshot(path=str(shots / "unseen_scam_card.png"), full_page=True)
            pop.close()
            tab.close()
            ctx.close()

            # PART 4: investigator mode in a second profile. Chrome's permission prompt cannot be clicked under
            # automation, so this copy grants the OPTIONAL debugger + downloads permissions up front (same code).
            inv_dist = Path(tmp) / "ext-investigator"
            shutil.copytree(DIST, inv_dist)
            man = json.loads((inv_dist / "manifest.json").read_text(encoding="utf-8"))
            man["permissions"] = man["permissions"] + man.pop("optional_permissions", [])
            (inv_dist / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
            ctx = p.chromium.launch_persistent_context(
                str(Path(tmp) / "chrome-profile-investigator"), channel="chromium", headless=not args.headed,
                args=[f"--disable-extensions-except={inv_dist}", f"--load-extension={inv_dist}"],
                viewport={"width": 1280, "height": 860}, accept_downloads=True)
            sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker", timeout=20000)
            base = f"chrome-extension://{sw.url.split('/')[2]}"
            sw.evaluate("cfg => chrome.storage.sync.set(cfg)", {"serverUrl": api, "lang": "en", "localList": True,
                                                                 "autoCheck": True, "consentAt": "2026-01-01T00:00:00Z"})
            # PART 4: investigator mode - full HAR via chrome.debugger, sanitized on the device, saved after 10 s idle.
            sw.evaluate("() => chrome.storage.sync.set({investigatorMode: true, evidenceUpload: true})")
            ctx.add_cookies([{"name": "sid", "value": "COOKIESECRET", "domain": "site-a.localhost", "path": "/"}])
            inv = ctx.new_page()
            inv.goto(site("site-a"))
            inv.bring_to_front()
            tab_id = sw.evaluate("async () => (await chrome.tabs.query({active: true, lastFocusedWindow: true}))[0].id")
            opts2 = ctx.new_page()
            opts2.goto(f"{base}/options/options.html")
            with inv.expect_navigation(timeout=20000):  # recording reloads the tab to capture the full page load
                started = opts2.evaluate("t => new Promise(r => chrome.runtime.sendMessage({type: 'investigatorStart', tabId: t[0], url: t[1]}, r))",
                                         [tab_id, site("site-a")])
            check("investigator recording starts on a candidate site", started.get("ok") is True, str(started))
            refused = opts2.evaluate("t => new Promise(r => chrome.runtime.sendMessage({type: 'investigatorStart', tabId: t, url: 'https://www.mashreq.com/'}, r))",
                                     tab_id)
            check("investigator mode never runs on a skipped (banking) site", refused.get("ok") is False, refused.get("error", ""))
            inv.evaluate("window.__ev = new Promise(r => { document.addEventListener('hami-evidence', e => r(e.detail));"
                         " setTimeout(() => r(null), 45000); })")
            inv.evaluate("fetch('/api/countries.json?token=TOKENSECRET&lang=en').then(r => r.text())")
            saved = inv.evaluate("window.__ev")
            check("evidence saved automatically after 10 s idle", bool(saved and saved.get("sha256")), str(saved)[:120])
            if saved and saved.get("sha256"):
                path, text = None, ""
                for _ in range(30):  # the download may still be finishing when the page reports the save
                    path = sw.evaluate("async () => { const d = await chrome.downloads.search({orderBy: ['-startTime'], limit: 1,"
                                       " state: 'complete'}); return d.length ? d[0].filename : null; }")
                    text = Path(path).read_text(encoding="utf-8") if path and Path(path).is_file() else ""
                    if text:
                        break
                    time.sleep(0.5)
                check("downloaded .har is sanitized (no cookie, no token)", text != "" and "COOKIESECRET" not in text
                      and "TOKENSECRET" not in text and '"name": "Cookie"' not in text and "countries.json" in text,
                      f"{len(text)} bytes")
                check("SHA-256 of the downloaded file matches the reported hash",
                      hashlib.sha256(text.encode("utf-8")).hexdigest() == saved["sha256"])
                up = saved.get("uploaded") or {}
                check("uploaded as evidence with matching hashes", bool(up.get("evidence_id")) and up.get("hash_match") is True,
                      str(up))
            opts2.close()
            inv.close()
            ctx.close()

    finally:
        proc.terminate()
        proc.wait(timeout=15)
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} extension assertions passed; screenshots in {shots}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
