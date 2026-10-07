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

## Nota (2026-10-05, EO-3)

El backtest que condiciona EO-4 corrió point-in-time sobre la serie de Shiller
(`ie_data.xls`, sha256 `044196da…`, hasta 2026-08). En cada mes desde 1881, sólo con lo
que se sabía entonces, el central es la mediana de las Fuentes con historia larga y el
p10–p90 sale del mismo mecanismo del Monte Carlo (bootstrap de los 120 meses previos)
recentrado de forma compuesta en ese central; se compara con el rendimiento real de
los 10 años siguientes. Decisiones del usuario (2026-10-05): términos reales; pasa si
el 80 % cae en el intervalo de Clopper-Pearson al 90 % de la cobertura en las ventanas
sin superposición.

| Clase | Fuentes del central | Sin superposición | Intervalo 90 % | Superpuestas | Veredicto |
|---|---|---|---|---|---|
| Acciones EE.UU. | 1/CAPE · Historia real del S&P | 9/14 (64 %) | 39 %–85 % | 73 % | pasa |
| Bonos EE.UU. | GS10 − inflación de 10 años previos · Historia real | 6/14 (43 %) | 21 %–68 % | 41 % | no pasa |
| Ex-EE.UU., emergentes, REITs | — | — | — | — | no calibrables (unas 2–3 ventanas independientes) |

La regla es de dos colas: una banda que contiene el resultado siempre (14/14) también
falla, porque declara 80 % y sobre-cubre.

Acciones pasa con poca potencia: con 14 ventanas el intervalo es ancho, las
superpuestas (73 %) quedan algo debajo del 80 % y el veredicto depende del mes en que
arrancan las ventanas: corriendo la regla sobre las 120 fases posibles, acciones pasa
en 93 (k entre 5 y 13) y bonos en 4 (k entre 3 y 8). Se juzga con la primera fase, la
que eligió el usuario; las demás se informan. Bonos no pasa por el método, no por la
muestra: la banda es angosta (4,3 pp de ancho medio, contra 11,7 en acciones) porque
sortear meses de los últimos 10 años no reproduce los regímenes de inflación que
mueven 10 años de bonos reales, y el central queda alto (los fallos caen debajo del
p10 tres veces más que arriba del p90; la Historia real de bonos se pasa 1,87 pp en
promedio). Ninguna variante medida pasa (bloques de 12/24/60 meses; toda la historia
previa), y probar hasta que una pase sobre las mismas ventanas sería ajustar al test.
El proxy de inflación de los bonos es un supuesto del backtest, no de la app. El
«Long Interest Rate GS10» de Shiller arranca en 1871, antes de que existiera un Tesoro
a 10 años: es una serie de tasas largas empalmada, y ni la página ni el archivo
documentan el empalme, así que la parte temprana de bonos es la más débil.

Consecuencia: EO-4 recentra el Monte Carlo de forma compuesta y sólo tiene evidencia
para borrar el haircut en acciones de EE.UU.; qué hacer con bonos es una decisión
pendiente del usuario. La decisión de fondo no cambia.

## Nota (2026-10-06, EO-4a)

El Monte Carlo deja el haircut global. Recentra la **cartera** de forma compuesta en el
promedio ponderado de las Estimaciones de sus activos, con la volatilidad propia de esos
activos: la mediana de los caminos rinde la Estimación. Es el mismo contrato que EO-3
probó sobre el S&P, que también es una cartera. La primera versión recentraba cada
activo en el central de su Clase, y la QA en vivo mostró por qué no: una acción sola
recibía el rendimiento compuesto del índice con su propia volatilidad, o sea un
rendimiento aritmético mayor que el del índice, y tres acciones con rebalanceo semanal
proyectaban 8,3 %/año sobre una Estimación de 6,7 %.

Lo que el haircut sigue cubriendo, con su rótulo (decisiones del usuario, 2026-10-05):
bonos de EE.UU. (EO-3 no pasó), los tickers sin Clase y las Clases sin Fuentes vigentes.
Cripto proyecta 0 % real, el Escenario pesimista. La contracción de cada activo hacia
su Clase según el score queda para EO-4b. La decisión no cambia.

## Nota (2026-10-06, EO-4b)

El Optimizer toma como μ de cada activo la misma Estimación que el Monte Carlo: el
central de su Clase (cripto, 0 % real); bonos de EE.UU., tickers sin Clase y Clases sin
Fuentes vigentes, su historia semanal con el mismo haircut del Monte Carlo,
compuesto, pero sobre la ventana del Optimizer (`OPTIMIZER.price_history_years`, 2
años), no los 10 del Monte Carlo. Con eso el rendimiento esperado de la cartera es el promedio ponderado de
las Estimaciones, el número en el que EO-4a recentra la proyección.

