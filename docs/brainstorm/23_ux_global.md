# 🎨 UX Global — Brainstorming (transversal)

> **Qué es hoy:** Streamlit con un menú lateral de 19 pantallas (colapsa en "ver 9
> más"), buen lenguaje en español, disclaimers presentes, capturas en
> `_screenshots/`. La estética es limpia y consistente.

La crítica principal es estructural: **demasiadas pantallas al mismo nivel** y casi
todas arrancan vacías. El producto es potentísimo pero pide mucho esfuerzo de
entrada.

## Ideas

### Idea 1 — Reorganizar el menú por "lo que querés hacer"
- **Qué:** agrupar en 4-5 secciones claras (Mi plan · Investigar · Simular ·
  Monitorear · Ajustes) y esconder lo técnico.
- **Por qué:** 19 ítems con "ver 9 más" abruman; agrupar por intención guía y reduce
  la carga mental.
- **Tipo:** UX / UI · **Esfuerzo:** Medio

### Idea 2 — Menos pantallas: fusionar las que se solapan
- **Qué:** Allocation→Optimizer, Watchlist→Screener, Eval/Macro/Calidad→fondo,
  Comité/Chat/Ficha→experiencia única.
- **Por qué:** cada pantalla debe ganarse su lugar; menos puertas = producto más
  entendible.
- **Tipo:** UX / Flujo · **Esfuerzo:** Alto

### Idea 3 — Terminar con las pantallas en blanco
- **Qué:** que toda pantalla muestre algo útil al entrar (último resultado, ejemplo,
  estado), nunca solo un botón.
- **Por qué:** el "tool-first" obliga a trabajar antes de ver valor; el "result-first"
  invita a explorar.
- **Tipo:** UX · **Esfuerzo:** Medio

### Idea 4 — Funcionar bien en el celular
- **Qué:** revisar que tablas y gráficos sean usables en pantalla chica.
- **Por qué:** mucha gente revisa sus inversiones desde el teléfono; Streamlit en
  mobile suele quedar incómodo.
- **Tipo:** UX / Técnica · **Esfuerzo:** Alto

### Idea 5 — Sensación de velocidad
- **Qué:** estados de carga claros, resultados parciales mientras calcula, y nunca un
  spinner mudo largo.
- **Por qué:** la app hace cosas pesadas (screener, IA, Monte Carlo); sin feedback se
  siente colgada y la gente recarga.
- **Tipo:** UX / Técnica · **Esfuerzo:** Medio

### Idea 6 — Lenguaje consistente y sin jerga (con glosario a un clic)
- **Qué:** unificar términos en toda la app y enlazar cada término técnico a su
  explicación.
- **Por qué:** la jerga inconsistente confunde; el glosario accesible incluye sin
  simplificar de más.
- **Tipo:** UX · **Esfuerzo:** Medio

### Idea 7 — Modo oscuro y accesibilidad
- **Qué:** soporte de tema oscuro, buen contraste y tamaños de fuente legibles.
- **Por qué:** comodidad visual y alcance a más usuarios (incluida gente mayor, muy
  relevante en retiro).
- **Tipo:** UI · **Esfuerzo:** Bajo

### Idea 8 — Onboarding y tooltips contextuales
- **Qué:** ayudas que aparecen la primera vez que usás cada pantalla.
- **Por qué:** enseñan en el momento justo sin obligar a leer un manual.
- **Tipo:** UX · **Esfuerzo:** Medio

### Idea 9 — Coherencia visual de los gráficos
- **Qué:** misma paleta y estilo en todos los Plotly, con etiquetas siempre claras.
- **Por qué:** la consistencia visual hace al producto sentirse pulido y profesional.
- **Tipo:** UI · **Esfuerzo:** Bajo

### Idea 10 — Internacionalización (español/inglés)
- **Qué:** poder cambiar el idioma de toda la interfaz.
- **Por qué:** abre el producto a un público mucho más amplio sin reescribir nada del
  motor.
- **Tipo:** UX / Negocio · **Esfuerzo:** Alto

### Idea 11 — Atajos y navegación con teclado
- **Qué:** ir a cualquier pantalla o acción escribiendo (paleta de comandos).
- **Por qué:** acelera al usuario frecuente y es una alternativa al menú gigante.
- **Tipo:** UX · **Esfuerzo:** Medio
