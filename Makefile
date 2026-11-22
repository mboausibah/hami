# Hami — developer commands. Works with GNU make on Linux/macOS and on Windows (Git Bash sh).

ifeq ($(OS),Windows_NT)
  VENV_PY := .venv/Scripts/python.exe
  SYS_PY  ?= py -3.12
else
  VENV_PY := .venv/bin/python
  SYS_PY  ?= python3
endif
ROOT := $(CURDIR)
PY   := $(ROOT)/$(VENV_PY)
BE   := cd backend &&
export PYTHONUTF8=1

.PHONY: help venv deps db run api testsites corpus import capture-labels capture-legit capture-har-candidates \
        capture-live train train-synthetic eval eval-live discovery discovery-once static-check test e2e \
        clients extension check docker-up docker-down clean-storage

help:
	@echo "make run              start API (http://localhost:8000) + synthetic test sites"
	@echo "make import           private + public + synthetic data -> data/processed/records.jsonl + report"
	@echo "make train            dataset version + candidate model + held-out metrics + promotion rule"
	@echo "make train-synthetic  same, synthetic data only (no private data needed)"
	@echo "make eval / eval-live re-run held-out evaluation / evaluate on approved live URLs"
	@echo "make capture-legit    capture approved legit_urls.csv (homepage + up to 3 nav pages, rate-limited)"
	@echo "make discovery        certificate-transparency discovery worker (loop)"
	@echo "make static-check     scan authorized files for suspected secrets (values never stored)"
	@echo "make extension        build the Chrome extension into clients/extension/dist (+ zip)"
	@echo "make check            backend tests + e2e checks + client type-check and lint"

$(VENV_PY):
	$(SYS_PY) -m venv .venv
	$(PY) -m pip install --upgrade pip

.venv/.deps: backend/requirements.txt backend/requirements-dev.txt | $(VENV_PY)
	$(PY) -m pip install -r backend/requirements-dev.txt
	$(PY) -m playwright install chromium
	@touch .venv/.deps

venv deps: .venv/.deps

db: deps
	$(BE) $(PY) -m app.cli migrate

run: deps
	$(BE) $(PY) -m app.cli devserver

api: deps
	$(BE) $(PY) -m uvicorn app.main:app --host 0.0.0.0 --port 8000

testsites: deps
	$(BE) $(PY) -m app.cli testsites

corpus: deps
	$(PY) testsites/generator/generate.py

import: deps
	$(BE) $(PY) -m ml.import_private

capture-labels: deps
	$(BE) $(PY) -m ml.capture_lists labels --yes

capture-legit: deps
	$(BE) $(PY) -m ml.capture_lists legit --yes

capture-har-candidates: deps
	$(BE) $(PY) -m ml.capture_lists har-candidates --yes

capture-live: deps
	$(BE) $(PY) -m ml.capture_lists live --yes

train: deps
	$(BE) $(PY) -m ml.train --kind full

train-synthetic: deps
	$(BE) $(PY) -m ml.train --kind synthetic

eval: deps
	$(BE) $(PY) -m ml.evaluate

eval-live: deps
	$(BE) $(PY) -m ml.eval_live

discovery: deps
	$(BE) $(PY) -m app.discovery.worker

discovery-once: deps
	$(BE) $(PY) -m app.discovery.worker --once

static-check: deps
	$(BE) $(PY) -m app.static_check

test: deps
	$(BE) $(PY) -m pytest -q tests

e2e: deps
	$(PY) scripts/e2e_check.py --start-local

clients:
	cd clients && npm install --no-audit --no-fund

extension: clients
	$(PY) scripts/make_icons.py
	cd clients && npm run build -w @hami/extension

check: test e2e extension
	cd clients && npm run typecheck && npm run lint
	$(PY) scripts/extension_check.py

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down
