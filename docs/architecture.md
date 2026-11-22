# Hami architecture

Hami has three parts: the backend (FastAPI), the clients (a Chrome extension today, mobile later) and the reviewer
console. A link is captured in an isolated browser, analyzed, and scored by rules plus a small classifier. A
reviewer confirms cases. Confirmed cases protect everyone else through kit fingerprints, domain inheritance,
links between sites and on-device lists.

```
 Chrome extension ──(URL, hostnames, snapshot metadata, opt-in evidence)──►  FastAPI  ──► capture (Playwright, sandboxed)
   on-device pre-filter, local lists, badge, banner                          │            sanitize (HAR, HTML)
                                                                             │            analyze (visible page + delivered code)
 Reviewer console (/review, token) ◄──────────────── cases, links, brief ──── │            kit fingerprints + infrastructure
                                                                             │            scoring (rules + calibrated LR)
 Discovery worker (CT logs, rate-limited) ──► queued domains ──────────────► │            linking / alerts
                                                                             ▼
                                                     Database (DATABASE_URL)   Artifact store (STORAGE_URL)
```

## Backend modules (backend/app)

| Module | Role |
|---|---|
| `api/routes.py` | Public API: `POST /scans`, `GET /scans/{id}`, `GET /artifacts/{id}` (capability key), `POST /lookup/hosts`, watches and alerts, `GET /indicators/high-risk-hosts`, `GET /indicators/local-lists`, `POST /snapshots`, `POST /evidence`, `GET /health`. Rate-limited per device and IP. |
| `capture/` | Playwright Chromium. Opens the page, takes screenshots at each step, enables the accessibility tree of Flutter apps, dismisses pop-ups and switches language or country. It never signs in, submits forms, pays, downloads or follows discovered links. |
| `sanitize/` | HAR/HTML sanitizer. Removes cookies, credential-like headers (checked by name and by value), token-like query parameters, request bodies, WebSocket messages, sensitive JSON keys, e-mails and phone numbers. Bodies are hashed (`_hami_sha256`) before they are dropped. Strict mode (used for imported sessions and evidence) also drops non-static bodies of authenticated requests. |
| `analyze/` | Visible-page analysis: Arabic/English normalization, behaviors (deposit-to-unlock, advance fee, credential request, gambling deposit, investment promise, parcel fee…), identity check against the listing name. A separate pass reads the site's own delivered JavaScript strings (the "delivered code" source); vendor and common files are skipped. |
| `analyze/assets.py`, `linking/kit.py` | Kit fingerprinting from delivered files: SHA-256, content-hashed build names (Vite/webpack), near-identical similarity (bottom-k shingle sketches) and distinctiveness filters. Libraries, analytics, common services, files seen on legitimate captures or on 6+ sites, and files under 512 B are ignored. A match is strong at ≥3 distinctive files including an app chunk or language pack. Shared hosts and API naming patterns count as infrastructure signals. |
| `cases.py` | Reviewer-confirmed context for a scan: same exact host, same registrable domain (PSL via tldextract, private suffixes on, so `*.oss-…aliyuncs.com` tenants are not merged), kit and infrastructure matches. |
| `scoring/` | Four tiers (`high_risk`, `caution`, `no_strong_signals`, `insufficient`) decided by explicit rules. The calibrated classifier only confirms behaviors and never raises a tier alone. Every tier comes with plain-language clues in Arabic and English that cite the observation behind them. |
| `linking/` | Proposes links between sites (same kit, shared infrastructure, shared payment/contact details…), at most one open link per host pair. Watch alerts are sent only after a reviewer approves the link. |
| `snapshots.py` | Idle snapshots from the extension. Only metadata is accepted (URLs without query strings, types, status, timings, sizes, visible text). The backend fetches the public JS/CSS itself without cookies, then stores a HAR-format artifact and kit-matches it. |
| `evidence.py` | Investigator-mode uploads. Verifies the device's SHA-256 against the exact bytes received, re-sanitizes in strict mode, stores the HAR and records both hashes in `evidence_files`. |
| `discovery/` | Certificate-transparency discovery, rate-limited. Matching new domains are queued for a safe capture. |
| `static_check/` | Suspected secrets in authorized files. Stores category and location only, never the value. |
| `review_ui/` | Reviewer console behind the `.env` token: queue, case view (observation vs inference, artifacts with hashes), link approval, training jobs, model promotion. |
| `db/` | SQLAlchemy engine selected by `DATABASE_URL`, plain-SQL migrations per dialect (see below). |
| `storage.py` | Content-addressed artifact store behind the `ArtifactStore` interface (see below). |

ML code lives in `backend/ml`:
- `import_private` / `import_sessions`: private labels, sessions, public datasets and synthetic pages → `records.jsonl`.
- `train`: kit-grouped split, 5-fold kit-grouped CV, thresholds tuned on out-of-fold scores, promotion rule.
- `promote`: manual override, recorded with a reason.
- `eval_live`: seen-kit vs unseen-kit.
- `tier_check`: system-level tiers on a DB copy.

