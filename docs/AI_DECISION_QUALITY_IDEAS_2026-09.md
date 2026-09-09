# Ideas de AI para calidad de decisión (2026-09-08)

> Documento de **ideación, no de implementación**. No es spec ni el próximo
> sprint — eso sigue en [`BACKLOG.md`](BACKLOG.md). Generado el 2026-09-08 a
> partir de `docs/ai_integration.md`, el path real de decisión
> (`analysis/prompts.py`, `analysis/ai_analyzer.py`, `analysis/strategy.py`) y
> un research de vendors (estado Partial). Complementa
> [`DIAGNOSTICO_PROXIMO_NIVEL_2026-09.md`](DIAGNOSTICO_PROXIMO_NIVEL_2026-09.md)
> y [`brainstorm/21_capa_ia_agentes.md`](brainstorm/21_capa_ia_agentes.md); no
> los reemplaza.

Audiencia: el maintainer que decide qué construir después.

---

## 1. Tesis (cerrada)

No reabrir ni contradecir:

- **Mejorar el negocio** = calidad para el usuario actual de la app local. No
  es SaaS, freemium ni canal B2B.
- **Integrar sin problema** = mejorar la toma de decisiones. Si falta
  información, la AI la **recupera**. Si no puede, **no inventa**.
- **BUY/SELL y asignación personalizada siguen**, con disclaimer (PDF / About)
  y fundamentos correctos.
- El motor determinista no se toca: scores, pesos, Monte Carlo, stress y
  disparo de alertas siguen en código. La AI enriquece, narra, debate y —con
  overlay— emite acción/confianza.

---

## 2. Qué ve hoy la AI al decidir vs qué falta

`AIAnalyzer.analyze` arma **una** completion a temperatura 0
(`equity_decision_prompt` / `crypto_decision_prompt`) y parsea JSON con
`extract_json_object`. No hay tools en ese path. El chat sí tiene tools, pero
`ChatAgent._route` elige **exactamente uno**: `analyze_ticker`, `plan_status` o
`retirement_projection`.

| Dato | ¿Entra al prompt de decisión? | Efecto si falta |
|------|-------------------------------|-----------------|
| Ratios yfinance (ROE, D/E, P/E…) | Sí, número o `N/A` (`fmt` en `prompts.py`) | El modelo igual emite tesis; no hay tool de recuperación |
| `data_quality` (good/partial/poor, missing, stale, conflictos) | **No** | `apply_data_quality_policy` en `apply_safety_overlay` degrada la **acción después**; el `reasoning` puede seguir siendo de STRONG BUY |
| Edad del cache (`get_age_hours`) | **No** | Stale no baja el level (`AUDIT_DATA_QUALITY.md`, gap P1) |
| 10-K / 10-Q texto | **No**. SEC/FMP reconcilian XBRL y **no puntúan** | Moat cualitativo se apoya en `longBusinessSummary[:700]` |
| Macro fechado (`analysis/macro_rag.py`, TF-IDF) | Solo el estratega del **comité** | En decisión ticker, `macro_factors` sale de «tu conocimiento actual» |
| Competitors, insider, transcripts, 8-K | **No** | El campo Catalizadores se inventa |
| Track record de *ese* ticker | **No** | Sin feedback de aciertos |
| Plan / holdings | No en decisión por ticker | Asignación 1–15 % es genérica; `max_position_pct` del overlay sí aplica |

Con AI off el producto sigue usable (screener, optimizer, MC, alertas, PDF).
Chat y comité hacen `st.stop()` si AI está apagada. `enrich_only` es flag
in-process, no knob de Settings: enriquece moat/tailwind cacheados y deja la
decisión rule-based.

Eso choca con la tesis: hoy, si falta información, la AI **no la resuelve**.

---

## 3. Split de vendors (research Partial, 2026-09-08)

Elección por contrato de APIs y de este repo, **no** por bake-off de calidad
de decisión (ese bake-off no existe; Idea 5 de Eval IA sigue siendo propuesta).

| Camino | Vendor / modelo |
|--------|-----------------|
| Default (decisión, comité, chat con tools de la app) | Anthropic `claude-sonnet-4-6` (ya shipped) |
| Cuando faltan cifras de 10-K/10-Q | xAI `grok-4.6` Collections / `collections_search` |
| Un solo vendor | Claude PDF + citas + `web_fetch` (no replica el workflow SEC de Collections) |
| Privado | ZDR en API comercial (Claude / OpenAI / xAI). No Ollama para emitir BUY/SELL |

