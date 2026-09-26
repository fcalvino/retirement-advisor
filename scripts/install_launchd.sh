#!/usr/bin/env bash
# Instala (o desinstala) la corrida diaria en launchd (macOS).
#
# Usage:
#   bash scripts/install_launchd.sh              # renderiza + bootstrap (idempotente)
#   bash scripts/install_launchd.sh --uninstall  # bootout + borra el plist
#
# Renderiza deploy/launchd/com.retirement-advisor.daily.plist.template con la ruta de
# este repo en ~/Library/LaunchAgents/. Para probarlo sin esperar a las 07:30:
#   launchctl kickstart -k gui/$(id -u)/com.retirement-advisor.daily

set -euo pipefail

LABEL="com.retirement-advisor.daily"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
TEMPLATE="$PROJECT_DIR/deploy/launchd/$LABEL.plist.template"
TARGET_DIR="${LAUNCH_AGENTS_DIR:-$HOME/Library/LaunchAgents}"
TARGET="$TARGET_DIR/$LABEL.plist"
DOMAIN="gui/$(id -u)"

if [[ "$(uname)" != "Darwin" ]]; then
    echo "launchd es de macOS; en Linux usá cron o systemd (README)." >&2
    exit 1
fi

# bootout falla si no estaba cargado: eso no es un error acá.
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true

if [[ "${1:-}" == "--uninstall" ]]; then
    rm -f "$TARGET"
    echo "Desinstalado: $LABEL"
    exit 0
fi

if [[ ! -x "$PROJECT_DIR/venv/bin/python" && ! -x "$PROJECT_DIR/venv/bin/python3" ]]; then
    echo "Falta $PROJECT_DIR/venv — corré 'make setup' primero." >&2
    exit 1
fi

mkdir -p "$TARGET_DIR" "$PROJECT_DIR/logs"
# '|' como separador: la ruta tiene '/'.
sed "s|__PROJECT_DIR__|$PROJECT_DIR|g" "$TEMPLATE" > "$TARGET"
plutil -lint "$TARGET" >/dev/null
launchctl bootstrap "$DOMAIN" "$TARGET"
echo "Instalado: $TARGET (diario 07:30)"
echo "Probar ahora: launchctl kickstart -k $DOMAIN/$LABEL  → logs/launchd_daily.*.log"
