You are building **Hami (حامي)**, our team's entry for the AD Police x 42 Abu Dhabi hackathon (ScamShield AI challenge: detecting fraudulent links and websites across the open internet, including Search Engine results and Maps). We must finish a **working MVP today**. The proposal is at `docs/proposal.pdf` (also `docs/proposal.docx`). Read it first and treat it as the spec. Our own private datasets and scam sites are in `data/private/`.

**Hami** checks links before someone pays. A hosted backend opens the page safely, reads what it asks the visitor to do in Arabic or English, and returns a clear risk level. Warnings appear in an **iOS and Android app** (share a link from WhatsApp, Messages or a browser) and a **Chrome extension** (current page, any link, Google Search results and Google Maps business listings). A **discovery worker** finds newly registered look-alike domains in public certificate transparency logs before anyone reports them. Reviewed cases retrain the model, alert people who opted in, and link rebranded scam sites into a redacted case brief for investigators.

**This is a product, not a demo.** The organizers disqualify idea-only entries, concepts, pitch decks and mockups without working functionality, and asked for "a working prototype". Hami must work on **real, public links on the open internet**, from real devices, through a hosted API. Synthetic test sites exist only for automated tests and reproducibility. No mocked responses, hardcoded results, fake data on screens or placeholder features. If something can't be finished, cut it and say so in the README — never fake it.

---

## 0. Hackathon rules you must satisfy

- The **master** branch (not `main`) of our GitHub repo holds the entire MVP and a `README.md`. Set it up with `git branch -M master`.
- `README.md` must include: (1) the problem and solution, (2) the reasoning behind our technical choices, trade-offs, what we left out and what we'd do differently with more time, (3) instructions to build and run the project.
- We must also submit **technical documentation** and a **PPT** explaining the **architecture, model choices and privacy design**. You generate both (section 10).
- **No third-party intellectual property** in the repo: no real brand names or logos in test sites, screenshots in docs, or app assets. Fictional brands only. (Real scam sites are analyzed at runtime; their content is not committed.)
- **No hacking**: only visit public pages, the way a normal browser would. Never probe storage buckets, APIs, admin panels, directories or anything beyond a normal page visit. Rate-limit the discovery worker and never run mass scans from the campus network.
- **Private data stays private**: `data/private/` is git-ignored and never committed, copied into test sites, logged or printed in full.

---

## 1. Priorities for a one-day build

Work in this order. Finish and commit each tier before the next. Keep `master` runnable at all times.

**P0 — the core product:**
1. Backend scan pipeline: capture → sanitize → store → analyze → score → `POST /scans`, working on real public URLs.
2. Importer for `data/private/` + synthetic corpus generator + training command + model v1 trained on our data.
3. Chrome extension: check the current page and right-click a link; bilingual result card.
4. Hosting: Docker image and a public HTTPS URL for the API (section 8), so clients work from any network.
5. Synthetic test sites + `scripts/e2e_check.py` passing checks 1 and 4.

**P1 — the full product:**
6. Expo mobile app on Android: paste, share-to-app, result card, watch, updates screen, Arabic RTL. A release APK in `clients/mobile/dist/` that installs on any Android phone and talks to the hosted API.
7. Extension on Google Search results (shields) and Google Maps business panels (website vs listing name check).
8. Reviews, linking, watches, reviewer-approved alerts, retraining with the promotion rule. `e2e_check.py` checks 2 and 3 pass.
9. Discovery worker on certificate transparency logs.

**P2 — if time allows:**
10. iOS build (needs a Mac with Xcode, or EAS Build). If no Mac, iOS must still be configured and ready to build.
11. Extension local high-risk list with warning banner, alerts badge, options page polish.
12. Static check of authorized files, redacted case brief export, reviewer console polish.

**Always reserve the last stretch for section 10** (README, technical documentation, PPT). They are required for submission.

---

## 2. Safety and privacy rules

