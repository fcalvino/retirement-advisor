# Retirement Advisor

[![CI](https://github.com/fcalvino/retirement-advisor/actions/workflows/ci.yml/badge.svg)](https://github.com/fcalvino/retirement-advisor/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/streamlit-1.x-FF4B4B)](https://streamlit.io/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-992%20passing-brightgreen)]()

> **Sistema local de planificación de retiro.**
> Armá un plan vivo (perfil → cartera → simulaciones → activar), lo seguís contra el mercado y lo actualizás — con score fundamental, Monte Carlo (decumulación, drags, realista vs conservador), comité, chat y alertas. Una sola app en tu máquina, sin suscripciones ni cuentas.

---

## ¿Qué hace?

Retirement Advisor es el **sistema operativo de un plan de retiro**, no solo un screener. Sobre un universo de 39 tickers (acciones US, ETFs, ADRs argentinos y **BTC-USD**) combina:

**Plan vivo**
- **Onboarding de perfil** (edad, capital, ahorro, tolerancia) que siembra defaults en Optimizer y Simulaciones
- **🗺️ Mi Plan**: guardar / activar / cargar escenarios, salud vs mercado, trades de alineación, evolución longitudinal, PDF para compartir y respaldo JSON
- **Simulaciones Monte Carlo** con decumulación (fixed real / % constante / guardrails simplificados), drags económicos opt-in y caja **realista vs conservador** siempre visible
- **💬 Hablá con tu plan** — chat con herramientas reales del motor (atajo en lenguaje natural; necesita API key)
- **Comité de inversión** por ticker y sobre el portfolio actual (interpreta, no recalcula; opt-in con IA)
- **Track Record** honesto de señales (hit rate, no marketing)
- **Calidad de datos** por ticker (completitud + frescura; política partial/poor en score y optimizer)
- **Colas de viento** sector-país (curadas; la IA solo interpreta, no cambia el score)
- **Libro personal** — sizing de convicciones en paralelo al optimizer de retiro

**Research y motor**
- **Análisis fundamental** en 5 dimensiones (rentabilidad, salud financiera, valuación, crecimiento, dividendos)
- **Consistency Score** (estabilidad multi-año) + **Piotroski F-Score** (mejora contable año contra año)
- **Economic Moat** cuantitativo + evaluación cualitativa por AI
- **Análisis técnico** (SMA de 200 semanas ~3,8 años — no la clásica de 200 días —, RSI, MACD, ADX, Bollinger) sobre barras semanales de 10 años — cálculo local con NumPy/Pandas, sin librería de indicadores
- **Decisión AI** con razonamiento en lenguaje natural (Claude, GPT-4o, Grok o Nous)
- **Optimizador Mean-Variance** con 3 perfiles, glide path por edad y núcleo determinístico
- **Stress testing** en 6 crisis históricas
- **Watchlist** con alertas de precio
- **Motor de alertas** persistente (12 tipos) con email, Telegram y reportes PDF mensuales

No es un SaaS multiusuario, no modela doble moneda AR como eje de producto, no compara en profundidad dos planes guardados y no corre un LLM local.

---

## Screenshots

### 🏠 Screener — ranking de todo el universo
```
┌─────────────────────────────────────────────────────────────────────┐
│  📊 Opportunity Screener                                            │
│                                                                     │
│  Strong/Buy: 14  │  Hold: 18  │  Sell/Reduce: 6  │  Screened: 39  │
│                                                                     │
│  Ticker │ Company          │ Signal      │ Score ████░ │ Moat       │
│  ────── │ ──────────────── │ ─────────── │ ─────────── │ ────────── │
│  NVDA   │ NVIDIA Corp      │ 🟢 STRONG…  │ █████ 91.2  │ 🟦 Wide    │
│  MSFT   │ Microsoft Corp   │ 🟢 STRONG…  │ █████ 88.7  │ 🟦 Wide    │
│  GOOGL  │ Alphabet Inc     │ 🟢 BUY      │ ████░ 79.4  │ 🟦 Wide    │
│  AAPL   │ Apple Inc        │ 🟢 BUY      │ ████░ 77.1  │ 🟦 Wide    │
│  ...                                                                │
└─────────────────────────────────────────────────────────────────────┘
```

### 🗺️ Mi Plan — el hub del retiro
```
┌─────────────────────────────────────────────────────────────────────┐
│  🗺️ Mi Plan                         ● Activo · Conservador 30y      │
│                                                                     │
│  Prob. de la meta   │  Desvío vs mercado  │  Qué hacer este año     │
│       78%           │      −4.2%          │  Aportar + rebalancear  │
│                                                                     │
│  Realista (sin haircut)  mediana $1.9M  │  p10 $0.81M               │
│  Conservador (motor)     mediana $1.6M  │  p10 $0.68M               │
│                                                                     │
│  [PDF para compartir]  [Exportar JSON]  [Cargar en Simulaciones]    │
└─────────────────────────────────────────────────────────────────────┘
```

### 📈 Portfolio Optimizer — Efficient Frontier
```
┌─────────────────────────────────────────────────────────────────────┐
│  📈 Portfolio Optimizer                   Perfil: Moderado  ▼       │
│                                                                     │
│ Atractivo est. │  Volatilidad  │ Ratio atr./vol │  Div. Yield       │
│     14.2%      │     15.8%     │      0.90      │    2.3%           │
│                                                                     │
│  Efficient Frontier                                                  │
│  10% ┤                                          ★ (óptimo)         │
│   8% ┤                               ·  · ·  · ·                   │
│   6% ┤                     ·   ·  ·                                 │
│   4% ┤          · ·  ·                                              │
│      └──────────────────────────────────────── Volatilidad          │
│       8%    12%   16%   20%   24%   28%                             │
└─────────────────────────────────────────────────────────────────────┘
```

### 📋 Watchlist — monitoreo con alertas de precio
```
┌─────────────────────────────────────────────────────────────────────┐
│  📋 Watchlist                                                       │
│                                                                     │
│  Tickers: 6  │  En señal BUY: 4/6  │  Alertas: 3  │  Disparadas: 1│
│                                                                     │
│  🔔 AAPL cayó por debajo de $180.00 (precio actual: $176.40)       │
│                                                                     │
│  Ticker │ Empresa        │ Precio   │ Score ██░  │ Señal      │ Alerta │
│  NVDA   │ NVIDIA Corp    │ $134.20  │ █████ 91   │ 🟢 STRONG  │ ▲$140  │
│  MSFT   │ Microsoft      │ $425.80  │ ████░ 88   │ 🟢 STRONG  │ ▼$400  │
│  AAPL   │ Apple Inc      │ $176.40  │ ████░ 77   │ 🟢 BUY     │ ▼$180✅│
└─────────────────────────────────────────────────────────────────────┘
```

### 🎲 Monte Carlo — proyección 10 años
```
┌─────────────────────────────────────────────────────────────────────┐
│  🎲 Simulaciones — Monte Carlo (10 000 paths)                       │
│                                                                     │
│  $2.5M ┤                                              ░░░          │
│  $2.0M ┤                                        ░░░░░░███          │
│  $1.5M ┤                              ░░░░░░░░░░████████ │ p75      │
│  $1.0M ┤────────────────────────────██████████████████── │ p50      │
│  $0.5M ┤              ░░░░░░░░░░░░░░████████████████     │ p25      │
│        └────────────────────────────────────────────     │ p10      │
│         Año 1   Año 2   Año 4   Año 6   Año 8   Año 10           │
│                                                                     │
│  Mediana final: $1.82M  │  Mejor caso (p95): $2.94M               │
│  Peor caso (p5): $0.74M │  Prob. superar $1M: 78.3%               │
│  Realista vs conservador siempre visible (mediana + p10)          │
└─────────────────────────────────────────────────────────────────────┘
```

> 📸 *Los screenshots anteriores son representaciones en ASCII. Para ver la app real en acción, ejecutá `streamlit run dashboard/app.py` después de instalar.*

---

## Quick Start

Python **3.11 o 3.12** (eso corre el CI). El lockfile se genera contra 3.11; Docker usa `python:3.12-slim`.

```bash
# 1. Clonar y entrar al directorio
git clone https://github.com/fcalvino/retirement-advisor.git
cd retirement-advisor

# 2. Crear entorno e instalar dependencias
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 3. Copiar config y lanzar
cp .env.example .env
streamlit run dashboard/app.py
```

Abrí `http://localhost:8501` — sin necesidad de API keys para el análisis básico.

> **AI opcional**: Si querés decisiones en lenguaje natural, agregá tu `ANTHROPIC_API_KEY` (u OpenAI/xAI) en `.env`. Sin AI, el motor rule-based funciona perfectamente.

### Instalación reproducible (mismos números)

`requirements.txt` son rangos `>=` para editar a mano. Lo que **reproduce** numpy/scipy/pandas (y por tanto un plan auditado) es el lockfile hasheado — es lo que instala el `Dockerfile`:

```bash
pip install --require-hashes -r requirements.lock
# Tras cambiar requirements.txt:
make lock    # uv pip compile … --python-version 3.11
```

### ⚡ Primera hora (flujo real del producto)

Si solo querés **ver la herramienta funcionando** sin armar una cartera desde cero:

```bash
git clone https://github.com/fcalvino/retirement-advisor.git
cd retirement-advisor
./run.sh            # crea el entorno, instala todo y lanza la app (macOS/Linux)
```

`run.sh` es idempotente: la primera vez crea el `venv` e instala dependencias; las siguientes solo lanza la app. En Windows con `make` disponible podés usar `make run`.

#### Demo con Docker (sin instalar Python)

```bash
docker compose up --build
# → http://localhost:8501
```

Detalle y cómo publicarla: [`docs/DEMO_HOSTED.md`](docs/DEMO_HOSTED.md).
**Nota:** es una **demo single-user** (no SaaS multiusuario con cuentas).

Una vez abierta la app:

1. En **Inicio**, tocá **🎁 Cargar y activar plan de ejemplo** (o andá a **🗺️ Mi Plan**).
2. Mirá el hub **¿cómo viene tu plan?** (probabilidad, desvío, alertas) y **Hoy hacé esto**.
3. En **Mi Plan**: **qué hacer este año**, salud vs mercado, PDF **para compartir**, respaldo JSON.
4. En **🎲 Simulaciones**: realista vs conservador siempre visible + palancas si no llegás a la meta.
5. Opcional: **💬 Hablá con tu plan** (preguntas sugeridas; necesita API key de IA).
6. Research: **Screener → Stock Analysis** (desde ahí, Comité y Chat están a un clic).

Los planes de ejemplo viven en `data/sample_plans/*.json` (conservador 30y, FIRE moderado, retiro AR con ADRs).

> **Respaldá tu plan**: exportalo a JSON desde **🗺️ Mi Plan** y guardalo en tu nube/USB. Los datos viven en `data/retirement_plans.json` + `data/db/`. El perfil financiero (`data/user_preferences.json`) no se commitea — la plantilla versionada es `data/user_preferences.example.json`.

---

## Páginas del dashboard (menú por intención)

| Sección | Páginas | ¿Para qué? |
|---------|---------|-----------|
| Inicio | **Inicio**, **Hablá con tu plan** | Hub del plan + chat con herramientas reales |
| Mi dinero | **Mi Plan**, Portfolio, **Optimizer** (incluye asignación por edad) | Plan vivo, posiciones, cartera objetivo |
| Investigar | Screener, Stock Analysis, Watchlist | Research (Comité enlazado desde ficha/chat) |
| Proyectar | Simulaciones, Backtesting | Monte Carlo, stress, sensibilidad, decumulación |
| Seguimiento | Alertas, Track Record | Monitoreo + historial honesto de señales |
| Ajustes | Settings, About, Comité, Allocation detalle | Config + herramientas secundarias |
| Ajustes (`DEV_MODE`) | Eval IA, Calidad de Datos, Macro RAG | Solo con `DEV_MODE=1` o el toggle en Settings |

**Flujo de retiro recomendado:** Perfil → Optimizer → Simulaciones → **Mi Plan** (guardar + activar + respaldar) → Portfolio + Alertas.
**Atajo:** plan de ejemplo en 1 clic o chat en lenguaje natural.

---

## Configuración (.env)

```bash
# Cache (horas antes de refrescar datos de Yahoo Finance)
CACHE_TTL_HOURS=24

# AI Analysis (opcional — sin esto usa rule-based)
AI_PROVIDER=claude        # claude | openai | xai | nous
AI_MODEL=claude-sonnet-4-6
AI_ENABLED=true
ANTHROPIC_API_KEY=sk-ant-...

# Alertas por email (opcional)
EMAIL_FROM=tu@gmail.com
EMAIL_TO=destino@gmail.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_PASSWORD=tu_app_password

# Alertas por Telegram (opcional)
TELEGRAM_TOKEN=tu_bot_token
TELEGRAM_CHAT_ID=tu_chat_id

# Reportes PDF
REPORT_OUTPUT_DIR=reports
ALERT_INTERVAL_HOURS=24
REPORT_DAY=1
```

### Proveedores AI soportados

| Proveedor | `AI_PROVIDER` | Variable de entorno | Modelos recomendados |
|-----------|--------------|---------------------|----------------------|
| Anthropic (Claude) | `claude` | `ANTHROPIC_API_KEY` | `claude-sonnet-4-6`, `claude-opus-4-7` |
| OpenAI | `openai` | `OPENAI_API_KEY` | `gpt-4o`, `gpt-4o-mini` |
| xAI (Grok) | `xai` | `XAI_API_KEY` | `grok-3`, `grok-3-mini` |
| Nous Research | `nous` | `NOUS_API_KEY` o `hermes login` | `Hermes-3-70B` |

```bash
# Ejemplo con Grok (xAI)
AI_PROVIDER=xai
AI_MODEL=grok-3
XAI_API_KEY=xai-...
```

Sin AI configurado, el sistema cae automáticamente al motor de decisión rule-based.

---

## Cómo funciona

### Score fundamental (0–100)

Cada empresa se califica en 5 dimensiones:

| Dimensión | Pts | Métricas |
|-----------|-----|----------|
| Profitability | 25 | ROE, ROIC, margen neto, margen bruto |
| Financial Health | 20 | D/E ratio, current ratio, cobertura de intereses |
| Valuation | 25 | P/E, PEG, EV/EBITDA, P/B |
| Growth | 20 | CAGR de ingresos y EPS a 5 años, FCF yield |
| Dividends | 10 | Yield, payout ratio |

### Score Ajustado = Base + Bonos de calidad

| Componente | Pts máx | Lógica |
|------------|---------|--------|
| **Consistency Score** | +15 | Estabilidad de ROE, EPS y márgenes a 4+ años (std/CV) |
| **Piotroski F-Score** | +6 / +12 | 9 checks YoY de rentabilidad, liquidez y eficiencia |
| **Moat Bonus** | +10 | `min(moat_score × 0.5, 10)` según clasificación Wide/Narrow/Minimal |
| **Tailwind Bonus** | ±8 | `clamp(score × 0.8, −8, +8)` — colas de viento sector-país (puede restar) |

```
adjusted_score = clamp(fundamental + consistency + piotroski_bonus + moat_bonus + tailwind_bonus, 0, 100)
```

### Economic Moat (0–20 pts)

| Fuente | Pts | Método |
|--------|-----|--------|
| Cuantitativo | 0–12 | Retornos sobre capital, márgenes, pricing power, eficiencia |
| AI cualitativo | 0–8 | LLM evalúa 4 dimensiones: network effects, switching costs, brand, regulatory moat |

Clasificación: **Wide** ≥14 / **Narrow** ≥8 / **Minimal** ≥4 / **None**

### Colas de viento (tailwinds)

Outlook estructural **sector × país**, curado en `data/tailwinds/sector_country.json` (ej. Energy + Argentina / Vaca Muerta). Matching: ticker > industria+país > sector+país. La IA opcional (cache 30 días) **solo interpreta** — nunca cambia el score. Apagable con `TAILWINDS.enabled=False`.

### Señales de decisión

| Score Ajustado | Técnico | Señal |
|----------------|---------|-------|
| ≥ 75 | Alcista o neutro | **STRONG BUY** |
| ≥ 60 | No bajista | **BUY** |
| ≥ 45 | Cualquiera | **HOLD** |
| 35–44 | Cualquiera | **REDUCE** |
| < 35 | Cualquiera | **SELL** |

Bloqueos automáticos (override): D/E > 3, patrimonio negativo, RSI semanal > 80 con movimiento parabólico.

### Portfolio Optimizer (Mean-Variance)

Scipy SLSQP minimizando el **ratio atractivo/vol** negativo — `(atractivo estimado − Rf) / σ histórica`, que no es un Sharpe — sujeto a constraints por posición, sector, volatilidad y dividend yield:

| Perfil | Max Vol | Min Div | Max Pos | Max Crypto |
|--------|---------|---------|---------|------------|
| Conservador | 12% | 3.5% | 8% | **3%** |
| Moderado | 18% | 2.5% | 12% | **5%** |
| Agresivo | 25% | 1.5% | 18% | **10%** |

Los límites de crypto se aplican **por ticker** (BTC, ETH, etc.) independientemente del score — protección estructural para carteras de retiro. Fallback score-weighted cuando SLSQP es infeasible (e.g., universo growth-heavy con perfil Conservador). Goal-aware + glide path por edad viven en la misma página del Optimizer.

### Monte Carlo

Block-bootstrap sobre retornos semanales históricos de 10 años:
- Bloques de 4 semanas → preserva autocorrelación y fat tails (sin asunción gaussiana)
- Ajuste conservador: +10% volatilidad, −20% retorno histórico
- **Referencia realista** (opt-in, default en la UI): mismos paths **sin** haircut, para comparar apples-to-apples. La caja muestra **mediana + p10** (no p90: inflar vol puede ensanchar el techo)
- 10 000 simulaciones en < 2 segundos (vectorizado con NumPy)
- Fan chart con percentiles 5/10/25/50/75/90/95

### Decumulación y drags

Tres estrategias de retiro, opt-in (sin estrategia el MC de acumulación queda byte-idéntico):

| Estrategia | Qué hace |
|------------|----------|
| `fixed_real` | Retiro anual constante en poder de compra |
| `constant_pct` | % fijo del capital remanente |
| `guardrails` | % base con techo/piso y recortes/aumentos — **Guyton-Klinger simplificado** |

`guardrails` implementa 2 de las 4 reglas de Guyton-Klinger — preservación de capital (recorte cuando la tasa efectiva se va 20% arriba de la base) y prosperidad (aumento cuando se va 20% abajo). **No** implementa la regla de inflación (GK congela el ajuste después de un año negativo; acá se aplica siempre), la de manejo de cartera (de qué activo sale el retiro; acá se vende a prorrata) ni el límite temporal del recorte (GK lo suspende en los últimos 15 años).

El retiro reduce **unidades** (el capital sacado deja de componer). Ruina absorbente: si un path llega a 0, se queda en 0.

Drags económicos (también opt-in; default 0%): fee anual, tax de dividendos, costo de rebalanceo, buffer AR. El caso base sin drags se conserva siempre como referencia; los planes guardados recuerdan bajo qué supuestos se generaron. El buffer AR **no** debe sumarse al descuento ARS del optimizer (ya inclina la asignación lejos de ADRs).

Laboratorio de sensibilidad en Simulaciones: tornado (inflación, fricciones, retorno, vol) + escenarios what-if.

### Stress Testing

6 escenarios calibrados con datos de Bloomberg/FRED:

| Escenario | SPY drawdown |
|-----------|-------------|
| 2008 Crisis Financiera Global | -56.8% |
| 2000-2002 Burbuja Dot-com | -49.1% |
| 2020 COVID-19 | -33.9% |
| 2022 Inflación + Suba de Tasas | -19.4% |
| Recesión Severa (hipotético) | -30.0% |
| Stagflación Extrema (hipotético) | -25.0% |

### Mi Plan, chat y comité

- **Mi Plan** persiste un snapshot (allocation, núcleo, metas, MC, narrativa, supuestos) en `data/retirement_plans.json`. Activarlo lo convierte en objetivo vivo: drift, trades de alineación y alertas se miden contra esos pesos. Cada snapshot sella `lib_versions` (python/numpy/scipy/pandas) para detectar deriva de entorno.
- **Chat** enruta preguntas a herramientas del motor (plan, simulación, ticker) y narra solo sobre datos determinísticos.
- **Comité** (4 roles, disenso siempre presente vía «Abogado del Diablo»): por ticker desde Stock Analysis; sobre el **portfolio real** desde Portfolio. Interpreta números ya calculados; no relanza el optimizer.

### 🪙 Bitcoin y activos crypto

El motor incluye un pipeline analítico dedicado para Bitcoin (y otros activos crypto como ETH), completamente separado del pipeline de equity. El resultado es un `FundamentalResult` estándar — todos los consumidores downstream (dashboard, optimizer, AI) funcionan sin cambios.

#### Cómo analizar BTC

```bash
# Sin AI — score técnico + penalidades de volatilidad/drawdown
python main.py analyze BTC

# Con AI — activa la evaluación de Crypto Moat (cache 7 días)
AI_ENABLED=true python main.py analyze BTC

# Equivalente: BTC-USD (ticker de yfinance)
python main.py analyze BTC-USD
```

#### Scoring crypto (0–100)

Fórmula (lee `CRYPTO_MOAT` + `CryptoAnalyzer._compute_score`):

`clamp(base_score + tech_pts − vol_penalty − dd_penalty + moat_bonus, 0, 100)`

| Componente | Rango | Descripción |
|---|---|---|
| Base institucional | +28 | `CRYPTO_MOAT.base_score` — floor institucional |
| Señal técnica | +4 a +30 | BULLISH+fuerte=+30, BULLISH=+24, NEUTRAL=+16, BEARISH=+8, BEARISH+fuerte=+4 |
| Penalidad volatilidad | 0 a −25 | Vol anualizada: <40%→0, 40–60%→−8, 60–80%→−15, >100%→−25 |
| Penalidad drawdown | 0 a −15 | Max drawdown: >−30%→0, −30 a −50%→−5, −50 a −70%→−10, <−70%→−15 |
| Bonus moat AI | 0 a +8 | `min(total × bonus_factor, max_bonus)` — Wide puede sumar el tope |

**Rango típico BTC:**
- Bull + Wide Moat y vol/dd no extremos → **55–65** (HOLD — no STRONG BUY)
- Perfil histórico BTC (vol ~65 %, max DD ~−77 %) → **~28–36** (HOLD / REDUCE); el momentum solo no llega a BUY
- Bear + vol extrema → **0–10** (SELL / REDUCE)

#### Crypto Moat Framework (AI qualitative, 0–8 pts)

| Dimensión | Máx | Qué evalúa |
|---|---|---|
| Network Adoption | 2.0 | Efectos de red + adopción institucional global |
| Monetary Scarcity | 2.0 | Supply cap 21M + ciclo de halving |
| Security & Decentralization | 1.5 | Hash rate, nodos, resistencia al ataque 51% |
| Institutional & Regulatory | 1.5 | ETFs aprobados, claridad regulatoria soberana |
| Tech Resilience | 1.0 | Lightning Network, resiliencia ante competidores |

Clasificación: **Wide** ≥6 / **Narrow** ≥4 / **Minimal** ≥2 / **None** <2

La evaluación usa el prompt de Grok v2 (mayo 2026) con rúbricas detalladas y perspectiva de retiro conservadora. Se cachea 7 días (los ciclos de halving no cambian semanalmente).

#### Límites de asignación por perfil de riesgo

| Perfil | Max por ticker crypto | Justificación |
|---|---|---|
| Conservador | **3%** | Volatilidad histórica BTC >65% anualizada — preservación capital prioritaria |
| Moderado | **5%** | Exposición limitada con upside asimétrico |
| Agresivo | **10%** | Mayor tolerancia al riesgo y horizonte largo |

Los límites se aplican a través del optimizer (SLSQP bounds + fallback score-weighted) y son independientes del score del activo.

---

### Smart Alerts

12 tipos de alerta con debounce inteligente (SQLite):

| Tipo | Cooldown | Qué dispara |
|------|----------|-------------|
| Signal change | 24h | Cambio de señal (BUY→HOLD, HOLD→SELL, …) |
| Score drop ≥ 8 pts | 168h (7d) | Caída material del score ajustado |
| Score surge ≥ 8 pts + BUY | 168h | Suba material con señal de compra |
| Nueva oportunidad (BUY/STRONG_BUY) | 72h | Entra al radar por primera vez |
| Moat change | 336h (14d) | Cambia la clasificación de moat |
| Portfolio loss | 72h | P&L de una posición bajo el umbral |
| Portfolio drift | 168h | Peso se desvía del objetivo (plan activo u optimizer) |
| Portfolio rebalance | 168h | Deriva agregada: hay que rebalancear |
| SORR high | 336h (14d) | Prob. de drawdown temprano sobre el umbral |
| Goal risk | 168h | Cayó la probabilidad de cumplir una meta |
| Plan health degradation | 168h | Deriva estructural sostenida del plan activo |
| Market drop coach | 72h | Coach post-caída: el plan sigue OK o no |

Primera ejecución: guarda baseline silenciosamente sin disparar alertas (cold start).

---

## Universo de tickers por defecto

39 símbolos en `config.DEFAULT_TICKERS` (todos operados en USD):

```
US Mega-Cap: AAPL  MSFT  GOOGL  AMZN  NVDA  META  BRK-B
Financials:  JPM   V     MA     BAC
Healthcare:  JNJ   UNH   ABBV   PFE
Staples:     PG    KO    PEP    WMT
Industrials: HD    CAT   HON
Dividend:    O     T     XOM    CVX
ETFs:        SPY   QQQ   VTI    BND
Crypto:      BTC-USD
Argentina ADRs (USD): YPF  PAM  CEPU  LOMA  MELI  GLOB  TEO  EDN
```

Los ADRs argentinos aplican un descuento de 15% en el composite score para los perfiles Conservador y Moderado (riesgo macro ARS).

Para modificar el universo: editar `DEFAULT_TICKERS` en `config.py` o usar **⚙️ Settings** en el dashboard.

---

## Fuente de datos

Todos los datos provienen de **Yahoo Finance** vía `yfinance` (gratuito, sin API key):

- **Fundamentals**: `yf.Ticker().info`, `.financials`, `.balance_sheet`, `.cashflow`, `.dividends`
- **Técnicos**: precios semanales históricos de 10 años + cálculo local con NumPy/Pandas (SMA de 200 semanas ~3,8 años, RSI, MACD — sin librería de indicadores)
- **Cache**: SQLite local con TTL configurable (default 24h)
- **Calidad**: badge por ticker (completitud + frescura). Partial capea STRONG BUY; poor no entra al optimizer. Podés exportar un snapshot del universo desde ⚙️ Settings.

---

## Tests

```bash
pip install pytest
pytest tests/ -v
# o, con el venv del repo:
./venv/bin/python3 -m pytest tests/
```

La suite (992 tests) cubre el motor (scoring, moat, Monte Carlo, optimizer, decumulación), alertas, crypto, prompts, UI helpers y **oráculos del motor** (`tests/test_engine_oracles.py`, `tests/test_withdrawal_oracle.py`: el código vectorizado se compara contra una implementación de referencia escrita desde la definición financiera). Los tests de Monte Carlo, Optimizer y Crypto mockean `get_history`/`get_crypto_info` para no hacer llamadas de red.

Documentación completa (por rol): [`docs/INDEX.md`](docs/INDEX.md).

---

## Scheduler de alertas y reportes

El scheduler corre en background:
- **Alertas** cada `ALERT_INTERVAL_HOURS` horas — analiza el universo y despacha notificaciones si hay cambios de señal, caídas de score u oportunidades
- **Reporte PDF mensual** el día `REPORT_DAY` de cada mes a las 08:00
- **Salud del plan** (opt-in, `HEALTH.auto_record`) — registra un punto de la evolución del plan activo

```bash
source venv/bin/activate
python scripts/run_scheduler.py
```

Los logs se escriben en `logs/retirement_advisor.log` (rotación 10 MB, retención 7 días).

### Alertas Diarias (Cron — recomendado)

Para ejecutar una sola verificación de alertas y salir (ideal para cron), usá el script dedicado:

```bash
# Ejecución manual (con logs completos)
bash scripts/run_daily_alerts.sh

# Ejecución en background (solo logs WARNING+)
bash scripts/run_daily_alerts.sh --quiet
```

**Configurar cron** — todos los días a las 9:00 AM:

```bash
crontab -e
```

```cron
0 9 * * * /ruta/a/retirement_advisor/scripts/run_daily_alerts.sh --quiet >> /ruta/a/retirement_advisor/logs/daily_alerts.log 2>&1
```

**Optimización de tokens AI:** por defecto solo las alertas WARNING y CRITICAL generan explicaciones con AI (Grok/Claude/xAI). Las alertas INFO usan mensaje estándar, reduciendo el consumo de tokens.

| Severity | AI call | Configuración |
|----------|---------|---------------|
| CRITICAL | ✅ Sí | Siempre |
| WARNING  | ✅ Sí | Default |
| INFO     | ❌ No  | Ahorro de tokens |

Para ajustar, agregá en `.env`:
```env
ALERT_AI_MIN_SEVERITY=warning   # default — solo WARNING+ usan AI
ALERT_AI_MIN_SEVERITY=critical  # máximo ahorro — solo CRITICAL usa AI
ALERT_AI_MIN_SEVERITY=info      # máxima cobertura — todas usan AI
ALERT_AI_EXPLANATIONS=false     # deshabilitar AI completamente
```

### Cron (Linux/macOS) — Scheduler continuo

```cron
@reboot cd /ruta/a/retirement_advisor && /ruta/a/venv/bin/python scripts/run_scheduler.py >> logs/scheduler.log 2>&1
```

### systemd (Linux)

```ini
[Unit]
Description=Retirement Advisor — Scheduler de alertas
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/ruta/a/retirement_advisor
ExecStart=/ruta/a/venv/bin/python scripts/run_scheduler.py
Restart=on-failure
RestartSec=30
EnvironmentFile=/ruta/a/retirement_advisor/.env

[Install]
WantedBy=multi-user.target
```

### Docker

Imagen basada en `python:3.12-slim` (alineada con el CI). Instala `requirements.lock` con `--require-hashes`. Montá `data/` completo
para que **tus planes guardados, el historial de salud y la base SQLite**
persistan entre reinicios del contenedor, y `reports/` para los PDF.

```bash
# 0. Construir la imagen
docker build -t retirement-advisor .

# 1. Preparar config (AI opcional)
cp .env.example .env   # editá ANTHROPIC_API_KEY / OPENAI_API_KEY si querés AI

# 2. Dashboard
docker run -d --name ra-dashboard \
  -p 8501:8501 \
  --env-file .env \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/reports:/app/reports \
  retirement-advisor

# 3. Scheduler (alertas + reporte mensual + salud del plan)
docker run -d --name ra-scheduler \
  --env-file .env \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/reports:/app/reports \
  retirement-advisor \
  python scripts/run_scheduler.py
```

> **Persistencia:** los planes viven en `data/retirement_plans.json`, el historial
> de salud en `data/plan_health_history.json` y la base de alertas en `data/db/`.
> Montar `-v $(pwd)/data:/app/data` los conserva fuera del contenedor — hacé backup
> de esa carpeta con regularidad.

---

## Estructura del proyecto

```
retirement_advisor/
├── config.py                    # Umbrales, perfiles, universo de tickers
├── requirements.txt             # Rangos editables
├── requirements.lock            # Hash-pineado (make lock; lo usa Docker)
├── .env.example
├── analysis/                    # Scoring, moat, strategy, comité, chat, track record
├── data/                        # Fetcher, cache SQLite, planes, preferencias
├── portfolio/                   # Optimizer, Monte Carlo, decumulación, metas
├── alerts/                      # Engine, store, notifier, reporter
├── scripts/                     # Scheduler, refresh_context, check_doc_catalog
├── tests/                       # Suite pytest (oráculos + motor + UI helpers)
├── docs/                        # Catálogo por rol: docs/INDEX.md
└── dashboard/
    ├── app.py                   # Entry Streamlit + home (menú por intención)
    ├── shared.py                # Helpers cacheados, AI config, badges
    └── pages/                   # 18 páginas (3 solo en modo DEV_MODE)
```

El listado vivo de cada `.md` (guía vs metodología vs auditoría vs ideación) está en [`docs/INDEX.md`](docs/INDEX.md). No uses un recuento fijo de páginas del dashboard como si fuera el menú actual: hay 18 archivos en `dashboard/pages/` (Eval IA, Calidad de Datos y Macro RAG solo aparecen con `DEV_MODE`).

---

## Limitaciones conocidas

- **Supuestos económicos (drags)**: Por defecto las proyecciones (Optimizer, Monte Carlo, Plan) asumen **0% de fees, 0% de impuestos sobre dividendos y 0% de costo de rebalanceo**, y no modelan fricciones locales argentinas (cepo, brecha cambiaria, diferencial de inflación). Desde la pestaña **🎲 Simulaciones → 📊 Supuestos y drags** podés activar una capa configurable de drags realistas (fee, tax de dividendos, rebalanceo, buffer AR); el caso base sin drags se conserva siempre como referencia y los planes guardados recuerdan bajo qué supuestos se generaron.
- **Datos**: Yahoo Finance (yfinance) es la única fuente; puede tener datos faltantes o inconsistentes en empresas pequeñas. El sistema cae a valores neutrales cuando hay datos parciales y muestra un badge de calidad por ticker. Podés **exportar un snapshot del universo** (⚙️ Settings) para respaldo/offline.
- **Tickers personalizados**: Desde ⚙️ Settings podés agregar tickers custom (ej. VIST). Se integran al flujo pero quedan marcados como **⚠️ Custom** con calidad de datos parcial; su scoring es experimental y el optimizador los trata con cautela.
- **Monte Carlo**: El block-bootstrap usa historia real — no modela cambios estructurales (nuevas regulaciones, disrupciones de sector). El haircut conservador infla vol: por eso realista-vs-conservador compara mediana + p10, no p90.
- **AI Moat**: La evaluación cualitativa está basada en training data del LLM y puede estar desactualizada para empresas que cambian rápido.
- **Optimización**: El perfil Conservador puede ser matemáticamente infeasible con el universo default (vol 12% + div 3.5% son constraints difíciles de cumplir con acciones growth). En ese caso se aplica fallback score-weighted.
- **Stress test**: Los shocks sectoriales son calibrados desde datos históricos; una crisis futura podría diferir materialmente.
- **No es asesoramiento financiero**: Esta herramienta es educativa. Consultá con un asesor certificado antes de tomar decisiones de inversión.

---

## Licencia

MIT
