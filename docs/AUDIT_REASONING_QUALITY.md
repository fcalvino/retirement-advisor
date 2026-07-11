# Auditoría de calidad de razonamiento — Retirement Advisor

| Campo | Valor |
|-------|--------|
| **Fecha** | 2026-07-11 (audit) · **cierre residual D7–D15 2026-07-11** |
| **Alcance** | AI Analyzer, prompts, Moat, scoring fundamental, técnico, optimizer Mean-Variance, Monte Carlo, stress tester, alertas, crypto analyzer, strategy orchestrator, fetcher |
| **Modo de entrega** | Diagnóstico + implementación verificada (P0+P1+P2+P3 residuales) |
| **Tests en repo** | **575 passed** (`pytest -q --tb=no`, 2026-07-11) |
| **Estado** | **15/15 debilidades cerradas** (14 implementadas + 1 residual D4 blend documentado) |

---

## 1. Resumen ejecutivo

Retirement Advisor tiene una **arquitectura de capas bien pensada** (datos → scoring → decisión → portfolio → alertas) y una filosofía conservadora explícita en Monte Carlo (+10 % vol, −20 % mean) y en la documentación de moat. El modo **sin IA es de primera clase**: el motor rule-based y los fallbacks degradan con gracia.

Sin embargo, la **coherencia de razonamiento entre capas** presenta huecos de severidad alta que afectan la precisión del asesoramiento de retiro:

1. **La IA puede saltarse los hard-blocks de seguridad** del motor rule-based (apalancamiento, book value negativo, movimiento parabólico).
2. **La decisión equity usa `total_score` mientras el optimizador usa `adjusted_score`** (moat + consistencia + Piotroski + tailwind) → el mismo ticker puede ser HOLD en el screener y peso material en la cartera óptima.
3. **El retorno esperado del optimizador es un proxy de score (hasta ~18 % “anual”)**, no un ancla económica/histórica; el MC es conservador, el optimizer no → narrativas de plan sobre-optimistas si se leen en conjunto sin cuidado.
4. **Vocabulario de señales divergente** (`"STRONG BUY"` vs `"STRONG_BUY"`): el scheduler de producción alimenta alertas con el formato con espacio; las oportunidades de `STRONG BUY` no disparan en el set canónico de underscore.

Se documentan **15 debilidades** (mínimo 1–2 por módulo principal), cada una con cita de código, severidad, mejora concreta, ejemplo de implementación y criterio de verificación medible. Todas las propuestas son **compatibles con la arquitectura actual** (Python local, yfinance, Streamlit, IA opcional, sin cambios de schema en dataclasses públicas).

**Impacto esperado del P0 (1–2 días de implementación):** coherencia decisión↔portfolio, seguridad post-IA, y alertas de oportunidad fiables — sin tocar modelos de datos.

---

## 2. Metodología de auditoría

### 2.1 Procedimiento

1. Lectura completa de módulos de decisión/scoring y docs de arquitectura/metodología.
2. Trazado de flujos: `full_analysis` → Decision → screener/optimizer/alerts/MC.
3. Cruce con `docs/moat_methodology.md` y teoría estándar (Moat Buffett, Mean-Variance Markowitz, block-bootstrap).
4. Clasificación de gaps de **razonamiento** (no de estilo de código ni de UX).
5. Propuestas flag-based / aditivas para no romper 534 tests ni interfaces.

### 2.2 Módulos inspeccionados (≥8 + docs)

| # | Módulo | Path | Responsabilidad de razonamiento | LOC aprox. |
|---|--------|------|----------------------------------|------------|
| 1 | Strategy orchestrator | `analysis/strategy.py` | Matriz score×técnico, hard blocks, `full_analysis` | 290 |
| 2 | Moat | `analysis/moat.py` | Quant 0–12 + AI 0–8 + bonus | 722 |
| 3 | AI Analyzer | `analysis/ai_analyzer.py` | LLM decision/narrativas; fallback rule-based | 477 |
| 4 | Prompts | `analysis/prompts.py` | Contratos JSON, rúbricas, macro_factors | 1236 |
| 5 | Scoring | `analysis/scoring.py` | Consistency 0–15 + Piotroski 0–9 | 368 |
| 6 | Technical | `analysis/technical.py` | Señal semanal BULLISH/NEUTRAL/BEARISH | 358 |
| 7 | Optimizer | `portfolio/optimizer.py` | Mean-Variance SLSQP + ER proxy + constraints | 1068 |
| 8 | Monte Carlo | `portfolio/monte_carlo.py` | Block-bootstrap + haircut + SORR | 635 |
| 9 | Stress tester | `portfolio/stress_test.py` | Shocks sectoriales históricos | 323 |
| 10 | Alert engine | `alerts/engine.py` | Diff de snapshots → fire + explicación AI | 537 |
| 11 | Crypto analyzer | `analysis/crypto_analyzer.py` | Score crypto nativo + moat AI | 580 |
| 12 | Fetcher | `data/fetcher.py` | yfinance + cache (calidad de input) | 170 |
| — | Fundamental | `analysis/fundamental.py` | 5 dimensiones + `adjusted_score` | — |
| — | Docs | `docs/architecture.md`, `docs/moat_methodology.md` | Contrato de capas y metodología Moat | — |
| — | Config | `config.py` | Fuente de verdad de umbrales | — |

### 2.3 Flujo de decisión actual (resumen)

```
yfinance → fetcher/cache
    → fundamental (total_score + consistency + piotroski + moat + tailwind → adjusted_score)
    → technical (signal)
    → IF ai_enabled: AIAnalyzer (LLM) ELSE RetirementStrategy (rules)
    → apply_safety_overlay()   # P0 D1 — hard blocks always win
    → Decision (score = adjusted_score por default — P0 D2)
         ├── Screener / Stock Analysis / Track record
         ├── Optimizer (adjusted_score)
         ├── Monte Carlo / Stress
         └── AlertEngine (_normalize_signal — P0 D8)
```

---

## 3. Matriz de debilidades (módulo × severidad)

