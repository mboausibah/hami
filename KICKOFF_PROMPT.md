Read docs/BUILD_SPEC.md (the full spec), docs/proposal.pdf and data/private/README.md first.

Today we build PHASE 1: the Chrome extension and the COMPLETE backend and database behind it.
Do NOT build the mobile app or the submission docs (README write-up, TECHNICAL.md, PPT) yet,
but structure everything exactly as the spec describes so they plug in later.

Phase 1 scope (work in this order, commit after each):
1. Repo layout from the spec on the master branch. Keep the existing .gitignore (data/private and data/processed must never be committed).
2. Database: the full SQLite schema from the spec (scans, artifacts, observations, assessments,
   reviews with supersedes, dataset_versions, model_versions, links, watches, alerts,
   discovered_domains, static_findings) with plain SQL migrations.
3. Backend pipeline: capture -> sanitize -> store (SHA-256) -> analyze -> score, on real public URLs,
   with Arabic normalization, the 4 risk tiers, rules layer and listing identity check.
4. Data and model: inspect data/private (including PUBLIC_DATASETS.md and public_datasets/) and show me
   a summary BEFORE writing the importer. Detect language automatically when lang is empty.
   labels.csv has a scam_type column; report metrics per scam_type. Behavior tags may also include
   fake_shop, investment_promise and gambling_deposit. Domains referenced inside HAR files are review
   candidates only: capture them after I approve and never label them fraudulent without review.
   Legitimate negatives: capture each URL in data/private/datasets/legit_urls.csv with the safe pipeline
   (homepage plus up to 3 same-site navigation pages, no forms, rate-limited) after I approve.
   Public datasets: import them as described in PUBLIC_DATASETS.md, with a kit_id prefix per source,
   and report metrics per source and per scam type.
   Then: make import, make train, make train-synthetic, make eval, make eval-live, promotion rule.
5. All API endpoints in the spec: scans, artifacts, lookup/hosts, watches, alerts,
   indicators/high-risk-hosts, reviews, link review, alert approve/withdraw, train,
   clusters brief, discovery queue, health. Rate limits and reviewer token (.env, with .env.example committed).
6. Reviewer console (Arabic + English): scan queue, discovery queue, case page, labels,
   link review, alert approval/withdrawal, train button with held-out results, brief export.
7. Linking and clusters, pending alerts for watched cases, redacted case brief (Markdown + JSON).
8. Discovery worker on certificate transparency logs (rate-limited, patterns.yaml).
9. Static check of authorized files (never stores secret values).
10. Synthetic test sites A, B, C + listing page; scripts/e2e_check.py checks 1-4 all pass.
11. Chrome extension (MV3, Vite, TypeScript) using clients/shared, with everything in the spec:
    popup check, right-click check, bilingual result card (Arabic RTL), watch toggle, Updates tab,
    unread-alerts badge, Google Search shields, Google Maps business check, local high-risk list
    banner, opt-in auto-check, options page.
12. Docker: Dockerfile + docker-compose.yml (API + discovery worker), and `make run` for local
    use on http://localhost:8000 (the extension's default server URL). `make check` runs all tests.

Follow the safety rules and hackathon rules in the spec. No mocks or placeholder screens.
Commit after each step with a short labeled summary of what changed and what you verified.
When something needs me (approving data, kit groups, URL captures, loading the extension),
tell me exactly what to do and keep working on other steps meanwhile.
