# Hami حامي

Hami checks links people meet on Google Search, Maps, WhatsApp and SMS. It tells them in Arabic or English
whether a link is high risk, and why. It is a working MVP:
- a FastAPI backend that captures real public pages in a sandboxed browser, analyzes them and scores them
- a reviewer console
- a certificate-transparency discovery worker
- a Chrome extension

The mobile app is the next phase. Architecture details: [docs/architecture.md](docs/architecture.md).

## Build and run

```bash
cp .env.example .env              # set HAMI_REVIEWER_TOKEN
make run                          # API + reviewer console on http://localhost:8000 (/review), synthetic test sites
docker compose up -d --build      # production-style: API + discovery worker, one data volume
make extension                    # Chrome extension -> clients/extension/dist (Load unpacked) + zip
make check                        # backend tests, e2e checks, extension type-check/lint/build, extension checks in Chromium
```

- **Training.** Run `make import && make train` (private + sessions + public + synthetic data; needs `data/private/`) or `make train-synthetic` (no private data).
- **Promotion.** The promotion rule is applied automatically. A reviewer can override it with `make promote VERSION=… REASON="…"`, and the override is recorded.
- **Database.** SQLite by default. Hosted Postgres is a config change: `DATABASE_URL=postgresql+psycopg://…`. Artifacts go to a local content-addressed store selected by `STORAGE_URL`. See architecture.md.
- **Hosting.** No hosted URL yet. Plan: Cloudflare quick tunnel or a small VM behind Caddy, then set the URL in `clients/shared` and `.env.example`.

## Privacy design

Principles:
- Hami protects people without watching them.
- The extension decides on the device what is worth checking.
- It sends the least that can answer the question, and only to the configured Hami backend.

**On the device, nothing is sent:**
- Local lists sync every 30 minutes: reviewer-confirmed hosts and registrable domains, recent CT domains, kit file names.
- A pre-filter classifies every page locally:
  - sensitive categories (banks, government, health, e-mail, …) are skipped;
  - well-known sites (Tranco top 10,000 + allowlist) are skipped;
  - pages matching the local lists or kit file names become candidates.
- Confirmed sites show a red banner from the local list with no server call.

**Automatic checking (needs one-time consent):**
- A bilingual consent screen opens on install. Until the user agrees, nothing is checked automatically. It can be turned off in Options at any time.
- Only candidate pages are checked, and only their URL is sent: at most 30 per hour, each host at most once every 6 hours.
- Every checked tab gets a colored toolbar badge. A full-page banner appears only for High risk.

**Idle snapshot (consent + Options toggle):**
- Taken after 10 seconds without activity on a candidate page, at most once per page load. Rate-limited per device on the server.
- The device sends metadata only: resource URLs with query strings and fragments removed, types, status codes, timings, sizes, and visible text with e-mails and phone numbers redacted.
- Never sent: cookies, headers, request or response bodies, local storage.
- The backend fetches the public JS/CSS itself without cookies, then stores a HAR-format artifact marked as metadata from the user's browser.

**Investigator mode (off by default, for reviewers):**
- Records a full HAR through `chrome.debugger`. Chrome shows its "being debugged" bar while it records; Options explains this before it is turned on.
- The HAR is sanitized on the device by the same rules as the importer's strict mode:
  - removed: cookies, credential-like headers (checked by name and value), token-like query parameters, request bodies, WebSocket messages, sensitive JSON keys, e-mails, phone numbers;
  - authenticated non-static bodies are dropped.
- It is saved as a `.har` download after 10 seconds idle or on "Save evidence".
- It is uploaded only if "upload evidence" is also enabled. The server re-hashes the exact bytes, checks them against the device's SHA-256, sanitizes again, and stores both hashes.
- It never runs on sites the pre-filter skips.

**Other client data:**
- Search shields send result hostnames only, and only if enabled. No search queries and no browsing history are ever sent.
- Watches use a random device UUID. There are no accounts.

**Capture security:**
- The capture browser never signs in, submits forms, pays, downloads files, or follows discovered links.
- Discovery is rate-limited. Discovered domains are review candidates and are never labeled fraudulent without a reviewer.

**Stored data:**
- Every artifact is sanitized, SHA-256 hashed and immutable.
- Reviews are append-only; a correction supersedes the earlier decision and keeps it visible.
- Observations are separated from inferences in the case brief.
- The static check stores the category and location of a suspected secret, never its value.

**Private data:**
- `data/private` and `data/processed` are never committed.
- Imported browsing sessions go through the strict sanitizer. Tokens are never replayed.
- Test sites use fictional brands only.

## Extension permissions

| Permission | Why |
|---|---|
| `activeTab` | "Check this page" reads the URL of the tab the user clicked on. |
| `contextMenus` | "Check this link with Hami" on right-click. |
| `storage` | Settings, consent, local high-risk lists, device UUID. |
| `alarms` | Syncs the local lists every 30 minutes. |
| `scripting` | Shows the banner or result in the page the user asked about. |
| `webRequest` | Keeps a per-tab, in-memory list of resource URLs, types, status codes and timings for the idle snapshot. Only while automatic checking and snapshots are on. Never headers, cookies or bodies. |
| `http://*/*`, `https://*/*` | The on-device pre-filter and local banner must run on any page. Kit file names are matched against the page's resource names. Automatic checking works on sites nobody has reported yet. |
| Google Search / Maps content scripts | Search result shields and the Maps "Check this business website" button. |
| `debugger`, `downloads` (optional) | Requested only when investigator mode is turned on: full HAR recording and saving it as a `.har` file. |