| ID | Módulo | Severidad | Título corto | Estado P0 | Cita / implementación |
|----|--------|-----------|--------------|-----------|------------------------|
| D1 | strategy + ai_analyzer | **Alta** | IA salta safety blocks | **✅ Implementado y verificado** | `apply_safety_overlay` en `strategy.py` + `AIAnalyzer.analyze` / `full_analysis` |
| D2 | strategy + ai_analyzer | **Alta** | `total_score` vs `adjusted_score` | **✅ Implementado y verificado** | `effective_decision_score` + `STRATEGY.use_adjusted_score_for_decision=True` |
| D3 | strategy | **Alta** | Doc D/E>2.0 vs código >3.0 | **✅ Implementado y verificado** | `STRATEGY.max_debt_equity` (default 3.0) en `_check_safety_blocks` |
| D4 | optimizer | **Alta** | ER = proxy de score (over-optimism) | **✅ Implementado y verificado** | `OPTIMIZER.er_absolute_cap=0.14` en `_expected_returns` |
| D5 | moat | **Media** | ROIC sin WACC real | **✅ Implementado y verificado** | `_score_roic_sustained` + `MOAT.use_roic_wacc_spread` |
| D6 | scoring | **Media** | Missing data → 2.5 “neutral” | **✅ Implementado y verificado** | `CONSISTENCY.missing_data_score=0.0` |
| D7 | prompts | **Media** | Sin CoT forzado / few-shot / hard constraints | **✅ Implementado y verificado** | `_hard_decision_constraints_block` en `equity_decision_prompt` |
| D8 | alerts | **Media** | `STRONG BUY` vs `STRONG_BUY` | **✅ Implementado y verificado** | `_normalize_signal` en `alerts/engine.py` |
| D9 | crypto_analyzer | **Media** | Floor 35 + tech 45 sesgo momentum | **✅ Implementado y verificado** | `CRYPTO_MOAT.base_score=28`, tech max 30, max_bonus 8 |
| D10 | stress_test | **Media** | Sin shock Crypto | **✅ Implementado y verificado** | keys Crypto en todos los `SCENARIOS` |
| D11 | monte_carlo | **Baja–Media** | Pesos estáticos; haircut uniforme | **✅ Implementado y verificado** | warnings static + crypto vol_scale en `run()` |
| D12 | prompts (alerts) | **Baja** | Explicación sin causalidad multi-capa | **✅ Implementado y verificado** | cadena Hecho/Causa/Impacto en `alert_explanation_prompt` |
| D13 | ai_analyzer | **Baja** | Constraints de perfil hardcodeados en advice | **✅ Implementado y verificado** | `resolve_optimizer_profile()` |
| D14 | fundamental | **Baja** | Graham Y=4.5% fijo | **✅ Implementado y verificado** | `THRESHOLDS.graham_aaa_yield_pct` |
| D15 | technical | **Baja** | RSI oversold +10 en downtrend | **✅ Implementado y verificado** | oversold solo si uptrend SMA200/slope |

**Conteo:** 15 debilidades.  
**Cerrado:** **15/15** (implementación code en 14; D4 blend histórico queda backlog justificado — el cap ER 0.14 ya cubre over-optimism).

---

## 4. Debilidades detalladas y mejoras por módulo

### 4.1 `analysis/strategy.py` — RetirementStrategy + full_analysis

**Responsabilidad.** Combinar fundamental + técnico en `Decision` con matriz de umbrales (`STRATEGY.*`) y hard-blocks de seguridad. Orquestar el pipeline en `full_analysis`.

**Lógica actual.**
- Equity: `effective_score = total_score` (no adjusted).
- Crypto: `effective_score = adjusted_score`.
- Blocks: D/E > 3.0, P/B < 0, parabólico (precio vs 52w low >100 % y RSI>80).
- Matriz: score × señal técnica → STRONG BUY / BUY / HOLD / REDUCE / SELL; opcional `require_technical_uptrend`.

#### D1 — Alta: AI reemplaza por completo al motor (sin overlay de seguridad)

```284:288:analysis/strategy.py
    if ai_config and ai_config.enabled:
        from analysis.ai_analyzer import AIAnalyzer
        decision = AIAnalyzer(ai_config).analyze(fund, tech)
    else:
        decision = RetirementStrategy().decide(fund, tech)
```

El fallback a reglas solo ocurre si la API falla (`ai_analyzer.py` L36–38). El parse de la IA no revalida blocks.

**Mejora verificable — safety overlay post-decisión.**

```python
# analysis/strategy.py (propuesto)
def apply_safety_overlay(
    decision: Decision,
    fundamental: FundamentalResult,
    technical: TechnicalResult,
) -> Decision:
    """Never let LLM (or any path) upgrade past hard safety blocks."""
    strategy = RetirementStrategy()
    if getattr(fundamental, "is_crypto", False):
        if (technical.price_vs_52w_low_pct > 120
                and technical.rsi_weekly and technical.rsi_weekly > 80):
            decision.action = "AVOID"
            decision.blocked = True
            decision.block_reason = "Movimiento parabólico crypto"
            decision.confidence = "HIGH"
        return decision

    blocked, reason = strategy._check_safety_blocks(fundamental, technical)
    if blocked and decision.action in ("STRONG BUY", "BUY", "HOLD", "REDUCE"):
        decision.action = "AVOID"
        decision.blocked = True
        decision.block_reason = reason
        decision.confidence = "HIGH"
        decision.rationale = [f"BLOCKED (safety overlay): {reason}"] + list(decision.rationale or [])
    return decision

# full_analysis tail:
decision = apply_safety_overlay(decision, fund, tech)
```

| Criterio de verificación | Medible | Estado P0 |
|--------------------------|---------|-----------|
| Fixture D/E=4.0, LLM mock action=BUY | `action == "AVOID"` y `blocked is True` | ✅ `test_full_analysis_applies_overlay_with_mocked_ai` |
| Misma fixture sin AI | idéntico AVOID | ✅ `test_de_above_default_blocks` |
| Fixture sano score 80 BULLISH | sin regresión STRONG BUY/BUY | ✅ `test_safety_overlay_noop_when_safe` + suite |

**✅ Implementado y verificado (P0):** `apply_safety_overlay()` en `analysis/strategy.py`; llamada desde `full_analysis` y `AIAnalyzer.analyze` (éxito y fallback).

#### D2 — Alta: score dual (decisión vs portfolio)

```99:101:analysis/strategy.py
        _is_crypto = getattr(fundamental, "is_crypto", False)
        effective_score = fundamental.adjusted_score if _is_crypto else fundamental.total_score
```

Mientras `fundamental.py` construye:

```329:341:analysis/fundamental.py
        # Final adjusted_score = base + consistency + piotroski_bonus + moat_bonus
        #                        + tailwind_bonus (can be negative), capped to [0, 100]
        result.adjusted_score = round(
            min(
                max(
                    result.total_score + result.consistency_score +
                    result.piotroski_bonus + result.moat_bonus +
                    result.tailwind_bonus,
                    0.0,
                ),
                100.0,
            ), 1
        )
```

**Efecto en retiro:** un Wide Moat caro (MELI-like) puede quedar fuera de BUY en decision matrix pero entrar fuerte al Mean-Variance vía `adjusted_score` — el usuario ve mensajes contradictorios.

**Mejora:**

```python
# config.py StrategyConfig
use_adjusted_score_for_decision: bool = True  # default True; False = legacy total_score

# strategy.py / ai_analyzer.py
if getattr(fundamental, "is_crypto", False) or CFG.use_adjusted_score_for_decision:
    effective_score = fundamental.adjusted_score
else:
    effective_score = fundamental.total_score
```

