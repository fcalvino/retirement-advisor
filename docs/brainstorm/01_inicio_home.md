# 📈 Inicio (Home) — Brainstorming

> **Qué es hoy:** la portada. Muestra 4 datos del universo/perfil, un expander de
> "Mi perfil", el bloque "Tu camino a un plan de retiro activo" (5 pasos con
> progreso) y un expander de supuestos/limitaciones.
> Captura: `_screenshots/01_inicio.png`

La portada ya está bien pensada (el journey de 5 pasos es excelente). El problema:
sigue siendo **informativa, no accionable** — te dice qué hacer pero no te muestra
en qué estás parado hoy.

## Ideas

### Idea 1 — Resumen de "cómo viene tu plan" arriba de todo
- **Qué:** si hay un plan activo, mostrar en la portada 3 números: probabilidad de
  llegar a la meta, desvío vs el plan y la próxima acción sugerida.
- **Por qué:** hoy esos datos viven enterrados en Mi Plan y Portfolio. La portada
  debería responder "¿voy bien?" en 2 segundos, que es la única pregunta que
  importa día a día.
- **Tipo:** UX / Flujo · **Esfuerzo:** Medio

### Idea 2 — "Qué cambió desde tu última visita"
- **Qué:** una tarjeta con novedades: alertas nuevas, tickers que cambiaron de
  señal, drift que cruzó el umbral, datos que envejecieron.
- **Por qué:** convierte la app de "entro cuando me acuerdo" a "entro porque me
  avisa que pasó algo". Aumenta el retorno del usuario sin spamear mail.
- **Tipo:** UX / Negocio · **Esfuerzo:** Medio

### Idea 3 — Acción única destacada ("hoy hacé esto")
- **Qué:** un solo botón grande con la cosa más importante a hacer hoy (rebalancear,
  registrar salud, respaldar plan, revisar una alerta crítica).
- **Por qué:** demasiadas opciones paralizan. Un solo siguiente paso claro sube
  muchísimo la tasa de gente que efectivamente lo hace.
- **Tipo:** UX / Flujo · **Esfuerzo:** Bajo

### Idea 4 — Saludo y contexto personal
- **Qué:** "Hola, faltan 30 años para tu retiro. Vas por el paso 3 de 5." Usar el
  nombre y el horizonte real del perfil.
- **Por qué:** personaliza y recuerda el objetivo de largo plazo, que es lo que
  evita decisiones impulsivas.
- **Tipo:** UX · **Esfuerzo:** Bajo

### Idea 5 — Mini-gráfico de progreso del patrimonio
- **Qué:** una línea simple "dónde estás vs dónde deberías estar" para llegar a la
  meta, actualizada con el último valor del portfolio.
- **Por qué:** una imagen del progreso motiva más que una tabla. Refuerza la
  sensación de avance (clave en algo de 30 años).
- **Tipo:** UI / UX · **Esfuerzo:** Medio

### Idea 6 — Estado del sistema visible
- **Qué:** un semáforo chico: ¿hay API keys?, ¿los datos están frescos?, ¿el
  scheduler de alertas corrió?
- **Por qué:** hoy si falta una API key te enterás recién al usar IA. Mostrarlo
  arriba evita frustración silenciosa.
- **Tipo:** UX / Técnica · **Esfuerzo:** Bajo

### Idea 7 — Onboarding interactivo en vez de expander
- **Qué:** la primera vez, un mini-tour de 3 pantallas (perfil → optimizar → plan)
  con ejemplos reales, no solo el wizard de perfil.
- **Por qué:** baja la curva de aprendizaje de un producto que tiene 19 pantallas.
- **Tipo:** UX / Flujo · **Esfuerzo:** Medio

### Idea 8 — Modo "explorar con datos de ejemplo"
- **Qué:** botón "Ver la app con un plan de ejemplo cargado" desde la portada (ya
  existen sample plans; traerlos al frente).
- **Por qué:** deja que alguien nuevo vea el valor antes de cargar sus propios
  datos. Reduce el abandono inicial.
- **Tipo:** Negocio / UX · **Esfuerzo:** Bajo

### Idea 9 — Recordatorio de respaldo
- **Qué:** si hace mucho que no exportás el plan, un aviso suave en la portada.
- **Por qué:** los datos viven en archivos locales; una reinstalación los borra.
  El respaldo es el paso que más se saltea.
- **Tipo:** UX · **Esfuerzo:** Bajo