## Acceptance checks

Results from `make check` (backend tests, `scripts/e2e_check.py`, `scripts/extension_check.py` in real Chromium) and
from runs on real data.

| Feature | Status | How it was verified |
|---|---|---|
| Scan a URL | Partial | Real public URLs return tier, clues and hashed artifacts locally and from the Docker container. No hosted API URL yet. |
| Warnings on clients | Partial | Extension: High risk on the confirmed site, no warning on a legitimate one, Arabic RTL + English. The Android/iOS app is not built yet. |
| Share to app | Not built | Mobile app (next phase). |
| Search and Maps | Pass | Shields on every result (red from the local list, hostname lookup for others). The Maps check flags a listing-name mismatch. |
| Discovery | Pass | A live run against Cert Spotter queued a newly issued matching certificate. The reviewer queue shows tiers. |
| Training on our data | Pass | `make train` on private + sessions + public + synthetic data. Kit-grouped CV, versioned dataset and model, promotion rule applied. |
| Evidence and review | Pass | Reviews are append-only with `supersedes`, enforced by database triggers on SQLite and Postgres. |
| Opt-in alert | Pass | A watcher gets the approved update with its reason, a non-watcher doesn't, withdrawn shows as withdrawn. |
| Linking and brief | Pass | The rebrand (Site B) joins Site A's cluster. A legitimate site sharing services (Site C) stays out, with no same-kit link. The brief exports with hashes and the observation/inference split. |
| Extension local list | Pass | After review and sync, the banner shows with no server call from the page. |
| Static check | Pass | The brief shows category and location, never the value. |
| Inconclusive cases | Pass | They never train the model or trigger alerts. |
| Sign-in wall, same kit | Pass | Site D (login wall) is High via a same-kit match with confirmed Site A (≥3 identical files incl. a language pack), with a plain-language clue. A private regression links a real rebrand to its confirmed family through 57–63 identical files. |
| Registrable-domain inheritance | Pass | A support subdomain of a confirmed site is High (private regression). The PSL with private suffixes keeps shared hosting tenants apart. |
| Common libraries never match | Pass | A legitimate site with common libraries gets no kit match. The tier check on 111 legitimate pages gave 0 false alarms from rules, delivered code or kits. |
| Delivered code | Pass | The site's own JS strings are a separate source, with mention thresholds and their own clue. Payment gateways produce no code behaviors. |
| Automatic checking | Pass | Consent screen on install. Off before consent. A bank is skipped with nothing sent. A candidate gets a badge without a click. A banner appears only for High. |
| Idle snapshot | Pass | Sent after 10 s idle. Stored as a metadata HAR artifact with SHA-256. Kit match with Site A. No query strings, cookies or e-mails stored. |
| Investigator mode | Pass | Refused on a bank. Auto-saved after 10 s idle. The downloaded `.har` contains none of the planted cookie or token values. The file's SHA-256 matches the reported hash, and the upload is verified server-side. |
| Postgres via config | Pass | 68 backend tests and 29 e2e checks pass on PostgreSQL 16 with only `DATABASE_URL` changed. |

## Data sources and licenses

Public datasets are downloaded locally and never committed.

| Dataset | License | Citation | Use |
|---|---|---|---|
| Fraudulent and Legitimate Online Shops Dataset (1,140 URLs) | CC BY 4.0 | Janaviciute, A., Liutkevicius, A. (2023). Mendeley Data, V1, doi:10.17632/m7xtkx7g5m.1 | URL-only records for the URL baseline. The shops are not captured. |
| Phishing Website Dataset (10,395 sites) | CC BY 4.0 | Putra, I. K. A. A. (2023). Zenodo, doi:10.5281/zenodo.8041387 | Balanced sample of 1,000 phishing + 1,000 legitimate pages with ≥25 words of visible text. |
| Tranco top sites list | No license stated by Tranco. Upstream: CrUX (CC BY-SA 4.0), Cloudflare Radar (CC BY-NC 4.0), Majestic (CC BY 3.0), Cisco Umbrella. **Non-commercial use only.** | Le Pochat, V. et al. (2019). Tranco: A Research-Oriented Top Sites Ranking Hardened Against Manipulation. NDSS 2019. https://tranco-list.eu | Legitimate domains for the URL baseline (top 2,000). The extension's on-device skip list (top 10,000). Rank is not proof of safety. |

PhishTank was not used because it requires an application key. Private data (labeled URLs, legitimate captures and
the team's own browsing sessions) stays in `data/private/`.

## Known limitations

- No hosted API URL yet. The mobile app is not built.
- The current model is the synthetic one, because the promotion rule (recall not lower and FPR not higher) keeps it. The model trained on real data has much higher recall but a slightly higher FPR, so promoting it is a reviewer decision (`make promote`).
- Kit matching needs at least one reviewer-confirmed site in the family. An entirely new kit behind a sign-in wall can reach Caution from delivered code but not High.
- `STORAGE_URL=s3://…` is designed (`ArtifactStore`) but not implemented. There is no tool yet to move existing SQLite data into Postgres.
- The Tranco-based skip list is for non-commercial use.