| Criterio | Medible | Estado P0 |
|----------|---------|-----------|
| Fixture base=41, adj=66, tech BULLISH | action BUY (con buy_score=60) si flag True | ✅ `test_adjusted_score_drives_buy_when_flag_true` |
| Flag False → legacy total_score | no BUY con total=41 adj=66 | ✅ `test_legacy_total_score_when_flag_false` |
| Optimizer / decision score alineados | `fundamental_score == adjusted` por default | ✅ `effective_decision_score` + parse AI |

**✅ Implementado y verificado (P0):** `STRATEGY.use_adjusted_score_for_decision=True` (default); `effective_decision_score()` en strategy + AI parse.

#### D3 — Alta: documentación de leverage desalineada

- Docstring histórico: *“Never buy a stock with D/E > 2.0”*.
- Código histórico: `debt_equity > 3.0` hardcode.

**Mejora implementada:**

```python
# config.py StrategyConfig
max_debt_equity: float = 3.0  # valor real documentado; configurable

# strategy._check_safety_blocks
if fundamental.debt_equity is not None and fundamental.debt_equity > CFG.max_debt_equity:
    return True, f"Excessive leverage (D/E = {fundamental.debt_equity:.1f})"
```

| Criterio | Medible | Estado P0 |
|----------|---------|-----------|
| D/E=4 → AVOID | default threshold 3.0 | ✅ `test_de_above_default_blocks` |
| `max_debt_equity=2.0`, D/E=2.5 → AVOID | config-driven | ✅ `test_max_debt_equity_config_override` |
| Docstring alineado | menciona `STRATEGY.max_debt_equity` | ✅ inspección `strategy.py` header |

**✅ Implementado y verificado (P0).**

---

### 4.2 `analysis/ai_analyzer.py` — capa LLM

**Responsabilidad.** Sustituir (cuando está habilitada) la decisión rule-based; generar narrativas de plan, optimizer advice y plan-level macro risks. Fallback a `RetirementStrategy` en error.

#### D1 (continuación) — parse sin validación de seguridad

```443:477:analysis/ai_analyzer.py
    def _parse_response(self, raw: str, fund: FundamentalResult, tech: TechnicalResult) -> Decision:
        ...
        action = data.get("action", "HOLD").upper()
        valid_actions = {"STRONG BUY", "BUY", "HOLD", "REDUCE", "SELL"}
        if action not in valid_actions:
            action = "HOLD"
        score = fund.adjusted_score if getattr(fund, "is_crypto", False) else fund.total_score
        ...
        return Decision(... action=action ...)
```

**Mejora adicional en parse:**

```python
# Clamp allocation
if _alloc is not None:
    _alloc = max(0.0, min(15.0, _alloc))
# Confidence whitelist
conf = data.get("confidence", "MEDIUM").upper()
if conf not in {"HIGH", "MEDIUM", "LOW"}:
    conf = "MEDIUM"
# macro_factors: cap 2, schema strip (ya parcialmente en plan narrative)
```

#### D13 — Baja: constraints de perfil hardcodeados en optimizer advice

```244:266:analysis/ai_analyzer.py
        max_pos = 8.0
        min_pos = 8
        max_vol = 18.0
        min_div = 2.5
        max_crypto = 5.0
```

*(Histórico — pre-fix.)* Grok razonaba como si el perfil siempre fuera moderado genérico.

**Mejora implementada:** `resolve_optimizer_profile(profile_name)` + uso en `generate_optimizer_advice`.

| Criterio | Medible | Estado |
|----------|---------|--------|
| Agresivo → max_position 18% | no hardcode 8 | ✅ `test_aggressive_differs_from_hardcoded_old_defaults` |
| Nombre display “Moderado” | resuelve moderate | ✅ `test_display_name_lookup` |
| Unknown → conservador | safe default | ✅ `test_unknown_defaults_conservative` |

**✅ Implementado y verificado (P1 D13).**

---

### 4.3 `analysis/prompts.py` — biblioteca de prompts

**Responsabilidad.** Contratos JSON versionados, voz Grok, macro estructurado, rúbricas de moat cualitativo. Calidad de razonamiento LLM depende casi por completo de aquí.

**Fortalezas ya presentes.**
- Macro `0–2` factores con regla “preferir vacío a relleno” (`_macro_factors_output_spec`).
- Rúbricas 0.0–2.0 con ejemplos por dimensión (moat equity/crypto).
- Tailwind curado como fuente de verdad (no inventar colas de viento).
- Narrativa de plan conservadora (anti-hype).

#### D7 — Media: falta CoT numerado, few-shot y hard constraints del rule engine

El prompt de decisión pide secciones Tesis/Riesgos/Catalizadores/Asignación pero **no inyecta** los umbrales duros de `RetirementStrategy` ni prohíbe explícitamente STRONG BUY bajo D/E extremo.

**Mejora — bloque reutilizable + CoT:**

```python
def _hard_decision_constraints(fund, tech) -> str:
    from config import STRATEGY as S
    de = fund.debt_equity
    de_s = f"{de:.2f}" if de is not None else "N/A"
    return f"""
CONSTRAINTS DUROS DEL SISTEMA (no los viole; si aplican, action ≤ REDUCE o use HOLD/SELL):
- D/E actual = {de_s}. Si D/E > 3.0 → no BUY ni STRONG BUY.
- P/B negativo → AVOID/SELL.
- Parabólico: +100% vs 52w low y RSI weekly > 80 → no BUY.
- Umbrales score (referencia rule-based): STRONG≥{S.strong_buy_score}, BUY≥{S.buy_score}, HOLD≥{S.hold_score}.
- Score a usar en el razonamiento: ADJUSTED = {fund.adjusted_score:.1f} (no solo base {fund.total_score:.1f}).
"""

# Insertar en equity_decision_prompt antes de --- INSTRUCCIÓN ---
# + PASOS INTERNOS obligatorios en reasoning:
# 1) Citar 4 números duros  2) Evaluar constraints  3) Mapear a action
# 4) Macro solo si ancla a paso 1  5) Asignación ≤ min(perfil, moat)
```

**Few-shot mínimo (anti-hype):**

```text
EJEMPLO (no copiar números; copiar el estilo de rigor):
Empresa con ROE 22%, moat Wide, pero D/E 3.4 y P/E percentil 90 del sector.
→ action: HOLD o REDUCE, confidence: MEDIUM/LOW, allocation ≤ 3%.
Nunca STRONG BUY por narrativa de marca si el leverage viola constraints.
```

