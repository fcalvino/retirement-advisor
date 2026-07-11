# 🧪 Eval IA — Brainstorming

> **Qué es hoy:** harness que mide la *calidad* de las decisiones de IA contra casos
> "golden", con chequeos (estructura válida, acción esperada, scores
> determinísticos, esquema macro, tope conservador, riesgos presentes). Sirve para
> cambiar un prompt y ver si mejoró o empeoró. Captura: `_screenshots/15_eval_ia.png`

Es una herramienta de **desarrollador**, no de inversor. Está perfecto que exista,
pero probablemente no debería ocupar un lugar en el menú principal del usuario final.

## Ideas

### Idea 1 — Sacarla del menú de usuario
- **Qué:** mover Eval IA a un modo "desarrollador/admin" o a la línea de comandos.
- **Por qué:** un inversor no entiende ni necesita "eval harness"; ocupa un slot de
  menú escaso (recordá el "ver 9 más").
- **Tipo:** UX / Flujo · **Esfuerzo:** Bajo

### Idea 2 — Convertir su resultado en un sello de calidad para el usuario
- **Qué:** mostrar al usuario final una versión simple: "nuestras decisiones de IA
  pasan X de Y chequeos de calidad".
- **Por qué:** la calidad de la IA, comunicada simple, genera confianza; el detalle
  técnico no.
- **Tipo:** Negocio / UX · **Esfuerzo:** Medio

### Idea 3 — Correr la eval en cada cambio de prompt (automático)
- **Qué:** integrar la eval al flujo de desarrollo/CI para que ningún cambio de IA
  pase sin medirse.
- **Por qué:** el propio módulo nace para "no volar a ciegas"; automatizarlo cumple
  esa promesa.
- **Tipo:** Técnica · **Esfuerzo:** Medio

### Idea 4 — Más casos golden y de regresión
- **Qué:** ampliar el set de casos, incluyendo trampas (datos malos, empresa
  quebrada, euforia) para verificar prudencia.
- **Por qué:** cuantos más casos difíciles, más confiable es la red de seguridad de
  la IA.
- **Tipo:** Técnica / IA · **Esfuerzo:** Medio

### Idea 5 — Comparar proveedores con la misma vara
- **Qué:** correr la eval sobre Claude/Grok/OpenAI/Nous y mostrar cuál da mejores
  decisiones para este producto.
- **Por qué:** ayuda a elegir el default y a justificar el costo de cada proveedor.
- **Tipo:** IA / Negocio · **Esfuerzo:** Medio

### Idea 6 — Eval de las narrativas, no solo de las decisiones
- **Qué:** chequear también que las explicaciones en español sean claras, honestas y
  sin inventar cifras.
- **Por qué:** la narrativa es lo que el usuario lee; su calidad importa tanto como la
  decisión.
- **Tipo:** IA · **Esfuerzo:** Alto
