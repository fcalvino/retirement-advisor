# 💼 Portfolio — Brainstorming

> **Qué es hoy:** carga tus posiciones reales y muestra valor, P&L, métricas de
> riesgo (Sharpe, Sortino, beta, drawdown), alineación vs el plan activo (deriva +
> trades sugeridos) y la sección del "libro personal" (sizing por convicción).
> Captura: `_screenshots/04_portfolio.png`

Es una de las pantallas más completas. Observación de la captura: la "deriva total"
marcaba **98%** porque las posiciones reales (GOOGL, INTU) no se superponen con el
plan activo (AAPL, ACN…). Eso revela un punto ciego: la deriva pierde sentido
cuando cartera y plan casi no comparten tickers.

## Ideas

### Idea 1 — Deriva inteligente cuando no hay superposición
- **Qué:** detectar cuando la cartera y el plan comparten pocos tickers y, en vez de
  "98% de deriva", decir "tu cartera es casi totalmente distinta a tu plan".
- **Por qué:** un 98% no significa nada útil; un mensaje claro sí. Evita números que
  asustan sin informar.
- **Tipo:** UX / Técnica · **Esfuerzo:** Bajo

### Idea 2 — Carga de posiciones más fácil (pegar/importar)
- **Qué:** importar posiciones por CSV o pegando el resumen del broker, además de
  cargar a mano.
- **Por qué:** cargar posición por posición es la barrera #1 para empezar a usar
  esta pantalla.
- **Tipo:** Flujo / UX · **Esfuerzo:** Medio

### Idea 3 — Conexión con broker (lectura)
- **Qué:** integración de solo-lectura con algún broker/API para traer posiciones.
- **Por qué:** elimina la carga manual por completo; es el salto de "planilla" a
  "asistente vivo".
- **Tipo:** Técnica / Negocio · **Esfuerzo:** Alto

### Idea 4 — Atribución: ¿de dónde vino mi ganancia/pérdida?
- **Qué:** desglosar el P&L por posición y por sector, y vs el benchmark.
- **Por qué:** "gané 3.766" es lindo, pero "ganaste por GOOGL y perdiste por INTU"
  enseña a decidir.
- **Tipo:** UX · **Esfuerzo:** Medio

### Idea 5 — Riesgo en lenguaje humano
- **Qué:** traducir beta/Sharpe/drawdown a frases: "en una crisis como 2008 podrías
  ver caer ~X%".
- **Por qué:** las métricas de riesgo no significan nada para la mayoría; el ejemplo
  concreto sí, y prepara emocionalmente.
- **Tipo:** UX · **Esfuerzo:** Bajo

### Idea 6 — Aporte recurrente y su impacto
- **Qué:** registrar "aporto $X por mes" y mostrar cómo acelera la llegada a la meta.
- **Por qué:** en retiro el ahorro periódico pesa más que el stock-picking; el
  producto debería celebrarlo.
- **Tipo:** Flujo / UX · **Esfuerzo:** Medio

### Idea 7 — Detección de concentración y faltantes
- **Qué:** avisar si una posición pesa demasiado o si falta exposición a algo del
  plan.
- **Por qué:** la concentración no controlada es el mayor riesgo del inversor
  particular.
- **Tipo:** UX / Técnica · **Esfuerzo:** Bajo

### Idea 8 — Libro personal: hacerlo más visible y guiado
- **Qué:** el sizing por convicción (alta/media/baja) hoy está medio escondido al
  pie; convertirlo en un paso guiado con su propia tesis por posición.
- **Por qué:** es una idea diferencial (la libertad de concentrarse del individuo vs
  un fondo) y merece protagonismo.
- **Tipo:** UX / Negocio · **Esfuerzo:** Medio

### Idea 9 — Costo fiscal estimado de un rebalanceo
- **Qué:** antes de sugerir vender para alinear, estimar el impuesto que se gatilla.
- **Por qué:** un rebalanceo "óptimo" puede ser malo después de impuestos. Conecta
  con la idea de un módulo de impuestos.
- **Tipo:** Técnica · **Esfuerzo:** Alto

### Idea 10 — Foto histórica del portfolio
- **Qué:** guardar el valor del portfolio en el tiempo y graficarlo.
- **Por qué:** sin historia, no hay sensación de progreso ni se puede comparar vs el
  plan a lo largo del tiempo.
- **Tipo:** Datos · **Esfuerzo:** Medio

### Idea 11 — Múltiples carteras / cuentas
- **Qué:** soportar más de una cartera (ej. retiro vs trading vs hijos).
- **Por qué:** la gente separa objetivos por cuenta; mezclarlos distorsiona métricas
  y alineación.
- **Tipo:** Flujo · **Esfuerzo:** Alto
