# Estado del Proyecto — Retirement Advisor

> **Rol: `historical-plan`. Este archivo es un diario de fases ya shipeadas, no un backlog.**
> Lo que falta hacer vive en [`BACKLOG.md`](BACKLOG.md), priorizado y verificado
> contra el código. Cuando una fila del backlog se cierra, se muda acá con su commit.

## ✅ Todo implementado y en producción (GitHub main)

Este plan describe trabajo **ya completado**. El plan original (AI integration) fue implementado junto con las Fases 1.5, 2 y 3.

---

## U5-5 — Un ratio que un banco no puede tener no le falta (2026-08-28)

`_QUALITY_KEY_FIELDS` le exigía `debt_equity` y `current_ratio` a toda empresa, sin
conciencia de qué clase de empresa era. Un banco que toma depósitos no tiene
ninguno de los dos en el sentido que esas bandas suponen: no tiene estructura de
capital de trabajo, y `Total Debt / Equity` omite los depósitos, que son su
financiamiento principal.

**Corrección al enunciado del backlog.** La fila decía *"un banco no puede alcanzar
calidad de datos buena"*, y eso **no es lo que pasa**: 9 de los 11 bancos cacheados
**sí** llegan a "good", porque `partial_missing_fields` es 3 y les faltan 2. El
defecto real es más silencioso:

- cada banco gastaba permanentemente **2 de sus 3 campos de tolerancia** en ratios
  que estructuralmente no puede tener, así que **un solo hueco genuino lo tiraba a
  "partial"** donde una industrial necesitaba tres. BSAC es el caso vivo —un
  `revenue_cagr_5y` realmente ausente más los dos fantasmas— y es el único ticker
  que este PR mueve: **partial → good**, listando ahora sólo el hueco que de verdad
  tiene;
- `missing_fields` se renderiza al usuario, así que la app le decía que a nueve
  bancos les faltaban dos métricas cuando no les faltaba nada.

**El marcador es estructural, no una etiqueta**: la ausencia de `Current Assets` en
el balance. Es el precedente que `_derive_debt_equity` ya había fijado y
documentado —*"a diferencia de un string de industria, no puede derivar según cómo
lo escriba un feed"*— y sobre el universo cacheado selecciona exactamente a los
nueve bancos y a nadie más. Las aseguradoras tampoco tienen activos corrientes pero
sí reportan `debtToEquity`, así que nunca llegan a ese camino. Un balance
**ausente** no marca nada: no saber no es lo mismo que saber que el ratio no aplica.

Los campos exentos salen también del **denominador**. Dejarlos en `n_checked`
seguiría diciéndole al lector que la app fue a buscar algo que nunca estuvo ahí.

**Alcance medido sobre 164 tickers: 0 scores, 0 acciones y 0 confianzas se mueven.**
El único cambio es el badge de BSAC. `data_quality` **sí** condiciona decisiones vía
`apply_data_quality_policy`, así que valía verificarlo en vez de asumirlo.

Esto **no** construye un scorer bancario: X-01 sigue fuera de alcance, y un test
verifica que la exención nunca llegue a las dimensiones de puntaje.

Contrato: `tests/test_bank_data_quality_oracle.py`.

---

## U5-13 — El gap de capital, en dólares de un solo año (2026-08-28)

`compute_aggregates` sumaba el `target_nominal` de cada meta —el monto necesario
**en el año objetivo de esa meta**— y le restaba la suma de los `median_terminal`,
también cada uno en su propio año. Un auto en 2031 y un retiro en 2051 se sumaban
y el resultado se mostraba como *"te falta esto"*, sin ningún año adosado a la cifra.

Dólares nominales de años distintos no son la misma unidad, así que su suma no es
una cantidad. Y el error corre para un solo lado: cuanto más lejos la meta, más
sobrestima su objetivo nominal inflado el esfuerzo real. Medido de punta a punta
sobre un plan plausible —auto a 5 años, casa a 12, retiro a 25:

| | mezclando años | USD de hoy |
|---|---:|---:|
| capital requerido | 1.923.665 | **980.000** |
| gap de capital | 1.018.479 | **498.997** |

El requerido nominal sobrestimaba un **96 %**.

Cada meta se deflacta en sus propios términos —su horizonte, su
`expected_inflation`— y recién entonces se suma, vía `product_ux.present_value_usd`,
que ya era la única implementación de `nominal / (1+i)**n` para la superficie de
producto.

**Deflactar antes de sumar es la parte que importa** y tiene test propio: netear
primero los nominales deja que un excedente en dólares de 2051 cancele un faltante
en dólares de 2031. El faltante por meta además se pisa en cero antes de
descontarse, así que una meta sobrefondeada aporta cero y no crédito.

Los campos se **renombran** a `total_capital_needed_today` y `capital_gap_today` en
vez de cambiar de significado calladamente bajo el nombre viejo: un número cuyo
nombre no dice su unidad es exactamente cómo éste sobrevivió, y el repo ya trata
una etiqueta engañosa como el defecto (U1-1, U1-5, U1-6). No se persistían ni se
testeaban, así que no hubo migración; las dos superficies ahora dicen "USD de hoy"
en vez de dejarle el año al lector.

Contrato: `tests/test_capital_gap_oracle.py`.

---

## U5-15 — El horizonte anual dura un año (2026-08-28)

Dos defectos sobre la única evidencia que el motor tiene de sus propias
recomendaciones.

**El horizonte "anual" duraba 8,3 meses.** `horizons_days` traía `(30, 90, 252)` y
el docstring describía el 252 como *"≈ 12 trading months"*, mientras el scorer hace
aritmética de calendario pura: `rec.created_at + timedelta(days=horizon)`. 252 es
la cantidad de días **de trading** de un año, así que el número era correcto en una
unidad que el código nunca usó. Ahora es 365, y el docstring dice días de calendario
sin decir "trading months" en la misma frase.

**Una sola banda de HOLD servía para todos los horizontes.** `hold_band_pct = 5.0`
decidía si mantener fue lo correcto tanto a 30 días como a un año. La dispersión
crece con la **raíz cuadrada del tiempo**, así que una banda calibrada para un mes
es demasiado angosta para un año: casi cualquier acción se mueve más de 5 % en doce
meses, de modo que un HOLD quedaba mal calificado **por el paso del tiempo, no por
la decisión**. Las bandas pasan a ser por horizonte —5,0 / 8,7 / 17,4— con el valor
de 30 días conservado como ancla shipeada y los otros escalados desde él por √t.

Esos dos números derivados son una **elección de calibración, no un hallazgo
empírico**, y la config lo dice: la muestra es demasiado joven para zanjarlos. Decir
cuál es cuál es el punto — las bandas de P/FFO llevan la misma advertencia por la
misma razón.

**Por qué éste era el momento, medido sobre la base viva:** sólo el horizonte de 30
días fue puntuado alguna vez (**22 resultados**) y la recomendación más antigua tiene
**73 días**, así que nada se calificó nunca a 90 ni a 252. Recalificados contra las
bandas nuevas, **0 de los 22 cambian** — la banda de 30 días queda intacta por
construcción. El costo de migración es cero hoy y crece con cada mes que los
horizontes sigan mal, que es justamente el argumento que el backlog daba para esta fila.

Contrato: `tests/test_track_record_horizon_oracle.py`.

---

## U3-9 + U3-10 — Cada ratio, un solo año fiscal (2026-08-28)

Cada lado de un ratio se buscaba por separado, con su propio `dropna()`, así que
cada uno caía en el año que **esa fila** hubiera reportado por última vez. Nada
verificaba que coincidieran y nada marcaba el resultado cuando no lo hacían.

| ticker | qué mezclaba | antes | ahora |
|---|---|---:|---:|
| AAPL | EBIT 2025-09-30 ÷ intereses **2023**-09-30 | 33,8x | **29,1x** |
| LLY | EBIT 2025 ÷ intereses **2024** | 38,0x | **21,8x** |
| GOOGL | ingreso neto 2025 + D&A **2022** | — | — |
| MELI | dividendos **2022** sobre FFO 2025 | — | — |

