# 🗄️ Capa de Datos — Brainstorming (transversal)

> **Qué es hoy:** los datos entran casi todos por una sola fuente (yfinance), con
> cache en SQLite y TTL, reconciliación opcional con SEC EDGAR/FRED, snapshot offline
> y universos curados + tickers custom. Es la base sobre la que se apoya TODO.

La calidad del producto está limitada por la calidad de sus datos. Hoy la mayor
fragilidad reconocida es la **dependencia de una sola fuente sin reintentos**.

## Ideas

### Idea 1 — Segunda fuente de datos real (con fallback)
- **Qué:** una fuente alternativa de precios y fundamentals que entre si yfinance
  falla o discrepa.
- **Por qué:** hoy si un ticker falla, se loguea y se sigue; eso deja huecos
  silenciosos. Una segunda fuente da robustez y desempate.
- **Tipo:** Datos / Técnica · **Esfuerzo:** Alto

### Idea 2 — Reintentos y degradación elegante
- **Qué:** reintentar la descarga que falló y, si no se puede, mostrar claramente que
  ese dato falta en vez de tratarlo como cero/None.
- **Por qué:** un dato faltante tratado como cero distorsiona scores y carteras sin
  que nadie lo note.
- **Tipo:** Técnica · **Esfuerzo:** Medio

### Idea 3 — Datos fundamentales con fecha visible
- **Qué:** mostrar de cuándo es cada dato fundamental (último balance) y avisar si
  está viejo.
- **Por qué:** un balance de hace 18 meses no es comparable con uno reciente; la
  frescura cambia el análisis.
- **Tipo:** Datos / UX · **Esfuerzo:** Medio

### Idea 4 — Control de cache para el usuario
- **Qué:** ver el estado del cache y poder refrescar un ticker puntual sin borrar
  todo.
- **Por qué:** hoy el reset es total (borrar la base); algo más fino evita perder
  todo por refrescar uno.
- **Tipo:** UX / Técnica · **Esfuerzo:** Bajo

### Idea 5 — Datos de dividendos e historial de pagos
- **Qué:** sumar el calendario y la consistencia de pago de dividendos.
- **Por qué:** para un inversor de retiro que vive de dividendos, esto es central y
  hoy está poco desarrollado.
- **Tipo:** Datos · **Esfuerzo:** Medio

### Idea 6 — Más universos curados
- **Qué:** ofrecer listas listas: dividendos aristócratas, mercados emergentes, ETFs
  por temática, acciones argentinas.
- **Por qué:** el universo define lo que el usuario puede analizar; más listas de
  calidad amplían el público sin que cada uno arme la suya.
- **Tipo:** Datos / Negocio · **Esfuerzo:** Medio

### Idea 7 — Datos de tipo de cambio y bonos
- **Qué:** incorporar FX (USD/ARS) y rendimientos de bonos como series de primera
  clase.
- **Por qué:** habilita planes en doble moneda y una clase de activo "renta fija"
  real, hoy ausente.
- **Tipo:** Datos · **Esfuerzo:** Alto

### Idea 8 — Snapshot/respaldo automático y programado
- **Qué:** que el snapshot offline del universo se genere solo cada cierto tiempo.
- **Por qué:** garantiza un respaldo de datos sin depender de que el usuario se
  acuerde; clave ante caídas de la fuente.
- **Tipo:** Técnica · **Esfuerzo:** Bajo

### Idea 9 — Validaciones de sanidad en los datos
- **Qué:** reglas simples ("un P/E negativo enorme es sospechoso") que marquen datos
  raros antes de que entren al score.
- **Por qué:** un dato basura puede inflar o hundir un score; filtrarlo protege todo
  lo que viene después.
- **Tipo:** Datos / Técnica · **Esfuerzo:** Medio
