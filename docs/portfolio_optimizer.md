# Portfolio Optimizer — Metodología

> **Módulo:** `portfolio/optimizer.py` | **Config:** `config.py → ProfileConfig, OptimizerConfig`

## Visión general

El Portfolio Optimizer construye una cartera óptima para retiro combinando tres dimensiones:

1. **Score Ajustado** — calidad fundamental + consistencia + Piotroski + moat
2. **Dividend Yield** — ingreso recurrente en USD
3. **Moat Score** — ventaja competitiva duradera (0–20)

La optimización usa **Mean-Variance (SLSQP)** de scipy para maximizar el Sharpe Ratio sujeto a restricciones duras de riesgo, con fallback a asignación proporcional por score cuando SLSQP no converge.

---

## Flujo de optimización

```
scored_tickers (de Screener/Stock Analysis)
        │
        ▼
1. Filtrar: excluir ETFs y tickers con score < 30
        │
        ▼
2. Aplicar ARS risk discount (perfiles Conservador/Moderado)
        │
        ▼
3. Construir matriz de precios semanales (2 años, yfinance)
        │
        ▼
4. Calcular retorno esperado proxy + matriz de covarianza anualizada
        │
        ▼
5. SLSQP: minimizar −Sharpe sujeto a restricciones del perfil
        │         (2 intentos: dividend-biased y equal-weight start)
        ▼
6. Fallback score-weighted si SLSQP no converge
        │
        ▼
7. Monte Carlo Efficient Frontier (300 carteras aleatorias)
        │
        ▼
8. Sugerencias de rebalanceo vs. cartera actual
        │
        ▼
9. Frecuencia de rebalanceo recomendada según perfil
```

---

## Retorno esperado proxy

El retorno esperado de cada ticker es una combinación ponderada de tres componentes:

```
μ_i = score_weight × (score/100 × 0.18)
    + dividend_weight × (div_yield/100)
    + moat_weight × (moat/20 × 0.05)
```

Los pesos (`score_weight`, `dividend_weight`, `moat_weight`) varían según el perfil:

| Perfil | Score | Dividendo | Moat |
|---|---|---|---|
| Conservador | 35% | 45% | 20% |
| Moderado | 50% | 30% | 20% |
| Agresivo | 65% | 15% | 20% |

El componente Moat está fijo en 20% en todos los perfiles — el moat es crítico para retiro independientemente del apetito de riesgo.

---

## Tres perfiles de riesgo

| Parámetro | Conservador | Moderado | Agresivo |
|---|---|---|---|
| Pos. máx. por ticker | 8% | 12% | 18% |
| Vol. anual máx. | 12% | 18% | 25% |
| Div. yield mín. | 3.5% | 2.5% | 1.5% |
| Sector máx. | 20% | 25% | 30% |
| Min. posiciones | 10 | 8 | 5 |
| Rebalanceo recomendado | Anual | Semestral | Trimestral |

---

## Restricciones SLSQP

El optimizador impone simultáneamente:

```
Σ w_i = 1                          (suma a 100%)
w_i ∈ [1%, ub_i]                   (mín 1% por ticker, máx = pos. máx. del perfil)
√(w' Σ w) ≤ max_volatility_pct     (techo de volatilidad anual)
Σ_i w_i × div_i ≥ min_dividend     (piso de dividend yield)
Σ_{i ∈ sector} w_i ≤ max_sector    (techo por sector)
```

**Bound adaptativo:** `ub = max(pos_max/100, 1/n)` garantiza que la restricción de suma siempre sea satisfacible cuando n es pequeño.

---

## Fallback score-weighted

Cuando SLSQP no converge (infeasible o datos insuficientes), se usa asignación proporcional:

```python
w_i = score_i / Σ score_j   →   clip a pos_max   →   renormalizar (5 iteraciones)
```

El fallback puede violar el techo de volatilidad y el piso de dividendos del perfil. El dashboard muestra warnings explícitos cuando esto ocurre.

**¿Por qué puede ser infactible el perfil Conservador?**  
El universo por defecto tiene pocas acciones de alto dividendo (mayoría son growth: MSFT, NVDA, META, GOOGL). La combinación `vol ≤ 12% + div ≥ 3.5%` puede ser matemáticamente imposible. Las advertencias guían al usuario a agregar tickers de dividendo o cambiar de perfil.

---

## ARS Risk Discount

Los tickers argentinos (`YPF`, `PAM`, `CEPU`, `LOMA`, `TEO`, `EDN`) son **ADRs que cotizan en USD** en NYSE/NYSE American — no hay conversión de moneda al comprar.

