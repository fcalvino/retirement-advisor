# Auditoría de producto — Retirement Advisor  
**Visión:** Project Owner encargado de mejorar el proyecto  
**Fecha:** 2026-08-09  
**Idioma del informe:** español, sin jerga innecesaria  
**Alcance:** diagnóstico y priorización de producto (no es revisión de código ni plan de implementación técnica)

---

## 1. Qué es el producto y para quién

### En una frase
**Retirement Advisor** es una aplicación local que ayuda a una persona a **calificar inversiones de largo plazo, armar una cartera orientada al retiro y seguir un plan vivo** — con números honestos (a veces conservadores a propósito) y, si se quiere, ayuda de inteligencia artificial que **no inventa cifras**.

### Qué hace (en lenguaje de usuario)
- **Ordena un universo de acciones y ETFs** (más de 30 tickers por defecto, con ADRs argentinos y cripto como Bitcoin) según calidad de negocio, valuación y señales de compra/espera/venta.
- **Analiza en profundidad** un activo: salud financiera, “foso” competitivo (ventaja de la empresa a largo plazo), y una recomendación en lenguaje natural si hay IA configurada.
- **Construye una cartera** según perfil de riesgo (conservador / moderado / agresivo) y capital disponible.
- **Proyecta el futuro** con miles de escenarios posibles (¿llegás a la meta? ¿qué pasa en una crisis?) y con estrategias de retiro (cuánto sacar sin quedarte sin plata).
- **Guarda y activa un “Mi Plan”**: lista de compra, PDF, comparación con el mercado, desvíos, historial de salud del plan y respaldo exportable.
- **Monitorea** posiciones reales, alertas, historial de aciertos de las señales (Track Record) y, opcionalmente, un chat (“Hablá con tu plan”) y un “comité de inversión” con opiniones en desacuerdo a propósito.

Fuentes de esta descripción: `README.md` (qué hace, pantallas, quick start), `docs/CONTEXT.md` §1 y §6 (filosofía y features completas), `docs/VISION_GRAN_SALTO.md` (tesis de producto).

### Para quién es hoy
| Perfil | ¿Encaja? | Comentario de producto |
|--------|----------|------------------------|
| Inversor particular de largo plazo (5–30 años) | **Sí, núcleo** | El producto se define así en el resumen ejecutivo. |
| Persona en LatAm / Argentina (ADRs, riesgo país, retiro en USD) | **Sí, diferencial** | Universos y planes de ejemplo con ADRs; descuento de riesgo argentino documentado. |
| Alguien que quiere FIRE o retiro clásico | **Sí** | Presets de escenarios y planes de ejemplo (conservador 30y, FIRE moderado, retiro AR). |
| Usuario no técnico que no quiere instalar nada | **Parcial / débil** | Hay `run.sh` y Docker, pero sigue siendo “bajar y correr en tu máquina”. Eso excluye a la mayoría. |
| Asesor financiero con muchos clientes | **No aún** | No hay multi-usuario ni modo asesor (está en ideas de negocio, no en producto). |
| Day-trader o operador de corto plazo | **No** | Sin datos intradía; horizonte y filosofía son de largo plazo. |

### Posicionamiento actual (honesto)
Es un **motor de análisis y planificación de retiro de alta densidad**, pensado para uso individual, con datos en la propia máquina y sin suscripción obligatoria para el análisis básico.  
La visión estratégica ya lo dice con claridad: el siguiente salto **no es “otro score más”**, sino pasar de *herramienta que hay que saber operar* a *asesor que guía, conversa y rinde cuentas* (`docs/VISION_GRAN_SALTO.md`).

---

## 2. Recorrido del usuario de punta a punta

Desde **abrir la app** hasta **tener un plan accionable**. Lo siguiente está anclado al menú real y al “camino guiado” implementado en Inicio / Mi Plan.

### Mapa de la app (lo que ve el usuario)
El menú está **agrupado por intención** (Ola 1 UX), no como una lista plana de módulos:

| Sección del menú | Pantallas |
|------------------|-----------|
| (arriba) | **Inicio**, **Hablá con tu plan** (chat) |
| Mi dinero | **Mi Plan**, Portfolio, Optimizer, Allocation |
| Investigar | Screener, Stock Analysis, Comité, Watchlist |
| Proyectar | Simulaciones, Backtesting |
| Seguimiento | Alertas, Track Record |
| Ajustes | Settings, About (+ herramientas de desarrollo solo si el “modo dev” está activo: Eval IA, Calidad de Datos, Macro RAG) |

Fuente: `dashboard/app.py` (navegación), `docs/CONTEXT.md` §6 (Ola 1 UX).

### Camino ideal recomendado por el producto
En Inicio aparece un texto de flujo recomendado:  
**Screener → Stock Analysis → Optimizer → Simulaciones → Mi Plan (guardar + activar) → Portfolio + Alertas**.

Además hay un **viaje guiado de 5 pasos** (progreso en la portada):

1. **Definí tu perfil de retiro** (edad, capital, ahorro, tolerancia al riesgo) — wizard de ~1 minuto en Inicio o Settings.  
2. **Optimizá tu cartera** — Optimizer usa el perfil y el capital como valores por defecto.  
3. **Guardá tu plan** — Mi Plan consolida cartera + metas + proyección + narrativa.  
4. **Activalo como objetivo vivo** — el seguimiento y las alertas lo usan como meta.  
5. **Respaldá tu plan** — exportar a archivo para no perderlo si reinstalás la app.

Fuente: `dashboard/shared.py` (`plan_journey_status`, `next_priority_action`), `dashboard/app.py` (bloque “Hoy hacé esto” y “Tu camino a un plan de retiro activo”).

### Camino “probar en 5 minutos” (sin armar nada desde cero)
Para adopción temprana el producto ya ofrece un atajo:

1. Abrir con `./run.sh` (o el quick start del README).  
2. Ir a **Mi Plan** (o desde Inicio: “Probar con un plan de ejemplo”).  
3. Cargar y activar un ejemplo: Conservador 30 años, FIRE Moderado o Retiro AR con ADRs.  
4. Explorar salud vs mercado, evolución, estrategia de retiro y laboratorio de sensibilidad en Simulaciones.  
5. Descargar el **PDF del plan**.

Fuente: `README.md` (“Probar en 5 minutos”), `data/sample_plans/*.json`, empty-state de `dashboard/pages/12_Plan.py`.

### Día a día, una vez que hay plan activo
- **Inicio** muestra “Hoy hacé esto” (una sola prioridad) y, si hay plan activo, un resumen: probabilidad de meta, resultado mediano, retorno esperado y frescura de datos.  
- **Portfolio** compara posiciones reales vs el plan y sugiere movimientos de alineación.  
- **Alertas** avisan cambios de señal, desvíos y degradación de salud del plan.  
- **Mi Plan** permite refrescar vs mercado, registrar evolución y regenerar la explicación en lenguaje humano.  
- **Chat** permite preguntar en castellano sin recorrer menús (siempre anclado a cálculos reales cuando hay herramientas conectadas).

### Dónde se traba el recorrido (síntesis; detalle en §4)
1. **Muchas puertas** para la misma pregunta (“¿esta acción es buena?”: Stock Analysis, Comité, Chat).  
2. **Varias pantallas arrancan vacías** hasta que el usuario aprieta un botón (fricción de “herramienta primero”).  
3. El plan **ya es el corazón**, pero no siempre **tira del resto** de la app (hay que saber volver a Mi Plan).  
4. El camino “completo” (perfil → optimizador → simulación → plan) sigue siendo **multi-pantalla** aunque el viaje guiado ayude.

Fuente de este diagnóstico de fricción: `docs/brainstorm/00_INDICE.md`, `docs/brainstorm/99_PRIORIZACION.md`, `docs/brainstorm/23_ux_global.md`.

---

## 3. Fortalezas reales hoy

Estas no son promesas de roadmap: son **capacidades ya entregadas** y visibles en producto / documentación de estado.

### 3.1 Un motor analítico maduro y completo
Análisis fundamental en varias dimensiones, puntuación de calidad contable, “foso” económico, técnico de largo plazo, optimización de cartera, proyecciones con muchos escenarios, stress en crisis históricas, decumulación (cómo retirar dinero en el retiro), sensibilidad (“qué pasa si…”).  
El roadmap marca **fases de producto ya cerradas** hasta decumulación, historial de salud del plan, laboratorio de sensibilidad y adopción (planes de ejemplo, packaging).  
**Valor PO:** no hay que “inventar el análisis”; hay que **hacerlo usable y creíble**.

