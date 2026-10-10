# Retirement Advisor — developer convenience targets (Fase H.4).
#
# `make run` launches the app (creating the venv on first use via run.sh).
# `make test` / `make lint` run the CI checks locally.

PYTHON ?= python3
VENV   ?= venv
BIN     = $(VENV)/bin

.PHONY: help setup run test lint check estado worktree clean lock launchd-install launchd-uninstall

help:
	@echo "Targets disponibles:"
	@echo "  make setup   - crear el venv e instalar requirements.lock (+ requirements-dev.txt: ruff fijado)"
	@echo "  make run     - lanzar el dashboard (setup automático si falta)"
	@echo "  make test    - correr la suite de tests (pytest)"
	@echo "  make lint    - correr ruff"
	@echo "  make check   - lint + test (lo que corre el CI)"
	@echo "  make estado  - SHA, PR abiertos, worktrees, Orden actual y la fila (pending) (solo lectura)"
	@echo "  make worktree BRANCH=fix/x - worktree en ../ra-x desde origin/main, con el venv enlazado"
	@echo "  make lock    - regenerar requirements.lock (hashes) desde requirements.txt"
	@echo "  make clean   - borrar el venv y caches"
	@echo "  make launchd-install   - (macOS) corrida diaria 07:30: alertas + scoring"
	@echo "  make launchd-uninstall - (macOS) sacarla"

setup:
	./run.sh --setup   # lock + requirements-dev.txt, see run.sh (VENV-FROM-LOCK)

run:
	./run.sh

test: setup
	$(BIN)/pytest tests/ -q

lint: setup
	$(BIN)/ruff check .

check: lint test

# Read-only and without `setup`: a worktree has no venv, and the script is stdlib.
estado:
	@if [ -x $(BIN)/python3 ]; then $(BIN)/python3 scripts/estado.py; else $(PYTHON) scripts/estado.py; fi

# A worktree has no venv: link the clone's, so `make check` runs there as is.
#   make worktree BRANCH=fix/x [BASE=origin/main] [DIR=$$HOME/ra-x]  new branch
#   make worktree REF=<sha> DIR=$$HOME/ra-qa-main                      detached
BASE ?= origin/main
worktree:
	@if [ -z "$(BRANCH)$(REF)" ]; then \
		echo "uso: make worktree BRANCH=fix/x [BASE=origin/main] [DIR=…]  |  make worktree REF=<sha> [DIR=…]"; exit 1; fi
	@test -d "$(realpath $(VENV))" || { echo "no hay venv en $(CURDIR)/$(VENV): make setup"; exit 1; }
	@git fetch -q origin || echo "sin red: uso el $(BASE) local"
	@dir="$(DIR)"; [ -n "$$dir" ] || dir="../ra-$(notdir $(or $(BRANCH),$(REF)))"; \
	if [ -n "$(BRANCH)" ]; then git worktree add -q -b "$(BRANCH)" "$$dir" "$(BASE)"; \
	else git worktree add -q --detach "$$dir" "$(REF)"; fi && \
	ln -s "$(realpath $(VENV))" "$$dir/venv" && \
	echo "worktree: $$dir ($$(git -C "$$dir" log -1 --format='%h %s'); venv → $(realpath $(VENV)))"

# Audit D5 — regenerate the hash-pinned lockfile. Targets 3.11 (the CI floor) so
# a single lock installs across the whole supported range; 3.12 resolves from it
# too. Nothing requires >=3.12 any more since pandas-ta was removed. --universal keeps
# the platform markers: without it the lock resolved for macOS and dropped greenlet,
# which SQLAlchemy 2.0 needs on Linux, so the Docker build failed (STREAMLIT-ALIGN).
lock:
	uv pip compile requirements.txt --universal --generate-hashes --python-version 3.11 \
		--output-file requirements.lock

clean:
	rm -rf $(VENV) .pytest_cache .ruff_cache **/__pycache__

# macOS: daily one-shot run (alerts + outcome scoring) under launchd. See README
# "Alertas Diarias" — launchd runs a missed 07:30 on wake, a sleeping process does not.
launchd-install:
	bash scripts/install_launchd.sh

launchd-uninstall:
	bash scripts/install_launchd.sh --uninstall
