# Retirement Advisor

Herramienta de análisis de inversiones a largo plazo orientada al retiro. Combina análisis fundamental profundo, análisis técnico, Economic Moat, optimización de portafolio Mean-Variance, simulación Monte Carlo, stress testing y un motor de decisión con soporte AI para calificar acciones de 0 a 100 y emitir señales de inversión con razonamiento en lenguaje natural.

---

## Features

| Módulo | Descripción |
|--------|-------------|
| **Screener** | Ranking de 38+ tickers con score ajustado, señal y métricas clave |
| **Stock Analysis** | Score por dimensión, Piotroski F-Score, Consistency Score, Economic Moat, gráfico de precio, decisión AI |
| **Portfolio Tracker** | Posiciones abiertas, P&L, gráficos de pesos por sector |
| **Asset Allocation** | Recomendación conservadora de acciones/bonos/cash según edad |
| **Backtesting** | Curva de equity histórica, Sharpe, Sortino, Calmar, scatter Score↔CAGR |
| **Portfolio Optimizer** | Mean-Variance SLSQP con 3 perfiles de riesgo, Efficient Frontier |
| **Simulaciones** | Monte Carlo block-bootstrap (10 000 sims), fan chart, stress test de crisis históricas |
| **Alertas** | Motor de alertas persistente (SQLite), email y Telegram, generación de PDFs mensuales |
| **Settings** | Editor de universo, configuración AI, limpieza de caché |

---

## Instalación

### Requisitos

- Python 3.10+
- Git

### Pasos

```bash
git clone https://github.com/fcalvino/retirement-advisor.git
cd retirement-advisor

python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# Editar .env con tu configuración

streamlit run dashboard/app.py
```

Abrí `http://localhost:8501` en el navegador.

---

## Configuración (.env)

```bash
# Cache (horas antes de refrescar datos de Yahoo Finance)
CACHE_TTL_HOURS=24

# AI Analysis
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

### Bonos de calidad (Score Ajustado)

Sobre el score base se suman tres bonos:

| Componente | Pts máx | Lógica |
|------------|---------|--------|
| **Consistency Score** | +15 | Estabilidad de ROE, EPS y márgenes a 4+ años (std/CV) |
| **Piotroski F-Score** | +6 / +12 | 9 checks YoY de rentabilidad, liquidez y eficiencia |
| **Moat Bonus** | +10 | `min(moat_score × 0.5, 10)` según clasificación Wide/Narrow/Minimal |

`adjusted_score = min(base + consistency + piotroski_bonus + moat_bonus, 100)`

### Economic Moat (0–20 pts)

| Fuente | Pts | Método |
|--------|-----|--------|
| Cuantitativo | 0–12 | Retornos sobre capital, márgenes, pricing power, eficiencia |
| AI cualitativo | 0–8 | LLM evalúa 4 dimensiones: network effects, switching costs, brand, regulatory moat |

Clasificación: Wide ≥14 / Narrow ≥8 / Minimal ≥4 / None

### Análisis técnico

Indicadores calculados sobre **barras semanales de 10 años**:

- SMA200 y pendiente a 26 semanas
- RSI semanal
- MACD semanal
- ADX (fuerza de tendencia)
- Bandas de Bollinger
- Distancia desde máximo/mínimo de 52 semanas

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

Usa scipy SLSQP para minimizar el Sharpe negativo sujeto a:

- Pesos suman 1.0
- Máximo por posición (`max_position_pct`)
- Máximo por sector (`max_sector_pct`)
- Volatilidad anualizada ≤ `max_volatility_pct`
- Dividend yield ≥ `min_dividend_yield_pct`
- Mínimo de posiciones (`min_positions`)

Tres perfiles:

| Perfil | Max Vol | Min Div | Max Pos |
|--------|---------|---------|---------|
| Conservador | 12% | 3.5% | 8% |
| Moderado | 18% | 2.5% | 12% |
| Agresivo | 25% | 1.5% | 18% |

El return esperado por ticker es: `score_weight×(score/100×0.18) + div_weight×(yield/100) + moat_weight×(moat/20×0.05)`.

Fallback score-weighted cuando SLSQP no converge (e.g., perfil Conservador con universo growth-heavy).

### Monte Carlo

Metodología block-bootstrap sobre retornos semanales históricos (10 años):
- Bloques de 4 semanas → preserva autocorrelación y fat tails (sin asunción gaussiana)
- Ajuste conservador: +10% volatilidad, -20% retorno esperado vs. historia
- 10 000 simulaciones en < 2 segundos (vectorizado con NumPy)
- Fan chart con percentiles 5/10/25/50/75/90/95

### Stress Testing

6 escenarios históricos/hipotéticos con shocks por sector calibrados de Bloomberg/FRED:

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

Los ADRs argentinos aplican un descuento de 15% en el composite score para los perfiles Conservador y Moderado (riesgo macro ARS). Todos cotizan en USD.

Para modificar el universo: editar `DEFAULT_TICKERS` en `config.py` o usar **Settings** en el dashboard.

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

Cobertura actual: 133 tests — `StressTester`, `EnhancedScoring`, `Piotroski`, `MonteCarloSimulator`, `AlertEngine`, `PortfolioOptimizer`, `ConfigValidator` (Hermes OAuth).

Los tests de Monte Carlo y Optimizer mockean `get_history` para no hacer llamadas de red.

---

## Scheduler de alertas y reportes

El scheduler corre en background y realiza dos tareas:
- **Chequeo de alertas** cada `ALERT_INTERVAL_HOURS` horas (default: 24) — analiza el universo completo y despacha notificaciones por email/Telegram si hay cambios de señal, caídas de score u oportunidades.
- **Reporte PDF mensual** el día `REPORT_DAY` de cada mes a las 08:00 — genera y envía el informe completo.

### Ejecución manual

```bash
# Desde la raíz del proyecto, con el venv activado:
source venv/bin/activate
python scripts/run_scheduler.py
```

Los logs se escriben en `logs/retirement_advisor.log` (rotación 10 MB, retención 7 días).

### Cron (Linux/macOS)

Para que corra automáticamente al reiniciar el sistema, agregá una entrada con `crontab -e`:

```cron
# Lanzar scheduler al reiniciar (redirige stderr al log)
@reboot cd /ruta/a/retirement_advisor && /ruta/a/venv/bin/python scripts/run_scheduler.py >> logs/scheduler.log 2>&1
```

### systemd (Linux)

Creá `/etc/systemd/system/retirement-advisor-scheduler.service`:

```ini
[Unit]
Description=Retirement Advisor — Scheduler de alertas
After=network-online.target
Wants=network-online.target

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

