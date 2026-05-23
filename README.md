# Retirement Advisor

Herramienta de análisis de inversiones a largo plazo (horizonte 10–30 años) orientada al retiro. Combina análisis fundamental, técnico y un motor de decisión AI para calificar acciones de 0 a 100 y emitir señales de compra/venta con razonamiento en lenguaje natural.

---

## Instalación

### Requisitos

- Python 3.10+
- Git

### Pasos

```bash
# 1. Clonar el repositorio
git clone https://github.com/fcalvino/retirement-advisor.git
cd retirement-advisor

# 2. Crear entorno virtual
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Configurar variables de entorno
cp .env.example .env
# Editar .env con tu configuración (ver sección Configuración)

# 5. Lanzar el dashboard
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
ANTHROPIC_API_KEY=sk-ant-...   # Si usás Claude
# OPENAI_API_KEY=sk-...        # Si usás GPT-4o
# XAI_API_KEY=...              # Si usás Grok directamente
```

### Proveedores AI soportados

| Proveedor | `AI_PROVIDER` | Modelos recomendados |
|-----------|--------------|----------------------|
| Anthropic (Claude) | `claude` | `claude-sonnet-4-6`, `claude-opus-4-7` |
| OpenAI | `openai` | `gpt-4o`, `gpt-4o-mini` |
| xAI (Grok) | `xai` | `grok-4.3` |
| Nous Research | `nous` | `nousresearch/hermes-4-70b` |

> Para xAI y Nous también podés autenticarte vía [Hermes OAuth](https://hermes-agent.nousresearch.com/) sin API key explícita.

Si no configurás AI, el sistema cae automáticamente al motor de decisión rule-based.

---

## Dashboard

El dashboard tiene 5 secciones:

| Sección | Descripción |
|---------|-------------|
| **Screener** | Ranking de todos los tickers con scores, señales y métricas clave |
| **Stock Analysis** | Análisis detallado: score por dimensión, gráfico de precio, decisión AI |
| **Portfolio** | Posiciones abiertas, P&L, gráfico de pesos por sector |
| **Allocation** | Recomendación de asset allocation según tu edad (acciones / bonos / cash) |
| **Settings** | Editar universo de tickers, configurar AI, limpiar caché |

---

## Cómo funciona

### Score fundamental (0–100)

Cada empresa se califica en 5 dimensiones:

| Dimensión | Peso | Métricas |
|-----------|------|----------|
| Profitability | 25 pts | ROE, ROIC, margen neto, margen bruto |
| Financial Health | 20 pts | Deuda/patrimonio, current ratio, cobertura de intereses |
| Valuation | 25 pts | P/E, PEG, EV/EBITDA, P/B |
| Growth | 20 pts | CAGR de ingresos y EPS a 5 años, FCF yield |
| Dividends | 10 pts | Yield, payout ratio |

### Análisis técnico

Indicadores calculados sobre **barras semanales de 10 años**:

- SMA200 y su pendiente a 26 semanas
- RSI semanal
- MACD (alcista/bajista)
- ADX (fuerza de tendencia)
- Bandas de Bollinger
- Distancia desde máximo/mínimo de 52 semanas

### Decisión

Con AI activado, un LLM recibe todos los datos fundamentales y técnicos y devuelve una recomendación con razonamiento en español. Sin AI, se usa un motor rule-based:

| Score | Técnico | Decisión |
|-------|---------|----------|
| ≥ 75 | Alcista o neutro | **STRONG BUY** |
| ≥ 60 | No bajista | **BUY** |
| ≥ 45 | Cualquiera | **HOLD** |
| 35–44 | Cualquiera | **REDUCE** |
| < 35 | Cualquiera | **SELL** |

Bloqueos automáticos (override al score): D/E > 3, patrimonio negativo, RSI semanal > 80 con movimiento parabólico.

### Graham Value

Valor intrínseco estimado con la fórmula de Benjamin Graham:

```
Valor = EPS × (8.5 + 2 × tasa_crecimiento) × 4.4 / tasa_AAA
```

El **Margen de Seguridad** indica cuánto por debajo del valor Graham cotiza el precio actual. > 25% es atractivo.

---

## Universo de tickers por defecto

39 empresas, ETFs y ADRs argentinos:

```
# US Mega-Cap
AAPL  MSFT  GOOGL  AMZN  NVDA  META  BRK-B

# Financials
JPM  V  MA  BAC

# Healthcare
JNJ  UNH  ABBV  PFE

# Consumer Staples
PG  KO  PEP  WMT

# Industrials
HD  CAT  HON

# Dividend / Energy
O  T  XOM  CVX

# ETFs
SPY  QQQ  VTI  BND

# Argentina ADRs
YPF  PAM  CEPU  LOMA  MELI  GLOB  DESP  TEO  EDN
```

Para modificar el universo: editar `DEFAULT_TICKERS` en `config.py` o usar **Settings** en el dashboard.

---

## Fuente de datos

Todos los datos provienen de **Yahoo Finance** vía `yfinance` (gratuito, sin API key):

- **Fundamentals**: `yf.Ticker().info`, `.financials`, `.balance_sheet`, `.cashflow`, `.dividends`
- **Técnicos**: precios semanales históricos de 10 años + cálculo local con `pandas_ta`
- **Cache**: SQLite local con TTL configurable (default 24h) para evitar llamadas repetidas

---

## Estructura del proyecto

```
retirement_advisor/
├── main.py               # CLI entry point
├── config.py             # Universo de tickers, umbrales, configuración AI
├── requirements.txt
├── .env.example
├── analysis/
│   ├── fundamental.py    # Scoring fundamental (5 dimensiones, 0–100)
│   ├── technical.py      # Indicadores técnicos en barras semanales
│   ├── strategy.py       # Motor de decisión + full_analysis()
│   └── ai_analyzer.py    # Motor AI (Claude / GPT-4o / Grok / Nous)
├── data/
│   ├── fetcher.py        # Wrapper de yfinance con cache
│   └── cache.py          # SQLite cache con TTL
├── portfolio/
│   ├── tracker.py        # Posiciones, P&L, métricas de riesgo
│   └── allocation.py     # Asset allocation por edad
├── alerts/
│   └── notifier.py       # Alertas por email y Telegram
└── dashboard/
    └── app.py            # UI web con Streamlit
```

---

## Alertas (opcional)

Configurar en `.env`:

```bash
# Email
EMAIL_FROM=tu@gmail.com
EMAIL_TO=destino@gmail.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_PASSWORD=tu_app_password

# Telegram
TELEGRAM_TOKEN=tu_bot_token
TELEGRAM_CHAT_ID=tu_chat_id
```

---

## Licencia

MIT
