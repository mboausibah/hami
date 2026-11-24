# Hami: technical documentation

This document explains how Hami works and why it is built this way:
- architecture and data flow;
- data model;
- scoring and model choices;
- kit fingerprinting and delivered-code reading;
- the extension's automatic checks, idle snapshots and investigator mode;
- the discovery worker;
- privacy and capture security;
- evaluation, limitations and roadmap.

Module-level details: [architecture.md](architecture.md). Deployment: [DEPLOY.md](DEPLOY.md).

## 1. Architecture

```
                      ┌──────────────────────── Chrome extension (MV3) ────────────────────────┐
                      │ on-device pre-filter · local lists · consent · badge · High-risk banner │
                      │ popup / right-click · Search shields · Maps check · idle snapshot ·     │
                      │ investigator mode (optional permissions)                                │
                      └───────────────┬─────────────────────────────────────────────────────────┘
       URL / hostnames / snapshot     │ HTTPS or localhost
       metadata / opt-in evidence     ▼
┌──────────────────────────────────────────────── Hami API (FastAPI) ─────────────────────────────────────────────┐
│ 1 CAPTURE    Playwright Chromium, fresh context, ≤20 s, ≤150 requests, ≤1.5 MB per body; a few public actions │
│              (dismiss pop-up, language switch, country selector); never signs in, submits, pays or downloads │
│ 2 SANITIZE   cookies, credential headers, token params, request bodies, WebSocket messages, sensitive JSON    │
│              keys, e-mails, phones removed; every body SHA-256 hashed before anything is dropped             │
│ 3 STORE      content-addressed artifacts (HAR, HTML, screenshots, action log) + rows in the database          │
│ 4 ANALYZE    visible page (Arabic/English) · delivered code · delivered files (kit) · hostnames · identity    │
│ 5 SCORE      rules decide the tier, calibrated logistic regression confirms; clues in Arabic and English      │
│ 6 USE        warning · evidence log · linking + case brief · training data (after review)                     │
└──────┬───────────────────────────────┬────────────────────────────────┬─────────────────────────────────────────┘
       │                               │                                │
 Reviewer console (/review)     Discovery worker (CT logs)      Training pipeline (ml/)
 labels, links, alerts,         new look-alike domains →         dataset version → candidate →
 clusters, briefs, training     safe capture → review queue      kit-grouped CV → promotion rule
```

Capture is the only stage that touches the scam site. Everything after it works on sanitized, hashed copies, so
the analysis is repeatable and a reviewer sees exactly what the model saw. Stored captures stay usable after the
site disappears; results always say whether they come from a live or a stored capture.

**Deployment shape.** In this submission the API runs on the user's own computer (`docker compose up` or
`python tasks.py run`) and the extension talks to `localhost:8000`. The same stack runs on a server with PostgreSQL
and Caddy HTTPS (`docker compose --profile postgres --profile https up`). Data access goes through SQLAlchemy
(`DATABASE_URL`), and artifacts through a small `ArtifactStore` interface (local now, S3-compatible later).

## 2. Data model

Observations and inferences live in separate tables, so a correction never rewrites what was seen.

| Table | Purpose |
|---|---|
| `scans` | One capture or import: URL, host, source (search, maps, extension, discovery, …), listing name, status, live/stored, batch |
| `artifacts` | Sanitized HAR, HTML per step, screenshots, action log, analysis record. Each has a SHA-256 and a content-addressed key |
| `observations` | What was seen (immutable): indicator type, strength, redacted excerpt, host reference and relation (referenced / observed), source (visible page, delivered code, …), capture step |
| `assessments` | Inferences: tier, page score, code score, rules fired, clues, model version |
| `reviews` | Append-only labels (fraudulent / legitimate / inconclusive), behavior tags, scam type, `supersedes`, training eligibility |
| `asset_files` | Every delivered JS/CSS/font/image: SHA-256, file name, build-chunk name, size, shingle sketch |
| `links` | Proposed relationships between sites with evidence observations, strength and review status |
| `watches`, `alerts` | Opt-in watches (random device ID) and reviewer-approved alerts (approved / withdrawn) |
| `discovered_domains` | Certificate-transparency candidates and their capture status |
| `snapshots`, `evidence_files` | Idle snapshots and investigator-mode uploads (device and server SHA-256) |
| `static_findings` | Suspected secrets in authorized files: category and location only, never the value |
| `dataset_versions`, `model_versions` | Training snapshots (hash) and model versions (metrics, status) |