1. The capture browser never signs in, submits forms, pays, downloads to disk or follows discovered links. It runs only predefined non-submitting actions (switch language, open a country selector), with a time limit of about 20 s and caps on request count and response size. Run capture inside the container, not on a team laptop's normal browser profile.
2. The analyzer only reads saved, sanitized copies. It never executes scripts or makes network requests.
3. Strip cookies, `Authorization`/`Set-Cookie` headers, token-like query params, emails and phone numbers before storage.
4. The static checker stores category, file, location, time and review status — never the secret value — and never tests credentials.
5. Watches use a random device UUID. The extension never sends browsing history or search queries. On Google Search it sends **only result hostnames** for a lookup, and only if the user enables "Check search results" (on by default only for the local high-risk list, which needs no server call).
6. API rate limits per device ID and IP. Reviewer endpoints require a token from `.env`.

---

## 3. Stack (fixed — ask me before adding any other major dependency)

- Backend: Python 3.11+, FastAPI, Playwright (Chromium), scikit-learn, SQLite, BeautifulSoup + lxml, Jinja2, rapidfuzz, httpx (discovery worker only). Docker.
- Clients: TypeScript. Shared package for API client, types and ar/en strings. Mobile: Expo (React Native) + expo-router + expo-share-intent + expo-secure-store. Extension: Chrome Manifest V3 built with Vite.

## Repository layout

```
hami/
  backend/   app/{api,capture,sanitize,analyze,scoring,linking,discovery,static_check,db,review_ui}/  ml/  models/  tests/  Dockerfile
  testsites/ sites/  generator/  corpus/  static_files/
  clients/   shared/  extension/  mobile/
  data/      private/   (git-ignored, ours)   processed/ (git-ignored)
  scripts/   run.sh  e2e_check.py  make_docs.py
  docs/      proposal.pdf  proposal.docx  architecture.md  TECHNICAL.md  Hami.pptx  screenshots/
  Makefile  docker-compose.yml  .gitignore  .env.example  README.md
```

---

## 4. Backend

**Pipeline:** `submit → capture → sanitize → store (SHA-256 every artifact) → analyze → score → respond`.

- **Capture:** fresh Playwright context per scan, `en-AE`/`ar-AE` locale, Asia/Dubai timezone, realistic user agent. Save a HAR with response bodies, rendered HTML after each action, a screenshot per step, and a timestamped action log. Cache results per normalized URL for a configurable time so repeated checks return fast.
- **Analyzer:** per-language visible text; form fields (flag card / CVV / OTP / bank-password inputs); currency amounts (AED, درهم, $, Arabic-Indic digits); VIP/level tables; commission rates; invitation codes; withdrawal conditions; wa.me / t.me links; hostname references in HTML, JS and JSON bodies (label *referenced* vs *observed in traffic*); a layout fingerprint (DOM-structure shingles + form-field signature); claimed brand names from title, header and footer.
- **Arabic normalization** (`ml/arabic.py`, unit-tested): unify أ إ آ → ا, ى → ي, ة → ه for matching, strip tatweel and diacritics, Arabic-Indic → Western digits.
- **Model:** calibrated logistic regression on TF-IDF word 1–2 grams + char 3–5 grams of redacted text (hostnames removed), plus structured indicator features. Show the top-weighted phrases per decision.
- **Rules layer + tiers** (exactly as in the proposal):
  - **High risk** — strong fraud behavior (advance fee / deposit to unlock / commission for moving money) and the classifier agrees; or a strong reviewed-case link plus any fraud behavior.
  - **Caution** — fraud signals without a payment request, listing-identity mismatch, or score above the caution threshold.
  - **No strong signals** — wording must say this is not a guarantee.
  - **Insufficient evidence** — failed load, sign-in wall, cloaking suspected, or too little content.
  Weak signals (common analytics, CDN, hosting, payment providers) never raise the tier alone.
- **Listing identity check:** if a listing name is given (from the user or the Maps panel), compare it with the site's claimed names after Arabic normalization (rapidfuzz) → match / mismatch / unclear. A mismatch raises the tier to at least Caution.
- **Result payload:** tier, up to 3 clues (bilingual text, observation ID, screenshot URL), what to do now, what couldn't be checked, model version, and whether the result is from a live or stored capture.

**SQLite tables:** `scans`, `artifacts`, `observations`, `assessments`, `reviews` (with `supersedes`, never overwrite), `dataset_versions`, `model_versions` (candidate/current/retired, metrics JSON, dataset hash), `links` (relation_type, strength, evidence_obs_ids, review_status), `watches` (device_id), `alerts` (approved_by, sent_at, withdrawn_at), `discovered_domains` (domain, cert_seen_at, matched_pattern, scan_id, status), `static_findings` (no value column).

