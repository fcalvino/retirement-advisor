# Retirement Advisor

Herramienta de análisis de inversiones a largo plazo (horizonte 10–30 años) orientada al retiro. Combina análisis fundamental, técnico y un motor de decisión para calificar acciones de 0 a 100 y emitir señales de compra/venta.

---

## Instalación

Requiere Python 3.10+. Desde el directorio `outputs/`:

```bash
pip install -r retirement_advisor/requirements.txt
```

---

## Modos de uso

### 1. CLI (línea de comandos)

Desde `outputs/retirement_advisor/`:

```bash
# Análisis completo de un ticker
../venv/bin/python main.py analyze AAPL

# Análisis de varios tickers a la vez
../venv/bin/python main.py analyze AAPL MSFT GOOGL META

# Screener del universo completo (24 tickers por defecto)
../venv/bin/python main.py screen

# Screener limitado a los primeros N tickers
../venv/bin/python main.py screen --n 10

# Resumen del portafolio guardado
../venv/bin/python main.py portfolio

# Lanzar el dashboard web
../venv/bin/python main.py dashboard
```

### 2. Dashboard web (Streamlit)

```bash
../venv/bin/python main.py dashboard
```

Abre `http://localhost:8501` en el navegador. Tiene 5 secciones:

| Sección | Qué hace |
|---------|----------|
| **Screener** | Ranking de todos los tickers con scores y señales |
| **Stock Analysis** | Análisis detallado de un ticker: score por dimensión, gráfico de precio, decisión |
| **Portfolio** | Posiciones abiertas, P&L, gráfico de pesos por sector |
| **Allocation** | Recomendación de asset allocation según tu edad (acciones / bonos / cash) |
| **Settings** | Editar el universo de tickers, limpiar caché |

---

## Cómo leer los resultados

### Score fundamental (0–100)

El sistema califica cada empresa en 5 dimensiones:

| Dimensión | Peso | Qué mide |
|-----------|------|----------|
| Profitability | 25 pts | ROE, ROIC, margen neto, margen bruto |
| Financial Health | 20 pts | Deuda/patrimonio, current ratio, cobertura de intereses |
| Valuation | 25 pts | P/E, PEG, EV/EBITDA, P/B |
| Growth | 20 pts | CAGR de ingresos y EPS a 5 años, FCF yield |
| Dividends | 10 pts | Yield, payout ratio, años consecutivos de crecimiento |

### Señal de decisión

| Score | Técnico | Decisión |
|-------|---------|----------|
| ≥ 75 | Alcista o neutro | **STRONG BUY** |
| ≥ 60 | No bajista | **BUY** |
| ≥ 45 | Cualquiera | **HOLD** |
| 35–44 | Cualquiera | **REDUCE** |
| < 35 | Cualquiera | **SELL** |

Bloqueos automáticos (override al score): deuda/patrimonio > 3, patrimonio negativo, RSI semanal > 80.

### Graham Value y Margen de Seguridad

Calcula el valor intrínseco con la fórmula de Graham:

```
Valor = EPS × (8.5 + 2 × tasa_de_crecimiento) × 4.4 / tasa_AAA
```

El **Margen de Seguridad** es qué tan por debajo del valor Graham cotiza el precio actual. Valores > 25% son atractivos.

---

## Universo de tickers por defecto

24 empresas y ETFs de gran capitalización estadounidense:

```
AAPL  MSFT  GOOGL  AMZN  NVDA  META  BRK-B  JPM  V  MA
BAC   JNJ   UNH    ABBV  PFE   PG    KO     PEP  WMT  HD
SPY   QQQ   VYM    SCHD
```

Para agregar o quitar tickers, editar `config.py` → `DEFAULT_TICKERS`, o usar la sección **Settings** del dashboard.

---

## Portafolio

Agregar una posición (desde el dashboard → Stock Analysis → "Add to Portfolio", o editando `data/db/portfolio.json` manualmente):

```json
{
  "MSFT": {
    "shares": 10,
    "avg_cost": 380.00,
    "purchase_date": "2024-01-15"
  }
}
```

El portafolio calcula automáticamente: P&L total, retorno anualizado, Sharpe ratio, max drawdown y beta vs SPY.

---

## Alertas (opcional)

Configurar en `config.py` o variables de entorno:

```bash
# Email
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
EMAIL_FROM=tu@gmail.com
EMAIL_TO=destino@gmail.com
SMTP_PASSWORD=tu_app_password

# Telegram
TELEGRAM_TOKEN=tu_bot_token
TELEGRAM_CHAT_ID=tu_chat_id
```

Las alertas se disparan automáticamente cuando la señal de un ticker cambia (ej: HOLD → BUY).

---

## Caché

Los datos de yfinance se cachean en SQLite para evitar llamadas repetidas a la API. TTL por defecto: 4 horas.

```bash
# Limpiar caché completo (fuerza datos frescos)
../venv/bin/python -c "from data.cache import cache; cache.clear_all()"
```

---

## Estructura del proyecto

```
retirement_advisor/
├── main.py               # CLI entry point
├── config.py             # Umbrales, universo de tickers, configuración de alertas
├── requirements.txt
├── data/
│   ├── cache.py          # SQLite cache con TTL
│   └── fetcher.py        # Wrapper de yfinance
├── analysis/
│   ├── fundamental.py    # Scoring fundamental (5 dimensiones)
│   ├── technical.py      # Indicadores técnicos en barras semanales
│   └── strategy.py       # Motor de decisión + full_analysis()
├── portfolio/
│   ├── tracker.py        # Posiciones, P&L, métricas de riesgo
│   └── allocation.py     # Asset allocation por edad
├── alerts/
│   └── notifier.py       # Email y Telegram
└── dashboard/
    └── app.py            # UI web con Streamlit
```
