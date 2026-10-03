# Retirement Advisor — developer convenience targets (Fase H.4).
#
# `make run` launches the app (creating the venv on first use via run.sh).
# `make test` / `make lint` run the CI checks locally.

PYTHON ?= python3
VENV   ?= venv
BIN     = $(VENV)/bin

.PHONY: help setup run test lint check estado clean lock launchd-install launchd-uninstall

help:
	@echo "Targets disponibles:"
	@echo "  make setup   - crear el venv e instalar dependencias (+ requirements-dev.txt: ruff fijado)"
	@echo "  make run     - lanzar el dashboard (setup automático si falta)"
	@echo "  make test    - correr la suite de tests (pytest)"
	@echo "  make lint    - correr ruff"
	@echo "  make check   - lint + test (lo que corre el CI)"
	@echo "  make estado  - SHA, PR abiertos, worktrees, Orden actual y la fila (pending) (solo lectura)"
	@echo "  make lock    - regenerar requirements.lock (hashes) desde requirements.txt"
	@echo "  make clean   - borrar el venv y caches"
	@echo "  make launchd-install   - (macOS) corrida diaria 07:30: alertas + scoring"
	@echo "  make launchd-uninstall - (macOS) sacarla"

setup:
	./run.sh --setup
	$(BIN)/pip install -q -r requirements-dev.txt

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

# Audit D5 — regenerate the hash-pinned lockfile. Targets 3.11 (the CI floor) so
# a single lock installs across the whole supported range; 3.12 resolves from it
# too. Nothing requires >=3.12 any more since pandas-ta was removed.
lock:
	uv pip compile requirements.txt --generate-hashes --python-version 3.11 \
		--output-file requirements.lock

clean:
	rm -rf $(VENV) .pytest_cache .ruff_cache **/__pycache__

# macOS: daily one-shot run (alerts + outcome scoring) under launchd. See README
# "Alertas Diarias" — launchd runs a missed 07:30 on wake, a sleeping process does not.
launchd-install:
	bash scripts/install_launchd.sh

launchd-uninstall:
	bash scripts/install_launchd.sh --uninstall