**Trampa documentada:** las citas de Claude **no se combinan** con structured
outputs. El path de `Decision` exige JSON. Flujo: retrieve citado → evidence
pack → JSON de decisión. No citas y BUY/SELL en la misma llamada.

**No usar para BUY/SELL:** Ollama (JSON Schema + tools no están documentados
como un solo decode estricto). **No tratar como Grok actual:** `grok-4.3` /
`grok-4.20` / `grok-build-0.1` (siguen en Settings). **No Haiku** si el
criterio es español. **No** Gemini, BloombergGPT, FinGPT, LangChain, Pinecone
como vendor de este plan.

Settings está desfasado respecto de los flagships (`gpt-4o` vs gpt-5.6-*;
Grok viejo vs `grok-4.6`).

---

## 4. Las 22 ideas

Numeración estable 1–22. No fusionar. Cada idea deja intactos score, pesos, MC
y el disparo de alertas.

### A. Fundamento correcto *antes* de emitir BUY/SELL

#### 1. Meter `data_quality` en el prompt de decisión

- **Problema:** el overlay degrada BUY→HOLD por `poor`/`partial` después de que
  el modelo ya escribió una tesis de STRONG BUY.
- **Superficie:** `analysis/prompts.py` (`equity_decision_prompt`,
  `crypto_decision_prompt`); el dict vive en
  `FundamentalResult.data_quality` (`analysis/fundamental.py`).
- **Tecnología:** inyección de texto (level, campos missing, age, conflictos).
  Sin vendor nuevo.
- **Por qué no rompe el motor:** `apply_data_quality_policy` en
  `analysis/strategy.py` se queda; solo alinea la prosa con la acción.
- **Fricción:** Bajo.
- **Origen:** nueva (el overlay P0.2 ya existe).

#### 2. Loop de tools en la decisión

- **Problema:** una completion sin tools no puede completar un `N/A`, un
  `poor` o un conflicto.
- **Superficie:** `analysis/ai_analyzer.py`; adapters ya en
  `data/data_sources.py` (`SecEdgarSource`, `FmpSource`, financials).
- **Tecnología:** function calling nativo (Claude tools `strict` / schema) en
  el path de `analyze()`, no solo en chat. Si hay hueco, pide
  `get_financials` / SEC / FMP **antes** del JSON de `Decision`.
- **Por qué no rompe el motor:** los adapters no puntúan; el score lo sigue
  poniendo el fundamental. La AI arma el paquete de evidencia.
- **Fricción:** Medio.
- **Origen:** nueva como path de decisión; el registro de tools del chat ya
  existe (`analysis/chat_tools.py`).

#### 3. Missing no se rellena con memoria del modelo

- **Problema:** un ROE `N/A` hoy no impide STRONG BUY con un número inventado.
- **Superficie:** `analysis/prompts.py` + `eval_harness` /
  `scripts/run_eval.py`.
- **Tecnología:** regla de contrato: si el ratio sigue `N/A` tras el tool,
  `confidence` ≤ LOW y nada de STRONG BUY. Test replayable.
- **Por qué no rompe el motor:** no rellena el `FundamentalResult`; solo capea
  la acción/confianza del LLM.
- **Fricción:** Bajo.
- **Origen:** nueva (ancla de «fundamentos correctos»).

#### 4. Missing vs zero explícito en el prompt

- **Problema:** gap P1 de `AUDIT_DATA_QUALITY.md` (`roe if roe != 0 else None`
  y análogos). `fmt()` dice `N/A` o un 0 mentiroso (p.ej. D/E en equity
  negativo).
- **Superficie:** `analysis/prompts.py` `fmt()`; overlay de equity negativo ya
  en `apply_negative_equity_policy`.
- **Tecnología:** etiquetar ausente vs cero vs no aplicable. Sin API nueva.
- **Por qué no rompe el motor:** copy del prompt; el overlay de seguridad se
  queda.
- **Fricción:** Bajo.
- **Origen:** ya auditado P1; no está en el prompt.

#### 5. Paquete 10-K/10-Q con citas para moat y catalizadores

- **Problema:** el moat cualitativo se apoya en 700 caracteres de yfinance, no
  en un filing.
- **Superficie:** `analysis/moat.py`, prompts de moat/decisión.
- **Tecnología:** `grok-4.6` Collections (flujo SEC de primera parte) o, un
  solo vendor, Claude PDF + citas + `web_fetch`. Retrieve **antes** del JSON
  (citas Claude ≠ structured outputs en la misma llamada).
- **Por qué no rompe el motor:** el 0–12 cuantitativo no se muta; las frases
  cualitativas llevan página. SEC/FMP siguen sin puntuar.