Fuentes: `docs/CONTEXT.md` §6, `docs/ROADMAP.md` (Fases H, G, A–E), `README.md`.

### 3.2 Filosofía conservadora y transparente (diferencial de confianza)
Por defecto las proyecciones se inclinan a ser **prudentes** (más volatilidad y menor retorno esperado en la simulación). Existe comparación **“Realista vs Conservador”**, capa opcional de costos reales (comisiones, impuestos, rebalanceo, buffer Argentina), y disclaimers de supuestos en Inicio / About / plan.  
**Valor PO:** en retiro, **no arruinarse** importa más que promesas brillantes. Esa honestidad es un foso de producto si se ve y se entiende.

Fuentes: `docs/CONTEXT.md` §1, §8; Fase G y Fase J en roadmap/contexto; UI en Simulaciones y Mi Plan.

### 3.3 “Mi Plan” como sistema operativo del retiro
No es solo un informe estático: se **guarda, activa, compara, exporta/importa, genera PDF**, mide salud vs mercado, sugiere trades de alineación, registra evolución en el tiempo y puede narrarse con IA. Hay **planes de ejemplo** para ver valor en minutos.  
**Valor PO:** es el **corazón del producto** y la mejor pieza estratégica.

Fuentes: `dashboard/pages/12_Plan.py`, `data/plan_store.py`, `data/plan_context.py`, brainstorm `13_mi_plan.md`.

### 3.4 Guía de adopción ya empezada (no es solo “power user”)
- Wizard de perfil personal (Fase A).  
- Viaje de 5 pasos + botón **“Hoy hacé esto”** en Inicio.  
- Menú por intención; herramientas de desarrollo **fuera del menú cotidiano**.  
- Demo mode + `run.sh` / “Probar en 5 minutos”.  
**Valor PO:** se reconoce el problema de adopción y **ya se invirtió en él** (Ola 1 UX, Fase E, H.4).

Fuentes: `dashboard/app.py`, `dashboard/onboarding.py`, `docs/CONTEXT.md` §6 (Ola 1, Fase E, H.4).

### 3.5 Capa de confianza e IA con carácter propio
- **Comité multi-agente** con disenso explícito (incluye “abogado del diablo”) por ticker y sobre el portfolio real.  
- **Chat** que invoca herramientas reales y no debe inventar números.  
- **Track Record** para medir si las señales del pasado rindieron.  
- **Calidad de datos / reconciliación** y **Macro RAG** (más visibles en modo desarrollo).  
- Suite de tests grande y un QA de navegación de las pantallas con hallazgos documentados.  
**Valor PO:** hay insumos para **confianza auditable** y para un futuro “asesor que rinde cuentas”.

Fuentes: `docs/CONTEXT.md` §6, `docs/VISION_GRAN_SALTO.md` Apuestas 2–3, `logs/qa_report.md`, `tests/`.

### 3.6 Privacidad y control del usuario
Datos en la máquina del usuario; IA opcional; plan portable (export/import).  
**Valor PO:** argumento de venta real frente a apps que suben todo a la nube (`docs/brainstorm/24_negocio.md` Idea 9).

---

## 4. Debilidades, fricciones y flujos confusos

Priorizadas por **daño a adopción y claridad**, no por elegancia técnica.

### 4.1 Demasiada superficie, solapamientos de “misma pregunta”
Hay muchas pantallas. Varias responden casi lo mismo:  
- “¿Compro o no esta acción?” → Stock Analysis, Comité, Chat.  
- “¿Cómo armo / veo mi mezcla?” → Allocation vs Optimizer (Allocation es una regla por edad; Optimizer es la cartera concreta).  
El brainstorm lo resume: **consolidar > agregar**.  
**Fricción:** el usuario nuevo no sabe **dónde** debe estar.

Fuentes: `docs/brainstorm/00_INDICE.md`, `23_ux_global.md`, `99_PRIORIZACION.md`.

