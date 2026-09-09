# Cómo se integra la AI — Retirement Advisor

> **Módulo:** `analysis/ai_analyzer.py` (+ `committee`, `chat_agent`, moat/tailwind AI)

Este documento describe la AI **de producto** (el LLM que habla con el usuario y enriquece un análisis). No cubre las guías para coding assistants.

## Rol

La AI **enriquece, narra y debate**. No es el motor de cálculo.

Números de score, pesos, Monte Carlo, stress y alertas salen de código determinista. El LLM pone prosa, factores macro estructurados, un veredicto de comité y —en dos sitios puntuales— un **bonus cualitativo de moat**. Con la AI apagada el producto sigue siendo usable: screener, optimizer, simulación y alertas producen un portfolio válido.

## Qué no calcula

| Capa | Quién lo hace |
|------|----------------|
| Fundamental, consistency, Piotroski, técnico semanal | `analysis/fundamental.py`, `scoring.py`, `technical.py` |
| Decisión rule-based (tabla score × técnico) | `RetirementStrategy.decide()` |
| Moat cuantitativo (6 dims, 0–12) | `MoatAnalyzer.analyze()` |
| Score / clase / bonus de tailwinds | JSON curado `data/tailwinds/sector_country.json` |
| Pesos, μ, vol, ratio atractivo/vol, SLSQP, `profile_core_holdings` | `portfolio/optimizer.py` |
| Caminos Monte Carlo, ruina, stress, goals | `portfolio/monte_carlo.py`, `stress_test.py` |
| Disparo y cooldowns de alertas | `alerts/engine.py` |
| Bloqueos duros (leverage, libro, parabólico) | `apply_safety_overlay` — corre **después** de AI y de reglas |
| Texto 10-K/10-Q/8-K (evidence pack) | `data/sec_filings.retrieve_filing_pack` — **antes** del JSON de moat/decisión. No puntúa. Sin fuente: `apply_unsourced_catalyst_policy` vacía catalizadores y capea confidence |

## Qué sí hace

| Superficie | Módulo | Disparo | Salida | Si AI off / falla |
|------------|--------|---------|--------|-------------------|
| Decisión por ticker | `AIAnalyzer.analyze` vía `full_analysis` | Stock Analysis; screener solo con «Usar AI en el Screener» | `Decision` (action, confidence, rationale, risks, `ai_reasoning`, `macro_factors`, `catalysts`, allocation ≤15 %). El **score no lo pone el LLM** (`effective_decision_score`). Catalizadores sin filing se vacían en código | `RetirementStrategy.decide` + overlay. La API nunca propaga excepción |
| Moat equity cualitativo | `MoatAnalyzer.analyze_with_ai` | Mismo `full_analysis` si `enabled` | 4 dims 0–8. **No muta** el 0–12 cuantitativo. Suma al total 0–20 y puede mover clase/bonus → `adjusted_score` | Quant intacto, `ai_available=False`. Cache 168 h |
| Moat crypto | `CryptoAnalyzer._analyze_crypto_moat` | `full_analysis` crypto si `enabled` | Moat **solo AI** (5 dims, 0–8) → bonus | Bonus 0; score sigue con tech/vol/dd |
| Tailwinds | `TailwindAnalyzer.analyze_with_ai` | `full_analysis` si hay cola no-neutral | Prosa + ≤2 factors. **Nunca cambia el score** | Objeto curado. Cache 720 h |
| Comité ticker | `CommitteeAnalyzer.analyze` | `15_Comite.py` → «Convocar al comité». **No** entra en `full_analysis` | 5 agentes en paralelo; consenso **determinista** (`aggregate`) | `st.stop()` → Settings |
| Comité holdings | `analyze_portfolio` + `build_holdings_committee_context` | `3_Portfolio.py` → mismo botón | Interpreta el libro real (no recalcula). 4 roles; stance = salud del plan | `None`, sin botón |
| Chat | `ChatAgent.ask` | `18_Chat.py` | Router JSON + narrador. Tools: `analyze_ticker` (single-shot, no comité), `plan_status`, `retirement_projection`. El narrador no inventa cifras | `st.stop()` si AI off o `CHAT.enabled` false |
| Narrativa del plan | `generate_plan_narrative` | `12_Plan.py` | `{narrative, macro_risks≤2}` | Info; no llama |
| Narrativa de simulación | `generate_long_term_narrative` | `7_Simulaciones.py` | Prosa. El MC no es LLM | Mensaje de error en español |
| Consejo del optimizer | `generate_optimizer_advice` | `5_Optimizer.py` | Narrativa + core de *display*. `optimize()` **nunca** reescribe pesos. N>45: skip LLM. N>15: prompt top-15 | `profile_core_holdings` |
| Alertas | `AlertEngine._get_ai_explanation` | Scheduler / `8_Alertas.py` si `ALERTS.ai_explanations_enabled` | Texto causal | `""`; la alerta igual dispara |
| Eval | `eval_harness` | `14_Eval_IA.py` / `scripts/run_eval.py` | Checks sobre un `Decision` | Replay (CI, sin API). Live pide `AIAnalyzer.analyze`. `CommitteeProvider` existe en tests, no en la UI |
| Macro RAG | `analysis/macro_rag.py` | Se inyecta en el estratega macro del comité | **No es un LLM**: TF-IDF sobre docs fechados | String vacío |

`enrich_only=True` (flag in-process, no env): la AI sigue enriqueciendo moat/tailwind cacheados; la **decisión** queda rule-based.

## Qué números sí puede mover

Dos excepciones honestas, no el resto del motor:

1. **Bonus de moat equity (0–8)** y **moat crypto (0–8)** entran en `adjusted_score` y por eso pueden cambiar ranking.
2. **Action / confidence** de `Decision` cuando AI está enabled (después del overlay).

No mueve: score de tailwinds, pesos del optimizer, μ/vol, caminos de Monte Carlo, detección de alertas.

## Cómo se enciende

| Knob | Dónde |
|------|--------|
| Master | `AIConfig.enabled` ← `AI_ENABLED` / Settings |
| Screener | `AI_USE_IN_SCREENER`. `_get_ai_config(context="screener")` exige enabled **y** este flag |
| Proveedor | `AI_PROVIDER`: `claude`, `openai`, `xai` (Grok), `nous`. No existe el string `grok` |
| Keys | `ANTHROPIC_API_KEY` / `XAI_API_KEY` / `OPENAI_API_KEY` |
| Bulk optimizer | Banner si el universo > `OPTIMIZER.max_ai_screener_tickers` (40) y `use_in_screener=False`. No asumas que eso apaga el LLM en todos los paths masivos |

Temperatura 0 en todas las llamadas. UI: `dashboard/pages/9_Settings.py`.

## Caché

| Capa | Persistencia | TTL |
|------|--------------|-----|
| Moat equity / crypto AI | SQLite | 168 h |
| Tailwind AI | SQLite | 720 h |
| Comité (ticker y holdings) | SQLite (`CACHE_TTL_HOURS`) | 24 h |
| Decisión por ticker | No SQLite; `st.cache_data` 3600 s | — |
| Narrativas (plan, MC, optimizer) | Ninguna | — |

## Path sin AI

Sigue en pie: scoring, decisión rule-based, optimizer, Monte Carlo, stress, alertas, PDF. Lo que desaparece es prosa, comité, chat, factores macro estructurados y el bonus cualitativo de moat.

```
datos → fundamental/técnico → (filings texto, si AI on) → (AI opcional) → overlay → UI / alertas
                 ↘ optimizer / MC / stress   (nunca LLM)
```
