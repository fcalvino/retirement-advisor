# Retirement Advisor

[![CI](https://github.com/fcalvino/retirement-advisor/actions/workflows/ci.yml/badge.svg)](https://github.com/fcalvino/retirement-advisor/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/streamlit-1.x-FF4B4B)](https://streamlit.io/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-133%20passing-brightgreen)]()

> **Motor de análisis de inversiones a largo plazo orientado al retiro.**  
> Calificá, filtrá y optimizá un universo de acciones en segundos — con score fundamental 0–100, Economic Moat, decisión AI y simulaciones de riesgo — todo en una sola app local, sin subscripciones.

---

## ¿Qué hace?

Retirement Advisor analiza automáticamente un universo de 38+ tickers (acciones US, ETFs y ADRs argentinos) combinando:

- **Análisis fundamental profundo** en 5 dimensiones (rentabilidad, salud financiera, valuación, crecimiento, dividendos)
- **Consistency Score + Piotroski F-Score** para calidad contable real
- **Economic Moat** cuantitativo + evaluación qualitativa por AI
- **Análisis técnico** (SMA200, RSI, MACD, ADX, Bollinger) sobre barras semanales de 10 años
- **Decisión AI** con razonamiento en lenguaje natural (Claude, GPT-4o, Grok o Nous)
- **Optimizador de portafolio** Mean-Variance con 3 perfiles de riesgo
- **Monte Carlo** block-bootstrap con 10 000 simulaciones
- **Stress testing** en 6 crisis históricas
- **Watchlist** con alertas de precio en tiempo real
- **Motor de alertas** persistente con email, Telegram y reportes PDF mensuales

---

## Screenshots

### 🏠 Screener — ranking de todo el universo
```
┌─────────────────────────────────────────────────────────────────────┐
│  📊 Opportunity Screener                                            │
│                                                                     │
│  Strong/Buy: 14  │  Hold: 18  │  Sell/Reduce: 6  │  Screened: 38  │
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

### 📈 Portfolio Optimizer — Efficient Frontier
```
┌─────────────────────────────────────────────────────────────────────┐
│  📈 Portfolio Optimizer                   Perfil: Moderado  ▼       │
│                                                                     │
│  Retorno esp.  │  Volatilidad  │  Sharpe  │  Div. Yield             │
│     14.2%      │     15.8%     │   0.90   │    2.3%                 │
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
└─────────────────────────────────────────────────────────────────────┘
```

> 📸 *Los screenshots anteriores son representaciones en ASCII. Para ver la app real en acción, ejecutá `streamlit run dashboard/app.py` después de instalar.*

---

## Quick Start

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

---

## Páginas del dashboard

| Página | ¿Para qué? |
|--------|-----------|
| **🏠 Screener** | Ranking completo del universo — empezá aquí |
| **🔍 Stock Analysis** | Análisis profundo de un ticker: Piotroski, Moat, AI |
| **💼 Portfolio** | Posiciones abiertas, P&L, gráficos de sector |
| **📊 Allocation** | Regla conservadora acciones/bonos/cash según tu edad |
| **📈 Optimizer** | Cartera óptima Mean-Variance con Efficient Frontier |
| **📉 Backtesting** | Curva de equity histórica, Sharpe, Sortino, Calmar |
| **🎲 Simulaciones** | Monte Carlo 10k sims + stress test 6 crisis históricas |
| **🔔 Alertas** | Motor de alertas + email/Telegram + reportes PDF |
| **📋 Watchlist** | Tickers favoritos con alertas de precio en tiempo real |
| **⚙️ Settings** | Universo, AI, cache |

**Flujo recomendado**: Screener → Stock Analysis → Optimizer → Portfolio

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

| Proveedor | `AI_PROVIDER` | Modelos recomendados |
|-----------|--------------|----------------------|
| Anthropic (Claude) | `claude` | `claude-sonnet-4-6`, `claude-opus-4-7` |
| OpenAI | `openai` | `gpt-4o`, `gpt-4o-mini` |
| xAI (Grok) | `xai` | `grok-4` |
| Nous Research | `nous` | `nousresearch/hermes-4` |

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

```
adjusted_score = min(fundamental + consistency + piotroski_bonus + moat_bonus, 100)
```

### Economic Moat (0–20 pts)

| Fuente | Pts | Método |
|--------|-----|--------|
| Cuantitativo | 0–12 | Retornos sobre capital, márgenes, pricing power, eficiencia |
| AI cualitativo | 0–8 | LLM evalúa 4 dimensiones: network effects, switching costs, brand, regulatory moat |

Clasificación: **Wide** ≥14 / **Narrow** ≥8 / **Minimal** ≥4 / **None**

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

Scipy SLSQP minimizando Sharpe negativo sujeto a constraints por posición, sector, volatilidad y dividend yield:

| Perfil | Max Vol | Min Div | Max Pos |
|--------|---------|---------|---------|
| Conservador | 12% | 3.5% | 8% |
| Moderado | 18% | 2.5% | 12% |
| Agresivo | 25% | 1.5% | 18% |

Fallback score-weighted cuando SLSQP es infeasible (e.g., universo growth-heavy con perfil Conservador).

### Monte Carlo

Block-bootstrap sobre retornos semanales históricos de 10 años:
- Bloques de 4 semanas → preserva autocorrelación y fat tails (sin asunción gaussiana)
- Ajuste conservador: +10% volatilidad, -20% retorno esperado
- 10 000 simulaciones en < 2 segundos (vectorizado con NumPy)
- Fan chart con percentiles 5/10/25/50/75/90/95

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

### Smart Alerts

5 tipos de alerta con debounce inteligente (SQLite):

| Tipo | Cooldown |
|------|---------|
| Signal change | 24h |
| Score drop ≥ 8 pts | 168h (7d) |
| Score surge ≥ 8 pts + BUY | 168h |
| Nueva oportunidad (BUY/STRONG_BUY) | 72h |
| Moat downgrade | 336h (14d) |

Primera ejecución: guarda baseline silenciosamente sin disparar alertas (cold start).

---

## Universo de tickers por defecto

38 empresas, ETFs y ADRs argentinos (todos operados en USD):

```
US Mega-Cap: AAPL  MSFT  GOOGL  AMZN  NVDA  META  BRK-B
Financials:  JPM   V     MA     BAC
Healthcare:  JNJ   UNH   ABBV   PFE
Staples:     PG    KO    PEP    WMT
Industrials: HD    CAT   HON
Dividend:    O     T     XOM    CVX
ETFs:        SPY   QQQ   VTI    BND
Argentina ADRs (USD): YPF  PAM  CEPU  LOMA  MELI  GLOB  TEO  EDN
```

Los ADRs argentinos aplican un descuento de 15% en el composite score para los perfiles Conservador y Moderado (riesgo macro ARS).

Para modificar el universo: editar `DEFAULT_TICKERS` en `config.py` o usar **⚙️ Settings** en el dashboard.

---

## Fuente de datos

Todos los datos provienen de **Yahoo Finance** vía `yfinance` (gratuito, sin API key):

- **Fundamentals**: `yf.Ticker().info`, `.financials`, `.balance_sheet`, `.cashflow`, `.dividends`
- **Técnicos**: precios semanales históricos de 10 años + cálculo local con `pandas_ta`
- **Cache**: SQLite local con TTL configurable (default 24h)

---

## Tests

```bash
pip install pytest
pytest tests/ -v
```

133 tests cubriendo: `StressTester`, `EnhancedScoring`, `Piotroski`, `MonteCarloSimulator`, `AlertEngine`, `PortfolioOptimizer`, `ConfigValidator`.

Los tests de Monte Carlo y Optimizer mockean `get_history` para no hacer llamadas de red.

---

## Scheduler de alertas y reportes

El scheduler corre en background:
- **Alertas** cada `ALERT_INTERVAL_HOURS` horas — analiza el universo y despacha notificaciones si hay cambios de señal, caídas de score u oportunidades
- **Reporte PDF mensual** el día `REPORT_DAY` de cada mes a las 08:00

```bash
source venv/bin/activate
python scripts/run_scheduler.py
```

Los logs se escriben en `logs/retirement_advisor.log` (rotación 10 MB, retención 7 días).

### Cron (Linux/macOS)

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

```bash
# Dashboard
docker run -d --name ra-dashboard \
  -p 8501:8501 \
  --env-file .env \
  -v $(pwd)/data/db:/app/data/db \
  -v $(pwd)/reports:/app/reports \
  retirement-advisor

# Scheduler
docker run -d --name ra-scheduler \
  --env-file .env \
  -v $(pwd)/data/db:/app/data/db \
  -v $(pwd)/reports:/app/reports \
  retirement-advisor \
  python scripts/run_scheduler.py
```

---

## Estructura del proyecto

```
retirement_advisor/
├── config.py                    # Umbrales, perfiles, universo de tickers
├── requirements.txt
├── .env.example
├── analysis/
│   ├── fundamental.py           # Score fundamental (5 dimensiones, 0–100)
│   ├── scoring.py               # Consistency Score + Piotroski F-Score
│   ├── moat.py                  # Economic Moat cuantitativo + AI (0–20)
│   ├── technical.py             # Indicadores técnicos semanales
│   ├── strategy.py              # full_analysis() — orquestador principal
│   └── ai_analyzer.py           # Capa AI (Claude / GPT-4o / Grok / Nous)
├── data/
│   ├── fetcher.py               # Wrapper yfinance con caché
│   ├── cache.py                 # SQLite cache TTL
│   └── preferences.py           # UserPreferences — watchlist, alertas, config
├── portfolio/
│   ├── optimizer.py             # Mean-Variance SLSQP + 3 perfiles
│   ├── monte_carlo.py           # Block-bootstrap Monte Carlo
│   ├── stress_test.py           # 6 escenarios de crisis histórica
│   ├── tracker.py               # Posiciones, P&L, métricas de riesgo
│   └── allocation.py            # Asset allocation por edad
├── alerts/
│   ├── engine.py                # Motor de detección de alertas
│   ├── store.py                 # Persistencia SQLite (snapshots + historial)
│   ├── notifier.py              # Email + Telegram
│   └── reporter.py              # Generación de PDFs con reportlab
├── scripts/
│   └── run_scheduler.py         # Scheduler: alertas diarias + PDF mensual
├── tests/
│   ├── conftest.py
│   ├── test_scoring.py
│   ├── test_stress_test.py
│   ├── test_monte_carlo.py
│   ├── test_alert_engine.py
│   └── test_optimizer.py
├── docs/
│   ├── architecture.md
│   ├── moat_methodology.md
│   ├── portfolio_optimizer.md
│   ├── alert_system.md
│   └── ROADMAP.md
└── dashboard/
    ├── app.py                   # Entry point Streamlit + home page
    ├── shared.py                # Helpers, cache wrappers, parallel fetcher
    └── pages/                   # 10 páginas multipage
        ├── 1_Screener.py
        ├── 2_Stock_Analysis.py
        ├── 3_Portfolio.py
        ├── 4_Allocation.py
        ├── 5_Optimizer.py
        ├── 6_Backtesting.py
        ├── 7_Simulaciones.py
        ├── 8_Alertas.py
        ├── 9_Settings.py
        ├── 10_About.py
        └── 11_Watchlist.py
```

---

## Limitaciones conocidas

- **Datos**: Yahoo Finance puede tener datos faltantes o inconsistentes en empresas pequeñas. El sistema cae a valores neutrales cuando hay datos parciales.
- **Monte Carlo**: El block-bootstrap usa historia real — no modela cambios estructurales (nuevas regulaciones, disrupciones de sector).
- **AI Moat**: La evaluación cualitativa está basada en training data del LLM y puede estar desactualizada para empresas que cambian rápido.
- **Optimización**: El perfil Conservador puede ser matemáticamente infeasible con el universo default (vol 12% + div 3.5% son constraints difíciles de cumplir con acciones growth). En ese caso se aplica fallback score-weighted.
- **Stress test**: Los shocks sectoriales son calibrados desde datos históricos; una crisis futura podría diferir materialmente.
- **No es asesoramiento financiero**: Esta herramienta es educativa. Consultá con un asesor certificado antes de tomar decisiones de inversión.

---

## Licencia

MIT