| Criterio | Medible | Estado |
|----------|---------|--------|
| prompt contiene CONSTRAINTS + CoT | substrings estables | ✅ `test_hard_constraints_and_cot_steps_present` |
| D/E alto en prompt | valor y regla no BUY | ✅ `test_high_leverage_mentioned_in_constraints` |
| JSON template parseable | no braces sueltos | ✅ `test_json_template_is_parseable` |

**✅ Implementado y verificado (P1 D7):** `_hard_decision_constraints_block` + crypto constraints ligeros.

#### D12 — Baja: alert explanation sin causalidad

`alert_explanation_prompt` (L634–689) vuelca key-values y pide 2–3 oraciones; no fuerza:

1. qué cambió (delta),
2. causa probable anclada a campos,
3. severidad para un plan de retiro 10–30y,
4. acción concreta con horizonte.

**Mejora (fragmento):**

```text
Razona en este orden (reflejado en explanation):
1) Hecho: qué umbral se cruzó y con qué magnitud.
2) Causa probable: ¿ruido de un día, deterioro fundamental, o downgrade de moat?
3) Impacto retiro: ¿revisar tamaño, stop de aportes, o solo monitorear?
4) action_suggested: 1 verbo + 1 condición de salida ("Revisar si score no recupera 5 pts en 30d").
```

| Criterio | Medible | Estado |
|----------|---------|--------|
| Cadena causal en prompt | Hecho / Causa probable / Impacto retiro | ✅ `TestAlertExplanationPrompt` |

**✅ Implementado y verificado (P3 D12).**

---

### 4.4 `analysis/moat.py` + `docs/moat_methodology.md`

**Responsabilidad.** Ventaja competitiva durable: capa cuantitativa siempre-on; capa AI opcional cacheada 7 días; bonus al `adjusted_score` capeado en +10.

#### D5 — Media: ROIC sin comparación a WACC

Metodología (`moat_methodology.md`): *“ROIC vs WACC”*. Código:

```371:380:analysis/moat.py
        roic_avg = self._avg_roic(income_stmt, balance_sheet)
        if roic_avg is not None:
            if roic_avg >= 20:
                d.roic_sustained = 2.0
            elif roic_avg >= 12:
                d.roic_sustained = 1.0
            elif roic_avg >= 8:
                d.roic_sustained = 0.5
```

NOPAT usa tax fijo 21 % (`L590: nopat = ebit * 0.79`) — razonable como proxy, pero **no hay spread sobre costo de capital**.

**Mejora (sin API nueva):**

```python
# config MoatConfig
risk_free_proxy: float = 4.0
sector_erp: dict = field(default_factory=lambda: {
    "Technology": 5.0, "Energy": 6.0, "Financials": 5.5, "default": 5.0,
})

def _wacc_proxy(self, sector: str) -> float:
    erp = self.cfg.sector_erp.get(sector, self.cfg.sector_erp.get("default", 5.0))
    return self.cfg.risk_free_proxy + erp

# scoring:
spread = roic_avg - self._wacc_proxy(info.get("sector", "default"))
if spread >= 10: d.roic_sustained = 2.0
elif spread >= 4: d.roic_sustained = 1.0
elif spread >= 0: d.roic_sustained = 0.5
```

| Criterio | Medible | Estado |
|----------|---------|--------|
| ROIC alto con WACC alto no da full points | Energy ROIC=12 → 0.5 (spread) | ✅ `test_high_roic_low_spread_not_full_points` |
| Spread excelente → 2.0 | ROIC=20 Tech → 2.0 | ✅ `test_higher_spread_scores_higher` |
| Legacy absolute mode | flag False → umbrales 20/12/8 | ✅ `test_legacy_absolute_mode` |

**✅ Implementado y verificado (P2 D5):** `_score_roic_sustained` + `_wacc_proxy` + flags en `MoatConfig`.

**Mejora prompt AI (anti-sesgo de marca) — ⏳ residual:** few-shot / contraargumento en prompts (D7).

---

### 4.5 `analysis/scoring.py` — Consistency + Piotroski

**Responsabilidad.** Bonos aditivos de calidad contable multi-año. Piotroski bien implementado como checks YoY booleanos.

#### D6 — Media: missing data = 2.5 pts “neutrales” por dimensión

```179:183:analysis/scoring.py
        if ni is None or equity is None:
            return 2.5  # neutral
```

Con tres dimensiones fallidas → **+7.5 pts** al adjusted_score sin evidencia de estabilidad. Contrario al principio conservador de retiro.

**Mejora:**

```python
# ConsistencyThresholds
missing_data_score: float = 0.0  # was implicit 2.5

# en _roe_stability / _eps_stability / _margin_stability:
if insufficient:
    notes.append("Datos insuficientes para ROE stability — score 0 (conservador)")
    return self.ct.missing_data_score
```

| Criterio | Medible | Estado |
|----------|---------|--------|
| income/balance vacíos | `consistency_score <= 1.0` (no 7.5) | ✅ `test_empty_statements_do_not_gift_consistency` |
| balance ausente | `roe_score == missing_data_score` | ✅ `test_missing_balance_sheet_uses_missing_data_score` |
| data_quality poor en risks | wiring strategy | ⏳ residual |

**✅ Implementado y verificado (P1 D6):** `CONSISTENCY.missing_data_score = 0.0` en los tres componentes de stability.

---

### 4.6 `analysis/technical.py`

**Responsabilidad.** Señal de largo plazo sobre barras semanales 10y (SMA200, RSI, MACD, ADX, BB, volumen).

#### D15 — Baja: oversold bonifica sin contexto de tendencia

```254:261:analysis/technical.py
        if result.rsi_weekly is not None:
            rsi = result.rsi_weekly
            if 40 <= rsi <= 65:
                score += 15
            elif rsi < 30:
                score += 10       # oversold — entry opportunity
            elif rsi > 75:
                score -= 15
```

En downtrend (precio bajo SMA200), RSI bajo es a menudo continuación, no oportunidad de retiro.

**Mejora:**

```python
elif rsi < 30:
    if result.above_sma200 or result.sma200_slope_pct >= 0:
        score += 10
    # else: 0 — value trap risk
```

| Criterio | Medible | Estado |
|----------|---------|--------|
| oversold uptrend > downtrend strength | signal_strength | ✅ `test_oversold_downtrend_weaker_than_uptrend` |
| oversold solo no BULLISH | signal != BULLISH | ✅ `test_oversold_downtrend_not_bullish_alone` |

**✅ Implementado y verificado (P3 D15).**

---

### 4.7 `portfolio/optimizer.py` — Mean-Variance

**Responsabilidad.** Maximizar Sharpe sujeto a constraints de perfil (peso máx, sector, vol, div yield, min posiciones); fallback score-weighted; frontier Monte Carlo de pesos aleatorios; core determinístico.

#### D4 — Alta: expected returns desanclados de la realidad de mercado