LLY es la que conviene mirar: mostraba **38,0x contra un 21,8x real**, una
sobreestimación del 74 % presentada como un hecho.

**`aligned_latest` ancla en vez de descartar, y esa elección es todo el diseño.**
Negarse a producir el ratio cuando las columnas más nuevas no coinciden habría
vuelto a romper lo que un arreglo anterior reparó: el `dropna()` se agregó
justamente para que AAPL y LLY **no perdieran** la cobertura de intereses por una
última columna en blanco — su docstring lo dice. Retroceder al año compartido más
reciente conserva la métrica y la vuelve verdadera. Sólo una ausencia real de
solapamiento no devuelve nada.

El payout del FFO necesitó una segunda pasada: la primera versión alineaba los
dividendos contra el último ingreso neto, lo que sólo corre el desajuste un paso
—el FFO quedaba anclado en 2024 y el ingreso neto reportaba hasta 2025—. Ahora
`_ffo_parts` devuelve el período del que salió el FFO y el payout toma los
dividendos de **ese** año.

**Alcance medido: 0 scores, 0 acciones y 0 bandas de salud se mueven.** AAPL y LLY
quedan muy por encima del umbral de 10x en los dos casos, y 0 de los 13 REITs
cacheados tenían un FFO con años mezclados. Es un número mal en pantalla y una
trampa esperando a cualquier empresa cuyo ratio quede cerca del borde de una
banda — no un error de puntaje vivo.

Contrato: `tests/test_fiscal_alignment_oracle.py`.

---

## U3-8 — Un solo ROIC, gravado donde la empresa tributa (2026-08-28)

El ROIC alimenta la dimensión de calidad (7 puntos) **y** la durabilidad del moat,
así que un error acá entra dos veces al score ajustado. Tres defectos encima.

**Dos implementaciones.** `fundamental._compute_roic` y `moat._avg_roic` armaban
NOPAT / capital invertido cada una por su cuenta, y cada una escribía la misma tasa
distinto: `0.21` en una, `0.79` en la otra. Dos grafías de una constante esconden
que es una sola constante. La fórmula se muda a `analysis.utils.roic_pct`; la
**ventana** se queda con cada consumidor, porque esa diferencia sí es deliberada:
`fundamental` lee el último año para puntuar lo que la empresa gana **hoy**, y el
moat promedia los años disponibles para juzgar si **dura**. Un test verifica que
las dos coinciden dado un único año.

**La tasa era la de EE.UU., para todos.** La fija la ley que grava la ganancia
operativa, no el lugar donde cotiza el ADR. 25 de los 164 tickers cacheados no son
estadounidenses, y 4 cambian de banda de puntaje al gravarse bien:

| ticker | país | tasa | ROIC al 21 % | ROIC real | banda |
|---|---|---:|---:|---:|---|
| EDN | Argentina | 35 % | 16,1 | **13,3** | excelente → bueno |
| SBS | Brasil | 34 % | 15,5 | **12,9** | excelente → bueno |
| PAM | Argentina | 35 % | 11,2 | **9,2** | bueno → aceptable |
| ETN | Irlanda | 12,5 % | 14,5 | **16,1** | bueno → **excelente** |

ETN es la razón por la que esto no es una poda disfrazada de arreglo: Irlanda grava
al 12,5 %, así que la tasa de EE.UU. venía **subestimando** lo que esas empresas se
quedan. La corrección corta para los dos lados.

Las tasas viven en `config.TAXES` porque cambian por ley y no por código, y el
default de país desconocido **no** es la tasa de EE.UU.: una jurisdicción que no se
conoce es un supuesto, y ponerle el número de un país concreto lo disfraza de dato.

**ROA se reportaba con el nombre de ROIC.** Cuando los estados no daban un ROIC,
`returnOnAssets` se asignaba a `result.roic`, se puntuaba contra las bandas de ROIC
y se imprimía como "ROIC" en toda superficie. Denominador distinto, cantidad
distinta. El fallback se fue; medido sobre el universo cacheado disparaba en **0 de
164** tickers, así que hoy no mueve nada — era una trampa latente, no una muleta viva.

Contrato: `tests/test_roic_oracle.py`.

---

## U3-3 + U3-4 + U3-5 — La cadena de Graham (2026-08-28)

Tres defectos encadenados sobre `graham_value`, que termina en
`require_margin_of_safety` — la puerta que desbloquea STRONG BUY. Un error acá no
matiza una pantalla: cambia lo que el producto dice que hay que comprar.

**U3-5 — `g` era el crecimiento de la empresa, no el del accionista.** Salía del
CAGR de *Net Income*, bajo un campo llamado `eps_cagr_5y` y una etiqueta que decía
"EPS CAGR". Son números distintos cada vez que se mueve la cantidad de acciones, y
esa diferencia **es** el punto: es el crecimiento que el tenedor efectivamente
recibe. `Diluted EPS` está en todos los estados cacheados, así que la serie pasa a
ser la de por acción; Net Income queda como fallback con etiqueta propia —llamarlo
"EPS CAGR" sería este mismo defecto sobreviviendo en el único caso donde es
inevitable.

Lo que eso destapó, medido:

| ticker | NI CAGR | EPS CAGR | qué pasaba |
|---|---:|---:|---|
| O | +6,8 % | **−6,3 %** | REIT que crece emitiendo acciones |
| EXR | +4,2 % | **−10,5 %** | ídem |
| MDT | +8,5 % | **−1,1 %** | dilución |
| MET | −13,8 % | **+18,5 %** | recompras en un tramo flojo |

O y EXR **hacen crecer sus ganancias y las achican por acción**. El motor puntuaba
lo primero llamándolo lo segundo, así que valuaba un crecimiento que esos tenedores
nunca recibieron. O baja de BUY a HOLD por esto.

**U3-3 — una empresa que no crece no tenía valor.** `if eps > 0 and growth_used > 0`
no producía nada, aunque Graham definió el 8,5 justamente como el múltiplo de una
empresa que no crece: `V = EPS × 8,5 × 4,4 / Y`, que da 41,56 con EPS 5. Estable,
rentable y sin crecer es el arquetipo de una tenencia de retiro, y era el único
perfil que la valuación se negaba a poner en precio. Una empresa **en declive**
sigue sin valor: ahí la fórmula no es una valuación, y su múltiplo se vuelve
negativo por debajo de `g = −4,25`.

**U3-4 — la tasa detrás del número no se nombraba.** `Y` es un proxy congelado del
4,5 % del rendimiento AAA, y toda superficie imprimía "Graham Intrinsic Value" sin
mencionarlo, invitando a leer como fijo un número que se mueve al revés que las
tasas. `graham_value_help` nombra la tasa, la cita **desde config** y dice que es un
proxy. Traer el AAA en vivo sigue fuera de alcance (X-04) — decir qué número se está
usando no lo necesita.

**Alcance medido sobre 164 tickers:** 17 scores se mueven, todos en la dimensión de
crecimiento; 4 señales cambian (ADP y AMX a STRONG BUY, AXP a BUY, O a HOLD). Los
valores de Graham van de 102 a 101: tres empresas ganan uno que siempre debieron
tener (HON, MET, TMO) y cuatro pierden uno que nunca debieron tener (EXR, LTM, MDT, O).

Contrato: `tests/test_graham_chain_oracle.py`.

---

## U3-1 — No saber la tendencia no es saber que baja (2026-08-28)

`above_sma200` era un `bool` con default `False`, y `_compute_trend` caía a `False`
cuando la media móvil daba NaN. Una empresa listada hace menos de ~3,8 años
reportaba **exactamente lo mismo** que una que cotiza debajo de su media de largo
plazo, y cuatro consumidores leían el segundo significado: `strategy` anotaba el
riesgo *"long-term downtrend caution"*, `personal_sizer` abría una ventana de
"agregar en debilidad", los dos prompts le afirmaban al LLM *"precio DEBAJO de la
media"*, y la ficha del ticker mostraba ❌. Ninguna de esas era una conclusión
sobre la empresa: eran conclusiones sobre el largo de su serie de precios.

