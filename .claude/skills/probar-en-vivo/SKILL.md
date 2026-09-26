---
name: probar-en-vivo
description: Prueba un cambio en la app real de retirement-advisor (Streamlit + Playwright) sobre una copia de la base del usuario, con capturas y sin tocar sus datos. Obligatoria después de cualquier desarrollo, antes de dar la tarea por terminada o abrir un PR; `make check` y AppTest no la reemplazan.
---

# Probar en vivo

Después de cualquier desarrollo, el cambio se prueba en la app levantada, no solo en la
suite. `make check` prueba el código; AppTest prueba una página aislada con el análisis
stubbeado. Ninguno ve lo que ve el usuario con datos reales: EMPTY-FEED-SA (MSFT sin red
salía SELL) y el caption de LLM-2 («quedó registrado» sobre un dedup) aparecieron recién
en la QA en vivo. Esta skill corre **después** de `make check` en verde, no en su lugar.

## Límites

- La base, el `portfolio.json` y el `.env` del usuario no se tocan: todo corre contra una
  copia y se prueba con hashes que no cambiaron.
- Correr la app **desde el worktree**, nunca desde `~/retirement_advisor`: preferencias,
  planes y convicciones se escriben en `data/*.json` del directorio de código
  (`data/preferences.py`, `data/plan_store.py`), y los logs en su `logs/`.
- IA apagada salvo que el cambio sea de IA. Una corrida con llamadas pagas en vivo
  (comité, chat) necesita el OK explícito del usuario con alcance y cantidad de llamadas.
- Sin red no hay datos: si yfinance no responde, decirlo; no simular la prueba.

## 1. Aislar

```bash
REAL=~/retirement_advisor/data/db
mkdir -p .context/live
shasum -a 256 $REAL/retirement_advisor.db $REAL/portfolio.json > .context/live/sha_before.txt
sqlite3 -readonly $REAL/retirement_advisor.db ".backup .context/live/retirement_advisor.db"
cp $REAL/portfolio.json .context/live/portfolio.json
```

`config.DB_PATH` lee `RETIREMENT_ADVISOR_DB_PATH` (`config.py:17`), y `portfolio.json` y
los backtests cuelgan de `DB_PATH.parent`, así que la copia los aísla a los dos. Si el
worktree no tiene venv, usar `~/retirement_advisor/venv` sin instalar nada en él.

## 2. Levantar

En background, con un puerto libre:

```bash
RETIREMENT_ADVISOR_DB_PATH=$PWD/.context/live/retirement_advisor.db AI_ENABLED=false \
  <venv>/bin/python3 -m streamlit run dashboard/app.py \
  --server.headless true --server.port 8599 --browser.gatherUsageStats false \
  > .context/live/streamlit.log 2>&1
```

Esperar a `curl -s http://localhost:8599/_stcore/health` = 200. Sin `.env` en el
worktree la IA ya queda apagada; `AI_ENABLED=false` lo deja explícito.

## 3. Manejar con Playwright

Escribir un script en `.context/live/` (Playwright y Chromium ya están en el venv y en
`~/Library/Caches/ms-playwright`). Casos mínimos: **el que fallaba** y **un control** que
tiene que seguir andando. Lo que ya se aprendió de la app:

- Las páginas se abren por URL: `http://localhost:8599/Stock_Analysis` (el título de
  `st.Page` en `dashboard/app.py`, sin el número del archivo).
- Esperar a que termine cada rerun: que no exista `[data-testid="stStatusWidget"]`.
- El símbolo de Stock Analysis entra por el expander «¿No está en el universo?…»,
  `Enter` y el botón «Analizar» (`exact=True`: hay otro «🔍 Analizar»).
- Stock Analysis tiene 4 `st.tabs`; lo que no está en la primera no es visible hasta
  hacer click en la pestaña (`get_by_role("tab").nth(i)`).
- Capturas en `.context/live/*.png`. Mirarlas antes de afirmar nada.

## 4. Cruzar

La pantalla sola no alcanza. Contrastar cada caso contra:
- el log de la corrida (`logs/retirement_advisor.log` del worktree);
- la copia: qué filas o posiciones se escribieron y cuáles no (`sqlite3 -readonly`,
  `portfolio.json` de `.context/live/`).

## 5. Cerrar

Matar el proceso (`pkill -f "streamlit run dashboard/app.py --server.headless true --server.port 8599"`)
y comprobar que los datos reales no cambiaron:

```bash
shasum -a 256 $REAL/retirement_advisor.db $REAL/portfolio.json | diff - .context/live/sha_before.txt
```

## 6. Reportar

En la respuesta y en el cuerpo del PR, en una sección «Verificación en la app real»:
cada caso con resultado esperado y observado, la evidencia cruzada (log o base), las
capturas embebidas (`![…](</ruta absoluta/.context/live/x.png>)`) y el hash real
sin cambios. Lo que no se pudo probar se dice con nombre: sin red, sin key, página
inaccesible. **Nunca presentar AppTest ni `make check` como prueba en vivo.**
