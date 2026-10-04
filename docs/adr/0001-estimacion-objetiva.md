---
status: accepted
date: 2026-10-03
---

# La app estima de forma objetiva; la prudencia es Postura del Perfil

Desde su creación la app fue «conservadora por defecto»: el Monte Carlo recorta un
20 % el rendimiento histórico y suma un 10 % de volatilidad, los prompts piden ser
conservadores y todo camino sin Perfil cae en Conservador. Ese sesgo no tenía
Fuente —sólo una frase en un docstring— y mezclaba dos cosas: lo que es probable
que pase y lo que el inversor quiere hacer al respecto. Decidimos separarlas: la
**Estimación** es Objetiva (sin ajuste deliberado, derivada de Fuentes declaradas,
sometida a Calibración donde el horizonte lo permite) y la prudencia se vuelve
**Postura**, explícita y editable en el Perfil. Los términos están en
[`GLOSARIO.md`](../GLOSARIO.md).

## Opciones consideradas

- **Seguir conservador.** Descartada: un haircut sin Fuente no es prudencia
  medible, y la app lo aplicaba de forma inconsistente (ver Consecuencias).
- **Un dial agresivo / equilibrado / conservador sobre las cifras.** Descartada:
  cambia de sesgo sin quitarlo; la cifra seguiría dependiendo de quién mira.
- **Estimación Objetiva + Postura en el Perfil.** Elegida. «Objetiva» no promete
  cifras más altas: con las proyecciones de gestoras de hoy, el central de renta
  variable de EE.UU. puede salir más bajo que el actual con haircut.

## Qué se decidió

- **Fuentes por Clase de activo:** historia de precios, valuación (CAPE de
  Shiller) y proyecciones a 10 años de gestoras (Vanguard, JPMorgan, BlackRock,
  Research Affiliates), cargadas a mano una vez por año con fecha y procedencia.
  Central = mediana de las Fuentes; Desacuerdo = su rango, siempre visible. Una
  Fuente de más de 12 meses avisa; de más de 24 sale del central.
- **Una sola Estimación por activo**, contraída hacia la de su Clase según su
  propia evidencia (el score, cuyo poder predictivo midió U6-1). La consumen el
  optimizador y el Monte Carlo; esto cierra la opción B pendiente de D3. El Monte
  Carlo sigue sorteando de la historia, recentrada en la Estimación.
- **Escenarios = Desacuerdo, no Azar:** pesimista, central y optimista son la
  Estimación desde cada Fuente; cada uno muestra su propio rango p10–p90. Se
  retiran los rótulos «Realista» y «Conservador».
- **El Perfil no toca la Estimación.** Se borra la escala por perfil de
  Simulaciones; el descuento por riesgo argentino rige para todos y su valor sale
  del riesgo país; el δ de Black-Litterman es el del mercado, fijo. El Perfil lleva
  topes, aversión al optimizar, Exigencia (editable; p. ej. 90/80/70 %), margen de
  seguridad y Escenario de planificación (pesimista para Conservador). Sin Perfil
  no hay Postura: la app muestra Estimaciones y pide elegir antes de dimensionar.
- **Cripto es Fuente declarada ausente:** sin central, Escenarios de 0 % real a su
  historia; el plan usa el pesimista. El techo HOLD de #149 se mantiene.
- **La IA se calibra, no se modera:** fuera «filosofía conservadora» y «nunca
  digas esto es genial»; el Abogado del Diablo se queda como método; el campo
  `recommended_max_allocation_conservative` pasa a `recommended_max_allocation` y
  el PM recibe la Postura. Un oráculo barre los prompts.
- **Señales:** el tope que sólo frena a la IA hacia arriba pasa a simétrico (la
  asimetría vuelve sólo si el track record la respalda); un dato faltante se imputa
  con la mediana del sector, no con 0; con datos parciales la señal se atenúa hacia
  HOLD en las dos direcciones. Los umbrales se quedan, rotulados «ranking relativo,
  no calibrado», hasta que haya outcomes a 1 año.
- **Prueba:** Trazabilidad (ningún ajuste sin Fuente, salvo Fuente declarada
  ausente) y un backtest del método con las Fuentes que tienen historia larga. El
  haircut global sólo se borra si ese backtest muestra que el rango declarado
  contiene el resultado con la frecuencia que dice.

## Consecuencias

- **Revierte X-07** («haircut del MC fuera de alcance») y la parte de la auditoría
  D3 que dejó entrar el Perfil por δ. Ese δ, además, iba al revés de su intención:
  Π = δ·Σ·w, así que el δ = 4,0 de Conservador producía el equilibrio **más**
  optimista de los tres perfiles. La postura vieja ni siquiera era conservadora de
  forma consistente; la pestaña Plan, con el selector en Conservador, aplicaba
  ×0,56 al rendimiento mientras la principal aplicaba ×0,80, sin avisar.
- **Los planes guardados cambian de cifras** al cambiar el método. Cada etapa que
  mueva una Estimación sube `ENGINE_VERSION` (los planes ya lo guardan); el
  historial de salud y el track record pasan a guardarla también, y una
  comparación entre versiones distintas se anota como cambio de método y no
  dispara la alerta de deterioro.
- Se implementa en siete etapas (EO-0 a EO-6, `BACKLOG.md`).

## Nota (2026-10-04, EO-0)

La segunda consecuencia supuso un riesgo que el código no tiene. La alerta de
«plan envejecido» compara sólo la deriva ponderada de precios entre registros
(`data/plan_context.py`), y la P50 de cada registro de salud es la del plan al
guardarse: un cambio de método no puede dispararla, así que el historial de salud
no necesita guardar la versión. El track record sí la necesita, pero no
`ENGINE_VERSION` —el contrato del motor del Monte Carlo—, sino una versión del
método de señales, y entra con EO-6, que es la etapa que cambia las señales. La
decisión no cambia.

## Nota (2026-10-04, EO-1a)

«Qué se decidió» dice que el Perfil lleva la «aversión al optimizar». En el código
no queda como número: el objetivo del optimizador maximiza el ratio sin un λ de
aversión, y el único δ era el del prior de Black-Litterman, que EO-1a fijó en el de
mercado. La aversión del Perfil entra sólo por sus topes (posición, volatilidad,
sector, dividendo) y el desplazamiento de bonos por edad. La decisión no cambia.