- **Fricción:** Medio.
- **Origen:** nueva.

#### 6. Macro RAG fechado en la decisión por ticker

- **Problema:** `macro_rag.py` (TF-IDF, no LLM) solo entra al estratega del
  comité. En `equity_decision_prompt` el modelo usa «tu conocimiento actual».
- **Superficie:** `analysis/macro_rag.py` → `equity_decision_prompt`.
- **Tecnología:** inyectar snippets fechados; prohibir conocimiento del modelo
  como fuente de `macro_factors`. Embeddings locales (Sentence Transformers)
  son opcionales; el swap ya está tratado como cambio localizado en el RAG.
- **Por qué no rompe el motor:** RAG no calcula score; `macro_factors` sigue
  siendo ≤2 y no mueve el score de tailwinds curado.
- **Fricción:** Bajo.
- **Origen:** nueva de superficie (el módulo RAG ya existe).

#### 7. Un evidence pack compartido para ficha, comité y chat

- **Problema:** tres opiniones sobre el mismo ticker con tres contextos.
- **Superficie:** `dashboard/pages/2_Stock_Analysis.py`,
  `analysis/committee.py`, `analysis/chat_agent.py`.
- **Tecnología:** un retrieve (DQ + filings + macros) reutilizado; el
  `aggregate` del comité **sigue determinista**.
- **Por qué no rompe el motor:** no unifica código de cálculo; unifica
  evidencia. El comité no entra a `full_analysis`.
- **Fricción:** Medio.
- **Origen:** ya en `brainstorm/21_capa_ia_agentes.md` Idea 1 y BACKLOG
  «unificar ficha+comité+chat» ❌; acá acotado a un pack, no a una sola
  pantalla.

#### 8. Stale: `age_hours` en el prompt + tool de refresh

- **Problema:** stale no degrada el level; el modelo no ve la edad del cache.
- **Superficie:** `data/cache.py` `get_age_hours`; prompts de decisión.
- **Tecnología:** mostrar horas; tool de re-fetch. Si el refresh falla,
  baja confidence. Sin cambiar la política P1 de level.
- **Por qué no rompe el motor:** no reescribe scores por antigüedad; solo
  transparencia y convicción.
- **Fricción:** Bajo.
- **Origen:** gap P1 de `AUDIT_DATA_QUALITY.md`.

### B. Recuperar lo que el motor no tiene (sin reemplazarlo)

#### 9. Catalizadores desde filings/8-K, no desde memoria

- **Problema:** el `reasoning` pide catalizadores 12–18 meses sin fuente.
- **Superficie:** contrato JSON de `equity_decision_prompt` (sección
  Catalizadores).
- **Tecnología:** mismo retrieve de idea 5 (MD&A / 8-K citados). Si no hay
  fuente: lista vacía y cap de confidence.
- **Por qué no rompe el motor:** no inventa un evento en el scorer.
- **Fricción:** Medio.
- **Origen:** nueva.

#### 10. ADRs / no-US: recuperar lo que SEC no tiene

- **Problema:** `SecEdgarSource` devuelve `{}` fuera de US (GGAL, BMA, YPF).
- **Superficie:** `data/data_sources.py`; prompt AR ya existe en
  `equity_decision_prompt` para `ARGENTINA_ADRS`.
- **Tecnología:** 20-F / estados CNV / FMP si hay key, **después** de validar
  números contra el adapter. Fallo visible; no improvisar márgenes.
- **Por qué no rompe el motor:** SEC/FMP siguen sin puntuar; el descuento de
  riesgo país ya es código (`country` en `FundamentalResult`).
- **Fricción:** Medio.
- **Origen:** nueva.

#### 11. Conflicto multi-fuente como input, no solo badge

- **Problema:** `attach_cross_source_quality` no reescribe scores y no entra
  al prompt.
- **Superficie:** `analysis/data_reconciliation.py`,
  `FundamentalAnalyzer._finalize_data_quality`.
- **Tecnología:** mostrar «yfinance ROE X vs SEC Y, mismo período» y bajar
  convicción. No promediar a ojo.
- **Por qué no rompe el motor:** P0.1 ya dice que la reconciliación no pisa
  scores.
- **Fricción:** Bajo.
- **Origen:** P0 cerrado como badge; hueco de prompt.

#### 12. Chat multi-paso

- **Problema:** `_route` elige un tool. «¿Si aporto 500 más, llego?» necesita
  más de un número del motor.
