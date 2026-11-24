#!/usr/bin/env python3
"""Real screenshots of Hami for the docs and the deck -> docs/screenshots/.

Everything runs locally and uses only the fictional-brand synthetic test sites (NovaMart VIP, OrbitaMall, Quorvia,
Al Waha Careers, the Al Noor listing): an isolated Hami API with a temporary database, the built extension in
Chromium, the reviewer console. Google Search is an original fixture served by request interception (Google is
not contacted).

    python tasks.py screenshots          (= python scripts/capture_screens.py)

The toolbar-badge shot needs a visible browser window and is taken with a screen copy of that window
(Windows: PowerShell + System.Drawing). On other systems it is skipped and the other shots still work.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from e2e_check import start_local  # noqa: E402
from extension_check import SEARCH_FIXTURE  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
DIST = REPO / "clients" / "extension" / "dist"
OUT = REPO / "docs" / "screenshots"


def grab_window(page, path: Path, top_css: int = 210) -> bool:
    """Top of the Chromium window only (toolbar with the extension badge), captured from the window itself with
    PrintWindow - other windows or the desktop can never end up in the image. Windows only."""
    if os.name != "nt":
        return False
    title = page.title().replace("'", "")
    cs = r"""
using System; using System.Runtime.InteropServices;
public class W {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint f);
  [DllImport("user32.dll")] public static extern uint GetDpiForWindow(IntPtr h);
  public struct RECT { public int L, T, R, B; }
}"""
    ps = f"""
