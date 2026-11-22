#!/usr/bin/env bash
# Local development run (same as `make run`): installs deps + Playwright Chromium if missing, creates the
# DB and .env reviewer token, ensures a current model exists, starts the API (and test sites), prints URLs.
set -euo pipefail
cd "$(dirname "$0")/.."
exec make run
