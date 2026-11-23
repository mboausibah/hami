#!/usr/bin/env python3
"""Publish the Chrome extension as a GitHub Release with hami-extension.zip attached.

    python tasks.py release              build, check the zip, create (or update) release v<manifest version>
    python tasks.py release --dry-run    everything except talking to GitHub
    python tasks.py release --no-build   use the committed clients/extension/hami-extension.zip

Needs the GitHub CLI (https://cli.github.com) signed in with `gh auth login` and push access to the repository.
The release notes include the zip's SHA-256 and the install steps. Download link used in the README:
    https://github.com/<owner>/<repo>/releases/latest/download/hami-extension.zip
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "clients" / "extension"
ZIP = EXT / "hami-extension.zip"
SECRET_RE = re.compile(rb"eyJ[A-Za-z0-9_-]{10,}\.eyJ|Bearer [A-Za-z0-9._-]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY|AKIA[0-9A-Z]{16}")


def check_zip(path: Path) -> dict:
    if not path.is_file():
        sys.exit(f"{path} not found - build it with: python tasks.py extension")
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if "manifest.json" not in names:
            sys.exit("zip has no manifest.json at its root (Chrome could not load it)")
        manifest = json.loads(z.read("manifest.json"))
        bad = [n for n in names if n.endswith((".map", ".env", ".ts")) or "node_modules" in n or n.startswith(".")]
        if bad:
            sys.exit(f"zip contains files that must not ship: {bad[:5]}")
        leaks = [n for n in names if SECRET_RE.search(z.read(n))]
        if leaks:
            sys.exit(f"zip contains something that looks like a token or key: {leaks[:5]}")
    return {"files": len(names), "version": manifest["version"], "name": manifest.get("name", "Hami"),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size_kb": round(path.stat().st_size / 1024)}


def notes(info: dict, tag: str) -> str:
    return f"""Hami Chrome extension {tag} (Manifest V3).

**Install (Load unpacked)**
1. Download `hami-extension.zip` below and unzip it into a folder.
2. Open `chrome://extensions`, turn on **Developer mode**, click **Load unpacked** and pick the folder.
3. Start the Hami backend on the same computer: `docker compose up` (or `python tasks.py run`) from the repository.
   The extension talks to `http://localhost:8000` by default (Options → Server URL to change it).
4. On first install a consent page explains automatic checking (Arabic + English). Nothing is checked
   automatically until you agree.

**File**: hami-extension.zip, {info['files']} files, {info['size_kb']} KB
**SHA-256**: `{info['sha256']}`

Privacy design and permissions: see the README.
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-build", action="store_true")
    ap.add_argument("--tag", help="release tag (default v<manifest version>)")
    args = ap.parse_args()

    if not args.no_build:
        subprocess.check_call([sys.executable, str(ROOT / "tasks.py"), "extension"], cwd=ROOT)
    info = check_zip(ZIP)
    tag = args.tag or f"v{info['version']}"
    print(f"zip ok: {info['files']} files, {info['size_kb']} KB, manifest version {info['version']}")
    print(f"sha256 {info['sha256']}")

    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(notes(info, tag))
        notes_file = f.name
    create = ["gh", "release", "create", tag, f"{ZIP}#hami-extension.zip", "--title", f"Hami extension {tag}",
              "--notes-file", notes_file, "--target", "master", "--latest"]
    upload = ["gh", "release", "upload", tag, f"{ZIP}#hami-extension.zip", "--clobber"]
    if args.dry_run:
        print("dry run - would run:\n  " + " ".join(create) + "\n  (or, if the release exists)\n  " + " ".join(upload))
        print("\n--- release notes ---\n" + notes(info, tag))
        return 0

    gh = shutil.which("gh")
    if not gh:
        sys.exit("GitHub CLI not found. Install it from https://cli.github.com, run `gh auth login`, then run this again.")
    if subprocess.call([gh, "auth", "status"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
        sys.exit("GitHub CLI is not signed in. Run `gh auth login`, then run this again.")
    exists = subprocess.call([gh, "release", "view", tag], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0
    cmd = upload if exists else create
    subprocess.check_call([gh, *cmd[1:]], cwd=ROOT)
    url = subprocess.run([gh, "release", "view", tag, "--json", "url", "-q", ".url"], capture_output=True, text=True,
                         cwd=ROOT).stdout.strip()
    print(f"{'updated' if exists else 'created'} release {tag}: {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