```583:595:portfolio/optimizer.py
            score_ret = (score / 100) * 0.18        # max ~18% from score
            div_ret = div / 100
            moat_ret = (moat / 20) * 0.05            # max ~5% from moat
            composite = (
                cfg.score_weight * score_ret
                + cfg.dividend_weight * div_ret
                + cfg.moat_weight * moat_ret
            )
```

Un ticker score 100 + moat 20 puede producir μ implícitos muy altos **sin** que existan earnings yields ni medias históricas que los justifiquen. Black-Litterman existe pero es opt-in (`BLACK_LITTERMAN.enabled`).

**Mejora (aditiva, config-first):**

```python
# OptimizerConfig
er_absolute_cap: float = 0.14          # 14% anual max por ticker en perfil conservador
er_blend_historical: float = 0.4       # 40% media hist. 2y anualizada + 60% score-view

# en _expected_returns, tras composite:
if self.opt.er_blend_historical > 0 and symbol in hist_means:
    composite = (1 - b) * composite + b * hist_means[symbol]
composite = min(composite, self.opt.er_absolute_cap)
```

Justificación MPT: la frontera eficiente es sensible a errores en μ (Chopra–Ziemba); capear y blendear reduce “error maximization” del SLSQP.

| Criterio | Medible | Estado |
|----------|---------|--------|
| scores=100, moat=20 | `mu <= er_absolute_cap (0.14)` | ✅ `test_er_absolute_cap_enforced` |
| Ranking score alto > bajo | se preserva bajo cap | ✅ mismo test + legacy tests |
| Cap deshabilitable | `er_absolute_cap=0` → μ puede >0.14 | ✅ `test_er_cap_disabled_allows_higher` |
| Blend histórico 40% | media 2y | ⏳ residual P2 |

**✅ Implementado y verificado (P2 D4):** `OPTIMIZER.er_absolute_cap = 0.14` aplicado en `_expected_returns`.

---

### 4.8 `portfolio/monte_carlo.py` — block-bootstrap

**Responsabilidad.** Proyectar paths de portafolio con muestreo de bloques de 4 semanas sobre retornos históricos semanales; ajustes conservadores; SORR; drags y decumulación opcionales.

**Fortalezas.** Sin supuesto gaussiano; haircut documentado; `include_realistic_reference` para transparencia; decumulación inyectable (Fase H.1).

#### D11 — Baja–Media: supuestos implícitos poco visibles en el razonamiento de producto

- Pesos **estáticos** (no rebalance anual en el path).
- Haircut **uniforme** (no extra para crypto/ARS).
- Historia única ≈ un régimen; crisis futuras pueden no estar en la muestra 10y.

**Mejora (bajo esfuerzo):**

1. Exponer en `MonteCarloResult.warnings` si algún peso > 0 en sector Crypto y `vol_scale` default del caller es 1.0 → warning “crypto sin haircut extra”.
2. Documentar en UI: *“Simulación con pesos fijos; no modela rebalanceo ni cambio de régimen.”*
3. Perfiles: `vol_scale=1.2` conservador, `1.0` moderado (ya hay hooks `vol_scale`/`return_scale` en `__init__`).

| Criterio | Medible | Estado |
|----------|---------|--------|
| Warning pesos fijos | en `result.warnings` | ✅ `test_static_weights_warning_always` |
| Crypto + vol_scale=1.0 | warning haircut extra | ✅ `test_crypto_without_extra_vol_warning` |
| Crypto + vol_scale>1 | sin warning haircut extra | ✅ `test_crypto_with_extra_vol_no_extra_warning` |

**✅ Implementado y verificado (P2 D11):** transparencia de supuestos; math de paths sin cambios.  
*Nota:* rebalance anual en-path y cambio de régimen quedan fuera de scope (complejidad alta / byte-compat MC).

---

### 4.9 `portfolio/stress_test.py`

**Responsabilidad.** Aplicar shocks sectoriales calibrados (2008, 2020, 2022, dot-com, recesión, stagflación) al desglose sectorial del optimizer.

#### D10 — Media: crypto cae en `default_shock`

Sectores listados no incluyen `"Crypto / Digital Asset"` ni `"Crypto"`. BTC en 2022 ≈ −65 % a −75 %; el default 2022 es −18 %.

**Mejora:**

```python
# En cada StressScenario.sector_shocks agregar, p.ej.:
"Crypto": -75.0,
"Crypto / Digital Asset": -75.0,
# 2022:
"Crypto": -70.0,
# COVID:
"Crypto": -50.0,
```

| Criterio | Medible | Estado |
|----------|---------|--------|
| 10% Crypto + 90% Tech vs 100% Tech en 2022 | DD más negativo con crypto | ✅ `test_crypto_worse_than_default_in_2022` |
| Keys en todos los escenarios | Crypto + alias Digital Asset | ✅ `test_crypto_sector_keys_present_in_all_scenarios` |
| Alias equivalentes | mismos DD | ✅ `test_crypto_digital_asset_alias_matches_crypto` |

**✅ Implementado y verificado (P2 D10).**

---

### 4.10 `alerts/engine.py` + scheduler

**Responsabilidad.** Cold-start baseline; 5 checks de universo; portfolio alerts; SORR/goal; cooldown/mute; digest.

#### D8 — Media (bug de producción): vocabulario de señales

```45:45:alerts/engine.py
OPPORTUNITY_SIGNALS = {"STRONG_BUY", "BUY"}
```

Producción:

```63:63:scripts/run_scheduler.py
                "signal":              getattr(dec, "action", ""),
```

`Decision.action` es `"STRONG BUY"` (espacio). Entonces:

- `"BUY" ∈ OPPORTUNITY_SIGNALS` → OK  
- `"STRONG BUY" ∉ OPPORTUNITY_SIGNALS` → **oportunidad STRONG BUY no dispara**  
- Score surge con STRONG BUY tampoco entra por el filtro de L183

El propio engine documenta la divergencia al loguear track record (L434–444) pero **no normaliza en `run()`**.

**Mejora:**

```python
def _normalize_signal(signal: str) -> str:
    s = (signal or "").upper().strip().replace(" ", "_")
    aliases = {"STRONGBUY": "STRONG_BUY", "AVOID": "SELL"}  # optional
    return aliases.get(s, s)

# en run():
signal = _normalize_signal(str(t.get("signal", t.get("decision", "")) or ""))
```

| Criterio | Medible | Estado P0 |
|----------|---------|-----------|
| Baseline HOLD → `"STRONG BUY"` | dispara OPPORTUNITY | ✅ `test_opportunity_strong_buy_with_space` |
| Baseline HOLD → `"STRONG_BUY"` | dispara OPPORTUNITY | ✅ `test_new_buy_entry_fires_opportunity` |
| Snapshot espacio ≡ underscore | no SIGNAL_CHANGE falso | ✅ `test_normalize_does_not_fire_on_space_vs_underscore` |
| Tests underscore legacy | sin regresión | ✅ suite alert engine |

