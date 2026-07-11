# 🧭 Macro RAG — Brainstorming

> **Qué es hoy:** indexa hechos macro **fechados** (comunicados de la Fed, series de
> FRED, noticias económicas) y recupera los más relevantes para inyectarlos como
> contexto fresco en los prompts, en vez de confiar en la memoria (posiblemente
> vieja) del modelo. Captura: `_screenshots/18_macro_rag.png`

Es infraestructura de IA muy buena (ancla los factores macro a hechos verificables y
con fecha). Pero como pantalla de usuario es abstracta: poca gente entiende qué es
un "RAG" o por qué le importa.

## Ideas

### Idea 1 — Presentarlo como "el clima económico de tu plan"
- **Qué:** en vez de "Macro RAG", mostrar un panel simple: "esto está pasando en la
  economía y así afecta tu cartera".
- **Por qué:** "RAG" no significa nada para el usuario; "qué pasa en la economía y
  cómo me pega" sí.
- **Tipo:** UX / Negocio · **Esfuerzo:** Medio

### Idea 2 — Conectarlo a los factores macro del plan
- **Qué:** que los riesgos macro que muestra Mi Plan citen el hecho fechado concreto
  que los respalda.
- **Por qué:** transforma "factor macro" de afirmación de IA en algo trazable a una
  fuente con fecha. Es el propósito original; falta exponerlo al usuario.
- **Tipo:** IA / UX · **Esfuerzo:** Medio

### Idea 3 — Ingesta automática y fresca
- **Qué:** que los hechos macro se actualicen solos (FRED, comunicados) en vez de
  cargarse a mano.
- **Por qué:** un RAG con datos viejos pierde todo el sentido (su gracia es la
  frescura).
- **Tipo:** Técnica / Datos · **Esfuerzo:** Alto

### Idea 4 — Macro local (Argentina/LatAm)
- **Qué:** indexar también inflación, tasas y riesgo país locales.
- **Por qué:** para el público AR, lo macro local pesa más que la Fed; es un
  diferencial enorme.
- **Tipo:** Datos / Negocio · **Esfuerzo:** Alto

### Idea 5 — Línea de tiempo de hechos macro
- **Qué:** mostrar los eventos macro recientes en una línea simple, con su impacto.
- **Por qué:** ayuda a entender el contexto sin leer comunicados completos.
- **Tipo:** UI · **Esfuerzo:** Medio

### Idea 6 — Mejor relevancia (más allá de TF-IDF)
- **Qué:** mejorar cómo se eligen los hechos relevantes (hoy es un buscador simple por
  palabras).
- **Por qué:** si recupera hechos poco relevantes, mete ruido en los prompts en vez
  de señal.
- **Tipo:** Técnica · **Esfuerzo:** Alto

### Idea 7 — ¿Pantalla o motor de fondo?
- **Qué:** evaluar si Macro RAG necesita pantalla propia o si su valor se entrega
  mejor dentro de Stock Analysis y Mi Plan.
- **Por qué:** es más un ingrediente que un plato; quizás no merece un lugar fijo en
  el menú.
- **Tipo:** UX / Flujo · **Esfuerzo:** Bajo
