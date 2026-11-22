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
            ctx = p.chromium.launch_persistent_context(
                str(Path(tmp) / "chrome-profile"), channel="chromium", headless=not args.headed,
                args=[f"--disable-extensions-except={DIST}", f"--load-extension={DIST}"],
                viewport={"width": 1280, "height": 860})
            sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker", timeout=20000)
            ext_id = sw.url.split("/")[2]
            base = f"chrome-extension://{ext_id}"
            check("extension loaded (MV3 service worker running)", bool(ext_id), ext_id)
            sw.evaluate("cfg => chrome.storage.sync.set(cfg)", {"serverUrl": api, "lang": "en", "localList": True,
                                                                 "checkSearchResults": True, "autoCheck": False})

            # Popup check of Site A (popup page opened as a tab with ?target=).
            page = ctx.new_page()
            page.set_viewport_size({"width": 390, "height": 860})
            page.goto(f"{base}/popup/popup.html?target={site('site-a')}")
            page.click("#check-btn")
            page.wait_for_selector(".hami-card", timeout=90000)
            text = page.inner_text("#result")
            check("popup: Site A shows High risk with clues", "High risk" in text and "why" in text.lower(), text[:80].replace("\n", " "))
            check("popup: what to do + live label", "what to do now" in text.lower() and "Live check" in text)
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
            opts.close()
            hosts = sw.evaluate("() => chrome.storage.local.get('highRisk').then(x => x.highRisk.hosts)")
            check("high-risk list synced to the device", "site-a.localhost" in hosts, f"{hosts} v{synced.get('data', {}).get('version')}")
            api_hits: list[str] = []
            page.on("request", lambda r: api_hits.append(r.url) if r.url.startswith(api) else None)
            page.goto(site("site-a"))
            page.wait_for_selector("#hami-banner", timeout=15000)
            banner = page.evaluate("document.querySelector('#hami-banner').shadowRoot.textContent")
            check("banner shown on the confirmed site", "reviewer-confirmed" in banner)
            check("banner needed no server call from the page", api_hits == [], str(api_hits[:2]))
            page.screenshot(path=str(shots / "banner.png"))

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
            ctx.close()
    finally:
        proc.terminate()
        proc.wait(timeout=15)
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} extension assertions passed; screenshots in {shots}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