Sin embargo, su valor en pesos está expuesto a:
- Devaluación del ARS
- Controles de capital (cepo cambiario)
- Riesgo de intervención política (especialmente YPF)

Por eso, en perfiles Conservador y Moderado, se aplica un descuento del **15%** al Score Ajustado antes de la optimización:

```python
score_ajustado_efectivo = score_ajustado × 0.85
```

En perfil Agresivo, el descuento no se aplica — el usuario está asumiendo explícitamente mayor riesgo.

---

## Matriz de covarianza

```python
retornos_semanales = precio_semanal.pct_change().dropna()
cov_anual = retornos_semanales.cov() × 52 + I × 1e-6
```

La regularización diagonal (1e-6) evita matrices casi-singulares y mejora la estabilidad numérica de SLSQP.

**Datos requeridos:** mínimo 2 años × 40 semanas = 80 observaciones por ticker. Tickers con menos datos son excluidos del SLSQP (pero pueden aparecer en el fallback score-weighted).

---

## Frontera Eficiente (Monte Carlo)

Se generan 300 carteras aleatorias con restricciones de peso máximo por ticker:

```python
w ~ Dirichlet(1) → clip a max_pos → renormalizar
retorno, volatilidad, Sharpe → graficar scatter
```

La estrella azul marca la cartera óptima (máximo Sharpe dentro de las restricciones). La línea roja vertical marca el techo de volatilidad del perfil.

---

## Frecuencia de rebalanceo recomendada

| Perfil | Frecuencia base | Condición de ajuste |
|---|---|---|
| Conservador | Anual | → Semestral si vol > 18% |
| Moderado | Semestral | → Trimestral si vol > 18% |
| Agresivo | Trimestral | Sin ajuste |

El objetivo es minimizar costos de transacción y eventos imponibles, especialmente en perfiles conservadores donde la estabilidad prima sobre la optimización continua.

---

## Configuración de umbrales

Todos los parámetros son ajustables en `config.py` sin tocar el código de optimización:

```python
@dataclass
class OptimizerConfig:
    default_profile: str = "conservative"
    risk_free_rate: float = 0.045        # tasa libre de riesgo (proxy 10Y Treasury)
    price_history_years: int = 2         # años de historia de precios
    frontier_points: int = 300           # carteras Monte Carlo
    min_weight_pct: float = 1.0          # peso mínimo por ticker (evita dust)
    min_score_threshold: float = 30.0    # score mínimo para ser elegible
    ars_risk_discount: float = 0.85      # descuento score para ADRs argentinos

CONSERVATIVE_PROFILE = ProfileConfig(
    max_position_pct=8.0,
    max_volatility_pct=12.0,
    min_dividend_yield_pct=3.5,
    max_sector_pct=20.0,
    min_positions=10,
    score_weight=0.35,
    dividend_weight=0.45,
    moat_weight=0.20,
)
```

---

## Limitaciones conocidas

1. **Retornos esperados son proxies, no predicciones.** El score y el moat capturan calidad histórica, no retornos futuros garantizados. La optimización maximiza Sharpe en el espacio de proxies, no sobre retornos reales.

2. **Covarianza histórica = correlaciones pasadas.** Las correlaciones pueden cambiar drásticamente en crisis (flight-to-quality, correlation breakdown). El portfolio resultante puede concentrarse más de lo esperado durante eventos de cola.

3. **Sin datos de opciones ni deuda.** La volatilidad se computa solo desde precios de cierre. No incorpora spreads bid/ask, costos de transacción, ni impuestos sobre dividendos.

4. **Perfil Conservador puede caer en score-weighted.** La combinación `vol ≤ 12% + div ≥ 3.5%` es genuinamente difícil de satisfacer con un universo orientado a growth. Las warnings en el dashboard son informativas, no errores.

5. **ADRs argentinos: cotización en USD, riesgo en ARS.** El descuento del 15% es una heurística conservadora. En períodos de estabilidad cambiaria, puede ser excesivo; en crisis, puede ser insuficiente.

---

## Archivos relacionados

| Archivo | Rol |
|---|---|
| `portfolio/optimizer.py` | Motor de optimización |
| `config.py → ProfileConfig` | Parámetros de cada perfil |
| `config.py → OptimizerConfig` | Configuración global del optimizador |
| `dashboard/app.py` | Página "📈 Optimizer" |
| `docs/moat_methodology.md` | Metodología del Moat Score |
