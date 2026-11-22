# Hami — what you do

## Today, before building (about 30 min)

**1. Register the team.** Every member registers individually, then form the team (3–5 people). Deadline: **Tue 24 Nov, 11:00 AM**. Do this first.

**2. Install** (skip what you have):
- Python 3.11+ · Node.js 20+ · Git · Chrome · Docker Desktop
- Claude Code: `npm install -g @anthropic-ai/claude-code`

**3. Unzip** `hami_starter.zip`. You get a `hami` folder that already contains:
- `docs/` — proposal (PDF + Word), BUILD_SPEC.md, DAY_PLAN.md, team.txt
- `data/private/` — empty folders and CSV templates for your data
- `.gitignore` — keeps `data/private/` out of git
- `KICKOFF_PROMPT.md` — what you paste into Claude Code now
- `NEXT_PROMPTS.md` — what you paste later (Phase 2 and 3)

**4. Fill in team names** in `docs/team.txt`.

**5. Add your data** to `data/private/`:
- Scam sites → `sites/kit01_<name>/`, `sites/kit02_<name>/` … (one folder per scam family)
- Legitimate sites → `sites/legit_<name>/` (try to have as many as scam pages)
- Other datasets → `datasets/` as they are
- List pages in `datasets/labels.csv` (columns explained in `data/private/README.md`). If you run out of time, list what you can — Claude Code shows you anything unlabeled.
- Scam links still online → `datasets/live_urls.csv`
- Legitimate sites are already listed in `datasets/legit_urls.csv` (40 UAE job boards, gig platforms, shops, banks and government sites). Add more if you like.
- Public datasets: download the ones in `data/private/PUBLIC_DATASETS.md` into `data/private/public_datasets/`.
- Write a few lines in `data/private/README.md` about where the data came from.

**6. Set up git** (terminal in the `hami` folder):
```
git init
git branch -M master
git add .
git commit -m "Project docs and setup"
```
Check that no private data was added: `git status` and `git log --stat` must not show anything under `data/private/`.

**7. Create the GitHub repo** named `hami` (empty: no README, no .gitignore), add teammates as collaborators, then:
```
git remote add origin https://github.com/<your-username>/hami.git
git push -u origin master
```
On GitHub: **Settings → Branches →** make `master` the default.

## Build Phase 1 (extension + full backend and database)

**8.** In the `hami` folder run `claude`. Press **Shift+Tab** to auto-accept file edits. Paste the whole content of `KICKOFF_PROMPT.md`.

**9. Answer it when it asks:**
- Data summary and proposed scam-family groups → check and reply.
- Unlabeled pages → label them in `labels.csv` or tell it to skip them.
- Capturing your URL lists → approve only public pages; run from your own connection, not campus Wi-Fi.
- Reviewer token → it puts one in `.env`; keep it private.

**10. Test the extension** when it says it's ready:
1. Run `make run`.
2. Chrome → `chrome://extensions` → **Developer mode** on → **Load unpacked** → `clients/extension/dist`. Pin Hami.
3. Check:
   - A real scam link → Hami → **Check this page** → warning with clues and screenshots.
   - Right-click a link → **Check this link with Hami**.
   - Google "part time job Dubai" → shields on results.
   - Google Maps business → **Check this business website**.
   - A normal site (real job board) → not flagged.
   - Watch a scam result, check a second site from the same family, approve the link and alert in the reviewer console → badge shows 1 and the Updates tab explains why.
   - Export the case brief → both sites with hashes.
   - Label a scam as fraudulent → after the list syncs, reopening it shows the banner.
4. Run `make check` → all pass.

**11. Push:** `git push`. Then check on GitHub that `data/private` is not there.

## After Phase 1

**12.** Paste **Phase 2** from `NEXT_PROMPTS.md` (public HTTPS URL, Android app + APK, iOS if you have a Mac). You'll need: an Android phone with USB debugging or Android Studio emulator, and a free Expo account; optionally a Cloudflare tunnel or cloud VM.

**13.** Paste **Phase 3** (screenshots, README, TECHNICAL.md, WALKTHROUGH.md, PPT, fresh-clone check).

**14. Submit:** push to master and send the GitHub link through the Hackathon Submission Web App when it's provided. Tick the checklist in `docs/DAY_PLAN.md` section 5 first.

## If something goes wrong
- Claude Code stuck or going in circles → tell it: "Stop. Summarize what's failing, then fix only that."
- Running low on time → tell it to skip P2 items (iOS, banner, static check). Never skip the README, docs or PPT.
- Extension can't reach the server → check `make run` is running and the server URL in Hami's options is `http://localhost:8000`.