Las tres banderas de tendencia pasan a `Optional[bool]` y todos los lectores usan
`is True` / `is False` — la convención que `macd_bullish`, un campo más abajo,
seguía desde siempre.

**Poner `None` era la mitad chica.** `not None` es `True`, así que el sizer habría
seguido marcando debilidad; y `bool(None)` es `False`, así que dos call sites que
coercionaban a través de un dict habrían dado vuelta el default optimista de
`personal_sizer` justo cuando no se sabe nada. Las dos coerciones se fueron.

La línea del prompt tenía el mismo defecto por duplicado: el MACD usaba la misma
forma `x if flag else y` sobre un campo que es `Optional` desde siempre, así que un
MACD desconocido se le reportaba al modelo como bajista. Un helper `_tristate`
sirve a los dos, y la redacción conserva `de la {TREND_MA_LABEL}` intacto para que
la guarda de U1-3 pase **sin editarla**.

**Medido sobre el universo cacheado: 0 acciones, 0 scores y 0 señales técnicas se
mueven.** Una bandera desconocida ya aportaba 0 puntos a la señal, así que este PR
cambia lo que el motor **dice**, no lo que calcula — más la única conducta que
estaba mal: LTM (108 barras) sigue marcado como debilidad técnica, pero ahora por
la razón real (17,3 % debajo de su máximo de 52 semanas) en vez de también por una
inventada. Un ticker de historia corta cerca de sus máximos ya no se marca.

`test_window_and_nan_handling_are_untouched` congelaba `above_sma200: bool = False`
con una nota que decía que U3-1 lo haría `Optional` y que *hasta entonces* el
default debía quedarse. Ese "hasta entonces" llegó: el congelamiento se levanta y el
test conserva lo que U1-3 realmente protege —que la ventana sigue siendo de 200
barras **semanales**— con un nombre que lo dice.

Quedó afuera a propósito, abierto como **U3-1b**: `sma200_slope_pct` tiene la misma
forma (`float = 0.0`, donde "sin ventana" y "plana" son el mismo valor).

Contrato: `tests/test_trend_unknown_oracle.py`.

---

## U5-6 — El foso se paga una sola vez en μ (2026-08-28)

`optimizer._expected_returns` armaba μ como `score_ret + div_ret + moat_ret`, pero
el `adjusted_score` que alimenta `score_ret` **ya contiene** el bonus de moat
(`min(moat_total × 0,5, max_bonus)`, agregado en `FundamentalAnalyzer.analyze`). La
misma ventaja se pagaba dos veces, y el optimizer sobreponderaba empresas con foso
ancho respecto de lo que el propio motor dice que valen.

**Se sacó el término, no el bonus del score.** Era la disyuntiva que el backlog
dejaba abierta, y la otra rama tiene una trampa: `adjusted_score` está topado en
100, así que restarle el bonus resta de más —hasta 7 puntos— en los 6 tickers que
están en el tope, que es justo el techo del ranking donde el optimizer asigna.

Medido sobre las 150 equities cacheadas: μ baja de **7,49 a 6,99 pp** de promedio,
**0,95 pp** como máximo en el foso más ancho, y **2 nombres rotan en el top-20**.

`views.moat` se **borra**, no se pone en 0: un peso en cero se lee como una perilla
apagada, y volver a encenderla restauraría el doble conteo.

**Los pesos que quedan NO se renormalizan, y eso es el punto.** Llevar 0,50/0,30 a
0,625/0,375 mantiene la suma en 1 y deshace el arreglo: infla la contribución del
foso que legítimamente vive dentro del score junto con todo lo demás, subiendo μ
**+1,24 pp** contra los −0,50 que se acaban de quitar. Son escaladores por
componente, no partes de un todo; `er_absolute_cap` (14 pp) es lo que acota el total.

El test de la auditoría D3 afirmaba que los pesos suman 1,0. Era incidental —cierto
porque había tres pesos para tres componentes—. Lo que D3 protege es que μ sea
independiente del perfil, que no se tocó, así que la afirmación se movió a su sujeto
real en vez de borrarse.

El término de tailwind tiene la misma forma y se queda: es un tilt **declarado y
acotado**, con perilla (`TAILWINDS.optimizer_er_tilt`, ~±0,9 %), no un error de
contabilidad. El docstring ahora dice cuál es cuál.

`ENGINE_VERSION` → **`2026.08-tier3`**. Los planes guardados tienen asignaciones
inclinadas hacia el foso y el aviso de staleness lo dice.

**U6-1 sigue abierto.** Quitar un término duplicado no es lo mismo que anclar el
modelo: el proxy sigue sin estar atado a nada observable.

Contrato: `tests/test_mu_moat_oracle.py`.

---

## U3-7 — La escala del moat, por modo (2026-08-28)

El último P0 del [`BACKLOG.md`](BACKLOG.md), desbloqueado por U0-2.

**El defecto.** `wide_threshold = 14.0` vive en una escala 0–20 que sólo existe
cuando la capa de IA corrió. Sin ella el total **es** el tramo cuantitativo, que
topea en 12. O sea que Wide Moat era inalcanzable **por construcción**: medido
sobre los 164 tickers cacheados, **0 Wide sin IA contra 22 con IA**. De ahí salían
los otros tres: el Optimizer hardcodeaba `>= 14` sobre filas que en esa ruta suelen
venir sin IA, el docstring prometía `+10` cuando el bonus quant-only topea en 6, y
el mismo ticker mostraba un foso distinto según la pantalla sin que ninguna dijera
en qué modo estaba.

**La decisión, tomada con datos.** El backlog autorizaba «umbral de Wide para el
modo quant-only **o** un preset de foso cuantitativo alto». Se eligió lo primero:
`quant_only_wide_threshold = 11.0`, `narrow = 6.5`, `minimal = 2.5`.

No son los umbrales de 0–20 reescalados por 12/20 (serían 8,4 / 4,8 / 2,4). Ese
reescalado coincide con la etiqueta que produce la IA en apenas el **58 %** del
universo, porque un foso cuantitativo fuerte **predice** uno cualitativo fuerte en
vez de ser independiente de él. Ajustados contra la etiqueta con IA llegan al
**86 %**, sin ningún error de más de un escalón, y erran para el lado conservador:
16 subestimaciones contra 7 sobreestimaciones, y 2 falsos Wide sobre 13.

**Alcance, verificado sobre el universo real:** 57 etiquetas corregidas,
**0 `adjusted_score` movidos, 0 `moat_bonus` movidos, 0 señales movidas**. El
`no_hacer` del backlog —no recalibrar 82/68/55, no bajar Wide con IA prendida— se
respeta por construcción: la fórmula del bonus no se tocó.

**Además:** `classify_moat()` queda como implementación única a nivel módulo (el
Optimizer prefiere la etiqueta que el motor ya calculó y sólo clasifica como
fallback); `MoatDetail.scale_max` / `.mode_label` hacen que las pantallas puedan
decir en qué modo están, que era el cuarto defecto; y la clasificación tras un
**fallo** de la IA dejó de degradar al ticker por una caída del proveedor.

Fuera de alcance a propósito, abierto como **U3-7b**: el Optimizer sigue
normalizando por `/20` para *rankear* (`:483`, `:509`). Es el mismo supuesto de
escala única, pero en los pesos, y `:625` es el doble conteo de μ (U5-6).

Contrato: `tests/test_moat_scale.py` (20 tests).

---

## U0-2 — La matriz de score con IA on/off (2026-08-28)

El único desbloqueo del [`BACKLOG.md`](BACKLOG.md): U3-7 pedía elegir entre subir
el techo cuantitativo del moat y bajar `wide_threshold`, y esa decisión no se podía
tomar sin medir el mismo universo con la IA prendida y apagada.
`scripts/measure_score_impact.py` existía desde `b141b56` pero corría
`full_analysis(symbol, ai_config=None)` fijo — sólo rule-based.

