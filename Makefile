# Retirement Advisor — developer convenience targets (Fase H.4).
#
# `make run` launches the app (creating the venv on first use via run.sh).
# `make test` / `make lint` run the CI checks locally.

PYTHON ?= python3
VENV   ?= venv
BIN     = $(VENV)/bin

.PHONY: help setup run test lint check clean lock

help:
	@echo "Targets disponibles:"
	@echo "  make setup   - crear el venv e instalar dependencias"
	@echo "  make run     - lanzar el dashboard (setup automático si falta)"
	@echo "  make test    - correr la suite de tests (pytest)"
	@echo "  make lint    - correr ruff"
	@echo "  make check   - lint + test (lo que corre el CI)"
	@echo "  make lock    - regenerar requirements.lock (hashes) desde requirements.txt"
	@echo "  make clean   - borrar el venv y caches"

setup:
	./run.sh --setup

run:
	./run.sh

test: setup
	$(BIN)/pytest tests/ -q

lint: setup
	$(BIN)/ruff check .

check: lint test

# Audit D5 — regenerate the hash-pinned lockfile. Targets 3.11 (the CI floor) so
# a single lock installs across the whole supported range; 3.12 resolves from it
# too. Nothing requires >=3.12 any more since pandas-ta was removed.
lock:
	uv pip compile requirements.txt --generate-hashes --python-version 3.11 \
		--output-file requirements.lock

clean:
	rm -rf $(VENV) .pytest_cache .ruff_cache **/__pycache__