**API:**
- `POST /scans` `{url, source_type: search|maps|sms|whatsapp|manual|extension|discovery, listing_name?, lang}`; `GET /scans/{id}`; `GET /artifacts/{id}` (screenshots only, public).
- `POST /lookup/hosts` `{hosts: [...]}` → what Hami already knows about each host (reviewed tier or latest assessment), no new capture. Used for Search result shields.
- `POST /watches` `{scan_id, device_id}`, `DELETE /watches/{id}`, `GET /alerts?device_id=` (withdrawn alerts flagged).
- `GET /indicators/high-risk-hosts` — hostnames from reviewer-approved High risk cases only, with a version number.
- Reviewer endpoints (token): `POST /reviews`, `POST /links/{id}/review`, `POST /alerts/{id}/approve|withdraw`, `POST /train`, `GET /clusters/{id}/brief`, `GET /discovery/queue`.
- `GET /health`. CORS for the extension origin and the mobile app.

**Reviewer console** (Jinja, Arabic + English): scan queue, discovery queue, case page with screenshots and clues, label form (fraudulent / legitimate / inconclusive + behavior tags), link review, alert approval/withdrawal, train button with held-out results, brief export.

**Linking:** registration destination in captured JSON (strong), distinctive asset host (strong), same page template (medium), same payment script (medium), shared common service (weak, never alone). Candidate pair = one strong or two medium signals from different artifacts. Clusters = connected components of reviewer-approved links. Keep a common-service hostname list. A candidate link touching a watched case with a fraud behavior creates a **pending** alert; nothing is sent without reviewer approval.

**Discovery worker** (`app/discovery/`): polls a public certificate transparency source (e.g. crt.sh JSON queries by pattern, or a CertStream feed) every few minutes for newly issued domains matching patterns from reviewed cases and a config file (brand-like word + `vip`/`task`/`order`/`shop`, UAE terms, Arabic transliterations). New matches go into `discovered_domains`, are captured with the normal safe pipeline at a strict rate limit, and High risk or Caution results appear in the reviewer discovery queue. Patterns live in `backend/app/discovery/patterns.yaml`. Never publish or alert on discovery results without review.

**Case brief:** defanged URLs, first/last observed vs site-reported dates, evidence per link with artifact hashes, confidence and review status, static findings as redacted notes, observations vs inferences split. Markdown + JSON.

---

## 5. Our private data and training

1. **Inspect first.** List what's in `data/private/` (file types, counts, folder structure, label columns, languages). Report a short summary to me before writing the importer. Don't print page contents or personal data.
2. **Importer** `backend/ml/import_private.py` converts everything into `data/processed/records.jsonl` with: `id, source, kit_id, lang, label (fraudulent|legitimate|inconclusive), behavior_tags, text (redacted), html_path, hostnames, origin (private|synthetic|reviewed_scan)`.
   - Saved HTML/MHTML/HAR → through the same sanitizer and analyzer used for live scans.
   - URL lists → ask me first; if approved, capture them with the safe pipeline, rate-limited. Live scam URLs that still work are also our real-world evaluation set.
   - Our own scam sites → may be used for training and testing as they are, but any version that goes into `testsites/` must have real brand names and logos replaced with fictional ones.
   - Missing `kit_id` → group by layout fingerprint and shared distinctive hostnames, then show me the proposed groups.
   - Missing labels or behavior tags → mark as unlabeled and list them for me; never guess labels.
3. **Synthetic corpus** (`testsites/generator/`): Arabic and English scam pages across several kits, legitimate recruitment and shopping pages, and ambiguous pages. Fills gaps (especially legitimate look-alikes) and lets judges reproduce training without our private data.
4. **Commands:**
   - `make import` → processed records + a data report (counts by label, language, kit, behavior tag).
   - `make train` → dataset version from private + synthetic + reviewed records; kit-grouped train/test split; trains a candidate; prints precision, recall, false-positive rate on legitimate pages, PR-AUC and per-language results; compares against URL-only and URL+text baselines; promotes only if recall doesn't drop and the false-positive rate doesn't rise vs the current model; saves `backend/models/<version>/` with metrics JSON and dataset hash.
   - `make train-synthetic` → same, synthetic only.
   - `make eval` → re-run evaluation; `make eval-live` → evaluate on approved live URLs and report separately from the test set.
