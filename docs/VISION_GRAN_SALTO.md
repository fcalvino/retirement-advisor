# Visión — El Gran Salto

> Documento estratégico de producto. No describe trabajo ya hecho (para eso está
> `ROADMAP.md`), sino **hacia dónde saltar**. Pensado para guiar las próximas fases.
> Fecha: 2026-06. Estado del producto al escribir: 419 tests, Fases 1–H completas.

---

## Tesis central

El producto ya es un **motor de análisis técnicamente maduro**: fundamental + moat +
técnico + decisión IA multi-proveedor, optimizer mean-variance, Monte Carlo con
decumulación, stress test, tailwinds curados, plan vivo, alertas. La base analítica está
prácticamente completa. Agregar "otro score" da rendimientos decrecientes.

**El gran salto no es más análisis — es cambiar la categoría del producto:**

> De *motor de análisis que el usuario debe saber operar*
> a *asesor que conversa, razona en comité, actúa y rinde cuentas*.

Tres ideas reorganizan todo lo construido en esa dirección, apoyadas en dos habilitadores
(datos confiables y modelo más sólido) y abiertas a saltos de negocio. Todo lo que sigue
**reutiliza** la infraestructura existente: el codebase ya es una librería de herramientas
casi perfecta para un agente.

---

## Las 3 grandes apuestas

### Apuesta 1 — Interfaz conversacional: "Hablá con tu plan"

**Qué.** Un chat donde el usuario pregunta en lenguaje natural
(*"¿qué pasa si me jubilo 3 años antes?"*, *"¿por qué bajó NVDA en mi screener?"*,
*"¿estoy muy expuesto a Argentina?"*) y un **agente orquestador** elige y ejecuta las
funciones correctas, devuelve la respuesta con el gráfico y propone la acción.

**Por qué es el salto de UX.** Hoy son ~12 páginas de Streamlit que el usuario tiene que
saber recorrer en el orden correcto (Screener → Analysis → Optimizer → Plan…). La barrera
de uso es la navegación, no el motor. Un chat colapsa esa barrera a cero y vuelve
accesible toda la potencia que ya existe.

**Qué reutiliza (casi todo).** El motor ya está separado de la UI. Las funciones son
directamente "tools" para function-calling:
- `analysis/strategy.py:full_analysis`
- `portfolio/optimizer.py:optimize`
- `portfolio/monte_carlo.py:MonteCarloSimulator.run`
- `portfolio/stress_test.py:StressTester.run`
- `portfolio/sensitivity.py:run_sensitivity`
- `data/plan_context.py:compute_plan_vs_reality` / `compute_alignment_trades`

**Esfuerzo:** Alto. **Impacto:** Muy alto.
**Dependencias:** se beneficia enormemente de la Apuesta 2 (el orquestador *es* un agente)
y del eval harness (sección técnica). Streamlit pasa de ser *el producto* a ser un panel
de respaldo / power-user.

**Riesgos.** Que el agente ejecute la herramienta equivocada o alucine números → mitigar
con tool-calling estricto (la IA nunca inventa cifras, solo invoca funciones
deterministas) y mostrando siempre el dato crudo junto a la narrativa, como ya hace el
producto hoy.

---

### Apuesta 2 — Comité de inversión multi-agente

**Qué.** Reemplazar la llamada IA única (un prompt → una decisión) por la **simulación de
un comité** de agentes especializados que debaten y producen un dictamen con **disenso
explícito**:

| Agente | Rol | Reutiliza |
|--------|-----|-----------|
| Analista Fundamental | Defiende la tesis anclado a los números duros | `equity_decision_prompt` |
| Estratega Macro | Tasas, riesgo país, ciclo, liquidez | bloques `_*_macro_factors` |
| Risk Manager / Abogado del Diablo | **Red-team**: arma el bear case, busca por qué NO | prompt nuevo |
| Portfolio Manager | Concilia, dimensiona, decide allocation | `portfolio_optimizer_advice_prompt` |
| Behavioral Coach | Traduce a lenguaje humano, ancla al plan | `long_term_plan_narrative_prompt` |

**Por qué es un diferenciador real.** El LLM single-shot tiene sesgo de complacencia: si le
pedís una tesis, te la da. Un **abogado del diablo estructural** que siempre arma el caso
contrario genera disenso auditable y combate ese sesgo — exactamente la filosofía
conservadora del producto ("que el inversor no se arruine"). Es la diferencia entre
"ChatGPT te dice qué comprar" y "un comité de inversión te muestra el debate".

**Qué reutiliza.** Casi toda la lógica vive en `analysis/prompts.py` y
`analysis/ai_analyzer.py`. Es **orquestación de prompts existentes + 1–2 prompts nuevos +
un agregador de consenso**, no infraestructura nueva. El multi-proveedor ya soportado
(Claude/GPT-4o/Grok/Nous) incluso permite que distintos agentes corran en distintos
modelos.

