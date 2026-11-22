# Prompts for after Phase 1

Paste each one into Claude Code only when the previous phase works and is committed.

---

## Phase 2 — Put it online + phone app

```
Phase 1 is done. Re-read docs/BUILD_SPEC.md sections 7 and 8.

Phase 2 scope (commit after each):
1. Hosting: get the docker-compose stack running with a public HTTPS URL.
   First try a Cloudflare quick tunnel (cloudflared tunnel --url http://localhost:8000);
   also write the steps for a cloud VM with Docker + Caddy. Tell me exactly what I need to run or
   sign up for. Set the public URL as the default in clients/shared and .env.example, rebuild the
   extension, and run scripts/e2e_check.py against the public URL.
2. Expo mobile app (iOS + Android) exactly as in the spec: check screen, share-to-app via
   expo-share-intent, deep link hami://check, result card identical to the extension, watch toggle,
   Updates screen, settings with Arabic RTL switch, device ID in expo-secure-store.
3. Android release APK at clients/mobile/dist/hami.apk that installs on any Android phone and uses the
   public URL. Tell me what I need to do (emulator/phone, Expo account) and verify it on a device.
4. iOS: if I have a Mac with Xcode, build and run on a simulator/device; otherwise configure it so it is
   ready to build and document the steps.
No mocks or placeholder screens. Labeled summary after each step.
```

---

## Phase 3 — Submission documents + final check

```
Phases 1 and 2 are done. Re-read docs/BUILD_SPEC.md sections 9 and 10.

Phase 3 scope:
1. scripts/capture_screens.py: real screenshots of the extension (popup, Search shields, Maps check,
   banner), the Android app and the reviewer console into docs/screenshots/, using fictional-brand
   test sites for anything committed.
2. Run make train and make eval-live and keep the real metrics for the docs.
3. README.md with the three required parts (problem and solution; reasoning, trade-offs, what we left
   out, what we'd do with more time; build and run instructions), plus the public URL, extension and
   APK install steps, training steps, permission justification, privacy design, acceptance table and
   known limitations. Team from docs/team.txt.
4. docs/TECHNICAL.md (architecture, model choices with real metrics, privacy design, discovery,
   capture security, limitations, roadmap) and docs/WALKTHROUGH.md (six-minute run on real links).
5. docs/Hami.pptx via scripts/make_docs.py (python-pptx), 10-12 slides as in the spec, with the real
   screenshots and metrics; Arabic right-to-left.
6. Final check: clone the repo into a fresh folder, follow only the README, run make run and make check,
   and fix anything that fails. Confirm nothing from data/private is in git history
   (git log --all -- data/private must be empty). List what works, what's untested and what was cut.
```