```bash
sudo systemctl daemon-reload
sudo systemctl enable retirement-advisor-scheduler
sudo systemctl start retirement-advisor-scheduler
sudo systemctl status retirement-advisor-scheduler
```

### Docker (dashboard + scheduler juntos)

Para correr ambos procesos con Docker, levantá cada uno en su propio contenedor compartiendo el volumen de datos:

```bash
# Dashboard
docker run -d --name ra-dashboard \
  -p 8501:8501 \
  --env-file .env \
  -v $(pwd)/data/db:/app/data/db \
  -v $(pwd)/reports:/app/reports \
  retirement-advisor

# Scheduler (mismo imagen, comando distinto)
docker run -d --name ra-scheduler \
  --env-file .env \
  -v $(pwd)/data/db:/app/data/db \
  -v $(pwd)/reports:/app/reports \
  retirement-advisor \
  python scripts/run_scheduler.py
```

> Ambos contenedores comparten los volúmenes `data/db` (cache SQLite + alertas) y `reports` (PDFs generados).

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
│   └── cache.py                 # SQLite cache TTL
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
│   ├── conftest.py              # Fixtures compartidos
│   ├── test_scoring.py          # EnhancedScoring, Piotroski, Consistency
│   ├── test_stress_test.py      # StressTester — matemática pura
│   ├── test_monte_carlo.py      # MonteCarloSimulator (mocked fetcher)
│   ├── test_alert_engine.py     # AlertEngine (mocked store)
│   └── test_optimizer.py        # PortfolioOptimizer (mocked fetcher)
├── docs/
│   ├── architecture.md          # Mapa de módulos y flujo de datos
│   ├── moat_methodology.md      # Metodología Economic Moat
│   ├── portfolio_optimizer.md   # Metodología optimizer
│   ├── alert_system.md          # Sistema de alertas y scheduler
│   └── ROADMAP.md               # Historial de fases
└── dashboard/
    └── app.py                   # UI Streamlit — 9 páginas
```

---

## Limitaciones conocidas

- **Datos**: Yahoo Finance puede tener datos faltantes o inconsistentes, especialmente en balance sheets de empresas pequeñas. El sistema cae a valores neutrales cuando hay datos parciales.
- **Monte Carlo**: El block-bootstrap usa historia real para construir distribuciones futuras — no modela cambios estructurales (e.g., regulaciones nuevas, disrupciones de sector).
- **AI Moat**: La evaluación cualitativa de moat por LLM está basada en conocimiento de training data y puede estar desactualizada para empresas que cambian rápidamente.
- **Optimización**: El perfil Conservador puede ser matemáticamente infeasible con el universo default (volatilidad 12% + dividend yield 3.5% son constraints difíciles de cumplir simultáneamente con acciones growth). En ese caso se aplica fallback score-weighted.
- **Stress test**: Los shocks sectoriales son calibrados desde datos históricos de Bloomberg/FRED, pero una crisis futura podría diferir materialmente.
- **No es asesoramiento financiero**: Esta herramienta es educativa. Consultá con un asesor certificado antes de tomar decisiones de inversión.

---

## Licencia

MIT