### 4.2 Muchas pantallas “en blanco” hasta que apretás un botón
Patrón “herramienta primero”: Screener, Comité, Chat, Alertas, Track Record, etc., piden trabajo **antes** de mostrar valor.  
Aunque la Ola 1 UX atacó parte de esto, el propio brainstorm y la priorización siguen marcando **“matar pantallas en blanco”** como trabajo prioritario.  
**Fricción:** en la primera visita la app se siente vacía y “de experto”.

Fuentes: `docs/brainstorm/00_INDICE.md`, `99_PRIORIZACION.md`, `19_chat.md`.

### 4.3 El plan es el corazón, pero el día a día no siempre vive ahí
La portada mejoró (acción del día + resumen de plan activo), pero el brainstorm de Inicio sigue siendo válido: **aún es más informativa que “¿voy bien?” en dos segundos** con desvío, alertas y próxima acción unificadas.  
Mi Plan es denso (muchas secciones); el valor se diluye si no hay un **tablero de salud** dominante arriba.  
**Fricción:** el usuario no siente “esto es mi tablero de retiro” sino “una app con muchas herramientas”.

Fuentes: `docs/brainstorm/01_inicio_home.md`, `13_mi_plan.md`.

### 4.4 Resultados potentes que no se bajan a “qué hago mañana”
Las simulaciones pueden decir “no llegás” o mostrar un abanico de resultados, pero el salto a **“hacé esto para llegar”** (ahorrar más, retrasar retiro, recortar gastos, rebalancear) no es el centro de la experiencia.  
El producto ya genera **trades de alineación** y lista de compra del núcleo; falta unificar el mensaje de **una acción clara** desde el resultado de la proyección.  
**Fricción:** insight sin decisión = plan que no se ejecuta.

