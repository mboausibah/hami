# Hami - thin wrapper around tasks.py (the cross-platform task runner). `make X` == `python tasks.py X`.
# Extra arguments: make promote ARGS='m2026... --reason "..." --reviewer NAME'

ifeq ($(OS),Windows_NT)
  SYS_PY ?= py -3
else
  SYS_PY ?= python3
endif

TASKS := run api token migrate testsites corpus import import-sessions train train-synthetic eval eval-live eval-holdout \
         tier-check promote capture-labels capture-legit capture-har-candidates capture-live discovery static-check test test-postgres e2e \
         clients extension check docker-up docker-down export-indicators migrate-to-postgres release screenshots docs help

.PHONY: $(TASKS)
.DEFAULT_GOAL := help

$(TASKS):
	$(SYS_PY) tasks.py $@ $(ARGS)
