# 🎯 Priorización — Por dónde empezar

> Síntesis de todas las ideas del brainstorming, ordenadas para **decidir**, no para
> programar. Impacto = cuánto mueve la aguja para el usuario/negocio. Esfuerzo =
> cuánto cuesta hacerlo.

## La idea de fondo

El producto **no necesita más features** — necesita que las que ya tiene sean
**fáciles de encontrar, de entender y de accionar**. Tres movimientos pagan más que
cualquier feature nueva:

1. **Consolidar pantallas** (de 19 a ~10 bien agrupadas).
2. **Matar las pantallas en blanco** (mostrar valor al entrar, no un botón).
3. **Poner el Plan en el centro** y que todo salga y vuelva a él.

---

## ⭐ Quick wins (alto impacto / bajo esfuerzo) — empezar acá

| Idea | Módulo | Tipo |
|------|--------|------|
| Realista vs Conservador siempre visible (no plegado) | Simulaciones | UX |
| Preguntas sugeridas clicables en el Chat | Chat | UX |
| Mostrar resultados cacheados al entrar (no pantalla en blanco) | Screener | UX |
| Filtros y búsqueda arriba de la tabla | Screener | UX/UI |
| Veredicto/conclusión arriba, detalle abajo | Stock Analysis, Optimizer | UX |
| Acción única destacada ("hoy hacé esto") | Inicio | Flujo |
| Resumen honesto en una línea del track record | Track Record | UX |
| Sacar herramientas de dev del menú (Eval IA, etc.) | Eval IA / UX global | UX |
| Barra de progreso real durante análisis | Screener | UX/Técnica |
| Modo oscuro y accesibilidad | UX global | UI |
| Botón "probar con plan de ejemplo" en la portada | Inicio | Negocio |
| Distinguir "calculado" vs "interpretación de IA" | Capa IA | IA/UX |

---

## 🏗️ Apuestas grandes (alto impacto / alto esfuerzo) — planear con tiempo

| Idea | Módulo | Por qué importa |
|------|--------|-----------------|
| Reorganizar menú + fusionar pantallas que se solapan | UX global | Es el cambio que más mejora la usabilidad |
| Flujo único meta → cartera → simulación → plan | Capa Portfolio | Hila piezas que ya existen en un solo recorrido |
| Separar el motor de la interfaz (API interna) | Arquitectura | Habilita web, mobile, chat y multiusuario |
| Asistente "¿qué cambio para llegar?" en Simulaciones | Simulaciones | Vuelve accionable el resultado clave |
| Unificar ficha + comité + chat en una experiencia | Capa IA | Tres pantallas responden lo mismo hoy |
| El Chat como puerta de entrada principal | Chat | Posible futuro de la navegación |
| Módulo Doble Moneda (Argentina/USD) | Nuevos módulos | Diferencial real frente a competidores globales |
| Módulo de Impuestos | Nuevos módulos | Cambia decisiones y plata real |
| Versión web multiusuario | Negocio | Saca al producto del "corré un script" |

---

## 🔧 Mejoras de robustez/confianza (impacto medio, valen la pena)

| Idea | Módulo |
|------|--------|
| Segunda fuente de datos + reintentos | Capa de Datos |
| Calidad de datos visible donde se decide (no pantalla aparte) | Calidad de Datos |
| Deriva inteligente cuando cartera y plan no se superponen | Portfolio |
| Riesgo en lenguaje humano ("en una crisis caés ~X%") | Portfolio / Simulaciones |
| Track record automático + backfill histórico | Track Record |
| Alertas que corran solas + centro de notificaciones | Alertas |
| Macro RAG presentado como "el clima económico de tu plan" | Macro RAG |
| Carteras más robustas (paridad de riesgo / Black-Litterman) | Capa Portfolio |

---

## 🧭 Si solo hacés 5 cosas

1. **Reorganizar el menú y fusionar pantallas** (de 19 a ~10 por intención). Es lo
   que más baja la barrera de entrada. → `23_ux_global.md`
2. **Matar las pantallas en blanco**: mostrar el último resultado o un ejemplo al
   entrar, en Screener, Simulaciones, Comité, Chat. → varios
3. **Poner "cómo viene tu plan" en la portada y en el centro de todo.** →
   `01_inicio_home.md`, `13_mi_plan.md`
4. **Hacer visible la transparencia que ya tenés** (realista vs conservador, calidad
   de datos, calculado vs IA): es tu mayor diferencial y está escondido. →
   `08_simulaciones.md`, `17_calidad_datos.md`, `21_capa_ia_agentes.md`
5. **Volver accionable el resultado**: del "no llegás" al "hacé esto para llegar", y
   del análisis al trade/plan en un clic. → `08_simulaciones.md`, `06_optimizer.md`

---

## Una observación final

La fortaleza técnica de este producto es **rara y valiosa**: motor cuantitativo
serio, IA que no inventa, transparencia honesta (sesgo conservador explícito,
calidad de datos, track record auditable). El próximo nivel no es más potencia — es
**que esa honestidad y esa potencia se sientan, se entiendan y se usen** sin esfuerzo.
El producto ya piensa como un buen asesor; falta que **hable y guíe** como uno.