Fuentes: `99_PRIORIZACION.md` (“si solo hacés 5 cosas” #5), `docs/VISION_GRAN_SALTO.md` (coach proactivo, buckets).

### 4.5 Transparencia honesta a veces escondida
El producto tiene joyas de confianza (realista vs conservador, calidad de datos, “calculado” vs “interpretación de IA”, supuestos de costos) pero la priorización dice explícitamente que **están escondidas** o no siempre visibles donde se decide.  
**Fricción:** el diferencial no se siente; el usuario no sabe si confiar.

Fuente: `docs/brainstorm/99_PRIORIZACION.md`.

### 4.6 Chat como promesa del futuro, experiencia de entrada frágil
El chat es la apuesta de UX del “Gran Salto”, pero hoy puede arrancar vacío y, si no hay meta/simulación cargada, responder cosas como probabilidad 0% de forma literal (hallazgo de QA: el agente reporta el número del motor; falta un mensaje humano “definí una meta primero”).  
**Fricción:** la puerta más amable puede generar **desconfianza** en el primer uso.

Fuentes: `docs/brainstorm/19_chat.md`, `logs/qa_report.md` (OBS-1).

### 4.7 Distribución: el 99% no llega a abrir la app
Aunque el packaging mejoró (`run.sh`, Makefile, Docker, planes de ejemplo), el modelo sigue siendo **instalación local**. El brainstorm de negocio lo dice sin rodeos: “bajá Python y corré un script” excluye a casi todos.  
**Fricción de negocio:** sin distribución, el producto excelente **no se adopta**.

Fuente: `docs/brainstorm/24_negocio.md` Ideas 1–2.

### 4.8 Complejidad de lenguaje y de “mucho en una sola pantalla”
Términos como Monte Carlo, Efficient Frontier, Moat, Sharpe, decumulación, guardrails, etc. aparecen en la interfaz. Hay captions y disclaimers, pero **no un glosario unificado a un clic** en toda la app (idea de UX global).  
Mi Plan y Simulaciones son muy ricos; sin jerarquía “conclusión arriba, detalle abajo” el usuario se pierde.  
**Fricción:** audiencia de retiro a menudo no es analista financiero.

Fuentes: `docs/brainstorm/23_ux_global.md` Ideas 3 y 6; quick wins en `99_PRIORIZACION.md`.

### 4.9 Documentación de usuario desactualizada en puntos visibles
El README aún lista un subconjunto de páginas y un flujo corto “Screener → … → Portfolio”, mientras la app real tiene chat, plan, track record, comité, etc. y un flujo de retiro más largo.  
**Fricción:** quien llega por el README no ve el producto real; genera expectativa incorrecta.

Fuente: `README.md` (tabla de páginas y flujo recomendado) vs `dashboard/app.py` y `docs/CONTEXT.md` §6.

### 4.10 Dependencia de una sola fuente de mercado
Los precios y fundamentals entran principalmente por una fuente externa gratuita. Hay badges de calidad y algo de reconciliación, pero el propio documento de visión marca **los datos como debilidad estructural #1**.  
**Fricción de confianza:** un score hermoso sobre un dato viejo o inconsistente daña más que un score simple honesto.

Fuente: `docs/VISION_GRAN_SALTO.md` (habilitador de datos), `docs/CONTEXT.md` §8.

---

## 5. Riesgos de producto o de confianza para el usuario

| Riesgo | Por qué importa | Señales en el repo |
|--------|-----------------|--------------------|
| **Confianza numérica partida** | Si el optimizador “pinta bien” y la simulación “pinta mal”, el usuario no sabe a cuál creer. | Filosofía conservadora del motor de escenarios vs proxy de retornos del optimizador (audit de razonamiento y docs de contexto). Transparencia “realista vs conservador” mitiga si se ve. |
| **Datos incompletos o viejos presentados como verdad** | Decisiones de retiro con información floja. | Limitación de fuente única; badges de calidad existen pero no siempre están en el punto de decisión. |
| **IA que se percibe como “asesor mágico”** | Expectativa de certeza; riesgo legal y de mala decisión. | Disclaimers educativos presentes; visión advierte compliance si el producto “actúa” más. Comité y chat están pensados para no inventar, pero hay que cuidarlo en UX. |
| **Pérdida del plan del usuario** | Todo vive en archivos locales; una reinstalación o cambio de PC puede borrar el trabajo. | Journey de respaldo y export existen; el riesgo es de **comportamiento** (la gente no exporta). |
| **Sobrecarga de features → abandono** | Más pantallas sin un hilo único bajan el uso real del plan. | 19 módulos en brainstorm; priorización: “no necesita más features”. |
| **Track record que expone errores sin framing** | La transparencia es el punto, pero mal presentada puede asustar y no educar. | Visión Apuesta 3: framing honesto y horizontes largos. |
| **Cumplimiento / “¿es asesoramiento regulado?”** | A medida que el producto sugiere trades y suena a asesor, crece el riesgo legal si se escala a web multiusuario. | `docs/VISION_GRAN_SALTO.md` saltos de negocio; `24_negocio.md` Idea 10. |
| **Primera impresión rota** | Un PDF roto o un “0% de meta” en el chat mata la confianza en minutos. | QA documentó bug de PDF (corregido en validación) y OBS del chat con 0%. Hay que vigilar el **camino feliz del demo**. |
| **Alertas que no corren solas** | El valor de monitoreo depende de que el usuario (o un programador de tareas) ejecute el chequeo. | Hay scheduler y docs de alertas; no es “app que te avisa sola” out-of-the-box para todos. |

---

## 6. Backlog priorizado de mejoras

Al menos 8 ítems. **Impacto** = valor para el usuario / adopción / confianza. **Esfuerzo** = bajo / medio / alto en sentido de producto (no estimación de ingeniería fina).  
Criterio: mejorar el proyecto **usando lo que ya existe**, no reescribir por deporte.

| # | Mejora | Impacto | Esfuerzo | Por qué ahora |
|---|--------|---------|----------|---------------|
| 1 | **Portada = “cómo viene tu plan”** (probabilidad, desvío, alertas, una acción) y atajo al plan de ejemplo en un clic | Alto | Bajo–Medio | Es la pregunta diaria; ya hay datos en plan activo y “Hoy hacé esto”. |
| 2 | **Matar pantallas en blanco**: al entrar mostrar último resultado, ejemplo o estado (“aún no analizaste; probá AAPL / plan demo”) | Alto | Medio | Fricción #1 de adopción según brainstorm. |
| 3 | **Resultado accionable**: del “no llegás” a “para llegar: +$X/mes o +N años o recorte Y%” + CTA a plan/portfolio | Alto | Medio | Cierra el loop de valor del retiro. |
| 4 | **Hacer visible la transparencia** (realista vs conservador siempre a la vista; sello “calculado” vs “IA”; calidad de datos en Screener/Optimizer/Plan) | Alto | Bajo | Diferencial ya construido, mal exhibido. |
| 5 | **Chat con preguntas sugeridas clicables** + mensajes humanos cuando falta meta/plan | Alto | Bajo | Baja la barrera sin rehacer el menú. |
| 6 | **Consolidar pantallas solapadas** (ficha + comité + chat como una experiencia; Allocation integrada al Optimizer; menos ítems en “Investigar”) | Alto | Alto | Es el cambio de usabilidad más grande; alinear con menú por intención. |
| 7 | **Comparación profunda de 2 planes** (supuestos + resultados lado a lado, no solo métricas sueltas) | Medio–Alto | Medio | Decisión real del usuario: plan A vs B (ya en backlog H+ del roadmap). |
| 8 | **Plan “qué hacer este año”** (aportes, rebalanceo, fechas de revisión) generado desde el plan activo | Alto | Medio | Baja el plan de 30 años a tareas de 12 meses. |
| 9 | **Segunda fuente de datos / calidad visible en la decisión** | Alto (confianza) | Alto | Sin esto, todo el resto de IA y scores es frágil. |
| 10 | **Capa Argentina first-class** (doble moneda, brecha, instrumentos locales) más allá del descuento a ADRs | Alto (estratégico) | Alto | Diferencial de mercado LatAm. |
| 11 | **PDF / informe de retiro compartible con la pareja o un asesor** (más presentable, menos “export técnico”) | Medio–Alto | Medio | Decisiones de retiro son de a dos; marketing orgánico. |
| 12 | **Coach proactivo en caídas** (“tu plan sigue OK porque…” vía alertas) | Alto (comportamiento) | Medio | Donde realmente fracasan los inversores: el pánico. |
| 13 | **Distribución**: web multiusuario o al menos demo hosteada | Alto (alcance) | Alto | Sin esto el producto no escala usuarios. |
| 14 | **Alinear README y “primera hora”** con el producto real (flujo de retiro, Mi Plan, demo, chat) | Medio | Bajo | Costo bajo, evita expectativa rota. |
| 15 | **Track record con resumen honesto en una línea** en Inicio o Plan (“nuestras señales BUY a 12m: X% vs mercado”) | Alto (confianza) | Bajo–Medio | La apuesta de confianza del Gran Salto, ya parcialmente construida. |

---

## 7. Si solo hacemos 5 cosas

Lista corta, alineada al diagnóstico (no contradice las debilidades de §4). Orden de ejecución sugerido:

1. **Poner “cómo viene tu plan” en el centro de la portada y de la vida diaria de la app**  
   (resumen de salud + una acción + plan de ejemplo). Ataca §4.3 y adopción.

2. **Matar las pantallas en blanco** en Screener, Simulaciones, Comité y Chat  
   (último resultado / ejemplo / guía). Ataca §4.2.

3. **Volver accionable el resultado de la proyección y del plan**  
   (“para llegar hacé esto” + trades/lista de compra visibles). Ataca §4.4.

4. **Exhibir la transparencia que ya existe**  
   (realista vs conservador, calculado vs IA, calidad de datos donde se decide). Ataca §4.5 y riesgos de confianza.

5. **Bajar la barrera del chat y del menú**  
   (preguntas sugeridas + mensajes cuando falta contexto; seguir consolidando solapamientos). Ataca §4.1 y §4.6.

> Nota de coherencia: esto coincide en espíritu con `docs/brainstorm/99_PRIORIZACION.md` (“si solo hacés 5 cosas”) y con la tesis de `docs/VISION_GRAN_SALTO.md` (no más análisis; accesibilidad + confianza).  
> **Qué queda fuera a propósito de este top 5:** reescribir el motor, Black-Litterman, multi-tenant SaaS, nuevos scores. Son válidos más tarde; no son el cuello de botella de producto hoy.

---

## 8. Veredicto de Product Owner

### Estado actual (una frase)
**Producto analíticamente maduro y con un “Mi Plan” de retiro ya vivo, que aún se siente más como una caja de herramientas de experto que como un asesor que te guía cada día.**

### Principal apuesta de mejora
**Adopción y claridad del recorrido con el Plan en el centro** — que abrir la app responda “¿voy bien?” y “¿qué hago hoy?”, que las pantallas muestren valor al entrar, y que la honestidad (sesgo conservador, calidad de datos, track record) se sienta sin buscarla.  
En paralelo de confianza: **seguir midiendo aciertos (track record) y cuidar que chat/comité no generen una primera impresión confusa**.

### Qué NO conviene hacer ahora
- **No agregar más módulos de análisis** (“otro indicador”, otra página de research) mientras la superficie actual no se consolide.  
- **No reescribir la arquitectura o la interfaz completa** solo por moda; el menú por intención y el motor ya dan base.  
- **No empujar a “SaaS asesor regulado”** sin antes cerrar confianza de datos, framing legal y un camino de uso simple.  
- **No priorizar profundidad de modelo** (nuevos modelos de optimización sofisticados) por encima de **hacer usable y creíble lo que ya está**.  
- **No tratar el brainstorm como backlog de ejecución ciego**: es ideación; este informe prioriza con criterio de Product Owner.

### Cierre
La fortaleza técnica y de producto de este proyecto es **rara**: pocos productos personales de retiro combinan scoring serio, plan activable, decumulación, transparencia de supuestos, comité con disenso y chat anclado a números reales.  
El trabajo de Project Owner de acá en más no es “hacer más app”, sino **hacer que esa potencia se entienda, se confíe y se use** — del primer clic al plan activo respaldado.

---

## Anexo A — Inventario de capacidades (evidencia de estado)

| Capacidad | Estado en producto | Evidencia principal |
|-----------|--------------------|---------------------|
| Screener / ranking del universo | Completo | `dashboard/pages/1_Screener.py`, README |
| Análisis de un activo | Completo | `2_Stock_Analysis.py` |
| Portfolio + libro personal / sizing | Completo | `3_Portfolio.py`, Fase I en CONTEXT |
| Allocation por edad | Completo | `4_Allocation.py` |
| Optimizer de cartera | Completo | `5_Optimizer.py` |
| Backtesting | Completo | `6_Backtesting.py` |
| Simulaciones (escenarios, stress, metas, sensibilidad) | Completo | `7_Simulaciones.py`, Fase H.3 |
| Alertas | Completo | `8_Alertas.py` |
| Watchlist | Completo | `11_Watchlist.py` |
| Mi Plan (guardar/activar/PDF/export) | Completo | `12_Plan.py` |
| Track Record | Completo | `13_Track_Record.py` |
| Comité | Completo | `15_Comite.py` + dictamen en Portfolio |
| Chat | Completo | `18_Chat.py` |
| Onboarding de perfil | Completo | `dashboard/onboarding.py` |
| Planes de ejemplo | Completo | `data/sample_plans/` |
| Calidad de datos / Macro RAG / Eval IA | Completo (modo dev en menú) | `14_`, `16_`, `17_`, `app.py` |

## Anexo B — Fuentes consultadas (rutas)

- `README.md`
- `docs/CONTEXT.md`
- `docs/VISION_GRAN_SALTO.md`
- `docs/ROADMAP.md`
- `docs/INDEX.md`
- `docs/brainstorm/00_INDICE.md`
- `docs/brainstorm/01_inicio_home.md`
- `docs/brainstorm/13_mi_plan.md`
- `docs/brainstorm/19_chat.md`
- `docs/brainstorm/23_ux_global.md`
- `docs/brainstorm/24_negocio.md`
- `docs/brainstorm/99_PRIORIZACION.md`
- `docs/AUDIT_REASONING_QUALITY.md` (solo como apoyo de riesgos de coherencia/confianza)
- `logs/qa_report.md`
- `dashboard/app.py`, `dashboard/shared.py`, `dashboard/onboarding.py`
- `dashboard/pages/*` (inventario de pantallas)
- `data/sample_plans/*`

---

*Fin del informe de auditoría — Project Owner.*