«Qué se decidió» dice que la Estimación de cada activo se contrae hacia la de su Clase
según el score. El usuario decidió no hacerlo todavía (2026-10-06): U6-1 midió que el
score ordena el rendimiento pero no lo cotiza, así que un peso de contracción sería un
número sin Fuente. Dos acciones de la misma Clase reciben el mismo μ y el score sólo
elige el grupo de candidatos. Por la misma razón el posterior de Black-Litterman no
corre sobre la Estimación: el equilibrio Π sería un segundo ancla sin Fuente y la
confianza de cada view salía del score. La covarianza sigue siendo la histórica, con
Ledoit-Wolf. La contracción queda como fila aparte del BACKLOG (SCORE-CONTRACCION).
Hasta EO-4d, el descuento por riesgo argentino sólo baja el score de los ADRs, sin
llegar a μ. La decisión no cambia.

## Nota (2026-10-06, EO-4c-1)

Los Escenarios toman, para cada Clase, la Fuente vigente más baja (pesimista), la
mediana (central) o la más alta (optimista); una Fuente de más de 24 meses sale del
rango igual que del central. El haircut de bonos EE.UU. y de los tickers sin Clase, y el
0 % real de cripto, son iguales en los tres: el ADR pide para cripto «Escenarios de
0 % real a su historia», y el usuario eligió dejarlo en 0 % real en los tres
(2026-10-06). El Escenario de planificación es Postura: Conservador planifica con el
pesimista, Moderado y Agresivo con el central, y el usuario lo puede cambiar. El
Monte Carlo proyecta con él; el Optimizer no lo lee, así que la igualdad de EO-4b (el
rendimiento de la cartera es el promedio ponderado de las Estimaciones) vale en el
central, y un plan Conservador proyecta debajo de la cifra del Optimizer por el
Desacuerdo, a propósito. La UI que muestra los tres Escenarios es EO-4c-2. La
decisión no cambia.

## Nota (2026-10-07, EO-4c-2)

La UI muestra los tres Escenarios: un bloque en la pestaña Monte Carlo y una pestaña
«Escenarios» que reemplaza «Comparar perfiles» y sus escalas sin Fuente. El p10 y el
p90 de una proyección se llaman «Mala racha» y «Buena racha» —son Azar—, y «pesimista»
/ «optimista» quedan para el Desacuerdo entre Fuentes (decisión del usuario). La
historia reciente deja de ser una proyección y queda como la Fuente «Historia» de cada
Clase. Los dos Escenarios que no son la Postura corren con menos simulaciones
(`MONTE_CARLO.scenario_side_sims`), y la UI lo dice. Con esto «Qué se decidió» está
implementado salvo la contracción por score (SCORE-CONTRACCION) y el riesgo país
(EO-4d). La decisión no cambia.

## Nota (2026-10-07, EO-4d)

El riesgo país de EO-2c entra a la Estimación de los ADRs argentinos, en rendimiento.
Regla del usuario (2026-10-07, entre tres): el spread completo, en pp, se resta de la
Estimación de la Clase del ADR, sin bajar del 0 % real (la inflación implícita), igual
en los tres Escenarios porque es un dato citado y no Desacuerdo. El camino es uno solo,
`analysis.estimacion`, así que el Optimizer y el Monte Carlo dicen el mismo número. Se
va `OPTIMIZER.ars_risk_discount`: el score ya no se descuenta por ser argentino. Dato
«vieja» (más de 12 meses): se usa y se rotula; «fuera» (más de 24) o ausente: no se
resta y se avisa. Con haircut (sin Clase o Clase sin Fuentes) no se resta: su historia
ya trae el riesgo realizado. Con las Fuentes de hoy el piso manda: emergentes 7,225 %
menos 6,55 pp queda bajo la inflación implícita de 2,36 %, así que un ADR argentino
proyecta 0 % real. Descartadas: la pérdida esperada (spread × (1 − recuperación)) y el
spread neto del de la Clase emergente, porque cada una pide una Fuente nueva. «Qué se
decidió» queda implementado salvo la contracción por score (SCORE-CONTRACCION). La
decisión no cambia.

## Nota (2026-10-07, EO-6a)

EO-6 se parte en dos PRs por decisión del usuario: 6a sella cada recomendación del
track record con la versión del método de señales (`SIGNAL_METHOD_VERSION`, propia: no
es `ENGINE_VERSION` ni `COMMITTEE.prompt_version`) y 6b cambia la escalera. Las filas
escritas antes quedan sin versión, rotuladas «anterior a EO-6». 6a no mueve ninguna
señal. La decisión no cambia.