5. Trained model files may be committed (no raw pages). Raw private data may not.

---

## 6. Synthetic test sites (for automated tests only)

Served at `TESTSITE_BASE_URL`; used by `e2e_check.py` and unit tests so anyone can verify the product without live scam sites:
- **Site A** — scam portal (fictional brand): Arabic/English job page, VIP table, recharge page asking AED 500 to unlock tasks, invitation code, wa.me contact; country selector loads a JSON config listing a registration destination on Site B and asset host `cdn.novalogo-assets.test`.
- **Site B** — rebrand: different fictional brand, same asset host, similar form, same deposit flow.
- **Site C** — legitimate look-alike: shares a common analytics/CDN host with A, never asks for money.
- **Listing page** with a fictional agency name linking to Site A (identity mismatch).
- `testsites/static_files/`: authorized files with deliberately fake credentials.

These are never presented as the product's real-world results.

---

## 7. Clients

**Shared (`clients/shared`):** typed API client with configurable base URL (default = hosted API), response types, all ar/en strings, tier → color/icon/headline mapping, device-ID helper.

**Chrome extension (MV3):**
- Popup: "Check this page" (`activeTab`), result card (tier, clues with screenshot thumbnails, what to do, what couldn't be checked, live/stored label), "Watch for updates" toggle, Updates tab.
- Context menu: "Check this link with Hami".
- **Google Search:** content script on `google.com/search` and `google.ae/search` adds a small shield next to each organic result and ad: red/amber from the local high-risk list immediately; if "Check search results" is on, it sends result **hostnames only** to `POST /lookup/hosts`; each shield has "Check now" to run a full scan.
- **Google Maps:** content script on `google.com/maps` reads the open business panel's name and website link and shows a "Check this business website" button that scans the website with `source_type: maps` and the listing name, so identity mismatches are flagged.
- Keep all Google page selectors in one file (`selectors.ts`) with graceful fallback when they break.
- Background worker syncs `/indicators/high-risk-hosts` every 30 min into `chrome.storage.local`; a content script shows a dismissible bilingual banner on matching pages with no server call.
- Opt-in auto-check (off by default) for job/task-scam keyword pages. Badge with unread approved alerts. Options: server URL, language, search-results checks, auto-check — each explaining what is sent.
- Permissions: `activeTab`, `contextMenus`, `storage`, `alarms`, `scripting`; host permissions for the API origin and Google Search/Maps; content-script match for the local banner. Justify each in the README.
- Build to `clients/extension/dist` (Load unpacked) and a zip for sharing.

**Mobile (Expo, iOS + Android):**
- Check screen: URL field, "Paste from clipboard", optional listing name, source picker (Search / Maps / SMS / WhatsApp / Other).
- Share-to-app on iOS and Android via `expo-share-intent` (first URL from shared text). Needs a development or release build, not Expo Go.
- Deep link `hami://check?url=...`.
- Result screen identical to the extension's card; Watch toggle; guidance to report through official police channels.
- Updates screen: polled on foreground + pull-to-refresh (no push in the MVP).
- Settings: server URL, language with full RTL switch (`I18nManager.forceRTL` + reload). Device ID in `expo-secure-store`.
- Android release APK (`eas build -p android --profile preview` or local Gradle) saved to `clients/mobile/dist/hami.apk`.

---

## 8. Running and hosting

- `make run`: local development — install deps and Playwright Chromium if missing, create the DB, start the API (and test sites), ensure a current model exists, print URLs.
- `docker compose up -d`: production-style run of the API + discovery worker using the official Playwright Python image, with a volume for the DB and artifacts.
- **Public HTTPS URL** (pick what's available, document both):
  1. Fastest today: run the container on our laptop and expose it with a Cloudflare quick tunnel (`cloudflared tunnel --url http://localhost:8000`).
  2. Stable: deploy the same image to a small cloud VM with Docker and put Caddy in front for HTTPS.
  Set the resulting URL as the default in `clients/shared` config and `.env.example`.
- `make check`: backend tests, `scripts/e2e_check.py`, TS type-check and lint for shared, extension and mobile.
- `scripts/e2e_check.py` runs against the API (local or hosted) using the synthetic test sites and asserts:
  1. Site A with the listing name → High risk, identity-mismatch clue, hashed artifacts stored.
  2. Site B → proposed link to A; reviewer approves; a watcher of A gets the alert; a non-watcher doesn't.
  3. Approve B for training; retrain → new dataset + model version; metrics printed; promotion rule applied.
  4. Site C → common service recorded, not High risk, no alert.
- `scripts/capture_screens.py` (or part of make_docs): takes screenshots of the real clients (extension popup, Search shields, Maps check, Android screens) for the docs and deck, using fictional-brand test sites for anything committed.

### Acceptance checks

| Feature | Done when |
|---|---|
| Scan a URL | A real public URL returns tier, clues and hashed artifacts in under about 20 s through the hosted API. |
| Warnings on clients | A known scam URL shows High risk and a legitimate one doesn't, in Arabic (RTL) and English, in the extension and the installed Android APK (and iOS if buildable), from any network. |
| Share to app | Sharing a link from WhatsApp or the browser opens the result flow. |
| Search and Maps | Google Search results show shields; a Maps business website check flags a listing-name mismatch. |
| Discovery | A newly issued matching domain from CT logs appears in the reviewer queue with a tier. |
| Training on our data | `make train` uses private + synthetic data, prints metrics, versions and promotes correctly. |
| Evidence and review | A corrected label keeps the earlier decision visible. |
| Opt-in alert | Watcher sees the approved update with its reason; non-watcher doesn't; withdrawn shows as withdrawn. |
| Linking and brief | A rebrand joins its cluster, a legitimate site sharing services stays out, the brief exports with hashes and the observation/inference split. |
| Extension local list | After a site is reviewed High risk and the list syncs, opening it shows the banner with no server call. |
| Static check | The brief shows the finding's category and location, never the value. |
| Inconclusive cases | Neither train the model nor trigger alerts. |

---

## 9. Presenting the MVP

Write `docs/WALKTHROUGH.md`: a six-minute run on **real links** — (1) share a real suspicious job link from WhatsApp to the Android app; (2) Google Search shields and a Maps business check in Chrome; (3) a domain found by the discovery worker linked to a reviewed case, reviewer approval, update on the watcher's phone; (4) approve for training, retrain, show metrics, then a legitimate site sharing a common service not flagged. Include what to do if a scam site has gone offline (open the stored capture; the screen labels it).

---

## 10. Submission documents (required)

- **README.md** with exactly the three required parts, plus: what Hami is and that it's a working MVP; quick start (`make run`, `docker compose up`); the hosted API URL; how to install the extension and the Android APK; how to build iOS; how to train (`make import && make train`, or `make train-synthetic`); extension permission justification; privacy design; the acceptance table with which checks pass; known limitations. Team names from `docs/team.txt` if it exists.
- **docs/TECHNICAL.md**: architecture (diagram from the proposal), components, data flow, data model, scoring rules, model choices (why logistic regression + rules, features, Arabic handling, calibration, kit-grouped evaluation, promotion rule, real metrics from the last `make train` and `make eval-live`), discovery worker, privacy design, capture security, limitations, roadmap.
- **docs/Hami.pptx** generated by `scripts/make_docs.py` with python-pptx, 10–12 slides: title (Hami حامي, team), the problem in the UAE (figures from the proposal with sources), the task scam, product overview, architecture, how a scan works, Search/Maps/discovery, model choices + real metrics, privacy design, the clients with real screenshots, investigator view, what works vs roadmap, team. Clean layout; Arabic right-to-left.

---

## 11. How to work

1. Read the proposal and inspect `data/private/`. Post a short plan and the data summary, then continue unless something conflicts with this prompt.
2. Follow the P0 → P1 → P2 order. After each item: run its tests, fix failures, commit with a clear message, and give me a short labeled summary of what changed and what's verified.
3. If you're blocked on something only I can do (Android device/emulator, Xcode, Cloudflare/VM access, approving URL captures, confirming kit groups or labels), tell me exactly what to do and continue with other work meanwhile.
4. At the end, list what works, what's untested and what was cut. Never claim something works without having run it.