**✅ Implementado y verificado (P0):** `_normalize_signal` en entrada y en `prev_signal`; snapshots se guardan normalizados.

---

### 4.11 `analysis/crypto_analyzer.py`

**Responsabilidad.** Path paralelo que devuelve `FundamentalResult(is_crypto=True)` con score nativo (base + tech − vol − dd + moat) y moat cualitativo de 5 dimensiones.

#### D9 — Media: sesgo a momentum técnico vs estructura

```324:330:analysis/crypto_analyzer.py
        base  = 35.0
        tech_pts  = self._tech_pts(tech)   # hasta 45
        vol_pen   = self._vol_penalty(vol)
        dd_pen    = self._drawdown_penalty(max_drawdown)
        raw = base + tech_pts - vol_pen - dd_pen + moat_bonus
```

- NEUTRAL: 35+22 = 57 antes de penalties (cerca de BUY=60).
- Bull fuerte: 35+45 − 15 − 15 + 5 ≈ 55 (HOLD) — calibración consciente, pero **moat solo +5** frente a **tech +45**.

**Mejora (recalibración suave en `config.CRYPTO_MOAT` / constantes):**

```python
base = 28.0
# _tech_pts max 30 (escalar tabla)
# moat_bonus max 10 (factor × total ya en CryptoMoatDetail)
# strategy: if vol > 70 and action in BUY/STRONG BUY → cap at HOLD
```

| Criterio | Medible | Estado |
|----------|---------|--------|
| vol=90, BULLISH, moat=5 | score < buy_score (60) | ✅ `test_high_vol_bullish_below_buy_threshold` |
| tech pts desde config | no magic 45/35/22 | ✅ `TestCryptoTechPts` |
| vol extrema → HOLD | strategy cap | ✅ `test_crypto_extreme_vol_caps_buy` |

**✅ Implementado y verificado (P1 D9).**

---

### 4.12 `data/fetcher.py` + data quality

**Responsabilidad.** Única puerta a yfinance con retries y cache SQLite. No “razona”, pero **sesga** todo el razonamiento aguas abajo cuando devuelve parciales.

**Estado positivo:** `compute_data_quality` en `fundamental.py` ya marca missing fields y stale cache.

**Mejora de razonamiento (wiring):**

```python
# strategy._build_rationale
dq = getattr(fundamental, "data_quality", None) or {}
if dq.get("level") in ("partial", "poor"):
    decision.risks.append(
        f"Calidad de datos {dq['level']}: faltan {', '.join(dq.get('missing_fields', [])[:5])}"
    )
if dq.get("level") == "poor" and decision.action in ("STRONG BUY", "BUY"):
    decision.action = "HOLD"
    decision.rationale.append("BUY degradado a HOLD por data quality pobre")
```

| Criterio | Medible | Estado |
|----------|---------|--------|
| poor DQ + score alto → HOLD | action HOLD + risk | ✅ `test_poor_data_quality_degrades_buy_to_hold` |
| también en AI path (overlay) | apply_safety_overlay | ✅ soft gate en overlay |

**✅ Implementado y verificado (gap data_quality).**

### D14 — Graham Y configurable

| Criterio | Medible | Estado |
|----------|---------|--------|
| Campo config | `graham_aaa_yield_pct` | ✅ `test_config_field_exists` |
| Y↑ → V↓ | fórmula | ✅ `test_higher_yield_lowers_graham_value` |

**✅ Implementado y verificado (P3 D14):** `THRESHOLDS.graham_aaa_yield_pct` usado en `fundamental.py`.

### Residual D4 blend histórico

| Criterio | Decisión |
|----------|----------|
| Blend 40% media hist. 2y | **No implementado en esta iteración** — justificación: el cap `er_absolute_cap=0.14` ya acota over-optimism sin red/hist en unit path; blend requiere wire de price matrix en `_expected_returns` y complica tests offline. Documentado como backlog opcional post-cap. |

---

## 5. Ejemplos de prompts mejorados (listos para copiar)

### 5.1 Equity decision — inserto CoT + constraints

Añadir en `equity_decision_prompt` tras el bloque técnico:

```text
--- CONSTRAINTS DUROS DEL MOTOR RULE-BASED (obligatorios) ---
{hard_constraints_block}

--- PASOS DE RAZONAMIENTO (reflejar en `reasoning`, en español) ---
1. DATOS: citá score ajustado, moat class, ROE, D/E, señal técnica y 1 warning si hay.
2. SEGURIDAD: ¿viola constraints duros? Si sí, action ∈ {HOLD, REDUCE, SELL} y explicá.
3. MATRIZ: compará score ajustado con umbrales STRONG/BUY/HOLD del sistema.
4. MACRO: 0–2 factores SOLO si los conectás a un número del paso 1; si no, macro_factors=[].
5. ASIGNACIÓN: % conservador ≤ 8 (o menor si AR/emergente o vol alta); justificá confidence.

FEW-SHOT DE RIGOR:
Caso: moat Wide + ROE alto + D/E 3.5 → no STRONG BUY; HOLD/REDUCE, allocation ≤ 3%.
```

### 5.2 Moat cualitativo — auto-chequeo de contradicción

```text
ANTES de puntuar brand_strength ≥ 1.5, verificá:
- Si quant_total < 6/12, brand_strength no puede ser 2.0 (máx 1.0) salvo evidencia excepcional explícita.
Incluí una oración "Contraargumento:" en reasoning que ataque tu propia tesis de moat.
```

### 5.3 Alert causal

```text
explanation DEBE responder en 3 oraciones:
(1) Qué cambió en números.
(2) Si es más probable ruido de mercado o cambio de tesis de retiro.
(3) Qué haría un plan de 15–20 años (no day-trade).
```

---

## 6. Alineación con metodología financiera estándar

| Componente | Estándar | Estado actual | Gap de razonamiento |
|------------|----------|---------------|---------------------|
| **Economic Moat** | Buffett/Morningstar: ROIC > WACC de forma sostenida + fuentes cualitativas | Quant por umbrales de nivel; AI 4 dimensiones sólidas | Falta spread ROIC−WACC; AI puede desalinearse del quant |
| **Quality screens** | Piotroski F-Score | Implementación YoY correcta | Consistency regala puntos con missing data |
| **Margin of Safety** | Graham | Fórmula clásica EPS×(8.5+2g)×4.4/Y | Y AAA fijo 4.5 %; STRONG BUY acoplado a MoS |
| **Mean-Variance** | Markowitz (1952) | SLSQP max Sharpe + constraints de retiro | μ score-based → sensible a error de estimación |
| **Black-Litterman** | BL (1992) | Módulo opt-in | Deshabilitado por defecto; poco peso en “verdad” de μ |
| **Block bootstrap** | Politis/Romano; preserva dependencia serial | Blocks 4w, vectorizado, haircut | Pesos fijos; un solo régimen histórico |
| **Stress testing** | Escenarios históricos sectoriales | 6 escenarios calibrados | Crypto/ARS infra-representados |
| **Position sizing** | Kelly fraccional / rules conservadoras | max_position_pct por perfil + AI allocation | AI allocation no siempre clampado ni cruzado con safety |

