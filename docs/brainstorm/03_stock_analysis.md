# 🔍 Stock Analysis — Brainstorming

> **Qué es hoy:** la ficha profunda de un ticker — score y sus 5 dimensiones,
> consistency, Piotroski, moat (cuantitativo + IA), técnico, tailwind, decisión IA
> con factores macro. Es la pantalla más densa del producto (34 KB de código).
> Captura: `_screenshots/03_stock_analysis.png`

Tiene muchísima información de calidad. El riesgo es **sobrecarga**: el usuario ve
todo junto y no sabe qué mirar primero ni qué hacer después.

## Ideas

### Idea 1 — Veredicto arriba, detalle abajo
- **Qué:** primero una conclusión grande (comprar/mantener/evitar + 1 frase de por
  qué), y recién después las dimensiones para quien quiera profundizar.
- **Por qué:** la mayoría quiere la conclusión; los detalles son para validar, no
  para arrancar. Es la pirámide invertida del periodismo aplicada a finanzas.
- **Tipo:** UX / UI · **Esfuerzo:** Medio

### Idea 2 — "Tesis en 3 puntos" y "Riesgos en 3 puntos"
- **Qué:** dos columnas cortas: por qué sí / por qué no, en lenguaje simple.
- **Por qué:** obliga a sintetizar y ayuda a decidir sin leer todo. Refuerza la
  filosofía conservadora (siempre mostrar el bear case).
- **Tipo:** UX / IA · **Esfuerzo:** Medio

### Idea 3 — Gráfico de precio con contexto
- **Qué:** un gráfico simple de precio a 1/5 años con las señales técnicas marcadas.
- **Por qué:** hoy el análisis es muy numérico; una imagen del precio ancla todo lo
  demás y es lo primero que la gente busca.
- **Tipo:** UI · **Esfuerzo:** Medio

### Idea 4 — Botón "mandar al comité" y "preguntar al chat"
- **Qué:** desde la ficha, escalá a la opinión multi-agente o preguntá en lenguaje
  natural sobre ese ticker.
- **Por qué:** conecta las tres pantallas que hoy responden lo mismo por separado
  (ficha, comité, chat). Una sola historia.
- **Tipo:** Flujo · **Esfuerzo:** Bajo

### Idea 5 — "Cómo encaja en tu plan"
- **Qué:** mostrar si el ticker ya está en tu cartera/plan, con qué peso, y qué
  pasaría con tu meta si sumás una posición.
- **Por qué:** une el análisis individual con el objetivo de retiro. Una acción
  "buena" puede no servir a TU plan.
- **Tipo:** Flujo / UX · **Esfuerzo:** Alto

### Idea 6 — Comparar contra un par del sector
- **Qué:** elegir un competidor y ver las dimensiones lado a lado.
- **Por qué:** una acción nunca es buena o mala en el vacío, sino frente a su
  alternativa.
- **Tipo:** UX · **Esfuerzo:** Medio

### Idea 7 — Historial de la decisión IA
- **Qué:** guardar y mostrar qué decía la IA hace 1/3/6 meses sobre ese ticker.
- **Por qué:** muestra consistencia (o cambios) del análisis y alimenta el track
  record. Genera confianza.
- **Tipo:** Datos / IA · **Esfuerzo:** Alto

### Idea 8 — Calculadora de margen de seguridad
- **Qué:** "a qué precio sería una compra clara" según los umbrales del producto.
- **Por qué:** convierte el análisis en un disparador de acción concreto (precio
  objetivo) en vez de una foto estática.
- **Tipo:** UX · **Esfuerzo:** Medio

### Idea 9 — Modo "explicámelo simple"
- **Qué:** toggle que reescribe toda la ficha sin jerga, para principiantes.
- **Por qué:** atiende a dos públicos (experto y novato) sin partir el producto.
- **Tipo:** UX / IA · **Esfuerzo:** Medio

### Idea 10 — Aviso de calidad de datos integrado
- **Qué:** si los datos del ticker son parciales/viejos, decirlo arriba con énfasis.
- **Por qué:** una ficha que se ve completa pero está basada en datos flojos engaña.
  La honestidad de datos es un diferencial del producto.
- **Tipo:** Datos / UX · **Esfuerzo:** Bajo