- **Superficie:** `analysis/chat_agent.py`, `analysis/chat_tools.py`.
- **Tecnología:** loop nativo 2–3 tools; el narrador sigue viendo solo
  output determinista. Adapters futuros de optimizer/stress siguen siendo
  wrappers del motor (`optimize()` no reescribe pesos).
- **Por qué no rompe el motor:** misma garantía anti-alucinación, más pasos.
- **Fricción:** Medio.
- **Origen:** ya en `DIAGNOSTICO_PROXIMO_NIVEL_2026-09.md` § C (encadenar 2–3
  tools). Lo nuevo es tool use nativo vs JSON en el prompt.

#### 13. Asignación anclada al plan/libro si existen

- **Problema:** `recommended_max_allocation_conservative` 1–15 % es abstracta
  respecto del libro real.
- **Superficie:** `AIAnalyzer.analyze` + `chat_tools._tool_plan_status`.
- **Tecnología:** si hay plan activo, inyectar `plan_status` en la *decisión*
  (no solo chat). Overlay `max_position_pct` se queda.
- **Por qué no rompe el motor:** no cambia SLSQP ni el sizer; solo el %
  narrado/capeado del LLM.
- **Fricción:** Medio.
- **Origen:** nueva.

#### 14. Track record de ese ticker en el prompt, con n honesto

- **Problema:** el hit rate vivo es chico; esconderlo empeora la decisión.
- **Superficie:** `analysis/track_record.py` / `RecommendationLog`.
- **Tecnología:** «n=2 a 30 días, no uses esto como prueba». No calibra
  umbrales (eso es U5-1b, código).
- **Por qué no rompe el motor:** no mueve `PiotroskiConfig` ni scores.
- **Fricción:** Bajo.
- **Origen:** nueva.

### C. Que el output no mienta sobre los fundamentos

#### 15. Structured outputs nativos en Decision, moat y router

- **Problema:** `extract_json_object` sobre prosa. Parse fallido cae al
  rule-based; uno parcial puede emitir BUY con `rationale` vacío.
- **Superficie:** `analysis/ai_analyzer.py`, `analysis/utils.py`.
- **Tecnología:** `client.messages.parse` / JSON Schema (Claude default);
  OpenAI `responses.parse` si el usuario elige ese provider. Dejar de extraer
  JSON de completions libres.
- **Por qué no rompe el motor:** mismo dataclass `Decision`; fallback
  rule-based se queda.
- **Fricción:** Bajo.
- **Origen:** nueva de wrapper.

#### 16. Citas en `reasoning`: número del motor vs frase del filing

- **Problema:** badges cálculo vs IA ya existen (Ola 1); falta el ancla
  («ROE 22 % = `fund.roe`»; «switching costs = 10-K p. 12»).
- **Superficie:** prompts + UI que ya usa `render_calc_badge` /
  `render_ai_badge`.
- **Tecnología:** citas en el evidence pack (idea 5), no en la misma llamada
  que el JSON si el vendor lo prohíbe. Sin cita, ese tramo no sube
  confidence.
- **Por qué no rompe el motor:** no cambia números; cambia trazabilidad.
- **Fricción:** Bajo.
- **Origen:** extiende `brainstorm/21_capa_ia_agentes.md` Idea 12
  (anti-alucinación visible).

#### 17. Eval: «no inventó un ratio que era N/A» + schema

- **Problema:** el harness valida estructura, acciones, caps de asignación y
  riesgos-en-BUY, no «inventó un ROE».
- **Superficie:** `dashboard/pages/14_Eval_IA.py`, `scripts/run_eval.py`.
- **Tecnología:** checks sobre el default Claude. Guardrails Python del
  vendor está en Preview: usar el harness propio. Replay CI sin API se queda.
- **Por qué no rompe el motor:** eval no escribe scores de producción.
- **Fricción:** Bajo.
- **Origen:** extiende el eval existente.

#### 18. Prompt caching del evidence pack (comité / chat)

- **Problema:** comité ticker = 5 llamadas paralelas; holdings = 4. El
  wrapper manda completion plano; el cache SQLite (24 h / 168 h) no cubre el
  prefix del vendor. Sonnet 4.6 pide ≥1.024 tokens cacheables.
- **Superficie:** `AIAnalyzer._call_claude`.
- **Tecnología:** `cache_control` Anthropic (y equivalentes) sobre el pack
  de idea 7.
- **Por qué no rompe el motor:** costo/latencia; cero cambio de score.
- **Fricción:** Bajo.
- **Origen:** relacionada con `brainstorm/21_capa_ia_agentes.md` Idea 10
  (cachear respuestas).