**Principio de diseño recomendado (sin reescritura):**  
*Las capas estocásticas (MC, stress) y de seguridad rule-based son el “piso de retiro”; la IA narra y matiza pero nunca relaja el piso.*

---

## 7. Roadmap de implementación (impacto × esfuerzo)

```
                    IMPACTO
                 Bajo    Medio    Alto
        Alto |         |  D7    | D1 D2
ESFUERZO     |         |  D5    | D4
        Medio|  D15    | D6 D9  | D8
             |  D14    | D10 D11|
        Bajo |  D12    | D13    | D3
```

### P0 — Coherencia y seguridad — **✅ COMPLETADO (2026-07-11)**

| Item | Archivos | Tests | Estado |
|------|----------|-------|--------|
| Safety overlay post-AI | `strategy.py`, `ai_analyzer.py` | `TestSafetyOverlay` | ✅ |
| `use_adjusted_score_for_decision` | `config.py`, `strategy.py`, `ai_analyzer.py` | `TestAdjustedScoreForDecision` | ✅ |
| `max_debt_equity` config + doc | `config.py`, `strategy.py` | `TestMaxDebtEquity` | ✅ |
| Normalize signal en alerts | `alerts/engine.py` | `TestOpportunity` space + `TestNormalizeSignal` | ✅ |

### P1 — Razonamiento LLM + scoring — **✅ CERRADO**

| Item | Archivos | Estado |
|------|----------|--------|
| Missing data score 0 (D6) | `scoring.py`, `config.py` | **✅** |
| Profile constraints advice (D13) | `ai_analyzer.py` | **✅** |
| CoT + constraints prompts (D7) | `prompts.py`, `test_prompts.py` | **✅** |
| Crypto recalibración (D9) | `crypto_analyzer.py`, `strategy.py` | **✅** |
| data_quality en risks | `strategy.py` | **✅** |

### P2 — Finanzas de portfolio — **✅ CERRADO (blend hist. backlog)**

| Item | Archivos | Estado |
|------|----------|--------|
| ER absolute cap (D4) | `optimizer.py`, `config.py` | **✅** |
| Blend histórico μ | `optimizer.py` | ⏳ backlog justificado |
| ROIC−WACC (D5) | `moat.py` | **✅** |
| Crypto shocks stress (D10) | `stress_test.py` | **✅** |
| MC warnings (D11) | `monte_carlo.py` | **✅** |

### P3 — Residual — **✅ CERRADO**

| Item | Estado |
|------|--------|
| Alert prompt causal (D12) | **✅** |
| Graham AAA yield (D14) | **✅** |
| RSI oversold condicional (D15) | **✅** |
| Few-shot library moat sectorial extendida | ⏳ nice-to-have (rúbricas ya tienen ejemplos) |
| Committee como árbitro cross-AI | ⏳ opcional futuro |

---

## 8. Compatibilidad arquitectónica (no breaking)

| Requisito | Cumplimiento de las mejoras |
|-----------|----------------------------|
| IA opcional | Overlay y scores viven en path rule-based; prompts solo si AI on |
| Python local + yfinance + Streamlit | Sin nuevos servicios |
| Tests existentes | Flags con defaults que preservan o mejoran conservadurismo; P0 añade tests |
| Modelos de datos | No se eliminan campos de `Decision`, `MoatDetail`, `OptimizationResult`, `MonteCarloResult` |
| Interfaces | Firmas públicas se extienden solo con kwargs opcionales / config |
| Config-first | Nuevos umbrales en `config.py` |

---

## 9. Checklist de criterios de éxito (verificado)

| # | Criterio | Estado | Evidencia |
|---|----------|--------|-----------|
| 1 | ≥8 módulos + docs inspeccionados por lectura completa | **✅** | §2.2: 12 módulos + fundamental + 2 docs + config |
| 2 | ≥12 debilidades con citas y severidad (1–2 por módulo principal) | **✅** | §3: D1–D15; altas/medias/bajas |
| 3 | ≥1 mejora concreta verificable por módulo analizado | **✅** | §4.1–4.12 + §5 ejemplos |
| 4 | Reporte MD con resumen, matriz, ejemplos, justificación financiera, roadmap | **✅** | Este documento |
| 5 | Mejoras compatibles con arquitectura actual, sin breaking changes | **✅** | §8 |

### Registro de iteraciones

| Iter | Acción | Resultado | Gap residual |
|------|--------|-----------|--------------|
| 1 | Lectura módulos + docs; matriz D1–D15 | Hallazgos con citas | Falta artefacto MD |
| 2 | Redacción `docs/AUDIT_REASONING_QUALITY.md` | Artefacto completo | — |
| 3 | Verificación de criterios 1–5 audit | Todos ✅ | — |
| 4 | Cruce scheduler signal format + LOC | D8 bug prod confirmado | P0 pendiente |
| 5 | **P0 impl:** config + strategy + ai_analyzer + alerts + tests | 45 tests P0-related OK | Suite full |
| 6 | **P0 verify:** `pytest -q --tb=no` → **546 passed**; MD actualizado | D1/D2/D3/D8 ✅ | P1–P3 pendientes |
| 7 | **P1/P2 impl:** D6, D4, D10, D13, D5 + tests | 107 focused tests OK | Suite full |
| 8 | **P1/P2 verify:** `pytest -q --tb=no` → **562 passed**; MD actualizado | D4/D5/D6/D10/D13 ✅ | D7/D9/D11, P3 ⏳ |
| 9 | **Residual impl:** D7, D9, D11, D12, D14, D15 + DQ | código + tests nuevos | Suite full |
| 10 | **Cierre:** `pytest -q --tb=no` → **575 passed**; MD 15/15 | residuales ✅ | blend D4 hist. backlog |

### Implementación residual (iter 9–10) — evidencia

| ID | Evidencia tests |
|----|-----------------|
| D7 | `test_hard_constraints_and_cot_steps_present`, `test_high_leverage_mentioned_in_constraints` |
| D9 | `test_high_vol_bullish_below_buy_threshold`, `TestCryptoTechPts` (config), `test_crypto_extreme_vol_caps_buy` |
| D11 | `test_static_weights_warning_always`, `test_crypto_without_extra_vol_warning` |
| D12 | `TestAlertExplanationPrompt::test_causal_chain_instructions_present` |
| D14 | `test_graham_yield.py` |
| D15 | `test_technical_d15.py` |
| DQ | `test_poor_data_quality_degrades_buy_to_hold` |

