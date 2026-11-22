# Hami — build day plan

## 1. Name and description

**Project name:** Hami (حامي) — "protector".

**One line (registration form):**
Hami checks links before you pay — in search results, Maps, messages and websites — and warns you on your phone or in Chrome, in Arabic and English.

**Short description (about 50 words):**
Hami detects fraudulent websites across the open internet, starting with UAE task and job scams. It safely opens a link, reads what the page asks you to do in Arabic or English, and warns you in an iOS/Android app or a Chrome extension that also checks Google Search results and Maps listings. It finds new look-alike scam domains early and links rebranded sites into redacted briefs for police.

---

## 2. Before you start Claude Code (about 30 min)

**Install**
- Python 3.11+, Node.js 20+, Git, Chrome, Docker Desktop.
- Android: Android Studio with an emulator, or an Android phone with USB debugging on. A free Expo account if you build the APK with EAS.
- iOS (optional): a Mac with Xcode. Without one, Claude Code makes iOS ready to build and you present on Android.
- Hosting: `cloudflared` (free quick tunnel, fastest) or a small cloud VM with Docker. This gives Hami a public HTTPS address, so the app and extension work on any network — a real product, not a laptop-only setup.

**Repository**
1. Create the GitHub repo (e.g. `hami`). GitHub creates `main` by default — the rules require **master**:
   `git branch -M master`, push, then set master as the default branch in the repo settings.
2. Add all team members as collaborators.
3. Create these folders and files:
   - `docs/proposal.pdf` and `docs/proposal.docx` (the Hami_Proposal files)
   - `docs/team.txt` — one line per member: name, role
   - `data/private/` — your datasets and scam sites (see section 3)
4. Make sure `.gitignore` contains `data/private/` and `data/processed/` **before your first commit**.

**Start Claude Code** in the repo folder and paste `Hami_Claude_Code_Prompt.md`.

---

## 3. Preparing your data for training

Put everything in `data/private/`. Claude Code will inspect it and write an importer, but this layout makes it faster and more accurate:

```
data/private/
  sites/
    kit01_<name>/          one folder per scam kit or family of look-alike sites
      page1.html           saved HTML, MHTML or HAR files
      page2.har
    kit02_<name>/
    legit_<name>/          legitimate sites, same structure
  datasets/
    labels.csv             one row per page or URL
    live_urls.csv          scam URLs that are still online (for real-world testing)
  notes.md                 anything Claude Code should know (where data came from, languages)
```

