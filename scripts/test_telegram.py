"""
Diagnóstico de Telegram — ejecutar desde la raíz del proyecto:
    python3 scripts/test_telegram.py
"""
import os
import sys
from pathlib import Path

# Cargar .env explícitamente desde la raíz del proyecto
root = Path(__file__).parent.parent
sys.path.insert(0, str(root))
env_path = root / ".env"
print(f"Buscando .env en: {env_path}")
print(f".env existe: {env_path.exists()}")

from dotenv import load_dotenv

load_dotenv(dotenv_path=env_path, override=True)

token   = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN", "")
chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

# Only the bot id (the part before ":"), never any of the secret half: this prints to a terminal
# that gets pasted into chats and issues.
print(f"\nToken encontrado : {'SÍ (bot ' + token.split(':')[0] + ', secreto oculto)' if token else 'NO — no está en .env'}")
print(f"Chat ID encontrado: {'SÍ (' + chat_id + ')' if chat_id else 'NO — no está en .env'}")

if not token or not chat_id:
    print("\n❌ Falta token o chat_id. Revisá el .env")
    sys.exit(1)

import requests

print("\n--- Enviando mensaje de prueba ---")
url = f"https://api.telegram.org/bot{token}/sendMessage"
payload = {
    "chat_id": chat_id,
    "text": "🔔 *Retirement Advisor — Test de conexión*\n\n✅ Telegram funcionando correctamente.",
    "parse_mode": "Markdown",
}

try:
    resp = requests.post(url, json=payload, timeout=10)
    print(f"HTTP status : {resp.status_code}")
    data = resp.json()
    print(f"Respuesta   : {data}")
    if resp.ok:
        print("\n✅ ¡Mensaje enviado! Revisá tu Telegram.")
    else:
        print(f"\n❌ Error de Telegram: {data.get('description', data)}")
        if resp.status_code == 401:
            print("   → Token inválido. Verificá TELEGRAM_BOT_TOKEN en .env")
        elif resp.status_code == 400:
            print("   → Chat ID inválido o el bot no tiene acceso al chat.")
            print("   → Solución: enviá cualquier mensaje al bot primero, luego reintentá.")
except requests.exceptions.ConnectionError:
    print("❌ Sin conexión a internet o api.telegram.org bloqueado.")
except Exception as e:
    from data.redact import redact_secrets

    print(f"❌ Error inesperado: {redact_secrets(str(e), token)}")