```text
./venv/bin/python3 -m pytest -q --tb=no
# → 575 passed, 46 warnings  (exit code 0)
```

### Implementación y verificación P1/P2 parcial (detalle)

#### Resumen de cambios P1/P2

| Debilidad | Archivos clave | Evidencia tests |
|-----------|----------------|-----------------|
| **D6** missing consistency | `config.ConsistencyThresholds.missing_data_score`, `scoring.py` | `test_empty_statements_do_not_gift_consistency`, `test_missing_balance_sheet_uses_missing_data_score` |
| **D4** ER cap | `config.OptimizerConfig.er_absolute_cap=0.14`, `optimizer._expected_returns` | `test_er_absolute_cap_enforced`, `test_er_cap_disabled_allows_higher` |
| **D5** ROIC−WACC | `MoatConfig.use_roic_wacc_spread`, `moat._score_roic_sustained` | `tests/test_moat_roic.py` (4 tests) |
| **D10** crypto stress | `stress_test.SCENARIOS` keys Crypto | `test_crypto_worse_than_default_in_2022`, `test_crypto_sector_keys_present_in_all_scenarios` |
| **D13** profile advice | `resolve_optimizer_profile`, `generate_optimizer_advice` | `tests/test_resolve_profile.py` (6 tests) |

#### Evidencia pytest (P1/P2)

```text
./venv/bin/python3 -m pytest tests/test_scoring.py tests/test_optimizer.py \
  tests/test_stress_test.py tests/test_moat_roic.py tests/test_resolve_profile.py -q --tb=line
# → 107 passed

./venv/bin/python3 -m pytest -q --tb=no
# → 562 passed, 46 warnings  (exit code 0)
```

#### Principios respetados

- **Config-first:** umbrales en `CONSISTENCY`, `OPTIMIZER`, `MOAT` (flags y caps).
- **Aditivo / sin breaking:** sin cambios de schema en dataclasses públicas.
- **Piso rule-based:** safety overlay P0 intacto; scoring más conservador con missing data.
- **Conservadurismo retiro:** cap μ 14%, crypto stress realista, ROIC solo cuenta si supera WACC proxy.

### Implementación y verificación P0 (detalle)

#### Resumen de cambios

| Archivo | Cambio clave |
|---------|----------------|
| `config.py` | `StrategyConfig.use_adjusted_score_for_decision: bool = True`; `max_debt_equity: float = 3.0` |
| `analysis/strategy.py` | `effective_decision_score()`, `apply_safety_overlay()`, blocks con `CFG.max_debt_equity`, `full_analysis` llama overlay |
| `analysis/ai_analyzer.py` | score unificado, clamp conf/alloc, overlay en `analyze` (éxito + fallback) |
| `alerts/engine.py` | `_normalize_signal()`; normaliza signal actual y `prev_signal`; persiste canónico |
| `tests/test_strategy.py` | `TestMaxDebtEquity`, `TestAdjustedScoreForDecision`, `TestSafetyOverlay` |
| `tests/test_alert_engine.py` | opportunity con espacio; no false change space/underscore; unit normalize |
| `docs/AUDIT_REASONING_QUALITY.md` | este registro + estados ✅ |

#### Evidencia pytest

```text
# P0-focused
./venv/bin/python3 -m pytest tests/test_strategy.py tests/test_alert_engine.py -q --tb=line
# → 45 passed in 0.56s

# Full suite
./venv/bin/python3 -m pytest -q --tb=no
# → 546 passed, 46 warnings in 2.68s  (exit code 0)
```

#### Cumplimiento de criterios tabulados P0 (≥80 %)

| Debilidad | Criterios en §4 | Confirmados | % |
|-----------|-----------------|-------------|---|
| D1 | 3 | 3 | 100 % |
| D2 | 3 | 3 | 100 % |
| D3 | 3 | 3 | 100 % |
| D8 | 4 | 4 | 100 % |
| **Total P0** | **13** | **13** | **100 %** (≥80 % requerido) |

#### Estado por debilidad P0

| ID | Estado |
|----|--------|
| D1 Safety overlay | ✅ Implementado y verificado |
| D2 Adjusted score unificado | ✅ Implementado y verificado |
| D3 max_debt_equity config | ✅ Implementado y verificado |
| D8 Signal normalize | ✅ Implementado y verificado |

**Condición de terminación (implementación P0):** cumplida — 4/4 mejoras P0, suite 546 passed, documento actualizado, 100 % criterios P0 verificados.

---

## 10. Recomendación final (prioridad de negocio)

Para un asesor de retiro de largo plazo, el orden de valor es:

1. **Nunca confiar en la IA por encima del piso de seguridad** (D1).  
2. **Una sola definición de “calidad” del ticker en todo el producto** (D2: `adjusted_score`).  
3. **No presentar retornos de optimización como predicciones de mercado** sin cap/blend (D4 + copy UI).  
4. **Alertas que no mientan por un `_` vs espacio** (D8).  
5. **Prompts con CoT + constraints** para que el razonamiento cualitativo sea auditable (D7).

Con P0+P1, el sistema mantiene su stack actual y eleva de forma medible la **precisión y consistencia** del asesoramiento sin reescrituras de arquitectura.

---

## Apéndice A — Mapa rápido archivo → acción P0 (hecho)

| Archivo | Cambio P0 | Estado |
|---------|-----------|--------|
| `analysis/strategy.py` | `apply_safety_overlay`; `effective_decision_score`; `max_debt_equity` | ✅ |
| `analysis/ai_analyzer.py` | score unificado; clamp conf/alloc; overlay en analyze | ✅ |
| `config.py` | `use_adjusted_score_for_decision`, `max_debt_equity` | ✅ |
| `alerts/engine.py` | `_normalize_signal` en run + prev | ✅ |
| `tests/test_strategy.py` | D1–D3 coverage | ✅ |
| `tests/test_alert_engine.py` | formato `"STRONG BUY"` | ✅ |

## Apéndice B — Referencias internas

- `docs/architecture.md` — capas y flujo  
- `docs/moat_methodology.md` — score moat y limitaciones conocidas  
- `docs/portfolio_optimizer.md` — SLSQP y perfiles  
- `docs/alert_system.md` — tipos y cooldowns  
- `docs/CONTEXT.md` — estado de features y estándares  
- `analysis/eval_harness.py` / `eval_cases.py` — banco de regresión de razonamiento AI  

---

*Fin del reporte de auditoría de calidad de razonamiento.*
