# 📒 Track Record — Brainstorming

> **Qué es hoy:** historial auditable de cada recomendación que emitió el motor y su
> acierto medido contra el benchmark, a horizontes de 30/90/252 días, sin elegir
> ventanas favorables. En la captura: 8 recomendaciones logueadas, 0 evaluadas
> todavía (hace falta que pase el tiempo). Captura: `_screenshots/14_track_record.png`

Es una idea valiosísima y honesta: "no me creas, mirá mi historial". Su problema es
el **arranque en frío**: vacío hasta que pasen meses, así que pocos verán su valor a
tiempo.

## Ideas

### Idea 1 — Backfill con historia para mostrar valor ya
- **Qué:** evaluar contra el pasado las recomendaciones que el motor habría dado,
  para tener un track record poblado desde el día 1.
- **Por qué:** sin esto, la pantalla está vacía meses y nadie confía en algo que no
  muestra nada. (Cuidando el sesgo de mirar para atrás.)
- **Tipo:** Datos / Técnica · **Esfuerzo:** Alto

### Idea 2 — Resumen honesto en una línea
- **Qué:** "De las recomendaciones ya evaluables, acertó el X% y superó al benchmark
  en promedio por Y%." con su contexto.
- **Por qué:** el número resumen es lo que genera (o no) confianza; hoy hay que
  interpretarlo de una tabla.
- **Tipo:** UX · **Esfuerzo:** Bajo

### Idea 3 — Desglose por tipo de acierto
- **Qué:** mostrar el acierto separado por señal (compra/venta) y por sector.
- **Por qué:** un motor puede ser bueno para una cosa y malo para otra; saberlo es
  más útil que un promedio.
- **Tipo:** UX · **Esfuerzo:** Medio

### Idea 4 — Comparar fuentes de decisión
- **Qué:** acierto del rule-based vs IA vs comité, lado a lado.
- **Por qué:** responde "¿la IA realmente agrega valor?", una pregunta central del
  producto, con datos en vez de fe.
- **Tipo:** Datos / IA · **Esfuerzo:** Medio

### Idea 5 — Estado claro de "todavía no evaluable"
- **Qué:** distinguir visualmente lo pendiente (horizonte no cumplido) de lo evaluado.
- **Por qué:** el "0 evaluadas" actual parece un error; un mensaje de "madurando"
  lo explica.
- **Tipo:** UX · **Esfuerzo:** Bajo

### Idea 6 — Puntaje automático (sin apretar "puntuar pendientes")
- **Qué:** que la evaluación corra sola con el scheduler.
- **Por qué:** depender de un botón manual hace que el historial quede desactualizado.
- **Tipo:** Técnica · **Esfuerzo:** Medio

### Idea 7 — Usar el track record para calibrar la confianza
- **Qué:** si históricamente el motor acierta poco en cierto tipo de caso, bajar la
  confianza que muestra ahí.
- **Por qué:** cierra el círculo: el historial no solo se muestra, mejora las futuras
  recomendaciones.
- **Tipo:** Técnica / IA · **Esfuerzo:** Alto

### Idea 8 — Exportar el track record
- **Qué:** descargar el historial completo en CSV.
- **Por qué:** la auditabilidad es el punto; permitir que cualquiera revise los datos
  refuerza la credibilidad.
- **Tipo:** Datos · **Esfuerzo:** Bajo
