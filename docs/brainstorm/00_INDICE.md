# 🧠 Brainstorming — Llevar Retirement Advisor al siguiente nivel

> Documento de ideación, no de implementación. Acá no se cambia código del
> producto: se juntan **ideas** para decidir hacia dónde evolucionar.
> Generado tras navegar **cada pantalla** de la app en vivo (capturas en
> `_screenshots/`). Última actualización: 2026-06-20.

## Cómo leer esto

- Hay **un archivo por módulo** (las 19 pantallas del menú) + **7 archivos por
  capa/tema transversal** (datos, IA/agentes, portfolio, UX global, negocio,
  arquitectura, nuevos módulos).
- Cada idea está escrita en lenguaje simple, con su **por qué**, una **etiqueta
  de tipo** (UX / UI / Flujo / Técnica / Negocio / Agente / Datos / Nuevo módulo)
  y un **esfuerzo** estimado (Bajo / Medio / Alto).
- Al final, `99_PRIORIZACION.md` junta TODO y marca por dónde empezar.

## Foto rápida del producto hoy

Producto muy maduro: **19 pantallas**, motor de análisis fundamental + moat +
tailwinds, optimizador, Monte Carlo con decumulación, plan de retiro activable, y
una capa de IA grande (comité multi-agente, chat, RAG macro, eval harness, track
record, reconciliación de datos). La debilidad ya no es "faltan features" — es que
**hay demasiada superficie y mucha fricción de entrada**: casi toda pantalla
arranca vacía esperando que el usuario apriete un botón.

## Tres hilos que cruzan todo el documento

1. **Demasiadas puertas, poca cocina.** 19 pantallas (el menú colapsa en "ver 9
   más") y varias responden la misma pregunta ("¿esta acción es buena?":
   Stock Analysis, Comité, Chat). Consolidar > agregar.
2. **Todo es "tool-first".** Screener, Comité, Calidad de Datos, Chat, Alertas,
   Track Record y Eval arrancan en blanco. Falta el modo "mostrame algo útil
   apenas entro".
3. **El plan ya es el corazón — falta que tire del resto.** "Mi Plan" es lo más
   valioso; el resto de las pantallas deberían alimentarlo y volver a él.

## Mapa de archivos

### Módulos (pantallas del menú)
| # | Archivo | Pantalla |
|---|---------|----------|
| 01 | [inicio_home](01_inicio_home.md) | 📈 Inicio |
| 02 | [screener](02_screener.md) | 🏠 Screener |
| 03 | [stock_analysis](03_stock_analysis.md) | 🔍 Stock Analysis |
| 04 | [portfolio](04_portfolio.md) | 💼 Portfolio (+ libro personal) |
| 05 | [allocation](05_allocation.md) | 📊 Allocation |
| 06 | [optimizer](06_optimizer.md) | 📈 Optimizer |
| 07 | [backtesting](07_backtesting.md) | 📉 Backtesting |
| 08 | [simulaciones](08_simulaciones.md) | 🎲 Simulaciones |
| 09 | [alertas](09_alertas.md) | 🔔 Alertas |
| 10 | [settings](10_settings.md) | ⚙️ Settings |
| 11 | [about](11_about.md) | ℹ️ About |
| 12 | [watchlist](12_watchlist.md) | 📋 Watchlist |
| 13 | [mi_plan](13_mi_plan.md) | 🗺️ Mi Plan |
| 14 | [track_record](14_track_record.md) | 📒 Track Record |
| 15 | [eval_ia](15_eval_ia.md) | 🧪 Eval IA |
| 16 | [comite](16_comite.md) | 🏛️ Comité |
| 17 | [calidad_datos](17_calidad_datos.md) | 🔬 Calidad de Datos |
| 18 | [macro_rag](18_macro_rag.md) | 🧭 Macro RAG |
| 19 | [chat](19_chat.md) | 💬 Hablá con tu plan |

### Capas / temas transversales
| # | Archivo | Tema |
|---|---------|------|
| 20 | [capa_datos](20_capa_datos.md) | Datos, fuentes, cache, resiliencia |
| 21 | [capa_ia_agentes](21_capa_ia_agentes.md) | IA, prompts, **sumar/restar agentes** |
| 22 | [capa_portfolio](22_capa_portfolio.md) | Optimizer, Monte Carlo, riesgo |
| 23 | [ux_global](23_ux_global.md) | Navegación, mobile, idioma, velocidad |
| 24 | [negocio](24_negocio.md) | Monetización, distribución, posicionamiento |
| 25 | [arquitectura](25_arquitectura.md) | Rendimiento, tests, deploy, ¿Streamlit? |
| 26 | [nuevos_modulos](26_nuevos_modulos.md) | Módulos que hoy no existen |

### Cierre
- [99_PRIORIZACION](99_PRIORIZACION.md) — tabla maestra + quick wins + "si solo hacés 5 cosas".
