# 🏠 Screener — Brainstorming

> **Qué es hoy:** analiza todo el universo (85+ tickers) en fundamental + técnico y
> arma una tabla rankeada por score, con columnas de calidad de datos y "viento"
> (tailwind). Arranca **vacío**: hay que apretar "Refresh Analysis" y esperar.
> Captura: `_screenshots/02_screener.png`

El motor detrás es muy bueno. El problema es de **presentación y entrada**: pantalla
en blanco, una sola tabla larga, sin filtros ni una historia que guíe la mirada.

## Ideas

### Idea 1 — Mostrar resultados cacheados al entrar
- **Qué:** si ya hay análisis en cache, mostrarlo de una; el botón "Refresh" queda
  solo para actualizar.
- **Por qué:** la pantalla en blanco hace pensar que no hay nada. Mostrar el último
  resultado conocido es más útil y más rápido de percibir.
- **Tipo:** UX · **Esfuerzo:** Bajo

### Idea 2 — Filtros y búsqueda arriba de la tabla
- **Qué:** filtros por sector, país, señal (comprar/mantener), score mínimo, con o
  sin viento de cola, y un buscador de ticker.
- **Por qué:** una tabla de 85 filas sin filtros obliga a leer todo. Filtrar es lo
  primero que pide cualquiera que screenea.
- **Tipo:** UX / UI · **Esfuerzo:** Bajo

### Idea 3 — Vistas predefinidas ("top oportunidades", "alto dividendo", "value")
- **Qué:** botones que aplican un filtro+orden típico de un clic.
- **Por qué:** la mayoría busca lo mismo. Atajos pensados ahorran el armado manual
  y enseñan para qué sirve el score.
- **Tipo:** UX / Flujo · **Esfuerzo:** Bajo

### Idea 4 — Resumen narrado del universo
- **Qué:** arriba de la tabla, 2 frases: "Hoy 6 acciones dan señal de compra,
  lideradas por X e Y; el sector más fuerte es Tecnología."
- **Por qué:** transforma datos en insight. Es la diferencia entre una planilla y
  un asesor.
- **Tipo:** UX / IA · **Esfuerzo:** Medio

### Idea 5 — Comparación rápida (seleccionar 2-3 y ver lado a lado)
- **Qué:** checkboxes para elegir tickers y un panel comparativo de sus scores y
  dimensiones.
- **Por qué:** decidir es comparar. Hoy hay que abrir Stock Analysis de a uno.
- **Tipo:** UX · **Esfuerzo:** Medio

### Idea 6 — Acciones directas desde cada fila
- **Qué:** en cada fila, botones "analizar a fondo", "agregar a watchlist",
  "mandar al comité".
- **Por qué:** cierra el flujo sin saltar de pantalla y recordar el ticker.
- **Tipo:** Flujo · **Esfuerzo:** Bajo

### Idea 7 — Barra de progreso real durante el análisis
- **Qué:** "analizando 23/85…" con el ticker actual, en vez de un spinner mudo.
- **Por qué:** el análisis con IA tarda; sin feedback parece colgado y la gente
  recarga (lo que empeora el problema de file descriptors).
- **Tipo:** UX / Técnica · **Esfuerzo:** Bajo

### Idea 8 — Marcar lo que cambió desde la última corrida
- **Qué:** flechas ▲▼ de cambio de score y un badge "nuevo en señal de compra".
- **Por qué:** lo accionable no es el ranking estático sino lo que se movió.
- **Tipo:** UX / Datos · **Esfuerzo:** Medio

### Idea 9 — Explicación de cada columna a un clic
- **Qué:** tooltips o un mini-glosario plegable (qué es Moat, Consistency, Viento).
- **Por qué:** muchas columnas son jerga. Sin explicación, el usuario ignora justo
  lo que da ventaja al producto.
- **Tipo:** UX · **Esfuerzo:** Bajo

### Idea 10 — Heatmap de sectores
- **Qué:** un mapa de calor por sector/score para ver de un vistazo dónde está la
  fuerza.
- **Por qué:** apela a la vista, no a leer filas; bueno para detectar rotaciones.
- **Tipo:** UI · **Esfuerzo:** Medio

### Idea 11 — Alertas guardables desde el screener
- **Qué:** "avisame cuando este ticker pase a señal de compra" directo desde la fila.
- **Por qué:** conecta el descubrimiento con el monitoreo (módulo Alertas) sin
  fricción.
- **Tipo:** Flujo · **Esfuerzo:** Medio