**Esfuerzo:** Medio. **Impacto:** Muy alto. **Mejor ratio impacto/esfuerzo del documento.**
**Dependencias:** se vuelve mucho más confiable con la Apuesta 4 (RAG macro) y *requiere*
el eval harness para mejorarse sin volar a ciegas.

**Riesgos.** Costo de tokens (varias llamadas por decisión) → mitigar cacheando el comité
como hoy se cachea el moat AI, y reservando el comité completo para decisiones de peso
(no para refrescar 38 tickers). Latencia → correr agentes en paralelo.

---

### Apuesta 3 — Track record y calibración: confianza auditable

**Qué.** Persistir **cada recomendación** y medir su acierto histórico:
- *"Nuestras señales STRONG BUY rindieron X% vs SPY a 12 meses."*
- *Calibración*: "cuando decimos HIGH confidence, acertamos Y% de las veces."
- Curva de equity de las señales del modelo vs. benchmark.

**Por qué cambia todo en confianza.** Es lo único de alto impacto que el producto **no
tiene hoy**. Para una herramienta de retiro, el foso no es la sofisticación del modelo —
es la confianza. Un track record auditable convierte "creeme" en "acá está mi historial".
Es también el insumo honesto para mejorar el modelo: sin medir aciertos, no sabés si una
mejora mejora algo.

**Qué reutiliza.** La infraestructura de persistencia ya existe: `alerts/store.py`
(snapshots por ticker + historial), el patrón SQLite, los snapshots de plan. Es
principalmente **registro disciplinado + un módulo de scoring de aciertos + una página de
visualización**.

**Esfuerzo:** Bajo–Medio. **Impacto:** Muy alto (confianza) + Alto (mejora del modelo).
**Dependencias:** ninguna dura; se puede empezar ya. **Recomendado como primer paso.**

**Riesgos.** Mostrar un track record también expone los errores → es una decisión de
producto (la transparencia es el punto), pero conviene framing honesto y horizontes largos
(no cherry-picking de ventanas favorables).

---

## Habilitadores: datos y modelo

### Datos — la debilidad estructural #1

Todo entra por `yfinance`. **Garbage in, garbage out.** Peor aún: los prompts le piden al
LLM que *"use su conocimiento macro actual"*, que es training data potencialmente
desactualizada — los `macro_factors` pueden estar, en el peor caso, inventados.

Saltos:
- **Multi-fuente con reconciliación**: SEC EDGAR (fundamentals reales de los filings),
  FRED (macro), FMP/Alpha Vantage como cross-check, con un *agente de calidad de datos*
  que detecta discrepancias entre fuentes. Extiende el badge de calidad que ya existe
  (`compute_data_quality`).
- **RAG macro en tiempo real**: indexar releases de la Fed, datos económicos y noticias, e
  inyectarlos como **contexto fresco** en los prompts en vez de confiar en la memoria del
  modelo. Esto hace que `macro_factors` deje de ser un acto de fe y pase a estar anclado a
  hechos verificables y fechados.

**Esfuerzo:** Alto. **Impacto:** Alto y transversal (habilita que las Apuestas 1–3 sean
creíbles). Ya figura como pendiente "multi-source data" en el backlog H+.

### Modelo — upgrade cuantitativo

- **Black-Litterman** en lugar del proxy de expected returns
  (`score/100*0.18 + …` en `optimizer.py`). BL es la forma canónica de combinar el
  equilibrio del mercado con *views* subjetivas — y el score ajustado **es** exactamente
  una view. Resuelve de raíz el problema conocido de que el perfil **Conservador es
  matemáticamente infeasible** con el universo default (hoy se cae a fallback
  score-weighted).
- **Shrinkage de covarianza (Ledoit-Wolf)** en vez de covarianza muestral: más estable con
  pocos datos, menos pesos extremos.
- **Análisis de exposición a factores** (value / quality / momentum / size) de la cartera:
  hoy el usuario no sabe a qué factores está realmente expuesto.
- **Monte Carlo con regime-switching** (no solo block-bootstrap): modela cambios
  estructurales que el README ya reconoce como limitación.

**Esfuerzo:** Medio (BL, shrinkage) a Alto (regímenes). **Impacto:** Medio–Alto. Es
profundidad de modelo; conviene después de datos y agentes.

---

## Catálogo de nuevos módulos (por impacto)

- **Planificación financiera real, no solo de inversión.** Multi-cuenta (taxable vs.
  tax-advantaged), orden óptimo de retiro de fondos, *tax-loss harvesting*, modelado de
  aportes/pensión. Los "drags" (`EconomicDragConfig`) ya existen, pero no hay optimización
  tributaria real. — *Impacto: Alto.*