**labels.csv columns** (leave a cell empty if unknown):
`file_or_url, label, kit_id, lang, behavior_tags, notes`
- `label`: `fraudulent`, `legitimate` or `inconclusive`
- `kit_id`: the same ID for pages that are variants of one scam (keeps them in the same train/test split so the score isn't inflated)
- `lang`: `ar`, `en` or `mixed`
- `behavior_tags`: separated by `;`, from: `advance_fee; deposit_to_unlock; commission_transfer; brand_misuse; identity_mismatch; credential_request; off_platform_contact`

**What makes the model good**
- **Legitimate examples matter as much as scams.** Aim for at least as many legitimate pages as scam pages, ideally real recruitment and shopping sites. Without them the model flags everything.
- **Both languages**, for both labels.
- **Several kits.** Many different scam families beat many copies of one site.
- A practical target for today: 100+ fraudulent and 100+ legitimate pages across 10+ kits. Fewer still works; the synthetic generator fills gaps.
- Remove personal data (victims' names, phone numbers, IDs) where you can. The sanitizer strips more, but don't rely on it alone.
- **URL-only lists:** Claude Code asks before fetching them. Approve only public pages, fetched from your own connection, not a mass scan on the campus network.
- **Your own scam sites:** used for training and testing as they are. Any copy that goes into the repo's test sites needs real brand names and logos swapped for fictional ones.

**Training commands**
1. `make import` — converts your data and prints a report: counts by label, language, kit and behavior tag. Check it: are labels right, is anything unlabeled, are kits grouped correctly?
2. `make train` — trains on your data + synthetic data, prints held-out metrics and saves a model version.
3. Read the results:
   - **False-positive rate on legitimate pages** — the most important number. If it's high, add legitimate examples.
   - **Recall** — how many scams were caught. If low, check which behavior tags are missed and add examples.
   - **Per-language results** — if Arabic is weaker, add Arabic pages.
   - **Baselines** — the full model should beat URL-only; that comparison is a strong slide.
4. `make eval-live` — scores Hami on `live_urls.csv` (real, still-online scam sites) plus some real legitimate sites. Report this separately from the test-set numbers; it's your real-world result.
5. Add data → `make import && make train` again. A new model replaces the current one only if recall doesn't drop and false positives don't rise.
6. `make train-synthetic` — what judges can run without your private data. Make sure it works.

---

## 4. Timeline for today

Hours are from when you start Claude Code. Split the team so people work in parallel (one Claude Code session per person works well: backend/ML, clients, data/docs).

| When | Goal |
|---|---|
| H0–H0.5 | Setup above. Data person prepares `labels.csv` while Claude Code reads the proposal. |
| H0.5–H3 | **P0:** scan pipeline on real URLs, importer, first `make train` on your data. |
| H3–H4.5 | **P0:** Chrome extension checks pages; Docker + public HTTPS URL; `e2e_check.py` checks 1 and 4 pass. Commit. |
| H4.5–H7 | **P1:** Android app + APK with share-to-app; Search shields and Maps check; reviews, linking, alerts, retraining. |
| H7–H8 | **P1/P2:** discovery worker; iOS if you have a Mac; extension banner; static check and brief. |
| H8–H9.5 | **Docs:** README, TECHNICAL.md, WALKTHROUGH.md, PPT with real screenshots and metrics. |
| H9.5–H10 | Full walkthrough rehearsal on real links, fresh-clone test, final push to master, submit the link. |

If you fall behind, cut P2 first (iOS, banner, static check), then the discovery worker. Never cut the hosted API, the Android APK, the README, the docs or the PPT.

---

## 5. Submission checklist (from the terms and announcements)

| Requirement | How Hami covers it | Done |
|---|---|---|
| Every member registered individually; team of 3–5 formed by **Tue 24 Nov, 11:00 AM** | Register all members, then form the team; names in `docs/team.txt` | ☐ |
| True personal details at registration | Each member checks their own details | ☐ |
| Working product/MVP — no idea-only, pitch decks or mockups | Hosted API works on real links; APK and extension installable; `make check` passes | ☐ |
| Complete source code | Everything in the repo; nothing only on a laptop | ☐ |
| Pushed to GitHub, link submitted in the Submission Web App | Link submitted when provided | ☐ |
| Entire MVP on **master** branch | `git branch -M master`; master is default | ☐ |
| README: problem and solution | README part 1 | ☐ |
| README: reasoning, trade-offs, what was left out, what we'd do with more time | README part 2 | ☐ |
| README: build and run instructions | README part 3 (`make run`, Docker, extension, APK, iOS, training) | ☐ |
| Technical documentation: architecture, model choices, privacy design | `docs/TECHNICAL.md` (+ proposal PDF) | ☐ |
| PPT: architecture, model choices, privacy design | `docs/Hami.pptx` | ☐ |
| Original work, no plagiarism | Built by the team; open-source libraries listed with licenses | ☐ |
| No third-party IP | Fictional brands in test sites and committed screenshots; private data not committed | ☐ |
| No hacking of systems not designated | Only normal visits to public pages; no probing; rate-limited discovery; no mass scans on campus Wi-Fi | ☐ |
| Before the deadline | Final push and submission with time to spare | ☐ |

**Final check before submitting:** clone the repo into a fresh folder on another laptop, follow only the README, and run `make run` and `make check`. Then install the APK and the extension from the repo and check a real link on mobile data, away from your Wi-Fi.

---

## 6. Presenting the MVP

- Use the hosted HTTPS address, so phones work on mobile data and you don't depend on the event Wi-Fi.
- Present on real links: scam URLs from your collection that are still online (re-check them the morning of judging), a domain found by the discovery worker, and legitimate sites.
- Scam sites vanish quickly. If one is gone, open its stored capture; the screen labels it as stored.
- Have the APK installed on a phone, the extension loaded in Chrome and the reviewer console open before you start.
- Rehearse `docs/WALKTHROUGH.md` to about six minutes.