## Database: SQLAlchemy behind `DATABASE_URL`

All database access goes through `app/db`:

```
DATABASE_URL=                                          # default: SQLite file HAMI_DATA_DIR/hami.sqlite3 (WAL)
DATABASE_URL=postgresql+psycopg://user:pw@host:5432/hami   # hosted Postgres: a config change, no code change
```

- **Interface.** Application code uses a small dialect-neutral API on top of a SQLAlchemy `Engine`:
  - `with db() as conn`
  - `conn.execute(sql, params)` with `?` placeholders, translated to bound parameters
  - rows readable by name or index
  - `.lastrowid` (via `RETURNING` on Postgres) and `.rowcount`
  - `with tx(conn):` for atomic multi-statement writes; outside `tx`, each statement commits on its own
- **Portable SQL only.** `INSERT … ON CONFLICT DO NOTHING` instead of `INSERT OR IGNORE`. Time cutoffs are computed in Python and passed as parameters. Timestamps are ISO-8601 UTC text in both databases.
- **Migrations.** Plain SQL in `migrations/sqlite/` and `migrations/postgresql/` (same schema, same file names), applied in order and recorded in `schema_migrations`. Reviews and observations are append-only on both databases: SQLite triggers in one, PL/pgSQL triggers in the other, raising the same messages.
- **Verified.** The full backend suite (68 tests) and `scripts/e2e_check.py` (29 checks) pass on SQLite and on PostgreSQL 16. Run `make test-postgres PG_URL=…` against an empty database.
- **Docker.** `docker compose --profile postgres up -d` adds a Postgres service; point `DATABASE_URL` at it.
- **Migrating existing data.** There is no data-migration tool yet. For a move, export the tables in `schema_migrations` order and load them into the Postgres schema.

## Artifact storage: `ArtifactStore`

Artifacts (sanitized HARs, HTML, screenshots, action logs) are content-addressed. The key is
`<sha256[:2]>/<sha256>.<ext>`, and each artifact gets an `artifacts` row with its hash, size, MIME type and capture step.
The bytes go to a store with three methods:

```python
class ArtifactStore(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...
```

```
STORAGE_URL=                         # default: LocalStore(HAMI_DATA_DIR/artifacts)
STORAGE_URL=file:///srv/hami/artifacts
STORAGE_URL=s3://bucket/prefix       # S3-compatible (AWS S3, MinIO, R2): not implemented yet
```

`LocalStore` writes atomically (temp file + rename), refuses keys that escape its root, and skips writes for keys that
already exist (same key = same bytes). An S3-compatible store is one more class: `put_object` / `get_object` /
`head_object` with the key as object name. It is selected in `get_store()`. Nothing else changes, because the
database keeps only the key and the SHA-256, and `verify_artifact` re-hashes on read.

## Extension data flows

| Flow | When | What leaves the device |
|---|---|---|
| Local lists | every 30 min | Nothing. The device downloads `/indicators/local-lists`: confirmed hosts, registrable domains, recent CT domains and kit file names. |
| Pre-filter | every page | Nothing. Classification is on the device: sensitive categories (banks, government, health, mail…), the Tranco top-10k plus allowlist, the local high-risk list and kit file names. |
| Local banner | confirmed site | Nothing. The red banner comes from the local list. |
| Manual check | user clicks | The page URL (`POST /scans`). |
| Automatic check | only after one-time consent; candidates only | The URL of a candidate page. Limits: 30 per hour, each host at most once per 6 h. A colored badge is shown on every checked tab; a banner appears only for High risk. |
| Idle snapshot | consent + toggle; candidate page idle 10 s; once per load | URLs without query strings or fragments, resource types, status, timings, sizes and sanitized visible text. Never cookies, headers, bodies or storage. The backend fetches public JS/CSS itself. |
| Search shields | only if enabled | Result hostnames only (`POST /lookup/hosts`). |
| Investigator mode | off by default, separate toggle, optional `debugger` + `downloads` permissions | Full HAR via `chrome.debugger`, sanitized on the device and downloaded as `.har`. It is uploaded to `POST /evidence` with its SHA-256 only if the user also enabled "upload evidence". It never runs on sites skipped by the pre-filter. |

Nothing is ever sent anywhere except the configured Hami backend.

## Rule summary (scoring)

| Tier | Fires when (any) |
|---|---|
| High risk | Exact host reviewed fraudulent. Same registrable domain as a reviewed fraudulent site. Strong behavior and classifier agrees. Approved link to a reviewed case and a fraud behavior. Sign-in wall or thin page plus same kit as a reviewed case. Sign-in wall or thin page plus a fraud behavior in delivered code and classifier agrees on the code. |
| Caution | A fraud behavior without classifier agreement. Partial kit or infrastructure match. A fraud behavior in delivered code (thin page or classifier agrees). Identity mismatch. Other weaker combinations. |
| Insufficient | Thin page, no delivered code (< 40 words) and no match. |
| No strong signals | Otherwise. |
