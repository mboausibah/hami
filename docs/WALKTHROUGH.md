# Walkthrough: Hami on real links in about five minutes

Scam domains are written defanged (`betnala[.]com`). Type them without the brackets. Open scam sites only inside
this walkthrough, and never sign up, pay or enter details on them.

## 0. Start (one minute, once)

1. In the repository: `docker compose up` (or `python tasks.py run`). Wait until http://localhost:8000/health shows
   `"status":"ok"`. The log says `seed indicators: loaded 3 confirmed cases`.
2. Chrome → `chrome://extensions` → **Developer mode** → **Load unpacked** → `clients/extension/dist` (or the unzipped
   release). The consent page opens: read it and click **I agree** to turn on automatic checking.
3. Pin the Hami icon (puzzle piece → pin) so the badge is visible.
4. Optional, for the console: `docker compose exec api python -m app.cli token`, then open http://localhost:8000/review
   and sign in with the token.

## 1. A sign-in wall the user has never reported (60 seconds)

1. Open `https://betnala[.]com/`. It is a new gambling-deposit portal behind a login, never reviewed by us.
2. Within a few seconds, without clicking anything:
   - the Hami badge turns red (`!`);
   - a banner says **High risk**: "This site runs the same software as aed99.com, a confirmed scam (N identical files)."
3. Click the Hami icon to see the full card: tier, clues, what to do now, live/stored label. Switch the language in
   Options to show the Arabic, right-to-left card.

*Why it works:* the page shows only a login form, but the browser downloads the app's own files. They match the
seeded kit of the confirmed aed99 family. The site's own code also mentions deposits, withdrawals and bonuses
dozens of times.

## 2. A subdomain of a confirmed scam (20 seconds)

Right-click a link to `https://cs.aed99[.]com/`, or paste it into the popup's check. Result: **High risk**, "This page
is part of aed99.com, which a Hami reviewer confirmed as fraudulent." That is registrable-domain inheritance.

## 3. A legitimate site is not flagged (30 seconds)

Check `https://www.bayt.com/` (job board) or `https://www.noon.com/` (shop) with the Hami button. Result:
**No strong signals**, with the note that this is not a guarantee. Banks and government sites are skipped on the
device (nothing is sent). Hami was tested on 50 unseen legitimate UAE pages with 0 false alarms.

## 4. Google Search and Maps (60 seconds)

1. Options → turn on **Check search results** (sends result hostnames only).
2. Search Google for `part time job dubai`. Each result gets a shield: red for known scams (from the device's local
   list), green/amber from the server's hostname lookup, grey when unknown. **Check now** runs a full scan.
3. Open a business on Google Maps that has a website. Click **Check this business website with Hami**. The website is scanned
   with the listing name, and a site claiming a different company is flagged as a listing-name mismatch.

## 5. Investigator view (60 seconds)

In the reviewer console (http://localhost:8000/review):
1. **Scan queue**: every check with tier and score. The seeded cases are marked *seeded from team review*.
2. Open the betnala case:
   - clues, rules fired, the **Kit match** box (matched files);
   - the observations table (visible page vs delivered code);
   - artifacts with SHA-256;
   - a proposed **same_kit** link to aed99.com. Approve it.
3. **Case brief → Export Markdown**. It contains defanged URLs, first and last observed times, the evidence behind
   each link with artifact hashes, and observations kept separate from inferences. Every link is marked as a lead,
   not proof of ownership.
4. Optional, investigator mode: Options → **Investigator mode** (grants the optional debugger/downloads
   permissions). On a suspicious tab, popup → **Record this tab** → **Save evidence**. A sanitized `.har` is
   downloaded with its SHA-256.

## If a scam site has gone offline

Scam sites disappear quickly. Every capture is stored. In the console, open the earlier case (artifacts and
screenshots are kept) and click **Re-analyze stored capture**. The result is labeled **Stored capture** instead of
**Live check**. Kit matching and domain inheritance work from the seed file even when the live site is down. A
fresh scan of a dead site returns *Insufficient evidence*, never "safe".

---

## 60-second demo video: suggested shot list

| Time | Shot |
|---|---|
| 0–8 s | Title: "Hami حامي: warns before you pay". One line on UAE task and deposit scams. |
| 8–25 s | Open the betnala login page. The badge turns red and the banner appears without a click: "same software as aed99.com, a confirmed scam". |
| 25–35 s | Click the icon: the High-risk card in English, then Arabic (RTL). |
| 35–43 s | Google Search shields on "part time job dubai"; a legitimate job board shows "No strong signals". |
| 43–53 s | Reviewer console: the kit-match evidence, then the case brief export with SHA-256 hashes. |
| 53–60 s | "Runs locally with `docker compose up`. Privacy: decided on the device, nothing sent without consent." |