Reviews and observations are protected by database triggers against UPDATE/DELETE, on both SQLite and PostgreSQL.

## 3. Risk tiers and scoring rules

The result is a tier, not a raw probability, because people act on a clear instruction.

| Tier | Assigned when (any) |
|---|---|
| **High risk** | Invite-gated registration or a separate security/fund password, plus one of: first certificate under 30 days, task-scam route vocabulary in the site's own pages/code, brand-bait logos, a kit match (section 7). Exact host reviewed fraudulent. Same registrable domain as a reviewed fraudulent site. Strong fraud behavior and classifier agrees. Approved/strong link to a reviewed case and a fraud behavior. Sign-in wall or thin page and same kit as a reviewed case. Sign-in wall or thin page, fraud behavior in delivered code and classifier agrees on the code. |
| **Caution** | Two or more registration, route or domain signals; a registration/login wall with a scam signal. Fraud behavior without classifier agreement. Partial kit or infrastructure match. Fraud behavior in delivered code (thin page, or classifier agrees). Listing-identity mismatch. Classifier above the caution threshold. |
| **Insufficient evidence** | Page failed, too thin, a bot-challenge page instead of the site, a registration/login wall with nothing else, or a sign-in wall with no usable delivered code (< 40 words) and no match. Never reported as "safe". |
| **No strong signals** | Otherwise, with the explicit note that this is not a guarantee. |

Every tier comes with plain-language clues, up to three on the card. Each clue cites the sentence, file or reviewed
case behind it (e.g. "This site runs the same software as aed99.com, a confirmed scam (26 identical files).").
Weak signals never raise the tier on their own: common analytics, CDN, hosting and payment providers.

**Listing identity.** When a Search or Maps listing name is supplied, it is compared with the names the site
claims (title, header, footer, `og:site_name`). The comparison runs after Arabic normalization, using RapidFuzz
token matching. A mismatch is at least Caution and is shown as its own clue.

## 4. Model choices

- **Model.** Logistic regression, calibrated (sigmoid), on:
  - TF-IDF word 1–2 grams (40k features) and character 3–5 grams (`char_wb`, 80k features) from redacted visible text, with hostnames removed;
  - structured indicators: deposit/recharge requests, currency amounts, VIP/level tables, commission rates, invitation codes, withdrawal conditions, card/OTP/password fields, messaging-app contact links, delivered-code mention counts.
