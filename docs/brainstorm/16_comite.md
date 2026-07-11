# 🏛️ Comité de Inversión — Brainstorming

> **Qué es hoy:** en vez de una sola opinión de IA, un panel de agentes
> especializados (Portfolio Manager, Estratega Macro, Coach de Comportamiento y
> Abogado del Diablo) debate y produce un dictamen con **disenso explícito**. El
> Abogado del Diablo siempre arma el bear case. Arranca pidiendo un ticker.
> Captura: `_screenshots/16_comite.png`

Es la feature de IA más vistosa y la que mejor encarna la filosofía conservadora
(que el desacuerdo quede a la vista). Su debilidad: vive aislada, arranca vacía y
compite con Stock Analysis y Chat por la misma pregunta.

## Ideas

### Idea 1 — Mostrar el debate, no solo el veredicto
- **Qué:** presentar las posturas de cada agente como un diálogo, con quién está a
  favor y quién en contra y por qué.
- **Por qué:** el valor del comité es VER el desacuerdo; si solo se muestra el
  resultado, se pierde lo mejor.
- **Tipo:** UX / UI · **Esfuerzo:** Medio

### Idea 2 — Comité sobre el plan/cartera, no solo un ticker
- **Qué:** "convocá al comité" para revisar tu plan o tu cartera completa, no solo
  una acción.
- **Por qué:** la decisión importante de retiro es la cartera; un panel que la
  cuestione (¿demasiado riesgo? ¿concentración?) es oro.
- **Tipo:** Flujo / IA · **Esfuerzo:** Alto

### Idea 3 — Reservarlo para decisiones que importan
- **Qué:** ofrecer el comité automáticamente cuando estás por una decisión grande
  (entrar fuerte a una posición, cambiar el plan).
- **Por qué:** es caro (varias llamadas de IA); usarlo en el momento de máximo valor
  lo justifica.
- **Tipo:** Flujo · **Esfuerzo:** Medio

### Idea 4 — Hacer visible al Coach de Comportamiento
- **Qué:** que el agente de comportamiento te hable a vos ("ojo, ¿estás comprando por
  miedo a perderte la suba?").
- **Por qué:** el peor enemigo del inversor es su psicología; un coach explícito es
  un diferencial real y humano.
- **Tipo:** UX / IA · **Esfuerzo:** Medio

### Idea 5 — Unificar comité, ficha y chat en una sola experiencia
- **Qué:** que "analizar a fondo", "preguntar" y "convocar al comité" sean
  profundidades distintas de la misma pregunta sobre un activo.
- **Por qué:** hoy tres pantallas responden lo mismo; integrarlas reduce confusión y
  refuerza una sola historia.
- **Tipo:** Flujo / UX · **Esfuerzo:** Alto

### Idea 6 — Guardar el dictamen y revisarlo después
- **Qué:** persistir el veredicto del comité (y enlazarlo al track record).
- **Por qué:** sirve para mirar atrás ("¿qué decía el comité cuando compré?") y
  medir su acierto.
- **Tipo:** Datos · **Esfuerzo:** Medio

### Idea 7 — Dejar elegir/ajustar el panel
- **Qué:** permitir activar/desactivar agentes o sumar uno (ej. "experto en
  dividendos", "experto en Argentina").
- **Por qué:** distintos inversores valoran distintas voces; un panel a medida es más
  relevante. (Ver también el doc de IA/agentes.)
- **Tipo:** IA / UX · **Esfuerzo:** Alto

### Idea 8 — Nivel de confianza del consenso
- **Qué:** mostrar qué tan unánime fue el panel ("3 a favor, 1 en contra: consenso
  medio").
- **Por qué:** una decisión 4-0 no es lo mismo que una 2-2; el grado de acuerdo es
  información clave.
- **Tipo:** UX · **Esfuerzo:** Bajo
