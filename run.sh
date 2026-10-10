#!/usr/bin/env bash
#
# Retirement Advisor — one-command launcher (Fase H.4).
#
# Idempotent: the first run creates a virtualenv and installs dependencies;
# subsequent runs just start the Streamlit app. Designed for non-developers who
# only want to "download and run".
#
# Usage:
#   ./run.sh            # set up (if needed) and launch the dashboard
#   ./run.sh --setup    # only set up the environment, don't launch
#
set -euo pipefail

cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
VENV_DIR="venv"
PORT="${PORT:-8501}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "❌ No se encontró '$PYTHON'. Instalá Python 3.11+ desde https://www.python.org/ y volvé a intentar."
  exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
  echo "📦 Creando entorno virtual en ./$VENV_DIR ..."
  "$PYTHON" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# Install from the hash-pinned lock, the same pins CI and the Docker image install
# (VENV-FROM-LOCK). The stamp keeps the hash of the lock and requirements-dev.txt, so
# the venv is reinstalled when their content changes — not when requirements.txt or a file date does: a
# fresh checkout dates every file today. Installing from the ranges is how the venv
# sat on Streamlit 1.57.0 while the lock said 1.61.1 and CI ran 1.65.0.
#
# Worktrees made by `make worktree` link ./venv to the clone's: they never install
# into it (one on an old commit would downgrade everyone's), they only say so.
STAMP="$VENV_DIR/.deps-installed"
LOCK_HASH="$(cat requirements.lock requirements-dev.txt | shasum -a 256 | cut -d' ' -f1)"
if [ "$(cat "$STAMP" 2>/dev/null)" != "$LOCK_HASH" ]; then
  if [ -L "$VENV_DIR" ]; then
    echo "⚠️  ./$VENV_DIR es el venv compartido del clon y no coincide con este requirements.lock:"
    echo "    instalá desde el clon (make setup ahí); este worktree no lo toca."
  else
    echo "⬇️  Instalando dependencias desde requirements.lock (puede tardar la primera vez) ..."
    pip install --quiet --upgrade pip
    pip install --quiet --require-hashes -r requirements.lock
    pip install --quiet -r requirements-dev.txt   # ruff fijado (#150) + xlrd, como el CI
    echo "$LOCK_HASH" > "$STAMP"
  fi
fi

if [ ! -f .env ] && [ -f .env.example ]; then
  echo "📝 Creando .env a partir de .env.example (editalo para activar AI opcional)."
  cp .env.example .env
fi

if [ "${1:-}" = "--setup" ]; then
  echo "✅ Entorno listo. Ejecutá ./run.sh para lanzar la app."
  exit 0
fi

echo "🚀 Lanzando Retirement Advisor en http://localhost:$PORT ..."
exec streamlit run dashboard/app.py --server.port "$PORT"
