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

# Install/refresh dependencies only when requirements changed (or first run).
STAMP="$VENV_DIR/.deps-installed"
if [ ! -f "$STAMP" ] || [ requirements.txt -nt "$STAMP" ]; then
  echo "⬇️  Instalando dependencias (puede tardar la primera vez) ..."
  pip install --quiet --upgrade pip
  pip install --quiet -r requirements.txt
  touch "$STAMP"
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