- **Why.** It trains in seconds, runs on a laptop and is inspectable: the console lists the top-weighted phrases for each case. It handles mixed Arabic/English and Arabizi through character n-grams. Exact hostnames and templates live in the rules and kit layers, so the model learns behaviors rather than memorizing domains.
- **Arabic handling.** Alef variants unified, tatweel and diacritics removed, Arabic-Indic digits mapped. Patterns are compiled through the same letter table. Amounts in `٥٠٠ درهم` and `AED 500` produce the same feature.
- **Two views per page.** A "page" record (visible text) and a "code" record (strings from the site's own JS) are scored separately: `score` and `code_score`.
- **Kit-grouped evaluation.** All variants of one kit stay in one split (stable hash on the kit ID). 5-fold kit-grouped CV runs on the training split, and thresholds are tuned on out-of-fold scores: *agree* at ≤2% FPR (0.770), *caution* at ≤5% FPR (0.555).
- **Promotion rule.** A candidate replaces the current model only if, on the same held-out set, recall does not drop and the false-positive rate does not rise. A reviewer can override with a recorded reason (`python tasks.py promote`). Every model stores its dataset hash, feature settings and metrics.

### Training data

| Source | Records | Notes |
|---|---|---|
| Team's private labels and captures | labeled scam URLs, legitimate captures (homepage + up to 3 nav pages) | never committed |
| Team's browser sessions (HTTP Toolkit) | split by page host into kits | strict sanitizer, tokens never replayed |
| Phishing Website Dataset (CC BY 4.0) | balanced 1,000 + 1,000 pages | visible text |
| Online Shops Dataset (CC BY 4.0), Tranco | URL-only rows | URL baseline only |
| Synthetic corpus (fictional brands) | Arabic + English scams and legitimate look-alikes | fills gaps |

### Metrics of the live model `m20261122-172703-full`

| Evaluation | n | Precision | Recall | FPR (legit) | PR-AUC |
|---|---|---|---|---|---|
| Held-out (457 kits) | 684 | 0.971 | 0.831 | 0.022 | 0.968 |
| Held-out, Arabic pages | 57 | 1.000 | 0.739 | 0.000 | 1.000 |
| Held-out, English pages | 602 | 0.967 | 0.830 | 0.025 | 0.967 |
| 5-fold kit-grouped CV (1,860 kits) | 2,478 | 0.970 | 0.840 | 0.023 | 0.973 |
| CV, Arabic pages | 132 | 1.000 | 0.885 | 0.000 | 1.000 |

Baselines on the same test pages with a URL (n = 556):

| Variant | Precision | Recall | FPR |
|---|---|---|---|
| URL only | 0.862 | 0.656 | 0.084 |
| URL + page text | 0.974 | 0.749 | 0.016 |
| Full detector | 0.962 | 0.830 | 0.026 |

Recall per scam type (CV): task scam 0.91 (66), phishing 0.83 (1,012), gambling deposit 0.71 (17), fake shop 1.00
(12), investment 1.00 (12), other 1.00 (30).

System-level checks beyond the model:
- **Unseen legitimate pages** (`python tasks.py eval-holdout`). 50 UAE job boards, shops, gig and micro-task platforms not in training: 0 High, 0 Caution. The 95% upper bound is about 6%.
- **Tier check.** On 111 legitimate pages: 0 false alarms from rules, delivered code or kits. All 11 pages of the confirmed aed99 family were High.
- **Honest weakness.** The text model alone has recall 0 on the small set of real sign-in-wall pages from the team's sessions. Those are caught by kit matching and domain inheritance, which is the reason they exist.

## 5. Sign-in walls: kit fingerprinting

Scam operators reuse one web app (a "kit") across many brands. The login page hides the scam, but the browser
still downloads the app's files. Hami records every delivered file (`asset_files`) and matches them three ways:

1. **Identical file:** same SHA-256. Hashes are computed by the sanitizer before bodies are dropped.
2. **Same build name:** Vite/webpack content-hashed names (`en-US-DpCkNiEF.js`, `views-vipNew-B1bbRpqk.js`) are fingerprints too.
3. **Near-identical:** bottom-k (128) MinHash sketches of 8-token shingles, similarity ≥ 0.8 within the same build chunk.

**Distinctiveness.** These files are ignored:
- common libraries and frameworks (`common_assets.yaml`);
- files from common-service hosts;
- files seen on any legitimate capture or on 6+ unrelated sites;
- files under 512 B;
- JSON.

A **strong** match needs ≥ 3 distinctive files including an app-specific chunk or a language pack. Fewer files give
a partial match, which can only produce Caution.

**Infrastructure.** Shared API/CDN/support/payment hosts count as a strong signal. The same API naming scheme on
different brand domains counts as medium: for example `h5server.*api.com`, as in `h5server.betnalaapi.com`.

**Registrable-domain inheritance.** A subdomain of a reviewer-confirmed domain inherits it, using the Public Suffix
List with private suffixes. Shared platforms such as `*.github.io` and cloud-storage buckets are not merged.

**Seed indicators.** A fresh install has no reviewed cases, so `data/seed/indicators.json` ships the team's
confirmed cases. It holds only domains, hostnames, kit IDs, distinctive file hashes, names and sketches,
infrastructure hosts, labels and dates. It is loaded on first start and marked "seeded from team review".
Verified live on a fresh install:
- betnala.com: High, 26 identical files with aed99.com.
- betfugu.com: High, 13 identical files.
- cs.aed99.com: High through the domain.

## 6. Delivered-code reading

The visible page of a sign-in wall says almost nothing, but the site's own JavaScript describes the app behind
it. The aed99 English language pack mentions "deposit" 16 times and "withdraw" 38 times. Hami extracts string
literals from the site's own JS (vendor chunks and common libraries skipped) and treats them as a separate
**delivered code** source:

- **Mention groups** (deposits, withdrawals, VIP levels, tasks, invitations, commissions, betting, returns, bonuses…) are counted, with combinations required before a behavior is inferred:
  - deposits ≥ 3 and betting ≥ 3 → gambling deposit;
  - deposits ≥ 3 and (tasks ≥ 3, or VIP ≥ 3 with tasks ≥ 2 or invitations ≥ 3) → deposit to unlock;
  - deposits ≥ 2 and guaranteed/daily returns ≥ 2 → investment promise.
- Code behaviors never include credential requests or advance fees. Payment gateways legitimately contain card/OTP and fee wording.
- The classifier also scores the code text (`code_score`) when it has ≥ 40 words.
- Clue: "The site's own code (not the visible page) mentions deposits (51×), withdrawals (34×), bonuses (26×) and invitation codes (23×)."

## 7. Registration walls, referenced routes and bot challenges (unseen families)

A real miss shaped this part. An unseen task-scam registration page was rated "No strong signals" because Hami's
server never saw it: the site answered the capture browser with a Cloudflare bot challenge (403, "Just a
moment…"), and the challenge page itself was analyzed. Hami does not try to get past bot checks. Instead it now:

- **Recognizes challenge pages** (text and challenge-platform traffic). A challenge is never "No strong signals". It is Insufficient evidence at most on its own, and the challenge's own scripts and links never count as the site's code, kit files or identity.
- **Uses the page the user's browser shows.** With "Check this page" and with consented automatic checks, the extension sends the page's structure, computed on the device from the HTML and inline scripts:
  - same-site paths without queries;
  - image file names;
  - form-field descriptors without values;
  - redacted title and visible text.

  The server checks that this belongs to the same site, stores it as evidence (`browser_page_signals`), and never serves that result from the cache to anyone else.
- **Reads referenced routes** from the HTML, JS and JSON the site already delivered (no navigation, no API calls), and from the page structure above. Route words are grouped: recharge/deposit, withdraw, task orders (`rot_order`, grab, `submit_order`…), bind-bank, invite, VIP, crypto (usdt, trc20, pay/bit), security password (`pwd2`, paypwd…) and wealth products. The levels:
  - **task:** money-in routes plus task-order routes plus at least 3 groups;
  - **money:** recharge plus at least 3 groups.

  A telecom's "recharge" page or a micro-task platform's tasks/withdraw/invite routes alone never qualify.
- **Fetches lazy chunks.** The capture also fetches same-origin `.js`/`.json` chunks referenced by already-loaded bundles: no HTML, no API/auth/pay paths, at most 30 files / 10 MB, 0.15 s apart. Those bodies feed route reading, delivered-code reading and kit fingerprints.
- **Analyzes the registration wall:**
  - invite-gated registration (code in the address, or a required or pre-filled invitation field);
  - a separate security/fund/withdrawal password or PIN (Arabic and English);
  - phone-only sign-up with a default country code;
  - no company identity (no terms, privacy, address or contact);
  - known scam registration routes (`/index/user/register/invite_code/`, `#/pages/register`);
  - uni-app/H5 shells.

  A wall is a page that is mostly a sign-up/login form (under 300 words), so a homepage with a login box is not a wall.
- **Spots brand bait:** marketplace logos (alibaba, amazon, shein, noon…) as image names on a site that is not them.
- **Checks the domain:** random-looking label, abused TLD (.xyz, .top, .shop, .vip, .cc…), and the age of the first certificate from certificate transparency (Cert Spotter, crt.sh fallback; cached; at least 2 s between queries). Under 30 days is strong, under 90 medium. The clue says "first certificate", not registration date.

**Rules.**
- **High:** invite gate or security password, plus one of: first certificate under 30 days, task route vocabulary, brand-bait logos, kit match.
- **Caution:** two or more registration/route/domain signals, or a wall with a scam signal.
- **Insufficient evidence:** a wall or challenge with nothing else.
- A referral code on an established site with company identity cannot reach High on its own.

**Linking evidence from the same pages:**
- **Redirect / invitation gateway** (strong). The capture started on domain X and the scored page is on Y (HTTP redirect, meta-refresh or script redirect), and the landing page is a wall, shows scam signals or carries the same invite code. X is linked to Y. The shared invite code is named in the evidence, both domains become review candidates, and the discovery worker watches new certificates under both.
- **Registration-page template** (medium, proposes a link on its own). Distinctive wording (UI boilerplate and the site's own brand removed) plus form structure, stored as feature hashes. Sharing it with another site is template reuse, not common ownership. Templates shared by more than 6 unrelated sites are generic and never link.

## 8. Automatic checking, idle snapshots and investigator mode

**On-device pre-filter** (`prefilter.ts`). No network is involved. Every page is classified as:
- *skip*: sensitive categories (banks, government, health, mail…) and the Tranco top 10,000 + allowlist;
- *high risk*: on the local list of confirmed hosts and domains, which shows the banner with no server call;
- *candidate*: every other site. Recent CT domains and kit file names among the page's resources are recorded as extra reasons.

**Automatic checking.** Only after one-time bilingual consent and only for candidates. The URL and the page structure (section 7) are sent. The
device allows at most 30 checks per hour and checks each host at most once per 6 hours. The tab badge shows the
tier (`!` / `?` / `✓`), and the full-page banner appears only for High.

**Idle snapshot.** After 10 s without activity on a candidate page, once per page load, the content script
collects:
- resource URLs with query strings and fragments stripped;
- types, status codes, timings and sizes;
- redacted visible text.

It never collects cookies, headers, bodies or storage. The server fetches the public JS/CSS itself without
cookies, builds a HAR-format artifact marked as metadata from the user's browser, and runs kit matching.

**Investigator mode.** It is off by default and needs the optional `debugger` + `downloads` permissions. Chrome
shows its "being debugged" bar while it records. The flow:
1. A full HAR is recorded via `chrome.debugger`.
2. It is sanitized on the device by the importer's strict rules.
3. It is SHA-256 hashed with Web Crypto and downloaded as `.har`.
4. Only if the user agrees, it is uploaded to `POST /evidence`. The server verifies the device hash against the exact bytes received, re-sanitizes, and stores both hashes.

It never runs on sites the pre-filter skips.

## 9. Discovery worker

The worker polls public certificate-transparency sources for newly issued certificates:
- crt.sh pattern queries;
- SSLMate Cert Spotter for the registrable domains of confirmed cases;
- CertStream when reachable.

It keeps only certificates from the last 7 days. Names are matched against generic patterns (task/VIP/order
keywords, UAE references, brand-like labels derived at runtime from reviewer-confirmed hosts; no brand list in the
repository). Matches are captured with the same safe pipeline, rate-limited: 20 s between queries, 30 s between
captures, at most 5 captures per cycle, one cycle every 10 minutes. High-risk results go to the reviewer queue.
Nothing is published or alerted without review.

## 10. Linking, alerts and the case brief

Pairs of sites become link candidates with one strong signal (same kit, shared distinctive infrastructure,
registration destination in captured JSON, distinctive asset host) or two medium signals from different artifacts.
There is at most one open link per pair. Reviewers approve or reject; clusters are the connected groups of approved
links. Watchers of a case get an update only after a reviewer approves the alert, and withdrawals are shown as
withdrawn.

The case brief (Markdown/JSON) lists:
- the defanged URLs;
- first and last observed times, kept separate from site-reported dates;
- the evidence behind each link, with artifact hashes;
- confidence and review status;
- redacted static findings;
- a clear split between direct observations and inferences.

Every link is labeled as a lead, not proof of common ownership.

## 11. Privacy design and capture security

The full privacy design is in the README. In summary:
- Decisions about what to check are made on the device.
- Only the least that answers the question is sent, only to the configured Hami backend.
- No browsing history or search queries are ever sent.
- Watches use a random device ID, and there are no accounts.

Capture security:
- A fresh browser context per scan, with time, request and size caps.
- Only predefined public actions: dismiss pop-up, language, country selector.
- No sign-in, form submission, payment, download or following discovered links.
- `CAPTURE_ALLOW_HOSTS` limits local hosts, and private network targets are refused.
- The capture browser runs as a non-root user inside the container.

Data handling:
- Private datasets stay in `data/private` (never committed).
- Imported sessions are strictly sanitized. Domains referenced inside HAR files are review candidates only.
- The static check never stores or prints secret values.
- A deployed version would be reviewed against the UAE Personal Data Protection Law (Federal Decree-Law No. 45 of 2021) and police evidence-handling rules.

## 12. Limitations

- Chrome extension + local server only. iOS/Android apps and a hosted service are roadmap. Reviewer decisions are not shared between installs, apart from the seed file.
- An unknown kit behind a sign-in wall usually gets Caution, not High, until one site of the family is confirmed.
- Cloaking (clean content for automated browsers, geo-blocking) gives Insufficient evidence.
- Text inside images is not read (no OCR).
- Small samples for some scam types. Metrics are prototype results on our data, not open-internet accuracy.
- The S3-compatible artifact store is designed but not implemented.
- The Tranco-based skip list is for non-commercial use.

## 13. Roadmap

1. **Phones.** iOS and Android apps (one Expo codebase) with share-to-app from WhatsApp, Messages and browsers, deep links and the same bilingual card.
2. **Hosted service.** A UAE North deployment (DEPLOY.md) with shared reviewer decisions, role-based access, retention controls and push alerts.
3. **Coverage.** Screenshot OCR, more labeled kits (gambling, investment, parcel), Arabic legitimate look-alikes.
4. **Police integration.** Intake from reporting channels such as Aman, export of indicators in STIX, campaign briefs for investigators.