**Lo que apareció al intentar prender la IA.** El harness prometía *"nothing on
disk changes"* y esa promesa se rompía en tres lugares, ninguno cubierto por las
dos guardas originales:

1. `MoatAnalyzer` y `TailwindAnalyzer` construyen **su propia** `DataCache` a
   partir de `ai_cache_ttl_hours`, así que el bump de TTL del singleton nunca las
   alcanzaba. Y `DataCache.get` **borra** la fila que encuentra vencida: la
   primera corrida con IA habría destruido las 78 entradas de moat ya expiradas.
2. Un miss de caché llamaba al proveedor. Ahora `MOAT.ai_cache_only` /
   `TAILWINDS.ai_cache_only` devuelven el resultado cuantitativo intacto.
3. La capa de **decisión** no tiene caché y salía a la red — 8 s por ticker,
   verificado. `AIConfig.enrich_only` la deja en rule-based mientras el score
   sigue enriqueciéndose por moat y tailwind, que sí están cacheados.

Sin la tercera, la pata "IA on" no habría sido ni offline ni honesta:
`AIAnalyzer.analyze` se traga cualquier excepción y cae a rule-based, así que un
proveedor inalcanzable se habría leído como *"la IA no cambia nada"*. Por eso cada
fila lleva **`ai_ran`**, y la matriz cuenta aparte las que la IA nunca tocó.

**Lo que midió**, sobre los 164 tickers cacheados — la evidencia que U3-7 necesitaba:

| | `moat_score` máx | bonus máx |
|---|---:|---:|
| IA apagada | **12,0** | **6,0** |
| IA prendida | 19,0 | 9,5 |

Con `MOAT.wide_threshold = 14.0`, **Wide Moat es inalcanzable sin IA** en todo el
universo. El bonus quant-only topea en 6,0 contra los `+10` del docstring de
`moat.py`. La IA mueve el `adjusted_score` de **137 de 164** tickers.

Filas nuevas por ticker: `moat_score`, `moat_bonus`, `moat_classification`, `ai_ran`.
Salida: `--matrix PATH` (markdown). Contrato: `tests/test_score_matrix_harness.py`.

---

## Oleada 4 — Los flujos de caja del motor (2026-08-28)

Cerró las dos filas P0 de [`BACKLOG.md`](BACKLOG.md) que no dependían de nada, en
un solo PR como pedía la nota de alcance U4-1b: tocan la misma función y el mismo
invariante.

**U4-2 — una meta sin capital inicial descartaba todo el ahorro** (`9f05443`).
El pozo se expresaba como múltiplo de `initial_value` y el flujo como fracción de
él, así que un plan sin capital no tenía unidad en la que expresar sus aportes: la
fracción daba 0, los aportes se descartaban y `paths_usd = paths * 0` dejaba todo
en cero. El motor contestaba **0 % de probabilidad** a *"¿llego si ahorro X por
mes?"* en vez de admitir que no sabía modelar la pregunta. Como
`GoalPlanner._allocate_capital` reparte proporcionalmente, con `total_capital = 0`
le pasaba a **todas** las metas.

**U4-1 — el aporte "mensual" entraba una vez por año** (`9f05443`). Se
multiplicaba ×12 y se depositaba entero en la semana 52, así que once de los doce
depósitos perdían su rendimiento parcial: +1,8 % a +4,5 % de proyección según el
retorno, medido.

**Cómo:** el pozo pasa a guardarse en **unidades del índice de mercado** —
`wealth = units × market`. Un flujo compra o vende unidades al nivel de la semana
en que cae, y cada semana del resultado se escribe una sola vez, así que doce
eventos por año cuestan lo mismo que uno. La ruina sigue siendo absorbente porque
las unidades tienen piso en 0 — ahora una propiedad del álgebra, no de una rama
defensiva. La cadencia vive en `MONTE_CARLO.contribution_periods_per_year` (12) y
`withdrawal_periods_per_year` (1), así que la semántica tier1 es reproducible en
vez de borrada.

**Lo que el PR deliberadamente no hizo**, abierto como filas nuevas: **U4-1c** (la
cadencia del retiro) y **U4-5** (la palanca de aporte en Simulaciones).

**Efectos colaterales que aparecieron al poder arrancar en cero:** la ruina dejó
de contar las semanas previas al primer depósito (arrancar sin nada no es
bancarrota), el crecimiento del pozo dejó de dividir por capital cero, y
`mc_has_cash_flows` aprendió el parámetro nuevo — sin eso un plan de sólo aporte
habría reportado "sin flujos" y su crecimiento se habría rotulado *retorno* (U1-7)
justo donde más lo sobrestima.

`ENGINE_VERSION` → **`2026.08-tier2`**. De paso, el aviso de plan viejo dejó de
mentir: estaba escrito una sola vez para tier0 y se mostraba a cualquier plan
obsoleto, así que a un plan tier1 —cuyos retiros ya estaban bien— le decía algo
falso sobre sus propios números. Ahora las razones salen de `ENGINE_CHANGELOG`
filtrado por el sello que el plan lleva.

**Oráculos:** `tests/test_cash_flow_oracle.py` (21 tests). Los 133 de
`test_withdrawal_oracle` / `test_decumulation` / `test_sorr_oracle` /
`test_audit_2026_08_repro` pasan **sin editarse**, que era el criterio de
aceptación: D1, D2, la paridad del kernel y U2-2 siguen en pie.

---

## Fase H — Plan de Retiro como SO Personal: decumulación, historia, sensibilidad y adopción (2026-06)

Evolución de "construir el plan" a "maximizar su valor como sistema operativo de retiro", reutilizando >80% de la infraestructura existente (Monte Carlo con drags, PlanSnapshot extensible, shared helpers, journey, alertas, config-driven). Todo opt-in y conservador por defecto: con la capa nueva desactivada los números base son **byte-idénticos**. Suite completa: **419 pasando** (+68 sobre las 351 de Fase G), sin regresiones.

**H.1 — Motor de decumulación y withdrawal strategies (core retirement feature):**
- Nuevo `WithdrawalConfig` + singleton `WITHDRAWAL` en `config.py` (estrategia default, tasa base, bandas/pasos de guardrails, longevidad).
- Nuevo `portfolio/decumulation.py` (puro NumPy): `WithdrawalStrategy` (+ `fixed_real`/`constant_pct`/`guardrails`, `coerce`), `apply_withdrawal_strategy` y `decumulation_metrics`. `fixed_real` es byte-idéntico al `_apply_withdrawals` legacy (verificado por test).
- `portfolio/monte_carlo.py`: `run(..., withdrawal_strategy=, longevity_years=)` + métricas de decumulación en `MonteCarloResult` (`prob_sustain_real_pct`, `prob_legacy_pct`, `median_legacy`, `expected_depletion_year`, `longevity_years`). Sin estrategia → números base intactos.
- Persistencia: `PlanSnapshot.withdrawal_strategy` + métricas en `mc_summary` (backward-compat).
- UI: `render_withdrawal_controls`/`get_withdrawal_strategy`/`format_withdrawal_badge` en `shared.py`; sección "¿Cuánto dura tu ingreso?" en `7_Simulaciones.py`; estrategia + resultados en la tarjeta de `12_Plan.py`.
- Narrativa IA: `plan_level_narrative_prompt` describe la estrategia + riesgo de secuencia/longevidad (el LLM solo describe, no inventa reglas).

**H.2 — Historial longitudinal de salud del plan (confianza + detección temprana):**
- Nuevo `PlanHealthConfig` + singleton `HEALTH`. Nuevo `data/plan_health.py`: `PlanHealthRecord` + `PlanHealthStore` (JSON, dedup por día, cap de registros).
- `data/plan_context.py`: `record_plan_health`, `get_plan_health_history`, `compute_longitudinal_drift` (flag `degraded` por deriva sostenida ≥ umbral).
- Alertas: nuevo `AlertType.PLAN_HEALTH_DEGRADATION` + `AlertEngine.check_plan_health_degradation`. `scripts/run_scheduler.py` auto-registra salud (detrás de `HEALTH.auto_record`) y dispara la alerta de "plan envejecido".
- UI: sección "📊 Evolución de tu plan" en `12_Plan.py` (botón registrar, KPIs de tendencia, gráfico deriva/calidad, aviso de degradación, tabla de registros).

