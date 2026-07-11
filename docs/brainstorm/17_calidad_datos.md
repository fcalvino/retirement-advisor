# 🔬 Calidad de Datos — Brainstorming

> **Qué es hoy:** trae los mismos datos crudos de varias fuentes (yfinance + SEC
> EDGAR, FRED para macro) y marca dónde no coinciden, para que un número
> silenciosamente mal no se cuele en el análisis. Arranca pidiendo un ticker.
> Captura: `_screenshots/17_calidad_datos.png`

Es una idea madura y honesta (rara en productos de inversión). Pero hoy es una
pantalla técnica, manual y de un ticker por vez: el usuario común no la va a usar
aunque le sirva.

## Ideas

### Idea 1 — Que la calidad viva donde se usan los datos, no en una pantalla aparte
- **Qué:** el resultado de reconciliación debería aparecer como un sello en el
  Screener y en Stock Analysis, no obligar a venir acá.
- **Por qué:** nadie va a "verificar fuentes" proactivamente; la advertencia tiene
  que estar donde se decide. (Ya existe el badge de calidad — profundizarlo con la
  reconciliación multi-fuente.)
- **Tipo:** Flujo / Datos · **Esfuerzo:** Medio

### Idea 2 — Chequeo masivo del universo o del plan
- **Qué:** un botón "revisá la calidad de todos mis tickers" en vez de uno por uno.
- **Por qué:** lo relevante es "¿mi cartera está basada en datos confiables?", no un
  ticker aislado.
- **Tipo:** UX · **Esfuerzo:** Medio

### Idea 3 — Explicar el conflicto en humano
- **Qué:** "yfinance dice ROE 25% y SEC dice 22%: tomamos el de SEC porque es el
  filing oficial."
- **Por qué:** ver dos números distintos sin explicación confunde; la justificación
  educa y tranquiliza.
- **Tipo:** UX · **Esfuerzo:** Bajo

### Idea 4 — Más fuentes de datos
- **Qué:** sumar otra fuente (otro proveedor de fundamentals/precios) para tener
  desempate cuando dos discrepan.
- **Por qué:** con dos fuentes solo sabés que hay conflicto; con tres sabés cuál es la
  rara. Reduce el riesgo de fuente única (limitación conocida).
- **Tipo:** Datos / Técnica · **Esfuerzo:** Alto

### Idea 5 — Indicador de salud de datos a nivel app
- **Qué:** un resumen "el 90% de tu universo tiene datos consistentes; revisá estos 3".
- **Por qué:** convierte una herramienta de auditoría puntual en un termómetro
  permanente de confianza.
- **Tipo:** UX / Datos · **Esfuerzo:** Medio

### Idea 6 — Alerta cuando un dato clave cambia mucho
- **Qué:** avisar si una fuente reporta de golpe un valor muy distinto al histórico.
- **Por qué:** un cambio brusco suele ser un error de datos o un evento real
  importante; ambos merecen atención.
- **Tipo:** Datos · **Esfuerzo:** Medio

### Idea 7 — ¿Pantalla propia o función de fondo?
- **Qué:** evaluar si Calidad de Datos debe ser una pantalla del menú o un servicio
  silencioso que solo aparece cuando hay un problema.
- **Por qué:** con 19 pantallas, una que el usuario común casi no abre es candidata a
  integrarse en otras.
- **Tipo:** UX / Flujo · **Esfuerzo:** Bajo