#### 19. Knob de Settings: «IA no mueve ranking» vs «IA decide con overlay»

- **Problema:** `AIConfig.enrich_only` no es env ni Settings. El bonus de
  moat 0–8 y el action del LLM **sí** mueven ranking cuando AI está on.
- **Superficie:** `dashboard/pages/9_Settings.py`, `config.AIConfig`.
- **Tecnología:** switch de usuario. Con la tesis de este doc, el default
  sigue siendo «IA decide con overlay»; el otro modo sirve para comparar
  fundamentos.
- **Por qué no rompe el motor:** `enrich_only` ya está implementado
  in-process (U0-2).
- **Fricción:** Bajo.
- **Origen:** nueva de UX.

#### 20. Minimizar holdings en el prompt de ticker público

- **Problema:** el comité de holdings ya manda nombre del plan, pesos y valor.
  Una decisión de ticker público no necesita el libro.
- **Superficie:** prompts de decisión vs `build_holdings_committee_context`.
- **Tecnología:** plan solo en tools de asignación (idea 13). Higiene de
  payload; Anthropic/OpenAI/xAI no entrenan con API por default y retienen
  ~30 días salvo ZDR.
- **Por qué no rompe el motor:** no cambia cálculos.
- **Fricción:** Bajo.
- **Origen:** nueva.

#### 21. Digest de alertas con el mismo evidence pack

- **Problema:** `AlertEngine` dispara sin LLM; la explicación opcional puede
  ser `""` o prosa desanclada («el mercado está nervioso»).
- **Superficie:** `alerts/engine.py` `_get_ai_explanation`,
  `scripts/run_scheduler.py`.
- **Tecnología:** narrativa del lote citando el dato que cambió (precio, DQ,
  filing). El disparo y los cooldowns siguen en el engine.
- **Por qué no rompe el motor:** AI off deja la alerta igual.
- **Fricción:** Bajo.
- **Origen:** cercana a `brainstorm/21_capa_ia_agentes.md` Idea 7 (vigilante
  del plan), **sin** agente nuevo.

#### 22. Ollama solo prosa / offline, no emisor de BUY/SELL

- **Problema:** el README dice que hoy no corre LLM local. Idea 8 del
  brainstorm de agentes lo pide como privacidad. Los docs de Ollama no
  garantizan JSON Schema + tools como un solo decode estricto; un parse
  fallido ya degrada a HOLD o al motor de reglas.
- **Superficie:** `AIConfig.provider` (hoy `claude` / `openai` / `xai` /
  `nous`).
- **Tecnología:** `ollama.chat` solo para narrativa o modo offline. BUY/SELL
  queda en `claude-sonnet-4-6` hasta que un eval (idea 17) demuestre schema
  + tools.
- **Por qué no rompe el motor:** no pone un local LLM en `AIAnalyzer.analyze`.
- **Fricción:** Medio (ops: instalar Ollama).
- **Origen:** ya en `brainstorm/21_capa_ia_agentes.md` Idea 8; acá acotado a
  no-decisión.

---

## 5. Fuera de las 22

No cuentan. Cambian la tesis o no están maduras para «sin problema»:

- SaaS, cuentas, freemium, modo asesores (`DEMO_HOSTED.md` las rechazó: un
  usuario por instancia).
- OpenAI File Search hosteado (el plan viviría en discos del vendor).
- Voz Realtime (GA y cara; Streamlit + WebRTC no es integración chica).
- Agente fiscal sin motor de impuestos del *usuario* (`TaxConfig` es
  corporativo/NOPAT; módulo de impuestos sigue ❌ en BACKLOG).
- LLM que reescribe pesos, μ, Monte Carlo o el disparo de alertas.
- Más agentes (coach, vigilante, experto AR) **antes** del evidence pack:
  proliferación (`brainstorm/21_capa_ia_agentes.md`). Un rol AR tiene sentido
  **después** de poder recuperar 20-F/CNV (idea 10).

---

## 6. Orden sugerido

Sin esperar un bake-off de vendors:

1. **Idea 1** — `data_quality` en el prompt.
2. **Idea 2** — loop de tools de recuperación en la decisión.
3. **Idea 3** — missing no se rellena con memoria.
4. **Idea 5** — 10-K/10-Q citados (`grok-4.6` Collections o Claude PDF).
5. **Idea 6** — macro RAG fechado en la decisión por ticker.

Después: structured outputs (15), evidence pack compartido (7), eval de
no-invención (17). El split de vendors se cablea en 2 y 5, no como un
migración de Settings «porque hay un flagship más nuevo».
