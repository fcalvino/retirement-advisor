# ⚙️ Settings — Brainstorming

> **Qué es hoy:** configuración del proveedor de IA + API keys, perfil personal
> (wizard), universo de tickers, tickers custom, y reset. Es el panel de control.
> Captura: `_screenshots/10_settings.png`

Funciona, pero mezcla cosas muy distintas (claves técnicas, perfil personal,
universo) en una sola pantalla larga. Y configurar IA es la barrera técnica más
alta para un usuario no técnico.

## Ideas

### Idea 1 — Separar "lo mío" de "lo técnico"
- **Qué:** agrupar en pestañas: Mi perfil · IA y claves · Datos y universo · Avanzado.
- **Por qué:** el usuario que viene a editar su edad no debería toparse con API keys
  y viceversa.
- **Tipo:** UX / UI · **Esfuerzo:** Bajo

### Idea 2 — Asistente para configurar la IA
- **Qué:** un paso a paso simple: "elegí proveedor → pegá tu clave → probamos que
  funcione" con un test en vivo.
- **Por qué:** las claves de API son lo más confuso para no técnicos; un test
  inmediato evita el "no sé si quedó bien".
- **Tipo:** UX · **Esfuerzo:** Medio

### Idea 3 — Explicar qué hace cada proveedor y cuánto cuesta
- **Qué:** una tabla simple: Claude/Grok/OpenAI/Nous, para qué sirve cada uno, costo
  aproximado, y cuál recomendamos.
- **Por qué:** elegir proveedor a ciegas frena. Una guía corta da seguridad.
- **Tipo:** UX / Negocio · **Esfuerzo:** Bajo

### Idea 4 — Funcionar bien sin IA
- **Qué:** dejar clarísimo qué funciona sin claves (todo el análisis cuantitativo) y
  qué se desbloquea con IA.
- **Por qué:** muchos pueden no querer/poder poner una clave; no deberían sentir que
  la app está "rota".
- **Tipo:** UX · **Esfuerzo:** Bajo

### Idea 5 — Reset granular y respaldo
- **Qué:** en vez de un reset total, permitir borrar solo cache, solo perfil, o
  exportar/importar toda la configuración.
- **Por qué:** un reset que borra todo asusta; el respaldo da tranquilidad para
  experimentar.
- **Tipo:** UX / Técnica · **Esfuerzo:** Medio

### Idea 6 — Gestión visual del universo
- **Qué:** buscar y armar tu propia lista de tickers con buscador, no pegando
  símbolos.
- **Por qué:** el universo define todo lo que ves; armarlo a mano es propenso a
  errores.
- **Tipo:** UX · **Esfuerzo:** Medio

### Idea 7 — Preferencias de idioma y moneda
- **Qué:** elegir idioma (es/en) y moneda base (USD/ARS).
- **Por qué:** abre el producto a más público y resuelve el "todo en dólares" para el
  inversor argentino.
- **Tipo:** Negocio / Técnica · **Esfuerzo:** Alto

### Idea 8 — Indicador de salud de la configuración
- **Qué:** un check arriba: "IA conectada ✅ · datos frescos ✅ · alertas activas ⚠️".
- **Por qué:** centraliza el "¿está todo en orden?" que hoy se descubre a los golpes.
- **Tipo:** UX · **Esfuerzo:** Bajo
