# 🔔 Alertas — Brainstorming

> **Qué es hoy:** monitoreo proactivo del universo y portafolio. Detecta cambios de
> señal, caídas de score, riesgos de cartera, drift vs plan y nuevas
> oportunidades. Tabs: ejecutar análisis, historial, configuración, silenciados.
> Manda por email/Telegram (vía scheduler) y genera PDF.
> Captura: `_screenshots/09_alertas.png`

Es lo que puede convertir la app en un hábito ("me avisa, entro"). Pero hoy es muy
**manual**: hay que apretar "ejecutar análisis ahora" y configurar el scheduler por
afuera. La promesa de "proactivo" no se cumple sola.

## Ideas

### Idea 1 — Que corra sola de verdad (sin script aparte)
- **Qué:** un programador de alertas configurable desde la propia pantalla, que
  quede activo.
- **Por qué:** "proactivo" pero que dependa de un cron manual es contradictorio. El
  valor está en que avise sin que entres.
- **Tipo:** Técnica / Flujo · **Esfuerzo:** Alto

### Idea 2 — Alertas en lenguaje claro y accionable
- **Qué:** "MSFT bajó de señal de compra a mantener — ¿querés revisar o silenciar?"
  con botones.
- **Por qué:** una alerta que no dice qué hacer genera ansiedad sin acción.
- **Tipo:** UX · **Esfuerzo:** Bajo

### Idea 3 — Centro de notificaciones dentro de la app
- **Qué:** un ícono de campana con las alertas no leídas, presente en todas las
  pantallas.
- **Por qué:** hoy las alertas viven en su pantalla; deberían encontrarte a vos.
- **Tipo:** UX / UI · **Esfuerzo:** Medio

### Idea 4 — Alertas centradas en el plan, no solo en tickers
- **Qué:** avisar "tu plan bajó de 80% a 70% de probabilidad de éxito" o "tu cartera
  se desvió del plan".
- **Por qué:** lo que importa en retiro es el plan; las señales de tickers son
  secundarias. (Ya existe la alerta de salud del plan — destacarla.)
- **Tipo:** Flujo · **Esfuerzo:** Medio

### Idea 5 — Niveles de "ruido" claros
- **Qué:** dejar elegir fácil entre "solo lo crítico", "lo importante" y "todo".
- **Por qué:** demasiadas alertas se ignoran; muy pocas no sirven. El control del
  volumen es clave para que no las apaguen.
- **Tipo:** UX · **Esfuerzo:** Bajo

### Idea 6 — Resumen periódico (digest)
- **Qué:** un email/Telegram semanal o mensual con "cómo viene tu plan" en vez de
  alertas sueltas.
- **Por qué:** para un inversor de largo plazo, un resumen tranquilo es mejor que
  pings constantes que invitan a operar de más.
- **Tipo:** Negocio / UX · **Esfuerzo:** Medio

### Idea 7 — Alertas de precio objetivo
- **Qué:** "avisame si AAPL llega a US$ X" (margen de seguridad alcanzado).
- **Por qué:** es la alerta más pedida y conecta con la calculadora de margen de
  Stock Analysis.
- **Tipo:** Flujo · **Esfuerzo:** Medio

### Idea 8 — Recordatorios de mantenimiento
- **Qué:** "hace 6 meses que no revisás tu plan", "es momento de aportar",
  "respaldá tus datos".
- **Por qué:** las mejores acciones de retiro son aburridas y se olvidan; el
  recordatorio las sostiene.
- **Tipo:** UX · **Esfuerzo:** Bajo

### Idea 9 — Probar la alerta antes de confiar
- **Qué:** botón "mandarme una alerta de prueba" para validar email/Telegram.
- **Por qué:** si la configuración está mal, te enterás recién cuando perdés una
  alerta real.
- **Tipo:** UX / Técnica · **Esfuerzo:** Bajo

### Idea 10 — Más canales (push, WhatsApp)
- **Qué:** sumar notificación push del navegador o WhatsApp además de email/Telegram.
- **Por qué:** el canal correcto sube muchísimo la tasa de lectura.
- **Tipo:** Técnica · **Esfuerzo:** Alto