Add-Type -AssemblyName System.Drawing
Add-Type -TypeDefinition @'
{cs}
'@
[W]::SetProcessDPIAware() | Out-Null
$p = Get-Process | Where-Object {{ $_.Path -like '*ms-playwright*' -and $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle -like '*{title}*' }} | Select-Object -First 1
if (-not $p) {{ exit 2 }}
$h = $p.MainWindowHandle
$r = New-Object W+RECT
[W]::GetWindowRect($h, [ref]$r) | Out-Null
$w = $r.R - $r.L; $hh = $r.B - $r.T
$full = New-Object System.Drawing.Bitmap($w, $hh)
$g = [System.Drawing.Graphics]::FromImage($full)
$dc = $g.GetHdc(); [W]::PrintWindow($h, $dc, 2) | Out-Null; $g.ReleaseHdc($dc)
$scale = [W]::GetDpiForWindow($h) / 96.0
$crop = [Math]::Min($hh, [int]({top_css} * $scale))
$top = $full.Clone((New-Object System.Drawing.Rectangle(0, 0, $w, $crop)), $full.PixelFormat)
$top.Save('{path}', [System.Drawing.Imaging.ImageFormat]::Png)
"""
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True, text=True)
    if r.returncode != 0:
        print("toolbar capture skipped:", (r.stderr or r.stdout).strip()[:300])
    return r.returncode == 0 and path.is_file()


def pin_extension(profile: Path, ext_id: str) -> None:
    prefs_path = profile / "Default" / "Preferences"
    prefs = json.loads(prefs_path.read_text(encoding="utf-8")) if prefs_path.is_file() else {}
    prefs.setdefault("extensions", {})["pinned_extensions"] = [ext_id]
    prefs_path.write_text(json.dumps(prefs), encoding="utf-8")


def main() -> int:
    if not (DIST / "manifest.json").is_file():
        raise SystemExit("build the extension first: python tasks.py extension")
    OUT.mkdir(parents=True, exist_ok=True)
    proc, api, token, ts_port, tmp = start_local()
    site = lambda n: f"http://{n}.localhost:{ts_port}/"  # noqa: E731
    c = httpx.Client(base_url=api, headers={"Authorization": f"Bearer {token}"}, timeout=120)
    saved: list[str] = []

    def shot(page, name: str, **kw) -> None:
        page.screenshot(path=str(OUT / name), **kw)
        saved.append(name)

    try:
        # Server side: Site A confirmed by a reviewer, Site B (rebrand) linked and approved -> cluster + brief.
        a = c.post("/scans", json={"url": site("site-a"), "source_type": "search",
                                   "listing_name": "NovaMart VIP"}).json()
        c.post("/reviews", json={"scan_id": a["scan_id"], "label": "fraudulent", "scam_type": "task_scam",
                                 "behavior_tags": ["deposit_to_unlock", "advance_fee"], "training_eligible": True})
        b = c.post("/scans", json={"url": site("site-b"), "source_type": "manual"}).json()
        for link in c.get("/links", params={"scan_id": b["scan_id"]}).json()["links"]:
            c.post(f"/links/{link['link_id']}/review", json={"decision": "approve", "reviewer": "screens"})
        c.post("/scans", json={"url": site("site-c"), "source_type": "manual"})

        with sync_playwright() as p:
            ext = Path(tmp) / "ext"
            shutil.copytree(DIST, ext)
            profile = Path(tmp) / "chrome-profile"
            launch = dict(channel="chromium", headless=False, device_scale_factor=2,
                          args=[f"--disable-extensions-except={ext}", f"--load-extension={ext}",
                                "--window-position=40,40", "--window-size=1280,900"],
                          viewport={"width": 1280, "height": 780})
            ctx = p.chromium.launch_persistent_context(str(profile), **launch)
            sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker", timeout=20000)
            ext_id = sw.url.split("/")[2]
            base = f"chrome-extension://{ext_id}"
            sw.evaluate("cfg => chrome.storage.sync.set(cfg)", {"serverUrl": api, "lang": "en", "localList": True,
                                                                 "checkSearchResults": True})
            consent = ctx.new_page()
            consent.goto(f"{base}/consent/consent.html")
            consent.set_viewport_size({"width": 900, "height": 900})
            shot(consent, "00_consent.png", full_page=True)
            consent.click("#agree")
            consent.wait_for_selector("#done:not([hidden])")
            ctx.close()
            pin_extension(profile, ext_id)  # show the badge on the toolbar (not hidden in the puzzle menu)
            ctx = p.chromium.launch_persistent_context(str(profile), **launch)
            sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker", timeout=20000)
            for pg in ctx.pages[1:]:
                pg.close()

            # Result card, English and Arabic.
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.set_viewport_size({"width": 400, "height": 900})
            page.goto(f"{base}/popup/popup.html?target={site('site-a')}")
            page.click("#check-btn")
            page.wait_for_selector(".hami-card", timeout=90000)
            page.click("text=Check again (live)")  # the API scanned Site A moments ago; show a live check
            page.wait_for_selector("text=Live check", timeout=90000)
            page.wait_for_timeout(800)
            shot(page, "01_result_card_en.png", full_page=True)
            sw.evaluate("() => chrome.storage.sync.set({lang: 'ar'})")
            page.goto(f"{base}/popup/popup.html?target={site('site-a')}")
            page.wait_for_selector(".hami-card", timeout=60000)
            page.wait_for_timeout(800)
            shot(page, "02_result_card_ar.png", full_page=True)
            sw.evaluate("() => chrome.storage.sync.set({lang: 'en'})")

            # Sign-in wall (Site D, Quorvia) running Site A's build: kit-match clue.
            page.goto(f"{base}/popup/popup.html?target={site('site-d')}")
            page.click("#check-btn")
            page.wait_for_selector(".hami-card", timeout=90000)
            page.wait_for_timeout(800)
            shot(page, "07_signin_wall_kit_match.png", full_page=True)

            # Registration wall of a family Hami has never seen (Site E, fictional): no reviewed case, no kit match.
            page.goto(f"{base}/popup/popup.html?target={site('site-e')}index/user/register/invite_code/QV7K2M.html")
            page.click("#check-btn")
            page.wait_for_selector(".hami-card", timeout=90000)
            page.wait_for_timeout(800)
            shot(page, "12_unseen_registration_wall.png", full_page=True)

            # Local list synced -> automatic check on a candidate: toolbar badge + High-risk banner.
            opts = ctx.new_page()
            opts.goto(f"{base}/options/options.html")
            opts.evaluate("() => new Promise(r => chrome.runtime.sendMessage({type: 'syncNow'}, r))")
            opts.set_viewport_size({"width": 900, "height": 1000})
            shot(opts, "11_options_privacy.png", full_page=True)
            opts.close()
            page.set_viewport_size({"width": 1280, "height": 780})
            page.goto(site("site-a"))
            page.wait_for_selector("#hami-banner", timeout=60000)
            page.wait_for_timeout(1500)
            shot(page, "04_high_risk_banner.png")
            page.goto(site("site-d"))
            page.bring_to_front()
            tab = sw.evaluate("async () => (await chrome.tabs.query({active: true, lastFocusedWindow: true}))[0].id")
            for _ in range(120):
                if sw.evaluate("t => chrome.action.getBadgeText({tabId: t})", tab) == "!":
                    break
                time.sleep(0.5)
            page.wait_for_timeout(1500)
            if grab_window(page, OUT / "03_toolbar_badge.png"):
                saved.append("03_toolbar_badge.png")

            # Google Search shields (original fixture via interception) and Maps business check.
            html = SEARCH_FIXTURE.format(a=site("site-a"), c=site("site-c"))
            ctx.route("https://www.google.com/search*", lambda r: r.fulfill(status=200, content_type="text/html", body=html))
            page.goto("https://www.google.com/search?q=part+time+job+dubai")
            page.wait_for_function("document.querySelectorAll('[data-hami-done]').length >= 3", timeout=20000)
            page.wait_for_timeout(1500)
            shot(page, "05_search_shields.png", clip={"x": 0, "y": 0, "width": 760, "height": 220})
            page.goto(site("listing"))
            page.wait_for_selector("#hami-maps-check", timeout=15000)
            page.evaluate("document.querySelector('#hami-maps-check').shadowRoot.querySelector('button.btn').click()")
            page.wait_for_function("document.querySelector('#hami-maps-check').shadowRoot.querySelector('.hami-card')",
                                   timeout=90000)
            page.wait_for_timeout(800)
            shot(page, "06_maps_business_check.png")

            # Reviewer console: queue, Site D case with the kit match, case brief.
            page.goto(f"{api}/review/login")
            page.fill("input[name=token]", token)
            page.click("button[type=submit], button")
            page.wait_for_url("**/review**")
            page.goto(f"{api}/review")
            page.wait_for_timeout(500)
            shot(page, "08_console_queue.png")
            d = next(s for s in c.get("/scans", params={"limit": 100}).json()["scans"] if s["host"] == "site-d.localhost")
            page.goto(f"{api}/review/scans/{d['scan_id']}")
            page.wait_for_timeout(500)
            shot(page, "09_console_case_kit_match.png", full_page=True)
            brief = c.get(f"/clusters/{a['scan_id']}/brief", params={"format": "md"}).text
            esc = brief.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            page.set_content("<html><head><meta charset='utf-8'><style>body{margin:0;background:#f4f5f7;font:14px/1.5 "
                             "system-ui,sans-serif}.doc{max-width:980px;margin:24px auto;background:#fff;padding:28px 36px;"
                             "border:1px solid #dde1e6;border-radius:8px}h1{font-size:16px;margin:0 0 12px;color:#555}"
                             "pre{white-space:pre-wrap;font:13px/1.55 ui-monospace,Consolas,monospace;margin:0}</style></head>"
                             f"<body><div class='doc'><h1>Case brief (export from the reviewer console, Markdown)</h1>"
                             f"<pre>{esc}</pre></div></body></html>")
            shot(page, "10_case_brief.png", full_page=True)
            ctx.close()
    finally:
        proc.terminate()
        proc.wait(timeout=15)
    print(f"saved {len(saved)} screenshots to {OUT}:")
    for n in saved:
        print(f"  {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
