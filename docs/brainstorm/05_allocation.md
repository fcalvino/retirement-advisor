# 📊 Allocation — Brainstorming

> **Qué es hoy:** pantalla chica (2.6 KB) que sugiere un reparto por clase de activo
> según la edad/edad de retiro (regla tipo "glide path" simple).
> Captura: `_screenshots/05_allocation.png`

Es la pantalla más liviana y la que más se siente "de relleno". Hay dos caminos:
hacerla mucho más rica, o fusionarla con Optimizer/Mi Plan.

## Ideas

### Idea 1 — Fusionar Allocation dentro de Optimizer o Mi Plan
- **Qué:** mover esta sugerencia a un paso dentro del Optimizer/Plan en vez de una
  pantalla aparte.
- **Por qué:** menos pantallas, menos confusión. Hoy compite con Optimizer sin
  agregar tanto.
- **Tipo:** Flujo / UX · **Esfuerzo:** Medio

### Idea 2 — Glide path visual e interactivo
- **Qué:** un gráfico de cómo debería cambiar tu mezcla acciones/bonos/efectivo
  desde hoy hasta el retiro, con un slider de edad.
- **Por qué:** el concepto de "ir bajando riesgo con los años" se entiende mucho
  mejor viéndolo moverse que leyéndolo.
- **Tipo:** UI / UX · **Esfuerzo:** Medio

### Idea 3 — Comparar tu mezcla actual vs la sugerida
- **Qué:** traer la mezcla real del portfolio y superponerla a la recomendada.
- **Por qué:** la recomendación sola no acciona; el contraste con lo que tenés, sí.
- **Tipo:** Flujo · **Esfuerzo:** Medio

### Idea 4 — Incluir más clases de activo
- **Qué:** sumar efectivo/liquidez, bonos por tipo, oro, crypto, inmuebles (REITs).
- **Por qué:** un reparto de retiro realista no es solo acciones/bonos.
- **Tipo:** Técnica · **Esfuerzo:** Medio

### Idea 5 — Explicar el "por qué" de cada %
- **Qué:** una frase por clase: "a tu edad conviene ~X% en bonos para amortiguar
  caídas cerca del retiro".
- **Por qué:** sin el porqué, el usuario no confía ni aprende.
- **Tipo:** UX / IA · **Esfuerzo:** Bajo

### Idea 6 — Escenarios de tolerancia al riesgo
- **Qué:** tres versiones (conservador/moderado/agresivo) lado a lado para la misma
  edad.
- **Por qué:** la edad no es lo único; el carácter del inversor manda. Mostrar
  opciones ayuda a elegir con conciencia.
- **Tipo:** UX · **Esfuerzo:** Bajo

### Idea 7 — Reflejar el contexto argentino
- **Qué:** incorporar la realidad de un inversor AR (dólar, riesgo país, ADRs) en la
  sugerencia.
- **Por qué:** el público objetivo incluye argentinos; una regla genérica de EE.UU.
  no aplica del todo.
- **Tipo:** Negocio / Técnica · **Esfuerzo:** Medio
