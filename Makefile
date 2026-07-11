# Retirement Advisor — developer convenience targets (Fase H.4).
#
# `make run` launches the app (creating the venv on first use via run.sh).
# `make test` / `make lint` run the CI checks locally.

PYTHON ?= python3
VENV   ?= venv
BIN     = $(VENV)/bin

.PHONY: help setup run test lint check clean

help:
	@echo "Targets disponibles:"
	@echo "  make setup   - crear el venv e instalar dependencias"
	@echo "  make run     - lanzar el dashboard (setup automático si falta)"
	@echo "  make test    - correr la suite de tests (pytest)"
	@echo "  make lint    - correr ruff"
	@echo "  make check   - lint + test (lo que corre el CI)"
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

clean:
	rm -rf $(VENV) .pytest_cache .ruff_cache **/__pycache__