**H.3 — Laboratorio de sensibilidad y escenarios (what-if poderoso):**
- Nuevo `SensitivityConfig` + singleton `SENSITIVITY`. Nuevo `portfolio/sensitivity.py` (puro, `run_fn` inyectado): `run_sensitivity` (tornado de 4 factores: inflación, fricciones, retorno, volatilidad) + escenarios predefinidos ("inflación +1pp", "fricciones full", "mercado adverso", "vivir 5 años más") con deltas vs base; `tornado_rows` ordenado por impacto.
- UI: `run_plan_sensitivity` en `shared.py` (sobre `cached_monte_carlo`); sección "🔬 Sensibilidad del plan" en `7_Simulaciones.py` (tornado Plotly + tabla de escenarios, selector de métrica P10/mediana/ruina). El caso base es siempre la corrida actual.

**H.4 — Adopción y distribución (llegar a "plan activo" más fácil):**
- Demo mode: `data/sample_plans/*.json` (3 ejemplos que muestran las 3 estrategias) + `list_sample_plans`/`load_sample_plan` en `plan_context.py` (reutilizan `import_plan_from_dict`) + recuadro "🎁 plan de ejemplo" en el empty-state de `12_Plan.py` (cargar / cargar y activar).
- Packaging: `run.sh` (launcher idempotente), `Makefile` (setup/run/test/lint/check/clean), sección "⚡ Probar en 5 minutos" + Docker mejorado (build + montaje de `data/`) en `README.md`.
- CI/runtime: CI matrix Python 3.11/3.12; `Dockerfile` a `python:3.12-slim`.
- PDF: sección compacta "Estrategia de retiro (decumulación)" en `reports/investment_plan.py` cuando la simulación usó estrategia (acumulación pura → reporte byte-idéntico).

**Tests:** nuevos `test_decumulation.py`, `test_sensitivity.py`, `test_plan_health.py` + extensiones en `test_monte_carlo.py`, `test_plan_store.py`, `test_prompts.py`, `test_plan_context.py`.

**Pendiente (backlog H+):** deep plan compare (diff de supuestos + outcomes entre 2 planes guardados), historial de salud en el PDF, multi-source data, local LLM.

---

## Fase G — Remediaciones P0 post-Fase F (2026-06)

Tres debilidades P0 priorizadas del diagnóstico, atacadas reutilizando >80% de la infraestructura existente (plan vivo, journey, data quality, shared helpers, patrón Tailwind, config-driven). Todo configurable, conservador por defecto, sin romper el path determinístico.

**Item 1 — Transparencia radical de supuestos + capa de drags económicos:**
- Nuevo `EconomicDragConfig` + singleton `DRAGS` en `config.py` (fee anual, tax de dividendos, costo de rebalanceo, buffer AR; opt-in a nivel motor → cero regresiones).
- `portfolio/monte_carlo.py`: `run(drags=...)` aplica un drag anual efectivo compuesto semanalmente (exacto, O(semanas)) y expone métricas **base vs con-drags** en `MonteCarloResult`.
- Helpers en `dashboard/shared.py` (`get_economic_drags`, `format_drags_badge`, `render_drags_controls`, `render_assumptions_disclaimer`, `ASSUMPTIONS_TEXT`) + UI en `7_Simulaciones.py` y `12_Plan.py`.
- Captura de drags en `PlanSnapshot` (`drags_at_save`, base_* en `mc_summary`), sección de supuestos en el PDF (`reports/investment_plan.py`), bloque honesto en la narrativa IA (`analysis/prompts.py`), disclaimers centralizados en Home (`app.py`) y `10_About.py`.

**Item 2 — "Mi Plan" portable + journey de backup:**
- `data/plan_context.py:import_plan_from_dict` (puro, defensivo) + `dashboard/shared.py:export_plan_bundle` (JSON versionado + instrucciones de restauración).
- Export/Import en `12_Plan.py` (download por plan + file_uploader con activar opcional). Campos `export_version`/`export_notes` en `PlanSnapshot`.
- `plan_journey_status` extendido con paso "Respaldá tu plan" + nudge en Home.

**Item 3 — Resiliencia de datos + custom tickers seguros:**
- `custom_tickers` en `UserPreferences` (+ `add/remove/custom_symbols`). `data/universe_loader.py:get_effective_universe` mergea universo curado + customs (dedup, validación).
- UI en `9_Settings.py` (agregar/quitar con advertencias) + columna **Fuente** y warnings en `1_Screener.py` y `5_Optimizer.py` (badge ⚠️ Custom, calidad de datos parcial).
- `data/snapshot.py`: export de snapshot de datos del universo (precio + fundamentals clave) para backup/offline, con inyección de dependencias (testeable offline).

**Tests:** +nuevos tests en `test_monte_carlo.py`, `test_plan_store.py`, `test_plan_context.py`, `test_preferences.py` y `test_snapshot.py`. Suite completa: **351 pasando, sin regresiones**.

---

## Fase 0 — Quick Wins de Largo Plazo & UX (iniciada 2026)

Trabajo iniciado a partir del brainstorming de mejoras (ver plan en `.grok/sessions/.../plan.md`).

**Entregado en Fase 0:**

- **Mejores hints y mensajes para inversionistas de largo plazo** en `dashboard/app.py` y `dashboard/pages/7_Simulaciones.py` (flujo recomendado actualizado, mensajes educativos cuando no hay optimizer, mejor onboarding ligero en home).
- **Presets de escenarios comunes** (Acumulación pura, FIRE, Meta casa, Retiro clásico 30y) + **retiros que crecen con inflación** en Monte Carlo (`portfolio/monte_carlo.py`, `dashboard/shared.py`, `7_Simulaciones.py`). Esto es un cambio de modelado importante para planes realistas de 15-30 años.
- **Narrativa IA "Explicame este plan"** (`analysis/prompts.py` + `analysis/ai_analyzer.py` + botón en Simulaciones). Usa los proveedores AI existentes para generar una explicación conservadora y accionable del portafolio + simulación actual.
- Tests: 179 pasando (sin regresiones).
- Actualización de flujo recomendado y documentación inicial.

**Cierre de esta fase:** el leftover de “próximos pasos” de Fase 0 quedó absorbido por las fases A–J y el Gran Salto (todas shipped). No es backlog abierto — ver [`CONTEXT.md` §6](CONTEXT.md) para el estado actual.

---

## Fase A — Onboarding / Perfil de Usuario Personalizado (2026-06)

Cierra el item pendiente #1 del análisis de visión: capturar el contexto personal del
usuario para personalizar toda la app sin tocar código.

**Entregado:**

- **`UserPreferences` extendido** (`data/preferences.py`) con perfil personal: `onboarded`,
  `age`, `retirement_age`, `current_capital`, `monthly_savings`, `risk_tolerance`,
  `primary_goal_type`, `dividend_preference`. Defaults seguros → 100% backward-compatible
  con archivos de prefs viejos. Helpers derivados: `is_onboarded`, `primary_horizon_years`,
  `annual_savings`, `profile_key`, y `apply_personal_profile()` (mantiene `default_profile`
  sincronizado con la tolerancia al riesgo).
- **Wizard de onboarding ligero** (`dashboard/onboarding.py`): un `st.form` corto y opcional,
  con defaults conservadores. Se muestra en **Inicio** (si el usuario no completó el perfil)
  y en **⚙️ Settings → Mi Perfil** (siempre, para editar). Incluye `render_profile_summary()`.
