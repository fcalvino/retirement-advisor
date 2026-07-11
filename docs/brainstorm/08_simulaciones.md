# 🎲 Simulaciones & Stress Testing — Brainstorming

> **Qué es hoy:** la joya técnica (93 KB). Monte Carlo (block-bootstrap, sesgo
> conservador, escenario realista vs conservador), stress test histórico, escenario
> personalizado, comparar perfiles, metas, decumulación (cómo dura tu ingreso),
> sensibilidad (tornado) y supuestos/drags. Captura: `_screenshots/08_simulaciones.png`
> (y `_tab1..5`).

Tiene una potencia enorme escondida detrás de tabs y un botón "Ejecutar". El
problema es que **arranca vacío** y la riqueza (decumulación, sensibilidad,
realista vs conservador) está plegada en expanders que pocos abren.

## Ideas

### Idea 1 — La pregunta primero: "¿me va a alcanzar?"
- **Qué:** reemplazar el arranque vacío por una sola respuesta grande: probabilidad
  de llegar a tu meta, con un termómetro verde/amarillo/rojo.
- **Por qué:** es LA pregunta de retiro. Todo lo demás (fan chart, tornado) es para
  profundizar después.
- **Tipo:** UX / UI · **Esfuerzo:** Medio

### Idea 2 — Auto-correr al entrar con los datos del plan
- **Qué:** si hay plan activo, correr la simulación sola y mostrar el resultado; el
  botón queda para recalcular.
- **Por qué:** la fricción de "configurar + apretar + esperar" hace que mucha gente
  ni vea el resultado.
- **Tipo:** Flujo · **Esfuerzo:** Medio

### Idea 3 — Realista vs Conservador siempre visible
- **Qué:** mostrar las dos cifras lado a lado por defecto (hoy es opt-in y queda
  plegado), con una explicación de por qué difieren.
- **Por qué:** es una feature de transparencia única (Fase J) que casi nadie va a
  descubrir si está escondida. Evita que la gente sobre-ahorre por miedo.
- **Tipo:** UX · **Esfuerzo:** Bajo

### Idea 4 — Asistente "¿qué cambio para llegar?"
- **Qué:** si no llegás a la meta, sugerir las palancas: aportar $X más, retirarte 2
  años después, bajar la meta, o aceptar más riesgo — con el efecto de cada una.
- **Por qué:** un "no llegás" sin salida frustra. Mostrar las palancas vuelve el
  resultado accionable.
- **Tipo:** UX / Técnica · **Esfuerzo:** Alto

### Idea 5 — Decumulación al frente ("cuánto podés sacar por mes")
- **Qué:** traducir las estrategias de retiro a "podés sacar ~$X/mes y dura hasta los
  Y años con alta probabilidad".
- **Por qué:** es la pregunta del jubilado, no del que acumula; hoy está enterrada en
  un expander.
- **Tipo:** UX · **Esfuerzo:** Medio

### Idea 6 — Explicar el fan chart
- **Qué:** etiquetar las bandas: "en el mejor 10% terminás con X, en el peor 10% con
  Z, lo más probable es Y".
- **Por qué:** el gráfico de abanico es bello pero opaco; las etiquetas lo hacen
  entendible.
- **Tipo:** UI / UX · **Esfuerzo:** Bajo

### Idea 7 — Riesgo de secuencia explicado con un caso
- **Qué:** mostrar con un ejemplo qué pasa si los primeros años de retiro son malos
  (sequence-of-returns risk).
- **Por qué:** es el riesgo más subestimado del retiro; un caso concreto educa más
  que una métrica.
- **Tipo:** UX · **Esfuerzo:** Medio

### Idea 8 — Sensibilidad (tornado) traducida a decisiones
- **Qué:** al lado del tornado, "lo que más mueve tu plan es la inflación; cuidá eso
  primero".
- **Por qué:** el gráfico de tornado es de analista; la frase es para cualquiera.
- **Tipo:** UX · **Esfuerzo:** Bajo

### Idea 9 — Guardar y comparar simulaciones en el tiempo
- **Qué:** registrar el resultado de cada corrida para ver si tu plan mejora o
  empeora con el tiempo.
- **Por qué:** convierte la simulación de foto puntual en seguimiento (conecta con el
  historial de salud del plan).
- **Tipo:** Datos · **Esfuerzo:** Medio

### Idea 10 — Eventos de vida en la línea de tiempo
- **Qué:** poder marcar "compro casa en 2030", "hijo a la universidad en 2035" como
  retiros/ingresos puntuales.
- **Por qué:** la vida real no es un aporte parejo; los grandes gastos cambian todo.
- **Tipo:** Técnica / Flujo · **Esfuerzo:** Alto

### Idea 11 — Menos tabs, más recorrido guiado
- **Qué:** convertir las 5 tabs en un recorrido (resultado → ¿alcanza? → ¿y si pasa
  algo malo? → ¿cuánto puedo sacar?).
- **Por qué:** las tabs ponen todo al mismo nivel; un recorrido cuenta una historia.
- **Tipo:** UX / Flujo · **Esfuerzo:** Alto

### Idea 12 — Inflación argentina / doble moneda
- **Qué:** permitir simular en dólares pero con gastos en pesos, o viceversa.
- **Por qué:** para el público AR, la inflación local y el tipo de cambio dominan el
  resultado real.
- **Tipo:** Técnica / Negocio · **Esfuerzo:** Alto
