# 🏗️ Arquitectura y Calidad Técnica — Brainstorming (transversal)

> **Qué es hoy:** Python síncrono, Streamlit (UI), SQLite local, yfinance, capa de IA
> multi-proveedor, ~512 tests pasando, CI matrix 3.11/3.12, Docker. Config
> centralizada en `config.py`. Patrón limpio: funciones puras + inyección de
> dependencias, todo opt-in y backward-compatible.

La base técnica es notablemente sana (tests, config-driven, sin async forzado). Las
ideas apuntan a sostener eso a medida que crece y a destrabar los límites conocidos.

## Ideas

### Idea 1 — Resolver de raíz el límite de archivos (EMFILE)
- **Qué:** revisar el manejo de descargas paralelas y conexiones para que el screener
  no agote file descriptors.
- **Por qué:** es una limitación recurrente y mitigada a medias; resolverla mejora
  estabilidad y velocidad.
- **Tipo:** Técnica · **Esfuerzo:** Medio

### Idea 2 — ¿Streamlit alcanza para el siguiente nivel?
- **Qué:** evaluar si conviene mantener Streamlit o migrar la UI a algo más flexible
  (web app real) cuando se busque multiusuario/mobile.
- **Por qué:** Streamlit es genial para prototipar pero limita en navegación, mobile y
  multiusuario; conviene decidirlo a conciencia.
- **Tipo:** Técnica / Negocio · **Esfuerzo:** Alto

### Idea 3 — Separar el motor de la interfaz (API interna)
- **Qué:** exponer la lógica (análisis, optimizer, MC) como una capa reutilizable
  independiente de Streamlit.
- **Por qué:** permite web, mobile, chat o terceros sin reescribir el cerebro; es el
  paso clave para casi todo lo demás.
- **Tipo:** Técnica · **Esfuerzo:** Alto

### Idea 4 — Observabilidad: saber qué pasa
- **Qué:** métricas y logs de uso (qué falla, cuánto tarda, qué se usa) más allá de
  loguru.
- **Por qué:** sin visibilidad no se sabe qué mejorar ni qué se rompe en producción.
- **Tipo:** Técnica · **Esfuerzo:** Medio

### Idea 5 — Cobertura de tests donde más duele
- **Qué:** asegurar tests en los flujos de UI críticos y en los caminos de datos
  faltantes/errores.
- **Por qué:** el motor está bien testeado; la UI y los bordes (datos rotos) son donde
  aparecen los bugs reales.
- **Tipo:** Técnica · **Esfuerzo:** Medio

### Idea 6 — Pruebas de extremo a extremo automatizadas
- **Qué:** un set de tests que navegue la app como un usuario (justo lo que hizo
  Playwright para este brainstorming).
- **Por qué:** atrapa regresiones que los tests unitarios no ven (una página que no
  carga, un botón roto).
- **Tipo:** Técnica · **Esfuerzo:** Medio

### Idea 7 — Rendimiento percibido (cachear y precalcular)
- **Qué:** precalcular en segundo plano lo pesado (screener, simulaciones del plan)
  para que el usuario lo vea instantáneo.
- **Por qué:** la velocidad es UX; esperar 15s mata la exploración.
- **Tipo:** Técnica · **Esfuerzo:** Alto

### Idea 8 — Deploy de un clic
- **Qué:** facilitar correr la app sin saber de Python (instalador, imagen lista,
  botón de deploy a la nube).
- **Por qué:** la instalación es la barrera más alta hoy; bajarla amplía el alcance.
- **Tipo:** Técnica / Negocio · **Esfuerzo:** Medio

### Idea 9 — Gestión de secretos más segura
- **Qué:** mejor manejo de API keys (no solo `.env`), pensando en multiusuario.
- **Por qué:** claves en texto plano no escalan ni son seguras si el producto crece.
- **Tipo:** Técnica · **Esfuerzo:** Medio

### Idea 10 — Documentación viva y mantenible
- **Qué:** seguir el patrón de CONTEXT.md/refresh y sumar docs orientadas a
  contribuir/usar.
- **Por qué:** el proyecto ya cuida mucho la doc interna; extenderla a usuarios y
  futuros colaboradores sostiene la calidad.
- **Tipo:** Técnica · **Esfuerzo:** Bajo