- **Consumo del perfil como defaults inteligentes**:
  - `dashboard/shared.py` → `get_user_prefs()` + `seed_session_defaults_from_profile()`
    (siembra capital/horizonte una vez por sesión; `force=True` tras guardar el wizard).
  - **Optimizer** (`5_Optimizer.py`): perfil + "Capital a invertir" por defecto.
  - **Simulaciones** (`7_Simulaciones.py`): horizonte Monte Carlo + capital inicial + pre-fill
    del formulario de "Mis Metas" (tipo, horizonte, aporte anual, capital asignado).
  - **Allocation** (`4_Allocation.py`): edad + edad de retiro por defecto.
- **Reset** en Settings ahora también limpia el perfil personal.
- Tests: `tests/test_preferences.py` (7 nuevos) — defaults, mapping de perfil, round-trip
  de persistencia y backward-compat con archivos legacy. Suite total: 228 pasando.

**Fix incidental:** `analysis/crypto_analyzer.py` importaba `field` desde `typing` (typo) —
rompía la colección de tests; corregido (`field` viene de `dataclasses`).

---

## Fase B — Mi Plan de Retiro: orquestación + persistencia (2026-06)

Cierra la brecha entre "excelente analizador" y "plan persistente y accionable". Antes el
plan vivía fragmentado en session_state efímero (Optimizer / Simulaciones / Mis Metas).

**Entregado:**

- **`data/plan_store.py`** — `PlanSnapshot` (resumen JSON-serializable de un plan: allocation,
  core holdings, métricas, goals, `mc_summary`, narrativa, snapshot del perfil personal) +
  `PlanStore`/`plan_store` (`upsert`/`get`/`list`/`delete`, JSON en `data/retirement_plans.json`,
  mismo patrón que `UserPreferences`). `PlanSnapshot.from_session()` construye el snapshot desde
  los objetos vivos del Optimizer/MC/goals + prefs. **No** persiste el `OptimizationResult`
  completo (pesado/no portable); guarda los artefactos relevantes para el humano.
- **`dashboard/pages/12_Plan.py`** — página "🗺️ Mi Plan" (grupo Portfolio):
  - **Plan actual (sesión):** perfil + métricas + núcleo (Grok si existe, si no determinístico)
    + metas + resumen Monte Carlo + narrativa.
  - **Guardar plan** nombrado (guardar con nombre existente = actualizar, por `id` slug).
  - **Planes guardados:** ver (read-only), borrar, y **comparar 2 planes** (tabla de métricas).
  - **Lista de compra del núcleo** (USD por ticker, CSV) y **PDF** (reutiliza `InvestmentPlanReport`).
- Construye sobre Fase A (`get_user_prefs`) y reutiliza `profile_core_holdings`/`grok_core_holdings`
  + narrativa ya presentes en `OptimizationResult`.
- Tests: `tests/test_plan_store.py` (+6) — `from_session`, preferencia de core Grok, round-trip
  `upsert/get/list/delete`, upsert-replace por id. Suite total: **234 pasando**.

**Pendiente / próximos pasos:**
- ~~Delta vs precios de hoy al cargar un plan viejo (requiere fetch de precios actuales).~~ ✅ Entregado en Fase C.
- ~~Cierre del loop con el tracker (target vs posiciones reales, alertas de drift sobre el plan).~~ ✅ Entregado en Fase C.
- Superficie de `macro_factors` (per-asset) como "factores macro que más impactan tu plan" → Fase D.
- Narrativa AI del plan completo (`goal_narrative_prompt`) → Fase D.

---

## Fase C — Plan como Objetivo Vivo: activar + deltas + drift (2026-06)

Convierte "Mi Plan" de generador de snapshots estáticos en el **corazón operativo** del
producto: un plan guardado puede **activarse** como objetivo de retiro, y desde ahí el
tracker y las alertas lo usan como fuente de verdad. Apalanca casi toda la infraestructura
ya existente (`plan_store`, `PortfolioAlertDetector`, tracker, prefs) — es orquestación y
cierre de loop, no una feature nueva grande.

**Entregado:**

- **Plan activo (`data/preferences.py`)** — campo `active_plan_id` + `set_active_plan()` /
  `clear_active_plan()`. Default `""` → 100% backward-compatible.
- **`PlanSnapshot` extendido (`data/plan_store.py`)** — campos opcionales `last_refreshed_at`,
  `refreshed_metrics`, `macro_risks` (livianos), helper `target_weights()` (pesos objetivo
  desde la allocation, con fallback al núcleo), y captura opcional de `price_at_save` por
  ticker vía `price_lookup` inyectable en `from_session()` (best-effort, nunca rompe el guardado).
- **`data/plan_context.py` (nuevo, Streamlit-free)** — `get_active_plan()` (con self-heal si el
  id quedó colgado), `activate_plan()`, `deactivate_plan()`, `is_active()`, y
  `compute_plan_vs_reality(snap, price_lookup)` que calcula el delta de precio (hoy vs guardado),
  el drift ponderado del plan y deltas por ticker. Acceso a red inyectado → testeable offline.
- **`dashboard/shared.py`** — `plan_price_lookup()` (precio cacheado vía `get_info`) +
  `compute_plan_health()` (wrapper detrás del botón "Refrescar", fetch controlado).
- **Detector de drift generalizado (`alerts/portfolio_alerts.py` + `alerts/engine.py`)** —
  `run()` / `run_with_portfolio()` aceptan `target_weights` + `target_label`
  (`optimizer_weights` queda como alias backward-compat). Los mensajes dicen
  "drift vs tu Plan de Retiro «X»" en lugar de "vs el objetivo del optimizer".
- **Scheduler (`scripts/run_scheduler.py`)** — si hay plan activo + posiciones reales, el
  `job_alert_check` mide drift contra los pesos objetivo del plan activado.
- **UI `12_Plan.py`** — botón "🎯 Activar/Desactivar" por plan + badge de plan activo, y sección
  "📈 Salud vs mercado actual" con botón "🔄 Refrescar con datos de hoy" (delta de precio,
  precio guardado vs hoy, score promedio al guardar).
- **UI `3_Portfolio.py`** — sección "🎯 Alineación con tu Plan" (objetivo vs actual por posición,
  deriva total vs umbral de `config.ALERTS`, sugerencia de rebalanceo).
- Tests: `tests/test_plan_context.py` (nuevo, 9), `tests/test_plan_store.py` (+6 Fase C) y
  `tests/test_alert_engine.py` (+4 drift vs plan). Suite total: **252 pasando** (0 regresiones).

**Criterio de éxito cumplido:** el usuario puede guardar un plan, activarlo, ver si se está
desviando (en Portfolio y en alertas), y refrescarlo con el mercado de hoy.

---

## Fase D — Narrativa IA del plan, factores macro y what-if (2026-06)

Cierra los últimos pendientes de Fase B/C: todo plan guardado tiene una explicación humana
**regenerable y persistida**, los **riesgos macro** a nivel cartera son visibles, y un plan
puede recargarse en los flujos de Optimizer/Simulaciones para iterar.

**Entregado:**

- **`plan_level_narrative_prompt()` (`analysis/prompts.py`)** — prompt nuevo que, a partir de un
  `PlanSnapshot` (+ refresco de mercado opcional de Fase C), devuelve un JSON
  `{"narrative", "macro_risks"}`: explicación conservadora en español (estructura de viñetas
  fija) + 0-2 factores macro que más pueden romper el plan (`{factor, why, severity}`).
  Incorpora perfil personal, metas, Monte Carlo, núcleo, cartera, sectores y el delta de mercado.
- **`AIAnalyzer.generate_plan_narrative(snapshot, refreshed=None)` (`analysis/ai_analyzer.py`)** —
  reusa `_call_api` + `extract_json_object` con fallback robusto: error de API → mensaje útil;
  prosa sin JSON → se rescata como narrativa; macro normalizado y capado a 2. El path sin IA
  sigue funcionando (narrativa opcional).
- **UI `12_Plan.py`** — en el visor de cada snapshot: botón "🧠 Generar/Regenerar narrativa IA"
  (persiste `narrative` + `macro_risks` en el JSON del plan), sección "🌍 Factores macro que más
  impactan tu plan" (badges por severidad), y botón "📥 Cargar plan en Optimizer/Simulaciones"
  que siembra `session_state` (perfil vía preset hook, capital, horizonte, target, inflación,
  metas) para what-if inmediato.
