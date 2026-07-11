# 🤖 Capa de IA y Agentes — Brainstorming (transversal)

> **Qué es hoy:** 4 proveedores (Claude/Grok/OpenAI/Nous) intercambiables; capa de
> decisión por activo, narrativas, comité multi-agente (4 roles), chat con
> herramientas, eval harness, RAG macro y reconciliación de datos. La IA enriquece;
> el camino "sin IA" siempre produce un resultado válido.

Acá entra de lleno la consigna de **sumar o restar agentes**. La arquitectura es muy
buena (la IA nunca es el motor de cálculo, solo interpreta). El riesgo es la
**proliferación**: muchas superficies de IA que hacen cosas parecidas.

## Ideas — Restar / consolidar

### Idea 1 — Unificar las tres "opiniones sobre un activo"
- **Qué:** Stock Analysis (decisión IA), Comité y Chat responden la misma pregunta.
  Unificarlas en una experiencia con niveles de profundidad.
- **Por qué:** menos confusión, menos código duplicado, una sola voz del producto.
- **Tipo:** Agente / Flujo · **Esfuerzo:** Alto

### Idea 2 — Sacar las herramientas de desarrollador del menial del usuario
- **Qué:** Eval IA (y quizás Macro RAG y Calidad de Datos) son motores, no destinos;
  moverlos a "admin" o a segundo plano.
- **Por qué:** despeja el menú y enfoca al usuario en lo que decide.
- **Tipo:** Agente / UX · **Esfuerzo:** Bajo

### Idea 3 — Un único "orquestador" que decide qué IA usar
- **Qué:** que el sistema elija solo cuándo basta el cálculo, cuándo una opinión
  simple y cuándo convocar al comité (por costo/importancia).
- **Por qué:** evita que el usuario tenga que saber qué herramienta de IA usar; el
  producto decide el nivel adecuado.
- **Tipo:** Agente / Técnica · **Esfuerzo:** Alto

## Ideas — Sumar agentes

### Idea 4 — Agente "Coach de Comportamiento" siempre presente
- **Qué:** una voz que vigila decisiones impulsivas en toda la app (no solo dentro
  del comité).
- **Por qué:** el mayor riesgo del inversor particular es su psicología; un coach
  transversal es un diferencial humano enorme.
- **Tipo:** Agente / UX · **Esfuerzo:** Alto

### Idea 5 — Agente "Experto en Argentina/LatAm"
- **Qué:** un agente especializado en riesgo país, inflación, cepo, ADRs.
- **Por qué:** alinea el producto con su público real; ningún competidor global lo
  hace bien.
- **Tipo:** Agente / Negocio · **Esfuerzo:** Medio

### Idea 6 — Agente "Planificador fiscal"
- **Qué:** una voz que considera impuestos antes de sugerir vender/rebalancear.
- **Por qué:** los impuestos pueden dar vuelta una decisión "óptima"; hoy se ignoran.
- **Tipo:** Agente / Técnica · **Esfuerzo:** Alto

### Idea 7 — Agente "Vigilante del plan"
- **Qué:** un agente que monitorea el plan de fondo y avisa cuando algo lo amenaza
  (conecta con Alertas).
- **Por qué:** convierte la IA de "respondo cuando preguntás" a "te cuido el plan".
- **Tipo:** Agente / Flujo · **Esfuerzo:** Alto

## Ideas — Transversales de IA

### Idea 8 — IA local / privada como opción
- **Qué:** permitir un modelo que corra en la máquina del usuario, sin mandar datos
  afuera (está en el backlog del roadmap).
- **Por qué:** privacidad de datos financieros + cero costo de API; un argumento de
  venta fuerte.
- **Tipo:** Técnica / Negocio · **Esfuerzo:** Alto

### Idea 9 — Control de costos de IA
- **Qué:** mostrar cuánto se gasta en llamadas de IA y poner topes.
- **Por qué:** el comité y el screener con IA pueden costar; sin visibilidad, sorpresa
  en la factura.
- **Tipo:** Negocio / Técnica · **Esfuerzo:** Medio

### Idea 10 — Cachear y reutilizar más las respuestas de IA
- **Qué:** ampliar el cacheo de narrativas/decisiones para no repetir llamadas
  idénticas.
- **Por qué:** ahorra plata y tiempo; mejora la sensación de velocidad.
- **Tipo:** Técnica · **Esfuerzo:** Medio

### Idea 11 — Tono y nivel configurables
- **Qué:** dejar elegir si la IA te habla simple o técnica, breve o detallada.
- **Por qué:** un mismo producto sirve a novatos y expertos si adapta su voz.
- **Tipo:** IA / UX · **Esfuerzo:** Medio

### Idea 12 — Anti-alucinación visible siempre
- **Qué:** mostrar de forma consistente "este número es calculado / esta frase es
  interpretación de IA".
- **Por qué:** el usuario debe poder distinguir el dato duro de la opinión; es la
  base de la confianza.
- **Tipo:** IA / UX · **Esfuerzo:** Medio
