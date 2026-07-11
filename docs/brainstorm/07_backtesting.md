# 📉 Backtesting — Brainstorming

> **Qué es hoy:** corre una cartera contra la historia (5 años por defecto) y muestra
> equity curve, drawdown, Sharpe/Sortino/Calmar, con rebalanceo configurable y
> comparación vs benchmark. Captura: `_screenshots/07_backtesting.png`

Herramienta sólida pero "de analista". Para un inversor de retiro el riesgo es que
el backtest genere **falsa confianza** ("esto anduvo, entonces andará"). Las ideas
apuntan a hacerlo más honesto y más conectado al plan.

## Ideas

### Idea 1 — Backtest del plan, no de una cartera suelta
- **Qué:** botón "probar mi plan en la historia" que tome directo la cartera del plan
  activo.
- **Por qué:** hoy hay que rearmar la cartera a mano. El valor está en validar TU
  plan, no una cartera cualquiera.
- **Tipo:** Flujo · **Esfuerzo:** Medio

### Idea 2 — Resultado en lenguaje humano + advertencia honesta
- **Qué:** "Entre 2019 y 2024 habrías hecho ~X%, con una caída máxima de ~Y%. Ojo:
  el pasado no garantiza el futuro y 5 años es poco."
- **Por qué:** el número solo invita a extrapolar; el contexto y la advertencia
  protegen al inversor.
- **Tipo:** UX / IA · **Esfuerzo:** Bajo

### Idea 3 — Períodos de estrés predefinidos
- **Qué:** botones "crisis 2008", "COVID 2020", "inflación 2022" para ver cómo se
  habría comportado.
- **Por qué:** lo que importa para retiro no es el promedio sino el peor momento.
  Conecta con el Stress Test de Simulaciones.
- **Tipo:** UX · **Esfuerzo:** Medio

### Idea 4 — Comparar dos carteras/planes
- **Qué:** correr dos configuraciones a la vez y superponer las curvas.
- **Por qué:** "¿conviene A o B?" se responde comparando, no mirando una sola curva.
- **Tipo:** UX · **Esfuerzo:** Medio

### Idea 5 — Incluir aportes periódicos en el backtest
- **Qué:** simular "qué habría pasado si además aportaba $X por mes".
- **Por qué:** así invierte de verdad la gente de retiro; sin aportes el backtest es
  irreal.
- **Tipo:** Técnica · **Esfuerzo:** Medio

### Idea 6 — Mostrar el efecto de costos e impuestos
- **Qué:** una versión "neta" del backtest aplicando fricciones (ya existe la capa de
  drags).
- **Por qué:** el rendimiento bruto es optimista; el neto es lo que termina en tu
  bolsillo.
- **Tipo:** Técnica · **Esfuerzo:** Bajo

### Idea 7 — Advertir sobre el sesgo de mirar para atrás
- **Qué:** recordar que la cartera "ganadora" se eligió sabiendo el resultado
  (sesgo de selección).
- **Por qué:** es la trampa #1 del backtesting; un producto honesto la señala.
- **Tipo:** UX · **Esfuerzo:** Bajo

### Idea 8 — Guardar y nombrar backtests
- **Qué:** poder guardar un backtest para compararlo después.
- **Por qué:** hoy se pierde al cambiar de pantalla; sin memoria no hay aprendizaje.
- **Tipo:** Datos · **Esfuerzo:** Medio