- Tests: `tests/test_prompts.py` (+9) — estructura del prompt (campos JSON, voz conservadora,
  perfil/metas, bloque de refresco) y `generate_plan_narrative` (parse, cap de macro a 2,
  normalización, descarte de entradas malformadas, fallback de API, rescate de prosa).
  Suite total: **261 pasando** (0 regresiones).

**Criterio de éxito cumplido:** cada plan guardado es un documento vivo y explicable años
después, con sus riesgos macro a la vista, y recargable para iterar escenarios.

---

## Fase E — Alto Impacto Post-Plan Vivo: adopción, acción y confianza (2026-06)

Surge del análisis de visión post-Fase D (plan "Análisis de Visión + Áreas de Alto
Impacto"): la madurez técnica estaba completa, pero la **superficie de uso, la
accionabilidad y la confianza en los datos** del plan vivo podían mejorar mucho con
poco código nuevo. Se entregaron los 3 items P0 del análisis:

**E.A — Flujo guiado Onboarding → Primer Plan Activado (adopción/UX):**

- **`dashboard/shared.py` → `plan_journey_status(prefs)`** — los 4 pasos canónicos
  (perfil → optimizar → guardar plan → activar) con flag `done` cada uno, leyendo
  prefs + session_state + `plan_store`.
- **Home (`dashboard/app.py`)** — bloque "🚀 Tu camino a un plan de retiro activo":
  progress bar X/4, checklist con el próximo paso resaltado y botón
  "➡️ Siguiente paso" (`st.switch_page`). Cuando los 4 pasos están completos muestra
  el badge de plan activo. Flujo recomendado actualizado (ahora termina en
  Mi Plan → Portfolio + Alertas).
- **`12_Plan.py` empty state guiado** — en lugar de un warning muerto, muestra la
  checklist del journey + botones directos a Optimizer/Simulaciones + recordatorio
  de que el perfil ya siembra capital/perfil de riesgo.
- **CTAs de continuidad**: Optimizer (post-resultado) y Simulaciones (post-MC) sugieren
  ir a 🗺️ Mi Plan para consolidar.

**E.B — Trades sugeridos para alinear (cierre del loop de acción):**

- **`data/plan_context.py` → `compute_alignment_trades(snap, current_weights,
  total_value, *, price_lookup, drift_threshold_pct, min_trade_usd, max_trades)`** —
  función pura (Streamlit-free, lookup inyectable): compara `target_weights()` del plan
  vs pesos reales del tracker y devuelve trades priorizados (núcleo primero, luego por
  monto) con acción comprar/vender, monto USD y shares estimadas. Umbrales desde
  `config.ALERTS` (nuevos: `alignment_min_trade_usd`, `alignment_max_trades`;
  reusa `portfolio_drift_threshold_pct`). Nunca hardcodea.
- **UI `3_Portfolio.py`** — dentro de "Alineación con tu Plan", expander
  "🛒 Trades sugeridos" (auto-expandido si la deriva supera el umbral de rebalanceo):
  métricas comprar/vender, tabla priorizada (⭐ = núcleo) y disclaimer fuerte.
- **UI `12_Plan.py`** — sección "🛒 Acciones sugeridas para alinear tu portfolio" en el
  visor del plan **activo** (botón "🧮 Calcular", fetch controlado como el de salud).
- Tests: `tests/test_plan_context.py` (+8) — montos buy/sell, umbral, prioridad núcleo,
  filtro de montos chicos, cap de trades, posiciones fuera del plan, errores de price
  lookup tolerados, defaults desde config.

**E.C — Robustez y transparencia de calidad de datos (confianza):**

- **`config.py` → `DataQualityConfig` / `DATA_QUALITY`** — `stale_warning_hours=48`,
  `partial_missing_fields=3`, `poor_missing_fields=6`.
- **`data/cache.py` → `DataCache.get_age_hours(key)`** (probe read-only de frescura) y
  **`data/fetcher.py` → `get_info_age_hours(symbol)`**.
- **`analysis/fundamental.py` → `compute_data_quality(result, freshness_hours,
  has_financials)`** — función pura que clasifica `good/partial/poor` contando métricas
  clave en None (excluye `dividend_yield`: None es legítimo en growth) + flag `stale`
  independiente. Crypto/ETF/Index: solo se chequea precio usable. Nuevo campo
  `FundamentalResult.data_quality` poblado en `analyze()` (también en el fast-path
  crypto y en el early-return sin datos).
- **UI Screener** — columna "Datos" (🟢 OK / 🟡 Parcial / 🔴 Pobre / ⏳ stale) vía
  `data_quality_badge()` en `shared.py` + warning agregado con conteos cuando hay
  tickers degradados.
- **UI `12_Plan.py`** — la "Salud vs mercado actual" ahora advierte qué posiciones
  quedaron sin precio hoy (datos incompletos ⇒ delta/trades parciales).
- Tests: `tests/test_data_quality.py` (nuevo, 11) — thresholds, sin estados financieros,
  exclusión de dividend_yield, staleness independiente, crypto/ETF.

Suite total: **280 pasando** (0 regresiones).

**Criterio de éxito:** un usuario nuevo ve su progreso hacia el plan activo desde Home y
llega guiado en pocos clics; con drift sobre el umbral ve 2-6 trades concretos (núcleo
primero, con montos); y la calidad de los datos detrás de cada score es visible en vez
de silenciosa.

**Pendiente sugerido (P1, ver plan de visión):** D. transparencia de supuestos +
sensitivity de MC en el plan; E. historial longitudinal de salud del plan
(`health_history`); F. freshness/fallback rico de narrativas IA; captura opcional de
un snapshot de data quality al guardar el plan.

---

## Fase F — Colas de Viento Industria-País (Tailwinds, Idea 2) (2026-06)

Motivación (caso canónico): el outlook estructural positivo del oil & gas argentino por
Vaca Muerta (YPF, PAM, CEPU…) no era capturado de forma confiable — el path rule-based
es 100% backward-looking y el path AI dependía del conocimiento del modelo en cada call.
Esta fase hace del contexto sector-país un **input first-class, curado y auditable**.

**Arquitectura (espejo de MoatAnalyzer: base determinística + AI opcional cacheada):**

- **`analysis/tailwind.py` (nuevo)** — `TailwindDetail` + `TailwindAnalyzer`:
  - `analyze(symbol, sector, country, industry)` — siempre rápido, sin API. Matching
    contra datos curados con precedencia ticker > (industria, país) > (sector, país).
    Sin match / sin datos → Neutral, bonus 0 (subset estricto del comportamiento previo).
  - `analyze_with_ai(...)` — enriquecimiento cualitativo opcional (cache SQLite 30 días).
    El LLM **solo interpreta** el dato curado para la empresa concreta — nunca inventa
    colas de viento ni modifica el score. Falla → base curada intacta.
  - Funciones puras `classify_tailwind()` / `compute_tailwind_bonus()`.
- **`data/tailwinds/sector_country.json` (nuevo)** — fuente de verdad curada y editable:
  Energy+Argentina (Vaca Muerta, +8, ~10a, tickers YPF/PAM/CEPU/VIST/TGS),
  Technology+US (AI capex, +4, ~6a) y un headwind de balance
  (Utilities reguladas AR / EDN, −3, ~5a). Campo `last_reviewed` por entrada.
- **`config.py` → `TailwindConfig` / `TAILWINDS`** — thresholds Strong ≥6 / Moderate ≥3 /
  Headwind ≤−2, `bonus = clamp(score × 0.8, ±8)` (cap menor que moat: nunca domina),
  `optimizer_er_tilt=0.05` (≤±0.9% anual), TTL cache AI 720h, master switch `enabled`.

**Integración pipeline (fluye a todo el sistema):**

- `analysis/fundamental.py` — campos `tailwind_score/bonus/classification/detail` en
  `FundamentalResult`; `adjusted_score` ahora suma `tailwind_bonus` (clamp [0,100]).
- `analysis/strategy.py` — rationale (Strong) / risks (Headwind) en `Decision` rule-based.
- `portfolio/optimizer.py` — `TickerAllocation` extendido (defaults backward-compat),
  tilt explícito pequeño en `_expected_returns`, nota 🌬️/🌪️ en el "why" del core.
- `data/plan_store.py` — `from_session` persiste tailwind en allocation **solo cuando es
  material** (snapshots viejos y tickers Neutral quedan byte-idénticos).
- Prompts (`analysis/prompts.py`) — `_tailwind_context_block()` en equity decision,
  línea `tailwind=` en holdings del optimizer advice, sección "COLAS DE VIENTO" en
  `plan_level_narrative_prompt`, y nuevo `sector_country_tailwind_prompt` (enriquecimiento).
  Regla en todos: dato curado = fuente de verdad, el LLM no inventa.

**UI:**

- `shared.py` → `tailwind_badge()` / `_tailwind_badge_html()` (🌬️ fuerte · 🍃 moderada ·
  🌪️ headwind) + columna "Viento" en filas del screener.
- Screener: columna "Viento" + nota al pie. Stock Analysis: expander dedicado
  (badge, rationale curado, durabilidad, efecto en score, match, AI reasoning,
  disclaimer "outlook a fecha de curaduría, no garantía"). Visible también sin AI.
- Optimizer: columna "Viento" en la tabla de asignación + resumen de tailwinds materiales.
- Mi Plan: sección "🌬️ Factores estructurales de sector-país" en el visor del snapshot.

**Guardrails conservadores:** sin datos curados / todo Neutral ⇒ números idénticos al
pre-feature en todos los flujos; bonus estrictamente capped; todo configurable solo via
`config.py` (apagable con `TAILWINDS.enabled=False`); AI nunca es el motor.

- Tests: `tests/test_tailwind.py` (nuevo, **40**) — thresholds y caps, precedencia de
  matching, neutral para pares no cubiertos, archivo ausente/corrupto, config override,
  AI graceful failure + cache + score inmutable, prompts, rationale/risks, tilt del
  optimizer (chico y acotado), dicts legacy sin claves, snapshot capture + roundtrip +
  backward compat.

Suite total: **320 pasando** (0 regresiones).

**Criterio de éxito:** quien analiza u optimiza una cartera con YPF/PAM ve un factor
"Argentina Energy structural tailwind" consistente, explicable y auditable influyendo
en scores, sizing y narrativas — con o sin AI — mientras el path sin tailwinds queda
estrictamente intacto.

---

## Fases completadas (históricas)

---

## Fases completadas (en orden cronológico)

### Fase 1 — Base (commit 68d6a00)
Proyecto inicial: análisis fundamental 0–100, análisis técnico, decision engine rule-based, dashboard Streamlit, portfolio tracker, asset allocation.

### Fase 1.5 — Consistency + Piotroski (commits fa4b29b, 8225b43)
- `analysis/scoring.py`: Consistency Score (0–15) + Piotroski F-Score (0–9, verdadero YoY)
- `analysis/fundamental.py`: campos `consistency_detail`, `piotroski_detail` en `FundamentalResult`
- Dashboard: expanders con sub-scores F1–F9 y detalle de consistency

### AI Integration — capa de decisión (commits a2ac30a → f5c6434)
Refinamiento posterior: salida estructurada `macro_factors` (además del texto libre en reasoning) para contexto macro en prompts de equity/crypto moat y decision. Ver CONTEXT.md §9.
- `analysis/ai_analyzer.py` ✅ — `AIAnalyzer` reemplaza `RetirementStrategy.decide()` cuando AI está habilitado
- `config.py` → `AIConfig` (provider / model / api_key / enabled / use_in_screener)
- `analysis/strategy.py` → `full_analysis(symbol, ai_config=None)` — orquesta rule-based o AI
- `dashboard/app.py` → Settings con selector de proveedor + Decision tab con razonamiento AI
- Proveedores soportados: Claude (Anthropic), GPT-4o (OpenAI), Grok (xAI via Hermes OAuth), Nous Research

### Fase 2 — Backtesting Engine (commits 25d3dab, 4151937, da1a0b4)
- `analysis/backtesting.py` — equity curve, drawdown, Sharpe, Sortino, Calmar
- Rebalanceo configurable: anual / trimestral / mensual / buy-and-hold
- Dashboard página "📊 Backtesting" con charts interactivos, scatter score↔CAGR y descarga CSV

### Fase 3 — Economic Moat (commits 9b2ed74, 626ffed)
- `analysis/moat.py` — `MoatAnalyzer`: cuantitativo (0–12, siempre) + AI cualitativo (0–8, cacheado 7 días)
- Clasificación: Wide ≥14 / Narrow ≥8 / Minimal ≥4 / None
- `FundamentalResult` enriquecido: `moat_score`, `moat_bonus`, `moat_classification`, `moat_detail`
- `adjusted_score` = base + consistency + piotroski_bonus + moat_bonus (cap 100)
- Dashboard: badge HTML con colores, progress bars por dimensión, tooltips
- `docs/moat_methodology.md` — metodología, umbrales, ejemplos reales, limitaciones

### Fase 4 — Portfolio Optimizer (commits 1bc1778, 67d4950, 1de3a63, 050b15c)
- `portfolio/optimizer.py` — Mean-Variance (scipy SLSQP) + 3 perfiles de riesgo
- Perfiles: Conservador (vol≤12%, div≥3.5%), Moderado (vol≤18%, div≥2.5%), Agresivo (vol≤25%, div≥1.5%)
- Expected return proxy: `score_weight*(score/100*0.18) + div_weight*(yield/100) + moat_weight*(moat/20*0.05)`
- Fallback score-weighted cuando SLSQP es infeasible, con warnings específicos por constraint violado
- ARS risk discount: 0.85× en composite score para ADRs argentinos (perfil conservador/moderado)
- Monte Carlo Efficient Frontier: 300 carteras aleatorias coloreadas por Sharpe
- Dashboard página "📈 Optimizer": 4 tabs (Cartera, Frontier, Métricas, Rebalanceo)
  - **Cartera**: bar chart coloreado por Score Ajustado + línea de pos. máx, tabla con ProgressColumn, sector donut + top-10 pie
  - **Frontier**: scatter Monte Carlo + línea roja vol-ceiling del perfil + estrella azul portfolio óptimo
  - **Métricas**: tabla de estadísticas + compliance badges ✅/❌ por constraint + sector bars con colores
  - **Rebalanceo**: waterfall chart Δpeso + tabla buys/sells/holds filtrada por ≥0.5%
- Session-state caching: análisis de 38 tickers cacheado; cambio de perfil es instantáneo sin re-análisis
- Delta banner al cambiar de perfil: muestra Δretorno, Δvol, ΔSharpe, ΔDivYield + top-6 position movers
- `config.py` → `ProfileConfig`, `OPTIMIZER_PROFILES`, `OptimizerConfig`

---

## Archivos principales

| Archivo | Rol |
|---|---|
| `analysis/fundamental.py` | Score 0–100, llama a scoring y moat |
| `analysis/scoring.py` | Consistency Score + Piotroski F-Score |
| `analysis/moat.py` | Economic Moat cuantitativo + AI |
| `analysis/ai_analyzer.py` | AI decision layer (reemplaza rule-based) |
| `analysis/backtesting.py` | Motor de backtesting histórico |
| `analysis/strategy.py` | `full_analysis()` orquestador |
| `portfolio/optimizer.py` | Mean-Variance optimizer + 3 perfiles |
| `dashboard/app.py` | UI Streamlit: 18 páginas (menú por intención; 3 solo en DEV_MODE) |
| `config.py` | AIConfig, MoatConfig, BacktestConfig, ProfileConfig, OptimizerConfig |
| `docs/moat_methodology.md` | Documentación del moat |
| `docs/ROADMAP.md` | Estado del proyecto y fases completadas |