- **Estrategia de buckets para riesgo de secuencia.** Cash / bonos / equity por tramos
  temporales. El producto ya modela el riesgo de secuencia en decumulación pero no lo
  *operacionaliza*. — *Impacto: Alto.*
- **Capa Argentina first-class.** Modelado dual ARS/USD, brecha cambiaria, instrumentos
  CER/inflación — no solo el descuento de 15% a ADRs. Diferenciador de mercado enorme para
  LatAm. — *Impacto: Alto (estratégico).*
- **Coach proactivo anclado al plan.** Cuando el mercado cae 8%, un check-in automático
  *"acá está por qué tu plan sigue OK"*. Reutiliza el scheduler y las alertas. Ataca donde
  realmente fracasan los inversores de retiro: el comportamiento (pánico). — *Impacto:
  Alto.*
- **Proyector de ingreso por dividendos / escalera de cashflow** para la fase de retiro. —
  *Impacto: Medio.*

---

## Ingeniería / técnico

- **Eval harness para la IA.** Hoy hay tests de *estructura* de prompts
  (`test_prompts.py`) pero **ninguno de calidad de output**. Sin esto, cambiar un prompt es
  a ciegas y el comité multi-agente no se puede mejorar de forma disciplinada. Un set de
  casos dorados + scoring de respuestas es **prerrequisito** de las Apuestas 1 y 2. —
  *Esfuerzo: Medio. Impacto: Alto (habilitador).*
- **Sacar el cómputo pesado de Streamlit.** Streamlit re-ejecuta el script entero en cada
  interacción. Mover a job queue + cache de resultados; vector store para el RAG;
  observabilidad y logging de decisiones IA + costo por token. — *Esfuerzo: Medio.*
- **Frontend desacoplado** a mediano plazo. El motor ya está bien separado de la UI, así
  que el costo de migrar es acotado cuando el chat justifique una UI propia. —
  *Esfuerzo: Alto.*

---

## Saltos de negocio

- **B2B2C — "asesor en una caja" para advisors independientes de LatAm.** White-label del
  comité + reportes PDF branded. Ellos ya tienen los clientes; el producto aporta el motor.
  Probablemente el camino comercial más rápido. — *Potencial: Alto.*
- **SaaS hosteado multi-tenant** con tiers de datos premium (los datos buenos cuestan: ese
  es el upsell natural). — *Potencial: Medio–Alto.*
- **Riesgo transversal de compliance.** Cuanto más "asesor que actúa" sea el producto, más
  cerca del **asesoramiento financiero regulado** estás. El disclaimer actual alcanza para
  una herramienta educativa local; un SaaS que sugiere trades necesita revisión legal seria
  antes de escalar. No es un detalle: es un gate.

---

## Matriz de priorización

| Iniciativa | Esfuerzo | Impacto | Reusa infra | Cuándo |
|-----------|:--------:|:-------:|:-----------:|:------:|
| Track record / calibración | Bajo–Medio | Muy alto | Alta | **Ya** |
| Comité multi-agente | Medio | Muy alto | Alta | Temprano |
| Eval harness IA | Medio | Alto (habilitador) | Media | Junto al comité |
| RAG macro + multi-source | Alto | Alto (transversal) | Media | Antes de escalar IA |
| Interfaz conversacional | Alto | Muy alto | Alta | Tras comité + evals |
| Black-Litterman + shrinkage | Medio | Medio–Alto | Alta | Profundidad |
| Módulos planificación (tax/buckets/AR) | Medio–Alto | Alto | Media | Continuo |
| Coach proactivo | Medio | Alto | Alta (alertas) | Oportunista |
| B2B2C / SaaS | Alto | Estratégico | — | Tras confianza |

---

## Secuencia recomendada

1. **Track record / calibración** — bajo esfuerzo, reusa stores existentes, máximo retorno
   en confianza. Empezar ya.
2. **Comité multi-agente** + **eval harness** — orquestación de prompts existentes; el eval
   harness lo vuelve mejorable de forma disciplinada.
3. **RAG macro + multi-source** — habilita que 1 y 2 sean creíbles (macro fresco, datos
   reconciliados).
4. **Interfaz conversacional** — el salto de UX, una vez que el motor agéntico existe.
5. **Black-Litterman + módulos de planificación** (tributaria, buckets, capa AR) —
   profundidad de modelo y producto.

---

## Una observación honesta (para equilibrar)

El producto ya tiene una densidad de features altísima. Parte del Gran Salto podría ser
**consolidar y profundizar** (datos confiables + track record + conversación) en lugar de
seguir agregando módulos. Un motor en el que se puede *confiar* y con el que se puede
*hablar* vale más que 15 análisis nuevos. La sofisticación analítica ya está; lo que falta
es **confianza** (track record), **accesibilidad** (chat) y **fundamento de datos**
(multi-source + RAG). Ese es el verdadero salto de nivel.
