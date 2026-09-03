# Estado del Proyecto — Retirement Advisor

> **Rol: `historical-plan`. Este archivo es un diario de fases ya shipeadas, no un backlog.**
> Lo que falta hacer vive en [`BACKLOG.md`](BACKLOG.md), priorizado y verificado
> contra el código. Cuando una fila del backlog se cierra, se muda acá con su commit.

## ✅ Todo implementado y en producción (GitHub main)

Este plan describe trabajo **ya completado**. El plan original (AI integration) fue implementado junto con las Fases 1.5, 2 y 3.

---

## N3 — Tema Streamlit declarado (2026-09-01)

No había `.streamlit/config.toml`, así que el dashboard heredaba el default de
Streamlit y `run.sh` mandaba usage stats (Docker ya los apagaba por env).
Tema dark con contraste cuerpo ≥ 4.5:1, paleta fija, `gatherUsageStats = false`.
Sin toggle en runtime ni paleta Plotly. Locked por
`tests/test_streamlit_theme_contract.py`.

---

## N2b — El adapter de yfinance no es un segundo fetch (2026-09-01)

La fila pedía «fallback de fetch a SEC/FMP». Medida, SEC no habla el idioma del
scorer (cuatro hechos canónicos vs DataFrames de estados) y la reconciliación
**ya** llama a SEC en paralelo. El defecto que sí estaba: `YFinanceSource`
importaba `get_financials` adentro del método, así que un miss de `analyze()`
pagaba otro ciclo de retry — 7 `Ticker` donde correspondían 4.

El adapter pasa a leer la caché que el fetcher ya llenó (`FETCH.adapter_reads_cache_only`).
Miss → `{}` , no red. Scoring sigue siendo yfinance. Si yfinance no aportó
estados y SEC sí, el badge nombra las dos patas y **no** sube de `poor`.
`ENGINE_VERSION` no se bumpea. Locked por `tests/test_fetch_fallback_oracle.py`.

---

## U7-2 — Fuente vacío es ninguna fila, no todas (2026-09-01)

Vaciar el multiselect «Fuente» en Track Record mostraba **todas** las filas
porque el filtro vivía detrás de `if _picked:`. Ahora `filter_by_sources`
trata una lista vacía como cero filas; `None` (el widget no se dibujó) sigue
mostrando todo. Locked por `tests/test_track_record.py`.

---

## U7-1 — preset_gap compara contra la corrida, no contra el widget (2026-09-01)

`preset_gap` se reevaluaba en cada rerun contra los widgets. Sacar un valor a
mano disparaba «ese filtro no se aplicó», que es falso: el usuario aplicó un
filtro custom. Ahora compara el preset contra las **opciones que la corrida
puede ofrecer**. El caption solo sale cuando el preset nombra un valor que
ningún ticker de esta corrida carga. Locked por `tests/test_ranking.py`.

---

## U5-19 — Π es excess; las views q son totales (2026-09-01)

`implied_equilibrium_returns` documentaba Π como "CAPM equilibrium excess
returns" y las views `q` que le pasa el optimizer son retornos totales (el
proxy de score + dividendo). Se admitió en el docstring; no se restó Rf de
`q`. Ningún número se movió.

---

## U3-1b — Pendiente desconocida no es cero (2026-09-01)

Se dejó afuera de U3-1 para no mezclar dos campos en un PR de tipos.
`sma200_slope_pct` era `float = 0.0`, así que "no hay ventana" y "la media está
plana" eran el mismo valor. El gate D15 (`above_sma200 is True or slope >= 0`)
concedía el bonus de sobreventa a un ticker cuya pendiente nadie midió — y
`None >= 0` es `TypeError`, así que el default 0.0 no era inocente.

Misma forma que U3-1: `Optional[float] = None`; unknown no suma ni resta.
La ventana SMA no se movió (U1-3). `ENGINE_VERSION` no se bumpea: el técnico
no entra a μ ni al Monte Carlo. Locked por `tests/test_trend_unknown_oracle.py`
y `tests/test_technical_d15.py`.

---

## N7 — El dividendo de un fund no se muestra sobre 10 (2026-09-01)

Apareció midiendo U5-8. La dimensión reparte 4 + 3 + 3 = 10 (yield, payout,
racha) y `payoutRatio` está ausente en 13 de 13 funds cacheados y presente en
130 de 130 equities, así que los 3 del payout son inalcanzables para un fund.
La ficha mostraba igual «Dividend x/10» porque el `else` de Stock Analysis
separaba cripto del resto, no fund de equity.

Se cerró el rótulo, no el scorer: `format_dividend_score` / `dividend_score_max`
en `data/product_ux.py` (equity 10, fund 7). `_score_dividends` no se tocó —
0 scores se mueven. Locked por `tests/test_dividend_scale_label_contract.py`.

---

## N8 — La palanca indexa el gasto, no la inflación (2026-09-01)

Abierta al cerrar U4-3. La palanca del tornado bumpeaba `withdrawal_growth_rate`
— cuánto crece el gasto (o el aporte) cada año — y se llamaba «Inflación».
Medido: en acumulación con aportes el P10 **sube** al subir la palanca, porque
`_apply_cash_flows` indexa los depósitos con el mismo número. Eso no es «la
inflación te ayuda»; es un rótulo que promete un shock de retorno real que el
Monte Carlo no calcula.

Se cerró como U1-1 / U1-3 / U6-1: **se corrige lo que se lee, no lo que se
calcula**. Etiqueta canónica «Indexación del gasto» en `data/product_ux.py`.
Los identificadores (`inflation`, `inflation_hot`, `inflation_delta_pct`)
conservan el nombre legacy. `portfolio/monte_carlo.py` no se tocó;
`ENGINE_VERSION` no se bumpea. El signo invertido del flujo **sigue**; deja de
llamarse inflación. Modelar inflación en el retorno real es U6-2.

`constant_pct` sigue en «no aplica» (U4-3). Locked por
`tests/test_indexation_label_contract.py`.

---

## U0-3 + N4 — El backlog deja de mentir sobre lo que está abierto (2026-09-01)

U0-3 decía: CONTEXT §8 (a)(b) describen como abiertos dos defectos ya cerrados.
Medido el 2026-09-01, (a)(b)(e) **ya** estaban marcados cerrados. Lo que seguía
abierto en esa viñeta era **(c) ATR/ADX** y **(d) U3-1**, los dos shipeados
(U3-2, U3-1). Misma clase de defecto, otro par. Se cerró actualizando la viñeta,
no tocando código.

N4 pedía meter `auditoria_remediacion_unificada.csv` en el repo **o** versionar
su estado en BACKLOG. Se eligió el OR: el CSV se queda en Downloads (69 filas de
un momento, sin oráculo) y `docs/BACKLOG.md` es la fuente de «qué está abierto».
La foto 2026-08-28 (39/30/9) se reemplazó por un recuento contra el código de
hoy y una tabla de abiertas que un agente puede leer sin cruzar ROADMAP.

Ningún número, umbral ni fórmula se movió.

---

## N9 — La regla por edad gobierna el tramo defensivo, no el de bonos (2026-09-01)

La fila salió de U5-7, que arregló la etiqueta del perfil y dejó el buffer
donde estaba: *"el buffer de 5 % de cash se talla **del tramo de bonos**, así
que la regla que `recommended_bond_pct` enuncia nunca es la que la pantalla
muestra: a los 30 un Conservador lee 25 % donde la regla dice 30 %"*. Se difirió
con una razón explícita — mover el buffer corre los números del usuario default.

### La fila describía el defecto correcto y le erraba al tramo

El primer paso fue medir si seguía siendo cierta, y no lo era. La regla **sí** se
cumple, sobre el tramo **defensivo**:

```
bonds_pct + cash_pct == max(recommended_bond_pct(age, perfil), CASH_BUFFER_PCT)
```

**0 violaciones** sobre los 3 perfiles × edades 20–80, y también debajo del rango
de los sliders. A los 30 un Conservador lee 25 % en bonos + 5 % en efectivo, y la
regla dice 30: los dos números son correctos y **ninguna de las dos filas es la
regla por separado**. El tramo nunca estuvo corto — estaba nombrado por su mitad
más grande.

Eso cambia la banda del arreglo. No es una fórmula equivocada sino un enunciado
equivocado sobre una fórmula correcta, así que el remedio es el de U1-1, U1-3 y
U1-4: **se corrige lo que se lee, no lo que se calcula**. Verificado con diff
byte-idéntico de las 183 filas (3 perfiles × 61 edades) que produce `advise()`:
**ningún número, banda, offset ni fórmula se movió**, que es exactamente la razón
por la que U5-7 lo había diferido.

### El `max(…, 0)` no era una guarda

Parecía una guarda defensiva contra negativos y es un **piso de liquidez**: el
buffer son 5 pp fijos, no una porción del tramo, así que un inversor cuya regla
cae por debajo igual lo tiene. Agresivo a los 13: regla 3, defensivo 5. Los
sliders arrancan en 20, así que sólo se llega por la función — pinneado para que
nadie lo "arregle" y convierta el piso en una contradicción silenciosa.

### Una sola casa para el buffer

El 5 vivía escrito dos veces: el default de `AllocationAdvice.cash_pct` y el
`bond_pct - 5` que lo tallaba. Dos copias del mismo número son lo que deja
enunciar la regla en un lado y contradecirla en el otro — el mismo defecto de
config duplicada que U5-9 y U5-18c. Ahora es `config.CASH_BUFFER_PCT`, y un test
falla si el literal vuelve a `allocation.py`.

### Qué cambió en pantalla

Las dos superficies muestran el defensivo con su split debajo, y la copy sale de
`data/product_ux.py` (`DEFENSIVE_SLEEVE_LABEL`/`_SHORT`/`_HELP`,
`defensive_sleeve_caption`), no de cada página por su cuenta — que es como el
número de bonos terminó con un caption que hablaba de la regla entera.

`AllocationAdvice.defensive_pct` existe para que las dos pantallas lean el
número de un solo lugar en vez de sumarlo cada una.

### El barrido encontró una tercera superficie

`tests/test_defensive_sleeve_contract.py` sigue el patrón de U1-1: oráculo desde
la definición (la regla se recalcula en el test desde `bond_age_offset_pp`, no se
le pregunta al motor), diferencial sobre el offset —afirmar `defensive == 30.0`
sobreviviría a una perilla desconectada—, guard del piso, guard del literal
único, y barrido de etiqueta sobre las tres capas: los `.py` que renderizan copy,
`config.py`/`portfolio/allocation.py`, y el markdown vivo catalogado en
`INDEX.md`.

Ese barrido encontró que `docs/architecture.md` seguía diciendo
`bond_pct = min(age, 80)` — stale por partida doble: sin el offset por perfil que
introdujo U5-7, y nombrando el tramo equivocado. Los roles históricos
(`ROADMAP`, `AUDIT_*`, `brainstorm`) quedan afuera a propósito.

### Lo que deliberadamente no hizo

Mover el buffer al tramo de acciones quedó **descartado**, no pendiente: haría
que «Bonos» mostrara literalmente el número de la regla, pero bajaría 5 pp el
equity de todo usuario default a toda edad y dejaría el defensivo en regla + 5 —
la misma contradicción con el signo invertido.

`recommended_bond_pct` conserva el nombre legacy, igual que `above_sma200`
(U1-3) y `_wacc_proxy` (U1-4).

---

## U5-7 — La asignación por edad no leía el perfil del usuario (2026-09-01)

El backlog la tenía como higiene: *"el docstring promete «Conservative: age /
Aggressive: age − 10»; la función no toma perfil y siempre devuelve
`min(age, 80)`"*. Un docstring desalineado, bloque 4, no mueve un número.

Movía dos, en dos pantallas.

### La fila describía la mitad chica

`recommended_bond_pct` no era decorativa: `AllocationAdvisor.advise()` la usa
para fijar el trío bonos/equity/cash, y **dos superficies** lo leen —
`4_Allocation.py` y el bloque "Asignación por edad" del Optimizer. Como
`advise()` no tomaba perfil, todo el mundo recibía la senda conservadora:

| edad | equity Conservador | equity Moderado | equity Agresivo |
|---|---|---|---|
| 30 | 70 % | 75 % | **80 %** |
| 45 | 55 % | 60 % | **65 %** |
| 60 | 40 % | 45 % | **50 %** |
| 70 | 30 % | 35 % | **40 %** |

Antes, un Agresivo veía la primera columna: **10 pp menos de equity a toda
edad**, plano —el tope de 80 no muerde antes de los 90— y arrastrando la
sub-asignación, porque US/internacional/REIT son porcentajes de `equity_pct`.

El perfil nunca faltó. El onboarding **pregunta** la tolerancia al riesgo y
`data/preferences.py` la persiste en `default_profile`, con su propio comentario
diciendo *"Risk tolerance is the single source of truth for the optimizer
profile"*. Los dos call sites ya lo tenían en la mano: `4_Allocation.py` llamaba
a `get_user_prefs()` para sacar la edad y descartaba el resto, y en el Optimizer
`profile_key` estaba viva 24 líneas más arriba de la llamada.

### El segundo agujero, que la fila no menciona

El mismo `advise()` calificaba la concentración contra los topes **globales** de
`STRATEGY` (8 / 25 / 10) mientras el Optimizer calificaba contra los del
**perfil**. Medido:

    NVDA al 15 % con perfil Agresivo   → "⚠️ reducir a menos de 8%"   (tope real: 18)
    NVDA al 15 % con perfil Agresivo   → sin advertencia               (después)

Dos pantallas, una cartera, consejos contradictorios: Allocation le decía al
usuario que deshiciera la posición que el Optimizer le acababa de construir
dentro de su propio límite. El Conservador tenía la imagen espejo, sub-avisado
en sector (25 % global contra 20 % de su perfil).

Y `5_Optimizer.py` cerraba el círculo con una caption que decía *"Usá este marco
para elegir el perfil del optimizer (más bonos → Conservador; más equity →
Agresivo)"* sobre números que no se movían al cambiar el perfil.

**Cero tests.** Ni una línea en `tests/` mencionaba `AllocationAdvisor`,
`recommended_bond_pct` ni `bonds_pct`. Por eso el docstring pudo prometer
durante meses una regla que nadie implementó.

### El arreglo

`bond_age_offset_pp` entra en `ProfileConfig` (0 / −5 / −10) junto a
`risk_aversion` y los topes de concentración. **No reabre la auditoría D3**: D3
prohibió que el perfil tocara μ porque el retorno de un activo no depende de
quién lo mira —es propiedad del activo—; una senda de bonos por edad es lo
contrario, propiedad del inversor, que es justo lo que esa dataclass guarda.

El docstring nombraba dos reglas para un producto de tres perfiles. Moderado
queda en `age − 5`, el punto medio, que mantiene el orden monótono con
`risk_aversion` (4,0 / 2,5 / 1,5) en vez de inventar una tercera forma.

`advise()` toma `profile` y lo usa en las dos mitades. Sin perfil devuelve la
regla conservadora, así que ningún caller viejo cambia de comportamiento.

`tests/test_allocation_profile_oracle.py` (220 casos) es **diferencial**, no
literal — la lección explícita de `test_config_single_home_oracle`: afirmar
`bonds_pct == 45.0` lo pasaría un fix que mueve el número a config y después lo
ignora. El test ancla mueve `bond_age_offset_pp` y exige que la asignación se
mueva con él. Incluye una guarda anti-contradicción: para los tres perfiles, el
umbral con el que `advise()` advierte tiene que ser el `max_position_pct` de ese
perfil, así que Allocation no puede volver a contradecir al Optimizer.

`ENGINE_VERSION` **no** se bumpea: `AllocationAdvisor` tiene exactamente dos
consumidores y ninguno está en el camino de μ ni del Monte Carlo.

### Números que se movieron, incluido uno que nadie pidió

Un usuario que nunca tocó su perfil queda en Conservador, cuyo tope de sector es
**20 %** contra el 25 % global que `advise()` usaba antes. Puede ver una
advertencia de sector nueva sin haber cambiado nada. Es el defecto que la fila
pedía arreglar, no un efecto colateral, pero va anotado porque se ve.

### Lo que deliberadamente no hizo

El buffer de 5 % de cash se sigue tallando **del tramo de bonos**, así que la
regla que `recommended_bond_pct` enuncia nunca es la que la pantalla muestra: a
los 30 un Conservador lee 25 % donde la regla dice 30 %. Acá se arregló la
etiqueta —la función devuelve la regla y `advise()` documenta el tallado— y no
la fórmula, porque moverla corre los números del usuario default y es otra
decisión de producto. Abierta como **N9**.

---

## N6c — La suite también escribía en la tabla de alertas (2026-09-01)

Hermana de N6: mismo singleton de módulo alcanzable desde la suite, otra tabla,
dos meses antes. Lo que la hace valer no es el daño —es chico— sino que la fila
se equivocaba en las tres cosas que había que saber para arreglarla.

### La fila decía tres cosas y ninguna era cierta

| lo que decía | lo que había |
|---|---|
| «escritas cuando algún test usó el `alert_store` real» | ningún test lo hace hoy: los seis sitios usan `AlertEngine.__new__` o un doble |
| implícito: la escribió el camino del engine | la escribió `AlertStore.set_cooldown()` **directo**, sin pasar por el engine |
| implícito: se cierra copiando el bloque de N6 | copiarlo da un **verde falso** |

**Ningún test la escribió.** `test_alert_engine.py`, `test_sorr_oracle.py`,
`test_plan_health.py`, `test_product_ux.py` y el oráculo de N6 construyen el
engine con `AlertEngine.__new__(AlertEngine)`, que saltea `__init__`, y le
asignan un doble a mano; `test_scheduler.py` parchea la clase entera. Y `TEST1`
no aparece en ningún commit de código: `git log -S "TEST1" --all` sólo devuelve
los dos commits de *docs* que lo mencionan en `BACKLOG.md`. La aislación existía,
pero era un ritual de cuatro líneas repetido en cinco archivos, no una garantía.

**No la escribió el engine.** `alert_cooldowns` tenía 2 filas y
`alert_snapshots` 0. `_fire` (`engine.py:585-586`) escribe cooldown **y**
history, y `run()` guarda un snapshot por símbolo antes de poder disparar nada;
no hay en el repo ningún camino que borre snapshots. Con snapshots en 0 la firma
no cierra con `AlertEngine.run()`. Entró por el camino corto, que es el que la
fila no miraba.

### La trampa: la forma de N6 no transfiere

N6 cerró el track record **reemplazando** el singleton del módulo. Acá eso pasa
en verde con la fuga abierta, porque `alerts/engine.py:137` liga el store como
**default de argumento**:

```python
def __init__(self, store: AlertStore = alert_store, ...)
```

Ese default se evalúa al importar y se queda con **el objeto**, no con el
nombre. Medido: después de `alerts.store.alert_store = AlertStore()`,
`AlertEngine.__init__.__defaults__[0] is orig` sigue dando `True`, apuntando a
`data/db/retirement_advisor.db`. Es la misma clase de trampa que el comentario
de N6 describe para el *collection*, un nivel más adentro.

Por eso el `conftest.py` **muta el store en el lugar** —le reapunta `_engine` y
`_Session` al mismo objeto— en vez de reemplazarlo. Así queda sano todo el que
ya tenga una referencia, default de argumento incluido.

### El arreglo

- `alerts/store.py` — `AlertStore.__init__` toma `db_path` y guarda
  `self._engine`, el mismo idioma que `TrackRecordStore` (`track_record.py:342`).
  Sin eso no se puede ni liberar el archivo del usuario ni escribir el oráculo:
  el engine era una variable **local**, alcanzable sólo por
  `_Session.kw["bind"]`, detalle privado de SQLAlchemy. Cambio compatible —
  `AlertStore()` sigue resolviendo a `DB_PATH`.
- `tests/conftest.py` — redirección en tiempo de import al lado de la de N6,
  mutando en el lugar, con el comentario que explica por qué acá no alcanza con
  reemplazar. Sin ese comentario el próximo lector copia el bloque de arriba y
  rompe la garantía sin que nada se ponga rojo.
- `scripts/migrations/purge_test_alert_rows.py` — dry-run por default, borra con `--apply`.

**Acá borra y en N6 se marcó.** No es incoherencia: aquellas filas tenían
outcomes puntuados y lecturas que preservar, así que marcar era reversible y
borrar no. `alert_cooldowns` sólo se consulta por `key` exacta desde
`is_on_cooldown`, y un cooldown de un símbolo que no existe no alimenta ninguna
lectura ni ninguna métrica: no hay nada que un marcador preservaría.

### El oráculo, y el rojo que reprodujo el defecto en vivo

`tests/test_alert_store_isolation_oracle.py` fija la propiedad estructural —bajo
pytest ningún `AlertStore` alcanzable resuelve a `DB_PATH`— en vez de contar
filas, por las mismas razones que el de N6.

Correrlo en rojo, antes del arreglo, **agregó una tercera fila a la base del
usuario** (`AlertType.SIGNAL_CHANGE:TEST_ORACLE`, 2026-09-01): el defecto
reproducido en vivo, cuatro meses después de las dos originales. Se corrió sobre
un backup y se restauró; el hash volvió a `046109…602a`. Después del arreglo, la
suite completa deja la base **byte a byte idéntica**.

Mutación: cuatro formas de romperlo, y qué las ve.

| mutante | lo ve |
|---|---|
| reemplazar el singleton en vez de mutarlo (la forma de N6) | `test_the_engine_default_is_not_the_users_database`, `test_constructing_an_engine_writes_nothing_to_the_users_database`, `test_no_imported_module_holds_a_store_on_the_users_database` |
| mutar el objeto pero no el `DB_PATH` del módulo | `test_the_module_default_is_not_the_users_database` |
| `set_cooldown` deja de escribir (verde vacío) | `test_set_cooldown_never_reaches_the_users_database` |
| un caller nuevo que se ligue el singleton al importar | `test_no_imported_module_holds_a_store_on_the_users_database` |

### Lo que deliberadamente no hizo

- **No unificó los cinco rituales de `__new__`.** Con el conftest cubriendo el
  store, esos dobles pasan a ser conveniencia y no aislación. Consolidarlos es un
  PR de tests aparte.
- **No tocó `alerts/engine.py:137`.** Inyectar el store explícitamente sería más
  limpio, pero es el trade-off que N6 ya resolvió al revés y con razones
  escritas: cubre un caller y hay que acordarse en cada uno nuevo.

---

## U4-3 — El cero no era de la palanca, era del caso base (2026-08-31)

Cierra la oleada 4 entera. La fila decía: *«La palanca "Inflación" del tornado
bumpea `withdrawal_growth_rate`; sin retiros activos el swing es exactamente 0 y
el rótulo queda igual»*.

Medido offline sobre 5 tickers cacheados (AAPL/MSFT/JNJ/PG/XOM equiponderados,
10y semanal, seed 42, `n_sims=2000`, drags 0,60 %, inflación 3 % ± 1 pp), sin red
y con la palanca corrida por cada método de retiro:

| plan | swing Inflación (P10) | |
|---|---|---|
| acumulación, sin retiros ni aportes | **0,00 exacto** | la fila acierta |
| retiro `fixed_real` 40k/año | 1.717.777 | correcto |
| retiro `guardrails` 4 % | 296.017 | correcto |
| retiro `constant_pct` 4 % | **0,00 exacto** | **hay retiros y el swing es 0** |
| acumulación con aporte 12k/año | 112.059 | **signo invertido** |

### La fila tenía razón en el síntoma y no en la causa

La condición no es «no hay retiros», es «el método de retiro no indexa el gasto».
`constant_pct` toma un porcentaje del **pozo actual**, así que su `decide` nunca
lee `inflation_rate` (`portfolio/decumulation.py` ~:389) — y es una opción que el
usuario elige en el panel (`dashboard/shared.py:1082`). Arreglar «el caso sin
retiros» habría dejado el defecto intacto para un jubilado.

### El defecto que pesaba no estaba en la fila

`base_params` de `_render_sensitivity_lab` **no pasaba `annual_contribution`** y
`_sensitivity_run_fn` la defaultea a 0. La variable estaba resuelta doce líneas
más arriba en la misma página (`:253`, vía `contribution_inputs`) y la corrida
principal sí la usaba (`:368` — eso es U4-5, cerrada ese mismo día).

    caso base P10   sin el aporte      490.275
    caso base P10   con 12k/año      1.234.907   (2,52x)

No es sólo la palanca de inflación: **las cuatro palancas y los cuatro escenarios
se medían contra un plan que no era el del usuario.** Es exactamente el defecto
que U4-5 cerró en la pestaña de arriba, todavía abierto una sección más abajo de
la misma pantalla. El contrato de U4-5 no lo agarró porque mide los valores
pasados como `annual_contribution=` en formato kwarg, y el laboratorio arma un
**dict**: la regex nunca lo miró.

### Por qué los dos van en el mismo PR

Están acoplados: arreglar el aporte **solo** empeora la pantalla. Con aportes la
palanca de inflación deja de dar 0 y pasa a dar el signo invertido — y un número
al revés se lee peor que un cero.

### «No aplica» se mide, no se enumera

`sensitivity._applies`: una palanca no aplica cuando mover el supuesto a su valor
bajo y a su alto deja idénticas las **cuatro** métricas de `METRIC_KEYS`. El
laboratorio no necesita saber qué método de retiro indexa el gasto —`constant_pct`
y la acumulación pura salen solos de esa comparación— y sigue siendo correcto
cuando se agregue otro método.

Sobre las cuatro y no sobre la graficada: un plan solvente da `prob_ruin_pct = 0`
en todas las palancas, y el criterio angosto habría marcado como inaplicables a
tres palancas vivas. Es el test que hay que acertar para no marcar de más.

La fila **sigue en el eje**, rotulada «no aplica a este plan», con el hover
explicando por qué y el pie del gráfico aclarando que no es un cero medido.
Sacarla escondería que el motor consideró el supuesto: el usuario no podría
distinguir «no aplica» de «se olvidaron de esta palanca». La tabla de escenarios
recibe el mismo trato — decía «Δ vs base $0», que es la misma afirmación.

### Lo que deliberadamente no hizo → N8

`withdrawal_growth_rate` no es inflación, es indexación del gasto. El signo
invertido con aportes sale de `_apply_cash_flows` (`monte_carlo.py:803`), que
hace crecer los depósitos con el mismo número que la palanca mueve. **Este PR lo
destapa**: antes lo tapaba el cero del caso base sin aportes. Corregirlo pide que
la palanca toque el retorno real y no sólo el flujo, lo que mueve el Monte Carlo
y obliga a bumpear `ENGINE_VERSION` (U6-2). Abierto como **N8** en el backlog,
con la medición ya hecha.

`ENGINE_VERSION` no se bumpeó acá: no se tocó `portfolio/monte_carlo.py`. Misma
clase de cambio que U4-5 (`a7db06f`), que tampoco lo bumpeó.

### Un error propio, corregido antes de reportar

La primera corrida de la medición dio swing 0 también para `fixed_real`, lo que
habría sido un hallazgo falso mucho más grande. La causa era mía:
`WithdrawalStrategy.coerce` (`decumulation.py:145-147`) filtra en silencio las
claves que no reconoce, y yo le pasé `{"method": ..., "initial_rate_pct": ...}`
en vez de los nombres reales de los campos. Devolvió un `fixed_real` con
`annual_amount=0` — o sea, un plan que no retiraba nada. Queda anotado porque le
pasa igual a un plan guardado con una clave mal escrita: se convierte en «no
retira nada» sin avisar, en vez de fallar.

**Commits:** `ef66599` (oráculo, 7 de 49 en rojo), `59a0058` (fix).

---

## U5-18d — Las 53 filas de fixture salen del track record (2026-08-30)

### Qué se decidió y por qué no fue lo mismo que U5-18b

N6 cortó la sangría; quedaban **53 filas de 470** que la suite había escrito y
**11 outcomes** puntuados sobre ellas. U5-18b había resuelto un caso parecido
—deduplicar en lectura, no borrar— con el argumento de que «el motor emitió esas
filas; que las haya emitido por un bug no las vuelve falsas, las vuelve el
registro de un bug».

**Ese argumento no aplica acá, y la palabra que lo decide es *emitió*.** Las 80
duplicadas de U5-18b salieron de `full_analysis` sobre datos de mercado reales,
en un momento real, y el usuario pudo haberlas visto: el defecto era **contarlas
dos veces**, y colapsar corrige el conteo sin editar el hecho. Acá no hay hecho.
El `adjusted_score: 72.0` es un literal en `tests/test_alert_engine.py`, la señal
salió de un `store.seed(...)` y ningún precio se consultó — por eso las 53 tienen
`price_at_rec` NULL. Colapsar no alcanzaría porque no hay una fila legítima
detrás. El log de recomendaciones no es donde se documenta un bug de testing; eso
vive en git.

**Pero eso tampoco autoriza borrar.** Se marcan: `source='test_fixture'` sobre 53
ids, y las lecturas las excluyen. Mientras nada se borre, un error en la lista es
reversible y la contaminación sigue siendo medible.

### La regla: se enumeran los ids, nunca se shipea el patrón

Las 53 comparten rationale (`"Alerta de oportunidad: entró con señal …"`),
`source='rule_based'` y `price_at_rec` NULL, así que un `WHERE` con esa firma
parece la solución limpia. Es la peor posible:

- El rationale lo escribe `alerts/engine.py:521` y el source sale de `:528`. Los
  dos son **código de producción**: una corrida real del alert engine produce una
  fila **byte-idéntica** en las tres columnas, el precio NULL incluido (el loop de
  alertas no tiene precio, y el scorer lo resuelve en memoria sin persistirlo).
- `source='rule_based'` tampoco distingue: `2_Stock_Analysis.py:180` lo escribe
  cada vez que el usuario analiza un ticker con la IA apagada.
- Un patrón sobre `'%Alerta%'` **ya barrería una fila real**: la id 166 (CME,
  `source=screener`), que lleva esa palabra en un rationale legítimo.

La firma acierta 53/53 **hoy** por un accidente histórico: `alert_snapshots` tiene
**0 filas**, o sea que el alert engine nunca completó una corrida real contra esta
base (un arranque en frío guarda un baseline por ticker antes de poder disparar
nada). Eso es un hecho sobre el pasado, no una regla sobre el futuro. Lo único
cierto es que el conjunto está **cerrado**: la última fixture es la id 470 y desde
PR #50 la suite no puede escribir. Un `WHERE` por patrón se dispararía solo el
primer día que el scheduler corra de verdad, sobre exactamente las filas que el
path de alertas existe para producir, y sin un error que lo avise.

### Lo que cambió, medido sobre la base

`scripts/migrations/mark_test_fixture_rows.py --apply` corrido el 2026-08-30. Nada se borró:
470 filas y 22 outcomes antes y después; sólo cambió `source` en 53 filas.

| | antes | ahora |
|---|---:|---:|
| Recomendaciones logueadas | 470 | **417** |
| Evaluadas a 30 días | 22 | **11** |
| Tasa de acierto | 68,2 % | **45,5 %** |
| Exceso medio vs benchmark | +6,29 | **+3,21** |
| equity modelo / benchmark | 2,572 / 1,124 | **0,913 / 1,031** |
| STRONG BUY | n=4, 100 %, `inconclusive=False` | **no existe** |
| BUY, exceso medio | +4,08 | **−1,40** |
| pendientes de puntuar a 30 d | 445 | **406** |

**La corrección no le baja el número al motor: le da vuelta el signo.** El
producto mostraba el modelo convirtiendo $1 en $2,57 contra un mercado que hizo
$1,12; el registro real es el modelo **perdiendo 8,7 %** mientras el mercado gana
3,1 %. Y las cuatro STRONG BUY puntuadas eran las cuatro fixtures: sacadas, no
queda ninguna — el producto presentaba como concluyente (`inconclusive=False`) una
fila cuya muestra entera era salida de un fixture.

`include_fixtures=True` devuelve el 470 / 68,2 % / 2,572 exacto: la auditoría de
lo que pasó sigue disponible, que es la razón de marcar en vez de borrar.

### Dónde va el filtro

Tres sitios de query, con `include_fixtures: bool = False`:

| sitio | por qué |
|---|---|
| `get_pending_scoring` | el único con vencimiento: impedía que las 42 restantes se puntuaran de a 3 por día hábil desde el 2026-09-08 |
| `get_scored_rows` | antes del filtro «Fuente» de la página, así `test_fixture` no llega a ninguna métrica ni aparece como opción seleccionable |
| `get_recommendations` | el titular «Recomendaciones logueadas» contaba 470 donde hay 417 |

**No se compone con `collapse_same_local_day`.** Son dos preguntas —«¿cuántas
veces se contó esto?» contra «¿esto es una recomendación?»— y fusionarlas
repetiría el pecado original de U5-18, que U5-18b tardó un PR entero en desarmar.
Un test fija la ortogonalidad en las dos direcciones.

**Los 11 outcomes no se tocaron.** Caen con su fila por el join que
`get_scored_rows` ya hacía. El precio, explícito: `select count(*) from
recommendation_outcome` sigue diciendo 22, y por eso toda lectura tiene que
joinear.

### El oráculo y la mutación

`tests/test_track_record_fixture_exclusion_oracle.py`. Los 22 outcomes medidos
entran como literales, así que los números de arriba están fijados por el test y
no dependen de la base.

| mutante | lo ve |
|---|---|
| la lista de ids reemplazada por el patrón | `test_the_decoy_row_survives` |
| sin exclusión en `get_pending_scoring` | `test_get_pending_scoring_excludes_fixtures` |
| sin exclusión en `get_scored_rows` | `test_get_scored_rows_excludes_fixtures` |
| sin exclusión en `get_recommendations` | `test_get_recommendations_excludes_fixtures` |
| la exclusión colgada del flag del collapse | `test_exclusion_is_orthogonal_to_the_collapse` |
| `!=` en vez de `is_distinct_from` | `test_a_row_with_no_source_stays_visible` |

Los dos últimos tests los escribió la mutación. El de NULL estuvo **verde por
accidente** en su primera versión: pasarle `source=None` al constructor no produce
un NULL, porque la columna tiene `default="rule_based"` y SQLAlchemy lo aplica —
hay que forzarlo con un `UPDATE`. Sin eso el mutante sobrevivía con el test puesto.

El guard AST de U5-18b detectó al script de migración como lector nuevo del log
crudo y rompió `make check`; entró al allowlist con su razón — trabaja sobre la
fila, no sobre la muestra, así que colapsar escondería filas que tiene que editar.

### Efecto colateral: una medición publicada estaba hecha sobre las fixtures

CONTEXT §8 decía «con n=4 y n=13 el ruido es ±5,5 puntos y la diferencia observada
de +6,3 es indistinguible de cero». Los tres números reproducen exacto contra la
base (n=4, n=13, +6,32) y por eso nadie lo vio — pero el grupo de STRONG BUY eran
**4 de 4 fixtures**, y el +29,0 % del rango que la misma línea citaba también. La
conclusión sobrevivió por casualidad; el enunciado honesto es más fuerte: esa
comparación **todavía no se puede hacer**. Corregido, junto con U5-1b, que citaba
«22 filas» de muestra para recalibrar el bonus de Piotroski — son 11.

### Lo que este PR deliberadamente NO hizo

Sin aviso en la UI: apenas entra el filtro el número deja de estar mal, y la
contaminación estaba en su máximo (50 % de los outcomes) y se diluye sola a ~11 %
para fin de septiembre, cuando entren las 406 filas reales pendientes. Una
superficie para una ventana de cuatro semanas es trabajo que hay que borrar
después. Y quedó abierta **N6c**: `alert_cooldowns` tiene 2 filas de `TEST1` del
2026-05-24 — misma causa, otra tabla, dos meses antes.

---

## N6 — La suite de tests escribía en el track record del usuario (2026-08-30)

### El defecto

`AlertEngine._log_opportunity` (`alerts/engine.py:512`) importa el **singleton de
módulo** `track_record_store`, que apunta a `config.DB_PATH`. El fixture `store`
de `tests/test_alert_engine.py` reemplaza el store de *alertas*, no el del track
record, así que correr la suite escribía recomendaciones reales en la base del
usuario. Apareció midiendo U5-18b.

### La fila subestimaba el daño, y del lado que importa

Decía «3 filas durante un PR, contaminación futura». Medido el 2026-08-30 sobre
`data/db/retirement_advisor.db` en read-only: **53 filas de 470 (11,3 %)**, todas
con el rationale `"Alerta de oportunidad: entró con señal …"`, `source=rule_based`
y `price_at_rec` NULL. **18 lotes en 16 días locales**, del 19 de junio al 30 de
agosto, siempre AAPL/BUY, MSFT/BUY y XOM/STRONG BUY. Un lote por día porque el
dedup de U5-18 colapsa el resto; el 23 y el 28 de agosto la suite corrió dos
veces cruzando las 21:00 local y quedaron 6 — de ahí salen 6 de los 80
duplicados de U5-18b.

**No era contaminación futura: ya estaba puntuada.** De los 22 outcomes
scoreados, 11 son estas filas.

| | n | hit rate | exceso medio |
|---|---:|---:|---:|
| lo que publica el producto | 22 | **68,2 %** | +6,29 |
| las que escribió la suite | 11 | 90,9 % | +9,36 |
| las que el motor emitió | 11 | **45,5 %** | +3,21 |

**+22,7 pp inflados a favor del motor**, sobre el único juez que el motor tiene
sobre sí mismo. Las otras 42 no cumplieron los 30 días todavía: sin cortar la
sangría el sesgo crecía solo.

**Y eran cuatro tests, no tres.** Instrumentando `log_recommendation` bloqueada:
`test_signal_upgrade_fires_alert` (AAPL), `test_surge_with_buy_signal_fires`
(MSFT), `test_new_buy_entry_fires_opportunity` y
`test_opportunity_strong_buy_with_space` (XOM). El cuarto lo colapsa el dedup del
día — por eso aterrizaban 3 filas y no 4. Y el primero no es un test de
oportunidad: es el de cambio de señal, que al cruzar a BUY dispara el path igual.
Reproducido contra una **copia** de la base: 467 → 470 corriendo sólo ese archivo.

### El arreglo (`0ef727b`, oráculo en `63d82e7`)

`tests/conftest.py` apunta el track record a `:memory:` **en tiempo de import**:
el singleton y también el `DB_PATH` del módulo, para que un caller que construya
su propio store tampoco caiga en la base del usuario.

- **Por qué no inyectar el store en `AlertEngine`.** Es más explícito, pero cubre
  un solo caller y son siete los que alcanzan el mismo singleton —
  `track_record_scorer` y `dashboard/shared.py` entre ellos, los dos con camino de
  `log_recommendation`—. Cada caller nuevo tendría que acordarse.
- **Por qué en tiempo de import y no como fixture.** Medido: con la misma
  redirección escrita como fixture autouse, la suite completa deja
  `analysis.track_record_scorer.track_record_store` apuntado a la base del
  usuario. Un fixture corre *después* de la colección, y el scorer se liga el
  singleton en su propio namespace cuando lo importan durante la colección.

### El oráculo

`tests/test_track_record_isolation_oracle.py` no cuenta filas: dentro de la misma
suite el import ya pasó, el dedup esconde todo lote posterior al primero del día,
y una escritura real dejaría el daño hecho aunque el test la detecte. Fija la
propiedad —bajo pytest ningún módulo resuelve un `TrackRecordStore` a `DB_PATH`—
y la verifica sobre el camino de producción entero, espiando a qué base habría
escrito **sin escribirla**, así que corre en rojo sin tocar nada.

Mutación: tres formas de romperlo, tres tests distintos que las ven.

| mutante | lo ve |
|---|---|
| sólo el singleton, sin el `DB_PATH` del módulo | `test_the_module_default_is_not_the_users_database` |
| la misma redirección como fixture autouse (suite completa) | `test_no_imported_module_holds_a_store_on_the_users_database` |
| `_log_opportunity` deja de loguear (verde vacío) | `test_opportunity_alert_never_resolves_to_the_users_database` |

### Lo que este PR deliberadamente NO hizo

No tocó las 53 filas ya escritas ni los 11 outcomes. Qué hacer con ellas es una
decisión aparte, abierta como **U5-18d** en `BACKLOG.md`: tiene la forma de U5-18b
con una diferencia que manda —aquellas eran recomendaciones que el motor **sí**
emitió, contadas dos veces; éstas nunca lo fueron, así que colapsar en lectura
no alcanza porque no hay una fila legítima detrás—.

`make check` y `TZ=UTC make test` en verde (2367 passed, 1 skipped), con la base
en 470 filas y 22 outcomes antes y después. La suite completa, medida contra una
copia, no escribe en ninguna otra tabla (`cache`, `alert_*`, `macro_docs` quedan
idénticas).

---

## U3-2 — ATR y ADX con el suavizado que dicen usar (2026-08-29)

### El defecto

`_atr` y `_adx` suavizaban con `ewm(span=period)`, que es `alpha = 2/(period+1)`.
Wilder —quien definió los dos indicadores— usa `alpha = 1/period`. Con el
`period=14` del módulo eso es **0,0714 contra 0,1333**: el motor promediaba con
un suavizado casi el doble de reactivo que el del indicador cuyo nombre estaba
publicando. El RSI (`technical.py:304`) ya lo hacía bien desde siempre, así que
la referencia correcta vivía en el mismo archivo, doce líneas más arriba.

### La fila citaba tres sitios; son cuatro, y uno no mueve nada

La fila decía `technical.py:329,353-358`. Verificado contra `main`:

| sitio | qué suaviza | ¿mueve el número? |
|---|---|---|
| `_atr` | el True Range publicado en `atr_pct` | **sí** |
| `_adx` TR | el denominador de las dos patas DI | **no — se cancela** |
| `_adx` +DM | la pata alcista | **sí** |
| `_adx` −DM | la pata bajista | **sí** |
| `_adx` DX | el ADX mismo | **sí** |

Dos correcciones a la fila, en direcciones opuestas. El suavizado final del DX
**no estaba en el rango citado**, y es el que produce el número que lee el gate
de `:274`. Y el del TR dentro de `_adx`, que sí estaba citado, **no puede mover
el resultado**: `DI± = 100·S(DM±)/S(TR)` y `DX = 100·|DI⁺−DI⁻|/(DI⁺+DI⁻)`, así
que `S(TR)` es factor común y se va — verificado, bit-idéntico en tres de las
cuatro series de prueba y a 1e-15 en la cuarta. Se corrigió igual, porque es la
formulación del libro, y hay un test que **fija la cancelación** para que el
mutante sobreviviente de ese sitio no se lea como un agujero de cobertura.

### Medido sobre los 164 tickers cacheados

| | antes | después |
|---|---:|---:|
| Cruzan el gate `adx >= 25` (+5 al score técnico) | **105** (64,0 %) | **69** (42,1 %) |
| ADX mediana | 27,8 | 22,4 |
| ADX media | 31,3 | 24,2 |
| Nota «weak/ranging» (`adx < 15`, `:168`) | 4 | **25** |

**48 tickers cruzan el gate**: 43 salen y 5 entran (ABEV, BSAC, GS, PLD, TXN).
El ADX baja en 141 de 164 y sube en 22 — hasta −29,2 puntos (ITW 43,5 → 22,4;
MA 42,0 → 22,2; SWK 40,7 → 24,0). Que baje casi siempre no es casualidad: el
suavizado nervioso deja que los picos del DX sobrevivan al promedio, así que el
motor venía leyendo tendencia fuerte donde Wilder lee un mercado lateral.

**Y acá la fila también se quedaba corta al revés.** Decía «ATR y ADX son
sistemáticamente más nerviosos». Para el ADX es exacto. Para el ATR **no**: se
mueve en 163 de 164 tickers pero en las dos direcciones (85 bajan, 78 suben,
entre −30,4 % y +15,0 %) y la mediana de `atr_pct` queda en 5,60 → 5,63. Es
esperable: el ATR es un nivel, y cambiar el retardo del promedio lo corre para
donde vaya el precio; el ADX es un cociente doblemente suavizado, y ahí el
exceso de reactividad tiene un signo.

### Lo que no se movió, dicho explícitamente

**0 scores y 0 acciones.** Ningún `adjusted_score` cambia y ninguna decisión de
compra/venta cambia. Una sola señal técnica se da vuelta —**CMG**, BULLISH →
NEUTRAL, con ADX 25,6 → 19,6— y ni siquiera esa mueve la acción, porque la
escalera de `strategy.py:316` admite BULLISH **y** NEUTRAL para STRONG BUY.

Eso no vuelve el arreglo cosmético: el ADX es un número que el usuario ve en
`2_Stock_Analysis.py:687`, que entra en los dos prompts de IA
(`prompts.py:458,696`) y que decide +5 puntos del score técnico en 48 tickers.
Lo que dice es que hoy el score técnico está lejos de sus umbrales
(`>= 30` BULLISH / `<= -20` BEARISH) en casi toda la muestra, así que mover 5
puntos rara vez alcanza para cambiar de bucket.

### `ENGINE_VERSION` no se bumpea

Verificado, no asumido, por los dos lados. **Estructural:** `portfolio/optimizer.py`
no menciona `technical`, `full_analysis` ni `.action` en ninguna línea — el μ, la
covarianza y el Monte Carlo nunca ven un ADX. `personal_sizer` sí mira la pata
técnica, pero lee RSI, `above_sma200` y `price_vs_52w_high_pct`, no ADX ni ATR.
**Empírico:** la corrida de `measure_score_impact.py --compare` da 0 scores y 0
acciones movidas sobre 164 tickers. Nada de lo que un `PlanSnapshot` persiste
—`allocation`, `metrics`, `mc_summary`— depende de estos dos números.

### El oráculo

`tests/test_wilder_smoothing_oracle.py`, 22 tests. **No busca la palabra `span`**:
un grep verifica que alguien escribió lo que se le pidió, no que el número esté
bien, y pasaría en verde sobre un `rolling` roto. En su lugar hay una
implementación de referencia independiente, escrita desde la definición con el
bucle lento `avg = (avg*(n-1) + x)/n`, y el motor se mide contra ella (CONTEXT §5).

Verificado por mutación — cada sitio revertido a `span` por separado:

| mutante | resultado |
|---|---|
| `_atr` → span | **7 tests rojos** |
| `_adx` TR → span | 22 verdes — correcto, se cancela (hay un test que lo fija) |
| `_adx` +DM → span | **5 rojos** |
| `_adx` −DM → span | **5 rojos** |
| `_adx` DX → span | **6 rojos** |
| **MACD → Wilder** (anti-cheat) | **5 rojos** |

El anti-cheat importa: el MACD de `:315-318` usa `span` y **eso está bien** —un
MACD se define con EMA, no con Wilder—. Sin ese test, el próximo que barra el
archivo reemplazando cada `span` por `alpha=1/n` rompería el MACD en silencio
mientras «terminaba» esta fila.

De paso, `scripts/measure_score_impact.py` ahora registra `adx` y `atr_pct` y
reporta cambios de **señal técnica** y **cruces del gate de ADX 25** — antes sólo
miraba `action`, así que un cambio del tamaño de éste habría salido como
«0 señales modificadas».

---

## U5-18c — Una sola política, también al escribir (2026-08-31)

U5-18b colapsó las repeticiones del mismo día local **al leer** y U5-18d sacó
las 53 fixtures de los tres sitios. Faltaba el flujo de escritura:
`get_pending_scoring` devolvía las duplicadas, así que el scorer las iba a
puntuar —un lookup de red cada una— y a escribir outcomes que `get_scored_rows`
descarta acto seguido.

### Qué evita, y cuándo

| fecha | con colapso | sin colapso | evitados |
|---|---:|---:|---:|
| 2026-08-31 | 0 | 0 | 0 |
| 2026-09-23 | 93 | 93 | 0 |
| 2026-09-28 | 259 | 333 | **74** |
| 2026-10-15 | 332 | 406 | **74** |

**Cero hoy.** Las duplicadas son del 23 y 28 de agosto y cumplen 30 días a fines
de septiembre, así que el defecto no se puede ver ejecutando el motor hoy — por
eso el oráculo inyecta el `now` que la firma ya aceptaba.

No mueve ningún número: la lectura ya filtra, así que el hit rate y la curva
quedan igual. Se ahorran **74 llamadas de red** y 74 filas basura en
`recommendation_outcome`. Es la única de la familia cuyo costo es eficiencia y
no corrección.

### Sobrevive la primera, con la clave compartida

Igual que en la lectura y que en `_exists_today`. Si acá se eligiera la última,
el motor puntuaría una fila y mostraría otra.

La clave sale de `same_local_day_key` y no de una tupla armada en el sitio: es
lo único que garantiza que los tres no puedan derivar, y hay un test que falla
si alguien la reimplementa. `collapse_same_day=False` devuelve el crudo, misma
puerta de auditoría que `get_scored_rows`.

### Verificado antes de tocar nada

De los 74 pares, **ninguna segunda tiene outcome todavía**, así que colapsar el
pending no deja ningún outcome huérfano. Era el riesgo real de la fila.

### Una guarda que era código muerto

La primera versión traía un `if created_at is None: pasa entera`, copiado del
criterio de `collapse_same_local_day`. La mutación que lo borraba **sobrevivía**,
y al mirarlo el problema era la guarda: en `get_pending_scoring` no puede llegar
una fila sin fecha por dos razones independientes — la columna tiene
`default=utc_now`, y el `WHERE created_at <= cutoff` descarta los NULL porque en
SQL `NULL <= x` es falso.

Código defensivo inalcanzable no protege nada y esconde que el invariante ya lo
da el esquema — mismo criterio que la absorción en U4-1c. La guarda se fue y
quedó un test que fija **las dos razones**: si alguna cae, avisa.
`collapse_same_local_day` sí la necesita, porque recibe dicts.

Oráculo: `tests/test_pending_scoring_collapse_oracle.py`, 10 tests. Las cinco
mutaciones mueren.

---

## U5-8 — La fila no era cierta: ninguna equity de yield bajo cae debajo del no-pagador (2026-08-31)

La fila decía: «No pagar dividendo (+3) puntúa más que pagar un yield bajo (+2)».
Es cierto de la **sub-banda de yield** y falso del **score**. El no pagador cobra
sus 3 puntos y **retorna ahí mismo** (`fundamental.py:1538`), techo 3. El pagador
de yield bajo cobra 2 y sigue: payout (hasta +3) y racha de crecimiento (hasta
+3), techo 8. Para que la comparación del enunciado se sostenga, el pagador tiene
que perder también las otras dos dimensiones.

### Medido sobre los 164 tickers cacheados, sin red

| | n |
|---|---:|
| No pagadores (cobran el +3 y cortan) | 21 |
| Pagadores con yield medible | 143 |
| Pagadores con yield no medible (la rama de N5) | 0 |
| Pagadores con `dividend_score < 3` | **6** |
| Pagadores en la banda de yield **bajo** (+2) | 51 |
| De esos, con score final < 3 | 2 |
| **Equities** de yield bajo con score < 3 | **0** |

Los 51 de banda baja se reparten entre 5 y 8: 39 tienen payout excelente y 32 de
ésos suman además racha. La asimetría existe en el código y **no llega nunca al
score final de una equity**, porque el payout no le falta a ninguna: está
presente en 130 de 130.

### Los seis que sí quedan debajo, y por qué ninguno es esta fila

| Ticker | clase | score | yield | banda | payout | estado | racha | y+p+s |
|---|---|---:|---:|---|---:|---|---:|---|
| ABEV | equity | 1 | 5,64 % | alto | 77 % | sobre el techo | 0 | 1+0+0 |
| BSBR | equity | 1 | 5,95 % | alto | 131 % | sobre el techo | 0 | 1+0+0 |
| VALE | equity | 1 | 8,12 % | alto | 159 % | sobre el techo | 1 | 1+0+0 |
| BND | fund | 2 | 4,03 % | alto | — | ausente | 4 | 1+0+1 |
| QQQ | fund | 2 | 0,25 % | bajo | — | ausente | 0 | 2+0+0 |
| VGT | fund | 2 | 0,38 % | bajo | — | ausente | 0 | 2+0+0 |

Las tres equities son de yield **alto** con el payout sobre el techo: el motor
las castiga a propósito y les escribe la advertencia de dividendo insostenible.
Que una empresa que reparte más de lo que gana puntúe por debajo de una que
reinvierte no es el defecto — es la política.

### Lo que sí apareció, y no es U5-8

Los tres funds caen por otra causa: **`payoutRatio` está ausente en 13 de 13
funds cacheados y presente en 130 de 130 equities**. Los 3 puntos del payout son
inalcanzables para un fund por construcción, así que su techo real es 7 y no 10 —
y `2_Stock_Analysis.py:343` muestra igual «Dividend x/10», porque el `else` de
esa pantalla separa cripto del resto, no fund de equity. Es una etiqueta que
promete una escala que el activo no puede alcanzar, que es la banda 4 del
criterio. Queda abierto como **N7** en el Bloque 4.

### Cómo se midió

Re-scoring offline del universo cacheado con el mismo blindaje que
`scripts/measure_score_impact.py` —TTL en 3650 días, `attach_in_pipeline` en
falso, capas de IA en `cache_only`— y además `yf.Ticker` reemplazado por un doble
que revienta, de modo que un cache miss se cuenta como salteado en vez de salir a
la red. Salteados: 0. La atribución por componente (banda de yield, estado del
payout, tramo de racha) se recompone de `dividend_yield`,
`payout_ratio_effective`, `payout_basis` y `annual_dividend_totals`, que son los
mismos campos que `_score_dividends` persiste.

### Lo que este cierre deliberadamente NO hizo

No se tocó `_score_dividends`. Subir el no pagador de 3 a 2, o bajar la banda
baja, mueve el score de 21 y de 51 tickers para arreglar un caso que no existe en
el universo — y `total_score` alimenta el umbral de BUY. Un cambio así necesita
outcomes que lo justifiquen, no una lectura del código.

---

## U4-5 — La pantalla que pregunta «¿llego?» ya puede representar que ahorres (2026-08-31)

La pestaña principal de Simulaciones tenía un solo input de flujo —«Retiro
anual», con piso en cero— así que no podía expresar un aporte. Ahora tiene su
palanca, y el número va al motor, que desde tier2 lo deposita **mensualmente**.

### Lo que la fila no decía

**La misma pantalla ya conocía el ahorro.** La línea 458 lo resolvía con
`contribution_inputs` y lo usaba para calcular el consejo de «cuánto te falta»
(`compute_gap_to_goal_levers`, :471). O sea que el consejo asumía que el usuario
ahorra y la simulación que producía ese faltante, no. No era sólo una palanca
que faltaba: eran dos partes de la misma pantalla en desacuerdo sobre si el
usuario ahorra.

### Cómo se conecta

La clave del widget es `monthly_savings` a propósito — es la primera que
`contribution_inputs` mira y la unidad en la que el perfil pregunta. Lo que se
tipea acá pisa al perfil, que es lo correcto: un valor puesto en esta pantalla
gana sobre uno heredado.

El número que va al motor sale del helper, **nunca de un `×12` local**: es lo
que impide que dos pantallas le coticen plata distinta al mismo ahorrista
(U4-1). El contrato de `tests/test_cash_flow_oracle.py` se extendió para
cubrirlo, y ya no se mide por proximidad de líneas sino por la propiedad — todo
valor pasado como `annual_contribution` tiene que ser un nombre asignado desde
el helper.

**El motor no se tocó**: `cached_monte_carlo` ya aceptaba el parámetro.

### Alcance, medido

Sin aporte cargado nada se mueve — con `annual_contribution=0.0` el terminal es
exactamente el capital inicial capitalizado:

    aporte         0/año  →  terminal  201.235
    aporte     6.000/año  →  terminal  331.272
    aporte     9.600/año  →  terminal  409.293

`ENGINE_VERSION` **no se bumpea**: ningún plan guardado cambia de número.

### Un defecto que la medición encontró antes de shipearlo

El widget dice «0 = no aporto» y `contribution_inputs` **no lo cumplía**: su
`_positive` descarta el cero, así que un usuario que escribía 0 recibía igual
los 6.000/año de su perfil. Habría sido una etiqueta prometiendo lo que el
código no hace — introducida por este mismo PR.

La distinción ahora vive en la **presencia de la clave**, no en su valor: la que
no está significa «no sé, buscá en otro lado»; la que está en 0 significa «no
aporto», que es una respuesta y no la falta de una. Es el reverso de U3-1: allá
«no sé» se leía como «no», acá «no» se leía como «no sé». Sólo aplica a los
diccionarios explícitos — un atributo de `prefs` siempre existe, así que su 0
sigue significando «sin completar».

### Dos errores en el oráculo, corregidos antes de commitear

Uno **pasaba sobre el código roto**: `"annual_contribution=" in page` ya era
cierto porque la palanca de «cuánto me falta» pasaba uno.

El otro **marcaba código legítimo**: medía por proximidad —¿hay un
`contribution_inputs` a menos de 12 líneas?— y la asignación real está a 13.
Misma trampa que U7-3: una ventana angosta tapa al culpable y una ancha absuelve
al inocente. Reemplazada por la propiedad.

Oráculo: `tests/test_cash_flow_oracle.py`, 28 tests. Las cinco mutaciones mueren.

---

## U4-4 — La longevidad se simula, no se trunca (2026-08-31)

`decumulation_metrics` recortaba con `cap_week = min(longevity*52, n_cols-1)`.
Cuando la longevidad pedida superaba el horizonte simulado ganaba el segundo:
los años de más no existían, y la copy los nombraba igual.

### No era un caso borde: era el estado por defecto

    MONTE_CARLO.default_horizon_years   = 20
    WITHDRAWAL.default_longevity_years  = 30

El selector de horizonte arranca en 20; el widget de longevidad arranca en 30 y
acepta hasta 60. **Sin configurar nada**, el producto decía *«tu ingreso dura los
30 años en 97,86 % de los escenarios»* habiendo simulado 20. Y reportaba la
longevidad **pedida**, no la medida, así que Plan, PDF y prompts la repetían.

Medido antes del arreglo, para 20 / 30 / 45 / 60 años la respuesta era **la
misma**: 97,77 %. Los años no simulados son justo aquellos en que el pozo está
más chico, así que truncar era **sistemáticamente optimista**.

### Por qué extender y no negarse a contestar

El repo tiene precedente de decir «no sé» (U3-1, U2-4, U5-14, U7-3) y acá no
aplicaba: no faltaba un dato, **sobraba un recorte**. La pregunta está bien
planteada y el motor puede contestarla; negarse además dejaría la configuración
por defecto mostrando «desconocido» en una métrica central.

### Qué cambia

| longevidad | 10 | 20 | 30 | 45 | 60 |
|---|---:|---:|---:|---:|---:|
| sostiene | 100,00 | 97,86 | 91,96 | 85,52 | 83,58 |
| año agotamiento | 0,00 | 17,17 | 23,50 | 29,29 | 30,58 |

Baja de forma monótona, y el agotamiento ya puede caer más allá del horizonte.
**Con los defaults: 97,86 % → 91,96 %, −5,90 pp.**

`ENGINE_VERSION` → `2026.08-tier8`.

### Lo que no se mueve, y lo que costó que no se moviera

Las métricas de riqueza son del horizonte de proyección — terminal, fan chart,
CAGR, drawdown, SORR y ruina se leen en `horizon_week`, no al final del array.

El primer intento simulaba directamente el largo total, y eso **redibujaba
también los primeros años**: `_simulate_paths` sortea
`rng.integers(size=(n_sims, n_blocks))`, así que pedir más semanas cambia la
forma del array y corre todos los draws. Medido: mover la longevidad de 20 a 45
movía el capital terminal ~1 %. Ruido de muestreo, no sesgo — pero significaba
que preguntar *«¿cuánto me dura?»* cambiaba la respuesta a *«¿cuánto junto?»*, y
son dos preguntas independientes.

Ahora el horizonte se sortea primero, con su largo de siempre, y la cola se
**empalma** escalada por donde terminó. El terminal queda byte-idéntico en las
cinco longevidades: **1.923.483**.

### Un test que pasaba sobre el código roto

El primero que escribí para la monotonía usaba `sorted(probs, reverse=True)`,
que **acepta empates** — y con el recorte las probabilidades de 25, 35 y 45 eran
idénticas, así que pasaba sobre el defecto. Empatar era exactamente el síntoma.
Reescrito con comparación estricta.

Oráculo: `tests/test_longevity_horizon_oracle.py`, 17 tests, de los cuales nueve
fijan que las métricas de riqueza **no** se muevan. Las seis mutaciones mueren.

---

## U3-7b — El moat se rankea con la regla que lo mide (2026-08-30)

U3-7 arregló las **etiquetas**: dos escalas existen y no son intercambiables —
con IA el total corre 0–20, sin ella es el tramo cuantitativo solo, 0–12, donde
los umbrales de 14/8/4 vuelven «Wide» inalcanzable por construcción. Por eso
`classify_moat` exige `ai_available` en cada call site. Esta fila es la misma
corrección en los **pesos**.

### La fila describía un defecto y había otro

Dice: *«una fila sin IA queda sistemáticamente peor rankeada por no haber sido
enriquecida, no por la empresa»*. Eso necesita una población **mixta**.

Medido sobre las 150 equities cacheadas: el moat va de 0,5 a 12,0 y **ninguna
supera 12**. Ninguna pasó por la capa de IA, así que la población es **uniforme**
y no hay penalización relativa entre enriquecidas y no enriquecidas.

Lo que sí había: con moat ≤ 12 dividido por 20, el término de moat aporta el
**60 % de lo que declara `cfg.moat_weight`**. No perjudica a una fila en
particular — encoge el término entero frente al score y al dividendo.

Las dos cosas son ciertas y el arreglo cubre ambas, porque escala por el techo
que efectivamente aplica. Si algún día el screener corre con IA, la población se
vuelve mixta y aparece el defecto que la fila describe; hay un test para eso.

### La prueba más limpia salía del propio código

`_core_rank` documentaba:

    moat_factor = (a.moat_score / 20.0) + 0.5  # range 0.5–1.5

El rango real, con moat ≤ 12, era **0,53–1,10**. El comentario decía la
intención y el código entregaba el 60 % de ella. `moat_rank_factor` ahora cubre
0,5–1,5 de verdad, en las dos escalas.

### Qué se movió

Núcleo determinístico, sobre el universo cacheado:

| perfil | entra | sale |
|---|---|---|
| conservador | ADBE | CMCSA |
| moderado | GOOGL, META | LRCX, MA |
| agresivo | SPG | CINF |

Down-select: cambian 1 de 20 candidatos en Conservador, 2 de 30 en Moderado,
2 de 45 en Agresivo.

`ENGINE_VERSION` **no se bumpea**: cambia el orden de los candidatos y del
núcleo sugerido, no μ ni ningún número que un plan guardado persista.

### De paso

`_rank_score` era una función local adentro del down-select y ahora es método:
es lo que elige el pool sobre el que corre toda la optimización, así que merece
ser ejercitable directo — mismo criterio que `_clean_div_yield` y
`_expected_returns`. Las líneas que la fila citaba estaban corridas (483/509 →
516/542) y el tercer `/20` de `:625` efectivamente había desaparecido con U5-6.

`MOAT.quant_max_score` y `MOAT.ai_max_score` explicitan los dos techos, y
`_moat_had_ai` los lee del dato en vez de asumirlos: una fila que no lo trae se
toma como cuantitativa, porque equivocarse hacia esa escala sólo puede
sub-estimar un moat enriquecido, nunca inflar uno que no lo está.

### Un test que se habría salteado para siempre

El primero que escribí para fijar la población leía el baseline del scratchpad de
la sesión, con un `skipif` si no existía. En CI ese archivo no existe: se
saltearía siempre, y un skip permanente es un verde por ausencia — la misma clase
de defecto que el archivo existe para atrapar. Reemplazado por la medición
embebida como dato.

Oráculo: `tests/test_moat_ranking_scale_oracle.py`, 13 tests. Las seis
mutaciones mueren.

---

## U7-3 — El titular deja de afirmar lo que la muestra no sostiene (2026-08-30)

Con el track record limpio (U5-18b, U5-18d), su lectura honesta es que **no se
puede concluir nada**. Tres superficies concluían igual.

### Lo medido

| | valor | banda | intervalo | |
|---|---:|---:|---|---|
| tasa de acierto | 45,5 % | ±35,1 pp | [10,4 , 80,5] | contiene el 50 % de una moneda |
| exceso medio | +3,21 | ±6,86 | [−3,65 , +10,07] | contiene el cero |

n=11. El intervalo del acierto va de «pésimo» a «excelente». Eso **no** dice que
el motor pierda: dice que la muestra no permite saberlo, que es otra cosa y es
la que hay que decir. Ningún corte alcanza — BUY 6, HOLD 5, ai 6, committee 5,
MEDIUM 9, LOW 2, **HIGH 0**.

### Tres defectos

**(1) La misma página sostenía dos estándares.** La tabla por acción mostraba
«Margen ±» y decía «sin señal», porque `hit_rate_by_action` enriquecía cada
bloque con `excess_band_pct` e `inconclusive`. Doce líneas más arriba el titular
afirmaba en indicativo, porque `summary_stats` **no devolvía bandas**. Ahora
salen de ahí y las dos superficies las consumen del mismo lugar.

La banda de la **tasa de acierto** no la calculaba nadie, es la más ancha de
todas y es la que se muestra más grande. Se computa sobre los ceros y unos
—una tasa de acierto es la media de una variable binaria— y su hipótesis nula
**no es la de `mean_with_band`**: aquella pregunta si el intervalo contiene el
cero, y un acierto de cero no es lo interesante. `hit_rate_inconclusive`
pregunta si contiene 0,5.

**(2) El titular y el gráfico se contradecían en el signo.** El titular decía
«le ganó al mercado por +3,2 %» mientras el gráfico de la misma pantalla mostraba
el modelo en 0,9134 contra 1,0307 del benchmark. **Los dos bien calculados**: uno
promedia excesos, el otro los capitaliza, y con desvío 10,2 sobre un rango de
−23,5 a +13,7 el arrastre de volatilidad da vuelta la conclusión. Vocabulario
canónico en `product_ux` (`EXCESS_MEAN_LABEL` / `EQUITY_CURVE_LABEL`), mismo
remedio que U1-1/U1-2, y los dos help avisan que pueden discrepar en signo.

**(3) Una categoría sin observaciones no calibra.** El caption invitaba a
comparar HIGH contra LOW; HIGH tiene n=0.

### Lo que muestra ahora

    Tasa de acierto   sin señal   (help: 45 % ± 35 pp, de 10 % a 80 %)
    Exceso medio      sin señal   (help: +3,2 ± 6,9, contiene el cero)
    veredicto         «Con 11 recomendaciones todavía no alcanza para concluir
                      nada … No es que el motor ande mal ni bien — es que la
                      muestra aún no lo dice.»

El número no se esconde: sigue en el help. Se deja de **afirmar**.

**No se toca el motor** y **no se bumpea `ENGINE_VERSION`**.

### Dos errores míos que el ciclo atrapó

**Un fixture que mentía.** El primero que escribí inventaba los excesos y su
docstring decía que reproducían la muestra real: daban media −0,72 contra el
+3,21 medido. Reemplazado por los valores de la base, con un test que falla si
dejan de reproducirla.

**Un barrido que miraba tan lejos que no veía.** La mutación más importante —«la
página vuelve a afirmar el porcentaje sin banda»— sobrevivía: con una ventana de
±6 líneas, el `help=` contiguo nombra la banda legítimamente y tapaba a la
métrica de al lado. Y al apretarla a ±1 apareció un segundo error, de aritmética:
el slice `[n − C : n + C]` incluye C líneas antes y **ninguna después**, así que
la primera línea del help dejó de ver su propia banda. Las dos corregidas, con un
test que fija el caso exacto que se escapaba.

Oráculo: `tests/test_track_record_honesty_oracle.py`, 17 tests. La banda de
referencia se escribe desde la definición (Student's t) y **no** importa
`mean_with_band`: si el motor y la referencia comparten implementación, el test
no valida nada. Las seis mutaciones mueren.

---

## U5-18 — Un solo reloj, y un día que es el del usuario (2026-08-29)

### Lo que la fila decía, y lo que había

Dos correcciones antes del arreglo.

**El conteo.** No eran 15 `utcnow` en tres archivos: eran **31 en seis**.
`alerts/store.py` tenía 12 y ni figuraba en la fila; `analysis/macro_rag.py`
tres y `dashboard/pages/8_Alertas.py` uno.

**No había ningún cruce de relojes activo.** La fila decía «afecta la edad del
dato», y la edad del dato **estaba bien calculada**: cada módulo era
internamente consistente — `data/cache.py` escribe y lee en UTC,
`screener_store.py` escribe y lee en local, `last_refreshed_at` se sella y se
mide con el mismo reloj. Dos relojes en un mismo SQLite son un peligro latente,
no una resta mal hecha, y decirlo importa para no vender el PR como algo que no
es.

### Lo que sí estaba mal: el día

`TrackRecordStore._exists_today` cortaba a las 00:00 **UTC**. Para un usuario en
UTC−3 eso hace que el «día» corra de 21:00 a 21:00 local, así que el dedup
funcionaba perfecto en sus propios términos y dejaba pasar los que importan.
Medido sobre las 397 filas reales de `recommendation_log`:

| regla | duplicados |
|---|---:|
| (símbolo, acción, día **UTC**) | **0** |
| (símbolo, acción, día **LOCAL**) | **80** |

```
AAPL BUY, día local 2026-08-23:  09:32  y  21:12
                      en UTC:    23 12:32 y 24 00:12
```

Simulando las dos reglas en orden cronológico sobre la base real: el corte UTC
admite 394 filas, el local admite 317. **77 filas —el 19,4 % de la muestra— son
la misma recomendación repetida en el mismo día del usuario.**

Y eso pega donde más duele. CONTEXT §8 ya decía que *«149 recomendaciones del
mismo día no son 149 datos independientes — comparten el movimiento del mercado
de ese día»*: el track record es el único juez que el motor tiene sobre sí mismo,
y una quinta parte de su muestra eran repeticiones.

### Las dos decisiones del arreglo

`data/clock.py` es el reloj único, y separa dos cosas que se confundían:

* **se guarda en UTC**, porque es inequívoco — no tiene horario de verano, no
  salta si el usuario viaja y ordena bien. **No se migra nada**: toda fila ya
  escrita conserva su significado y el arreglo actúa de acá en adelante.
* **el día se corta en local**, porque «uno por día» es un concepto humano. La
  conversión es de ida y vuelta (UTC → local → medianoche → UTC) en vez de
  restar un offset fijo: restar horas a mano se rompe dos veces al año en
  cualquier país con horario de verano, y se rompe en silencio. Hay una mutación
  que verifica exactamente eso.

### La deprecación, de paso

`datetime.utcnow()` está deprecado desde Python 3.12. La suite emitía **167
advertencias** y ahora emite **11, ninguna de datetime** — las restantes son de
pandas y dateutil.

Los tests entran en el barrido a propósito: uno que llama al reloj deprecado se
rompe el día que Python lo saque, y dejarlos afuera habría sido hacer la mitad
del trabajo y llamarla completa.

Oráculo: `tests/test_clock_oracle.py`, 13 tests. El corte se verifica por ida y
vuelta —convertirlo a hora local tiene que dar exactamente medianoche— en vez de
leer la implementación, y el duplicado real medido en la base se reproduce como
caso. Las seis mutaciones mueren.

`ENGINE_VERSION` **no se bumpea**: no se mueve ningún número de ningún plan
guardado.

---

## U4-1c — Decidir anual, pagar en doceavos (2026-08-29)

U4-1 mensualizó los aportes y dejó los retiros anuales a propósito, porque la
estrategia de guardrails **es** una revisión anual. Esta es la mitad que
faltaba.

### Lo que estaba mal, y lo que la fila no decía

Dos efectos que se sumaban:

* **el lump de diciembre** — el año entero de gasto salía junto en la semana 52,
  así que ese dinero componía doce meses de más antes de irse. Esto sí estaba en
  la fila.
* **el año gratis** — `weeks = [yr * 52 for yr in 1..N]` ponía el primer retiro
  en la **semana 52**, o sea que el primer año de la jubilación transcurría
  entero sin que saliera un peso. Esto no estaba, y es la mitad más grande.

### Lo que no cambia: la decisión

El presupuesto se calcula en la primera cuota del año y las once restantes lo
repiten. Un guardrail recalculado doce veces al año es **otro método**, no el
mismo mejor pagado — hay un test que falla si los doce pagos de un año dejan de
ser iguales entre sí, con su anti-cheat al lado exigiendo que entre años sí
cambien.

`MONTE_CARLO.withdrawal_periods_per_year = 1` reproduce el motor tier2-tier6
exactamente, y toda la grilla del oráculo corre sobre **las dos cadencias**.

### El efecto NO es uniformemente conservador

Costó un test que afirmaba lo contrario y hubo que reescribirlo.

Con **gasto exógeno** (`fixed_real`) el total del año es un número dado, así que
adelantarlo sólo puede dejar menos capital:

| escenario | sostiene | año agotamiento | legado mediano |
|---|---:|---:|---:|
| fixed_real $40k | 99,28 → 99,17 (−0,11 pp) | 27,0 → 26,5 | **−3,1 %** |
| fixed_real $60k | 88,58 → 87,28 (**−1,30 pp**) | 23,0 → 22,5 | **−8,3 %** |

Con **gasto endógeno** (`constant_pct`, `guardrails`) el importe sale de la
riqueza, y repartir el pago obliga a decidir el presupuesto al **inicio** del
año en vez del final — no se paga en enero con una decisión de diciembre. En un
mercado que sube, decidir antes da un importe menor:

| escenario | legado mediano |
|---|---:|
| constant_pct 4 % / 5 % / 6 % | **+4,2 % / +5,3 % / +6,4 %** |
| guardrails 4 % / 5 % / 6 % | **+3,0 % / +3,8 % / +4,0 %** |

Hasta la fecha de agotamiento se mueve en las dos direcciones: en el bootstrap
del MC se adelanta medio año, y en el path determinístico de caída monótona de
la auditoría D2 se **atrasa** de la semana 208 a la 221 — un lump funde la
cartera de un golpe, doce cuotas la desangran de a poco. Las dos quedan fijadas.

El caso D1 de la auditoría: **553.133 → 536.748, −2,96 %**.

`ENGINE_VERSION` → `2026.08-tier7`.

### Las referencias se reimplementaron, no se ajustaron

67 tests fallaron al activar la cadencia, y todos por la misma razón: los **tres
oráculos independientes** codificaban la anual. Ajustarlos al resultado nuevo
habría congelado el bug — la lección D4 del propio repo, que este archivo cita
en su regla de mantenimiento.

Se reescribieron **semana a semana** desde la definición:
`test_withdrawal_oracle._oracle_path`,
`test_guardrails_label_contract._reference_guardrails` y
`test_audit_2026_08_repro._correct_sequential`. Una referencia que avanza de a
un año no puede expresar la cadencia que tiene que validar.

Los valores documentados de la auditoría **no se reemplazaron**: quedan fijados
bajo su cadencia, con el número nuevo al lado y la dirección exigida entre los
dos.

### Un clamp que parecía prudente y empeoraba la absorción

La primera versión recortaba cada cuota contra la riqueza disponible. Es peor:
`cash_flow_units` pisa las unidades a cero, así que pedir de más deja el pozo en
cero **exacto**, mientras que recortar dejaba una miga de 5e-19. El docstring
del primitivo ya lo decía —*"absorption is a property of the algebra rather than
of a defensive branch"* (auditoría D2)— y el recorte volvía a meter esa rama.

Lo destapó la identidad de bits entre los dos entry points, que se rompía en 9
de 500 paths. Esa identidad se conserva: `fixed_real` divide por las cuotas
**antes** de aplicar la inflación, igual que `_apply_cash_flows`.

Y la mutación encontró que la propiedad sólo se verificaba **de rebote**, por un
test de otro archivo que compara dos entry points por una razón distinta. Ahora
tiene el suyo, con la comparación que la distingue (`== 0.0`, no `<= 1e-9`) y
sobre un mercado **irregular**: en una curva suave la división da exacta por
casualidad y el mutante pasaba igual.

Oráculo: `tests/test_withdrawal_cadence_oracle.py`, 13 tests. Las seis
mutaciones mueren.

---

## U6-1 — El proxy se ordena, no se cotiza (2026-08-29)

La última fila del Bloque 2, y la que más cambió de forma al medirla.

### La fila decía «inventado». Es lo contrario, y peor, a la vez

Medido sobre las 149 equities cacheadas con ≥5 años de historia semanal:

| pregunta | respuesta |
|---|---|
| ¿El score predice retorno? | **Sí.** Pendiente +20,8 pp/100 pts sobre el CAGR realizado, p < 0,0001 |
| ¿El intercepto cero del motor es correcto? | **Sí.** Intercepto medido: **−1,43 %** |
| ¿μ está anclado a algo observable? | **No.** Correlación con el drift del Monte Carlo: **+0,025** |
| ¿Tiene la precisión que su formato promete? | **No.** R² = 0,116; rango p10–p90 de μ = 3,4 pp contra 19 pp del CAGR real |

O sea: la **estructura** está bien —el signo, la pendiente y el cero que asume—
y lo que está mal es que un número con R² 0,12 y un rango de 3,4 pp se
presentara como «7,2 % anual». Eso promete exactitud (no la tiene), precisión
(tampoco) y una unidad que invita a capitalizarlo o compararlo contra un plazo
fijo.

### Por qué no se recalibró el `0.18`

Dos razones independientes, y la segunda es la que cierra la discusión.

**Es hindsight.** La pendiente sale de regresar el score de *hoy* contra el
retorno de los *últimos diez años*, en una ventana con 13 % de CAGR medio.
Ajustar la constante a eso hornea dos sesgos y vuelve a μ más *confiado*, no más
correcto. Los datos forward-looking que harían falta no existen: el track record
tiene 22 filas, todas a 30 días (misma pared que U5-1b).

**Y no serviría.** Con el span llevado a 0,417, el score al que μ satura
`er_absolute_cap` cae **por debajo del score medio del universo** (69,5): más de
la mitad de los candidatos quedaría pegada al mismo techo, indistinguible entre
sí. Medido: **95 de 150 tickers contra el cap**, y el desvío de μ pasando de
1,45 pp a 1,41 pp. **El cap manda, no el span** — recalibrar *aplana* la vista.
Ese argumento quedó como test ejecutable, no como comentario.

### Dos cosas que la fila no anticipaba

**μ no elige acciones, elige pesos.** Con μ plano el optimizer selecciona el
mismo conjunto exacto en los tres perfiles (19/19, 30/30, 45/45 posiciones);
sólo se mueven los pesos, 20–46 pp de L1 sobre 200. La selección la hacen el
prefiltro y las restricciones. Eso acota el blast radius que la fila advertía:
es real, pero es sobre ponderación, no sobre qué entra a la cartera.

**El help estaba desactualizado.** Prometía «score + dividendo + moat» y U5-6
sacó el término de moat de μ dos semanas antes. Un rótulo que enumera un término
inexistente es la misma clase de defecto que esta fila cierra.

### Qué cambió, y qué no

`expected_return_pct` **no se toca**: Black-Litterman lo necesita en unidades de
retorno. Lo que cambia son las **16 superficies** que lo renderizaban con un
signo de porcentaje. La traducción es `μ / er_absolute_cap × 100`, estrictamente
monótona — el 100 es el cap del motor, no un redondeo elegido aparte.

**Verificado de forma exhaustiva: 11.175 pares comparados sobre el universo, 0
inversiones.** Mismo ranking, mismos pesos, misma cartera; descrita sin prometer
una precisión que no existe. `git diff main --name-only` no toca ningún archivo
del camino de scoring ni de μ, y **`ENGINE_VERSION` no se bumpea**.

### Lo que deliberadamente no hizo

`er_absolute_cap` sigue en 0,14 y nadie lo calibró tampoco. Hoy casi no muerde
—1 ticker de 150— así que no es urgente; pero si alguna vez se sube el span, el
cap pasa a ser la restricción que manda. El oráculo falla si eso pasa, en vez de
dejar el razonamiento envejecer en un comentario.

Oráculo: `tests/test_proxy_ordinal_oracle.py`, 13 tests, con un barrido sobre
toda superficie de usuario que falla si alguna vuelve a interpolar el proxy
seguido de un `%`. Las seis mutaciones mueren.

**De paso:** `ruff` atrapó un `F821` que los 2179 tests no vieron — un helper
que referenciaba una constante que ese archivo nunca había importado, porque
usaba el literal. Ningún test ejerce esa rama del PDF.

---

## N5 — Un yield que no era el de la empresa (2026-08-29)

Apareció contestando otra pregunta. Después de mergear el PR #42 quedaba abierto
si el techo de yield unificado en 30 % era demasiado permisivo para μ, porque
dejaba entrar el 24,7 % de ABEV. La respuesta fue que **el techo era la perilla
equivocada**: el número al que se le aplicaba no era el yield de la empresa.

### El dato que dio vuelta la pregunta

Los campos del feed se contradicen entre sí. Para ABEV, `dividendYield` dice
5,64 % y `fiveYearAvgDividendYield` 5,19 %; `trailingAnnualDividendRate / price`
—el que el motor prefería— da 24,70 %.

No es un caso aislado. Sobre los 164 tickers cacheados, **8 tickers**, 7 de
ellos ADRs latinoamericanos:

| sym | país | motor usaba | feed dice | ratio |
|---|---|---:|---:|---:|
| TEO | Argentina | 94,73 % | 0,31 % | **305×** |
| SBS | Brasil | 12,78 % | 0,63 % | 20× |
| ITUB | Brasil | 37,43 % | 2,19 % | 17× |
| VALE | Brasil | 36,94 % | 8,12 % | 4,6× |
| ABEV | Brasil | 24,70 % | 5,64 % | 4,4× |
| BAP | Perú | 13,00 % | 3,72 % | 3,5× |
| HON | EE.UU. | 4,37 % | 1,27 % | 3,4× |
| BSBR | Brasil | 18,55 % | 5,95 % | 3,1× |

El docstring del paso 1 lo justificaba como *"immune to the feed's unit
choices"*. Es cierto para **unidades** y falso para **monedas**: en un ADR
latinoamericano el dividendo se declara en moneda local y el precio cotiza en
USD, así que la división queda dimensionalmente limpia y numéricamente mal. Lo
mismo con un ADR de ratio distinto de 1:1, y con un spin-off registrado como
distribución (HON, la única que no es de moneda).

### Por qué el corte no es una calibración

Sobre los 130 tickers que traen los tres campos, el ratio
`(rate/price) / dividendYield` separa **dos poblaciones que no se tocan**:

    122 tickers  < 1,04×     sanos
      0 tickers  1,04–3,12×  banda vacía
      8 tickers  ≥ 3,12×     corruptos

Y un tercer campo arbitra: `fiveYearAvgDividendYield` le da la razón a
`dividendYield` en **8 de 8** casos disputados. No se prefiere un campo por
gusto — un testigo independiente coincide con uno de los dos, siempre. El corte
quedó en 2,0, en el centro de la banda vacía, y un test falla si se corre a un
borde.

### La segunda cara: un None que se contaba como un cero

Cuando el yield superaba el techo la función devolvía `None`, y su docstring
decía *"a loud None beats a confident wrong number"*. No era loud aguas abajo:
`_score_dividends` hacía `or 0.0`, caía en la rama `div_yield == 0` y pagaba
**+3 puntos** de crédito por reinvertir con la nota *"No dividend — growth
company reinvests FCF"*. **Itaú, Telecom Argentina y Vale** —tres pagadores
reales— le decían al usuario que no pagan. Misma forma que U3-1.

El comentario de `fundamental.py:181` documentaba el defecto sin verlo:
*"dividend_yield is deliberately excluded: None is legitimate for growth
stocks"*.

### Medido

Scores, contra baseline previo sobre 164 tickers: **6 se mueven**, entre −2 y
+4, **ninguna señal cambia**.

μ —que el harness no mide, porque μ no es un score— **8 de 164**, en las dos
direcciones:

| | | | | |
|---|---:|---|---:|
| ABEV | −4,66 pp | VALE | +2,44 pp |
| BSBR | −3,78 pp | ITUB | +0,66 pp |
| SBS | −3,64 pp | TEO | +0,09 pp |
| BAP | −2,78 pp | | |
| HON | −0,93 pp | | |

Los dos primeros **revierten con precisión la regresión que introdujo tier5**:
subir el techo del optimizer de 15 a 30 sacó un guard accidental. Aquel literal
`15.0` estaba mal por la razón que se dijo —config duplicada— y bien por
casualidad, porque tapaba este input corrupto. Los tres de la derecha suben
porque su yield se descartaba a cero.

`ENGINE_VERSION` → `2026.08-tier6`. **El techo no se tocó**: con el input sano
ningún yield real del universo se le acerca, así que pasa a ser un guard de
último recurso y su valor deja de importar.

### Dos errores que el ciclo atrapó, y que quedaron fijados

1. **Un falso positivo, en espejo del defecto.** El primer desempate incluía
   `lastDividendValue` como evidencia de que la empresa reparte. Es el registro
   del último dividendo pagado **alguna vez**: Adobe lo trae con fecha 2005,
   MELI 2017, PAM 2012. Le sacaba los +3 a 6 growth genuinas. Lo destapó la
   medición, que mostró 9 tickers movidos donde debían ser 3.
2. **El cross-check guardaba media familia.** `trailingAnnualDividendYield`
   arrastra la misma corrupción que la división y entraba por la ventana con el
   mismo número — ABEV bajaba de 24,70 % a 24,33 %, o sea nada. También lo
   destapó la medición.

Y la verificación por mutación encontró un tercero, en el oráculo: el mutante
que reproduce el error 2 **sobrevivía con los 31 tests en verde**, porque los
fixtures omitían `trailingAnnualDividendYield` y el mutante caía en el vacío en
vez de reponer el número malo. El test se ponía verde por una ausencia del
fixture. Corregido: los fixtures pasan los cinco campos reales, y un test nuevo
verifica que sigan reproduciendo el caso.

Oráculo: `tests/test_dividend_yield_provenance_oracle.py`, 39 tests. Las cinco
mutaciones mueren.

---

## U5-9 + U5-10 + U5-11 — Un número, una casa (2026-08-29)

Tres filas del backlog, un solo defecto: config y código en desacuerdo sobre
dónde vive un número. Se trabajaron juntas porque el arreglo de una destapa el
terreno de la siguiente.

### Lo primero fue verificar qué seguía vivo

**U5-9 estaba vencida en más de la mitad.** Enumeraba ocho literales; cinco ya
no existían, centralizados por filas posteriores que se trabajaron antes que
ésta:

| literal de U5-9 | estado real al abrirla |
|---|---|
| `0.21`/`0.79` del tax, `moat.py:626` | **cerrado** — U3-8 (`28bab01`): `TAXES.corporate_tax_rate_pct` + `analysis/utils.roic_pct`. `moat.py:626` ya no es el tax: es `roic_spread_good` |
| F6 `1.02` | **cerrado** — U5-3 (`d1aba8f`): `PIOTROSKI.max_dilution_pct` |
| MaxDD `1.5` | **cerrado** — U1-10: `OPTIMIZER.max_dd_vol_multiple` |
| payout `80` | **cerrado** — U5-4 (`ecb704c`): `max_payout_ratio` / `reit_max_payout_ratio` |
| `0.05` de μ | **cerrado** — es `TAILWINDS.optimizer_er_tilt` |
| `0.18` de μ | vivo — `optimizer.py:656,664` |
| quick `1.5`/`1.0` | vivo — `fundamental.py:1101,1103` |
| FCF `4`/`2` | vivo — `fundamental.py:1414,1416` |

Los tres vivos se mudaron 1:1 a `OPTIMIZER.score_return_span`,
`THRESHOLDS.min_quick_ratio_good/_ok` y `THRESHOLDS.fcf_yield_excellent/_good`.
**Cero tickers se mueven por esta parte.**

### U5-10 fue la cara cara

Las tres declaraciones de la tasa libre de riesgo seguían ahí, con las líneas
corridas (402→463, 694→878, 491→663), en dos unidades y con dos valores.
`config.RISK_FREE` las unifica en 4,5 % —el valor que dos de las tres ya
usaban— y expone las dos unidades como vistas derivadas, porque el 100× que las
separa es exactamente el error que comete una unificación a mano.

**La fila decía que no movía un número. Movía dos cosas, y una fuerte.**

1. El hurdle del spread de ROIC del moat sube 0,5 pp. Medido con
   `scripts/measure_score_impact.py` sobre los 164 tickers cacheados contra un
   baseline previo: **6 pierden entre 0,2 y 0,6 puntos** de `adjusted_score`
   (VLO, NFLX, CLX, PFE, SPGI, DOV), **ninguna señal cambia**.
2. **Los dos techos de yield.** «Este yield no puede ser real» valía 15 % en
   `PortfolioOptimizer._clean_div_yield` y 30 % en el scorer. Un yield entre
   ambos se puntuaba como bueno *y* se borraba de μ al mismo tiempo — la misma
   empresa cobraba por su dividendo en el score y no en el atractivo. Dos
   tickers del universo viven ahí:

   | ticker | yield | μ antes | μ ahora |
   |---|---:|---:|---:|
   | ABEV | 24,70 % | 7,65 % | **14,00 %** (toca el cap) |
   | BSBR | 18,55 % | 3,60 % | **9,16 %** |

   Sobrevive el techo del scorer porque es el que **loguea** el descarte en vez
   de blanquear el valor sin dejar rastro. Si 30 % resulta permisivo, ahora es
   una línea de config.

Dos vecinos de la misma fila:

- `MONTE_CARLO.block_size_weeks` no lo leía nadie — el simulador usaba su propia
  constante de clase `BLOCK_SIZE`, así que editar el campo de config era un
  no-op silencioso. Ahora es una property que lee config; mismo valor, y el
  Monte Carlo queda **byte-idéntico** (verificado por checksum de
  `_simulate_paths` contra el código previo).
- Los **dos caps de sector no se tocaron**: `THRESHOLDS.max_sector_pct` (higiene
  de cartera, `allocation.py`) y `ProfileConfig.max_sector_pct` (constraint del
  optimizer por perfil) miden cosas distintas y los dos se leen.

`ENGINE_VERSION` → `2026.08-tier5`, con su entrada en `ENGINE_CHANGELOG`.

### U5-11 fue la dirección contraria

No un número sin casa, sino cuatro campos con casa que nadie visitaba.
`weight_quality_moat_tailwind = 45` y sus tres hermanos se interpolaban en un
f-string que la página de Portfolio le muestra al usuario como *«Ponderación de
la lógica de sizing»*. `_decide_sizing` no pondera nada: es una cascada donde
gana el primer gate que dispara. Medido antes de tocar nada — con los cuatro
puestos en 90/5/3/2 las recomendaciones salían **idénticas**.

Se borran en vez de ponerse en 0 (un 0 se lee como feature apagada, y no había
feature) y la frase pasa a describir la cascada real. **Ningún número se mueve
acá**: era una etiqueta que prometía una fórmula inexistente.

### Los tests que se rompieron eran señal

Cuatro, y los cuatro valían la pena:

- `test_cost_of_equity_label_contract` atrapó que `COST_OF_EQUITY_HELP` tenía el
  «4 %» escrito a mano — el mismo defecto, en la copy. Ahora lee `MOAT`.
- `test_moat_roic` fijaba `Ke = 4 + erp` a mano. Se reescribió relativo al hurdle
  que el motor reporta, que es lo que lo vuelve un test del spread y no una
  segunda copia de la tasa.
- `test_optimizer::TestCleanDivYield` fijaba el techo viejo de 15.
- `test_return_label_contract` barrió `config.py` y encontró un «Sharpe» sin
  calificar en el docstring nuevo. El calificador estaba, en inglés: se agregó
  `realized` junto a `realizad`, ambos completos y no acortados a `realiz`, que
  dejaría que un «se realiza el cálculo» calificara un Sharpe pelado.

Oráculo: `tests/test_config_single_home_oracle.py`. Ninguno de sus tests grepea
un literal — un arreglo que moviera el número a config y siguiera leyendo el
literal pasaría un grep, así que cada test mueve la perilla y exige que la
respuesta del motor se mueva con ella. Verificado por mutación: revertir cada
uno de los siete arreglos mata su test.

---

## N2 (mitad barata) — Todo fetch de red reintenta (2026-08-29)

CONTEXT §8 arrastraba *"no hay retry automático"* como limitación conocida. Esa
frase estaba desactualizada, y la verdad era más rara: `_fetch_with_retry` existía
y hacía lo correcto, pero protegía **dos de los cuatro** fetchers.

| fetcher | reintentaba |
|---|---|
| `get_info` | sí |
| `get_history` | sí |
| `get_financials` | **no** → ahora sí |
| `get_dividends` | **no** → ahora sí |

Los dos desprotegidos no eran la mitad inofensiva. Una falla transitoria en
`get_financials` devuelve estados vacíos, y la cadena desde ahí es corta y
completamente silenciosa:

    estados vacíos → has_financials=False → calidad "poor"
                   → apply_data_quality_policy degrada BUY a HOLD

**Una llamada HTTP con hipo, en un camino que ya sabía sobrevivir a llamadas HTTP
con hipo, cambiaba lo que el producto recomienda.**

`get_dividends` distingue *"el feed contestó, y la respuesta es que no paga
dividendos"* de *"la llamada falló"*: no pagar no es un error y no se reintenta.

La política se muda a `config.FETCH` — cuánto esperar a un ticker con hipo depende
de cuántos tickers le queden a la corrida.

### Lo que costó, y lo que destapó

La suite pasó de **23 s a 7m26** — una regresión que introduje y tuve que perseguir.
Los tests llegan al camino de retry aunque crean haberlo mockeado:
`data_sources.YFinanceSource` importa `get_financials` **localmente**, así que
`patch("analysis.fundamental.get_financials")` no lo intercepta, y con un ticker
sintético no hay entrada de caché que lo sirva. Esa llamada **siempre** fallaba;
antes fallaba instantáneamente, y ahora dormía 6 s.

Su propio comentario dice que espera un cache hit porque `analyze` ya lo trajo — o
sea que en producción es una **llamada de red redundante** cada vez que la caché
falla. Queda anotado como **N2b**, no arreglado acá.

La suite recibe un fixture autouse que pone el backoff en cero —lo irrelevante en
tests es la demora, no el reintento— y vuelve a 24 s. Mi propio test entró en
conflicto con mi propio fixture al afirmar que el delay del singleton es positivo;
ahora verifica un `FetchConfig` fresco, así que comprueba lo que se shipea.

Contrato: `tests/test_fetch_retry_oracle.py`.

---

## N1 — El oficial sale del mercado, el paralelo lo pone el usuario (2026-08-29)

U2-5 cerró la **conversión** y construyó el vocabulario de procedencia. N1 es de
dónde salen los números — y las dos patas resultaron necesitar respuestas distintas.

**El oficial es cotizable** como `ARS=X` a través de la dependencia que el proyecto
ya carga. Estaba en **1.000 pesos/USD inventados contra 1.512 reales** —51 % abajo—
simplemente porque nadie lo había cableado. `usd_ars_quote` pasa por `get_history`,
así que comparte caché, TTL y manejo de fallas con todos los demás precios, en vez
de agregar una segunda forma de hablarle al mismo feed.

**El paralelo no tiene fuente gratuita**, así que es el número del usuario: un campo
en `UserPreferences`, un input en Settings, fechado al guardar y etiquetado como
suyo. Eso además vuelve alcanzable el `manual` que config tenía en su vocabulario y
que nada en el producto podía producir.

La procedencia pasa a ser **por pata**. `source_oficial` y `source_parallel`
responden por separado, así que la UI puede decir *"oficial del mercado al 28,
paralelo lo pusiste vos"*. `rate_source` se conserva para las superficies que ya lo
leen y reporta **la pata más débil**, porque un par está tan respaldado como su
mitad menos respaldada.

### La regla que sostiene todo

**La brecha exige que las dos patas tengan origen.** Un oficial de mercado contra un
paralelo placeholder es un número real menos uno inventado — el mismo defecto con
medio disfraz, y el que este diseño podía introducir más fácilmente.

Y al escribir el test apareció que **ya estaba vivo**: `test_c_c` seteaba sólo
`USD_ARS_OFICIAL` y afirmaba que la config leía `"env"` con `is_placeholder` en
False, así que un oficial real de 1450 se comparaba contra un paralelo inventado de
1200 y **la brecha se mostraba**. Ese test fijaba el medio disfraz; su sujeto —la
config sabe de dónde salieron sus tasas— sobrevive y ahora sabe más.

Una cotización fallida o no positiva cae al placeholder y lo dice. Inventar
frescura sería peor que admitir que no la hay, porque una etiqueta `market`
fabricada es exactamente lo que destraba la brecha.

**Verificado de punta a punta contra la cotización viva:** sin nada cargado → sin
brecha; oficial de mercado sin paralelo → **sigue** sin brecha; las dos con origen →
+15,7 % con cada pata nombrada.

Contrato: `tests/test_ar_fx_provenance_oracle.py`.

---

## U5-2 + U5-3 — Dos señales del Piotroski que respondían otra pregunta (2026-08-29)

Las dos eran **latentes** y se cerraron antes de dejar de serlo. Verificado contra
un baseline previo de los 164 tickers cacheados: **0 scores y 0 acciones se mueven**.

**U5-2 — una empresa sin deuda reprobaba el chequeo de apalancamiento.** F4
pregunta si la razón deuda-de-largo-plazo sobre activos **bajó**, con un `<`
estricto. Sin deuda de largo plazo en ninguno de los dos años eso da `0 < 0 =
False` y se pierde el punto. Una empresa no puede reducir lo que no tiene, y
apalancamiento cero no es una falta de mejora: es **el mejor estado posible** de lo
que se está midiendo.

El `<` estricto **se queda en todo lo demás**, porque mantener la deuda plana en
30 % de los activos genuinamente no es una mejora, y eso es lo que pregunta el
F_LEVER original. Sólo se exime el caso degenerado, y **tomar deuda desde cero
sigue reprobando**.

**U5-3 — el chequeo de dilución podía comparar dólares.** F6 leía
`["Ordinary Shares Number", "Share Issued", "Common Stock"]`, y el tercero es un
**importe en moneda**, no una cantidad de acciones:

| ticker | acciones | Common Stock | ratio |
|---|---:|---:|---:|
| AAPL | 14.773.260.000 | 93.568.000.000 | 6,33 |
| KO | 4.301.608.845 | 1.760.000.000 | 0,41 |

Magnitudes distintas **y en direcciones opuestas**, así que el fallback ni siquiera
habría fallado de forma consistente — comparar el valor par año contra año no dice
nada sobre dilución. El fallback se fue: sin una cuenta real de acciones la señal no
tiene respuesta y lo dice. Nunca corrió, porque `Ordinary Shares Number` está en
**150 de 150** balances cacheados, que es justamente lo que vuelve barato el momento.

La tolerancia de ±2 % pasa de literal dentro de la comparación a
`PIOTROSKI.max_dilution_pct`.

Contrato: `tests/test_piotroski_signals_oracle.py`.

---

## U5-17 — El bootstrap alcanza la observación más reciente (2026-08-29)

`_simulate_paths` sorteaba los inicios de bloque con
`rng.integers(0, T - block_size)`. `integers` **excluye** su cota superior, así que
los inicios se detenían en `T - block_size - 1` y ningún bloque podía llegar a la
última barra. La observación que el modelo más obviamente debería usar —la más
nueva— era la única que nunca usaba.

Y no era sólo la última. La cobertura decaía en toda la cola (1, 2, 3, …, 3, 2, 1,
**0**) mientras la cabeza sube simétricamente desde 1, así que la ventana quedaba
**asimétrica sin razón**. El arreglo devuelve la simetría que un block bootstrap no
circular debería tener: la primera barra la alcanza un solo inicio, y ahora la
última también.

**Medirlo requirió cuidado.** Mover la cota superior cambia qué valores sortea el
*mismo* seed, así que una comparación antes/después no distingue un sesgo
sistemático de una re-aleatorización. Sobre doce semillas por ticker, la dirección
sigue a si las últimas semanas corrieron por encima o por debajo de la media propia
de cada uno:

| ticker | últimas 4 semanas | vs su media | la proyección estaba |
|---|---:|---:|---|
| **PFE** | +2,76 %/sem | +0,11 % | **6,96 % baja** |
| KO | +0,66 %/sem | +0,23 % | 0,79 % baja |
| INTC | +0,18 %/sem | +0,40 % | 0,73 % alta |

PFE es el caso que importa: casi **siete por ciento** de una proyección de retiro
perdido por un off-by-one, y perdido **hacia abajo** para una empresa cuyo tramo
reciente fue el mejor que tuvo.

`ENGINE_VERSION` → **`2026.08-tier4`**. Todo plan guardado se ajustó sobre una
ventana a la que le faltaba su barra más nueva, y el aviso de staleness lo dice. Los
dos tests de staleness **no** necesitaron edición: se hicieron relativos al
changelog en tier3 justamente para que un tier nuevo no obligara a tocarlos.

Contrato: `tests/test_bootstrap_coverage_oracle.py`.

---

## U5-1 — El F-Score dice que mide cambio, no nivel (2026-08-29)

El F-Score de Piotroski son nueve chequeos **año contra año** —¿es esta empresa más
rentable, menos endeudada y más eficiente **que el año pasado**?— diseñados para
separar ganadores de perdedores entre acciones baratas en un horizonte de **1 año**.
Mide **cambio, no nivel**: una empresa mediocre que mejoró puntúa alto y una
excelente que se mantuvo igual puntúa bajo.

El screener lo describía como *"9 chequeos de salud contable"*, que se lee como un
nivel —y como algo durable— en la pantalla donde la mayoría lo encuentra. La ficha
de Stock Analysis ya decía "YoY"; el help de la columna no, ni el README ni
`portfolio_optimizer.md`. Un solo `PIOTROSKI_HELP` los sirve a todos.

**Verificado: 0 scores y 0 acciones se mueven.** Los 13 que difieren del último
baseline son los 13 REITs de U5-4, que mergeó después de tomarlo — chequeado, no
asumido.

### La calibración queda abierta, con su evidencia

Esta fila **no** cierra la pregunta de fondo, que se reabre como **U5-1b**:

| componente | paga | qué mide |
|---|---:|---|
| Piotroski | 0–**12** | mejora contra el año pasado |
| moat | 0–**10** | ventaja competitiva durable |
| consistencia | 0–15 | estabilidad multi-año |

El motor paga **más** por «mejoró desde el año pasado» que por «tiene un foso», en
un producto de retiro. Medido sobre 150 equities: **31 %** cobra `bonus_strong` y
**24 cruzan el umbral de BUY sólo por ese bonus**.

Si eso está mal es una pregunta de calibración, y este proyecto todavía no puede
fundarla: `recommendation_outcome` tiene 22 filas, **todas a 30 días**, y una señal
pensada a 1 año no se juzga en 30. U5-1 arregló lo que se podía arreglar sin
outcomes —la descripción— y dejó los pesos escritos uno al lado del otro en
`PiotroskiConfig` para que quien retome empiece por la comparación.

Contrato: `tests/test_piotroski_label_contract.py`, con el mismo barrido de docs
vivos que las otras seis guardas de vocabulario.

---

## U5-16 — El descuento ARS se aplica por país, no por lista (2026-08-29)

`optimizer.py` tenía `_ARS_TICKERS = {YPF, PAM, CEPU, LOMA, TEO, EDN}` como literal,
y toda optimización conservadora o moderada multiplicaba esos seis scores por
`ars_risk_discount`.

**Medido sobre los 167 tickers de los universos shipeados, esa lista es exactamente
el conjunto que el feed marca `country == "Argentina"`.** O sea que estaba bien — y
bien **por coincidencia**, no por construcción. Esta fila no era un error de puntaje
vivo, y queda dicho así en vez de insinuar lo contrario: los mismos seis se
descuentan antes y después, verificado.

**Fallaba en la única población que no podía enumerar.** Los `custom_tickers` se
mergean al universo efectivo, así que un usuario que agregara GGAL, BMA, SUPV, BBAR,
TGS, CRESY o IRS —ninguno shipea en ningún universo— no recibía descuento alguno, y
el riesgo macro no distingue quién tipeó el símbolo. Los siete quedan alcanzados.

Y una lista mantenida a mano contra un campo que ya existe es **un mecanismo de
más**: `info["country"]` es lo que reporta el feed, y U3-8 ya había atado la tasa
impositiva a él dos filas atrás. *"A qué país está expuesta esta empresa"* pasa a
tener una sola respuesta en el repo.

Llegar ahí exigió que el país efectivamente **llegara**: `FundamentalResult` tenía
`sector` e `industry` pero no `country`, así que las filas del optimizer nunca lo
llevaban. Ahora sí, poblado donde se pobla el sector.

**Una fila sin país no se asume expuesta.** Desconocido no es Argentina — la misma
regla que U3-1 aplicó a una media móvil ausente.

El descuento en sí no se toca: su tamaño, su perilla de config y la exención del
perfil agresivo siguen igual, cada uno con su test.

Tres tests de `test_optimizer.py` declaraban *"YPF es argentina"* **por el símbolo**,
que es justo lo que dejó de determinar la exposición. Su sujeto no cambió, así que la
fixture ahora lleva un país, que es la forma honesta de decirlo.

Contrato: `tests/test_ars_discount_oracle.py`.

---

## U5-14 — La deriva es desconocida si el plan no se pudo cotizar entero (2026-08-29)

U2-3 le había dado esta regla al detector de alertas, con estas palabras:

> *"se niega a correr del todo cuando cualquier posición no tiene precio usable:
> una posición sin cotizar es **desconocida**, no 0 %, y tratarla como 0 deflacta
> el total e infla el peso de todas las demás."*

`compute_plan_vs_reality` —el **otro** camino, el que alimenta
`PLAN_HEALTH_DEGRADATION`— nunca recibió ese gate. Dividía el movimiento ponderado
por la suma de los pesos **que logró cotizar**, reescalando en silencio la parte
cubierta del plan al 100 %. El docstring de `drift_breakdown` ya decía que excluir
un precio faltante es tarea del caller; un caller la hizo y el otro no.

**La dirección es lo que lo vuelve grave.** Sobre un plan de cuatro posiciones donde
una del 10 % cae 40 % y no se puede cotizar:

| | deriva reportada |
|---|---:|
| real, todo cotizado | **+1,20 %** |
| renormalizada al 90 % cubierto | **+5,78 %** |

El desplome no sólo desaparece: el número se mueve hacia **lo tranquilizador**, y es
una métrica de salud. El plan se reporta derivando *menos* justo en el momento en que
una parte dejó de ser rastreable.

`weighted_delta_pct` pasa a ser `None` salvo que el plan entero se haya cotizado, y
el resumen incorpora `unpriced` para que una superficie pueda decir cuál símbolo y
por qué. **Suprimir el agregado no esconde nada**: las filas siguen listando todos
los símbolos con su precio en blanco, así que lo que se quita es un número que nadie
podía sostener, no la evidencia.

`compute_longitudinal_drift` ya filtraba los `None` de la tendencia, así que aguas
abajo no hizo falta cambiar nada — verificado en vez de asumido, incluido que un plan
que nadie puede cotizar **no** queda marcado como degradado: la ausencia de evidencia
no puede convertirse en evidencia de deterioro.

Contrato: `tests/test_plan_health_coverage_oracle.py`.

---

## U5-12 — La curva del tracker cubre lo que se tuvo (2026-08-29)

Dos defectos sobre el módulo que juzga la cartera propia del usuario.

**Prometía un IRR que nunca tuvo.** El encabezado anunciaba *"annualized return
(IRR/XIRR)"*, y la palabra `irr` aparecía **exactamente una vez** en el módulo: en
esa línea. Lo que se calcula es `(total_value / total_cost) ** (1/years) − 1`, con
`years` tomado de la **primera** compra de todo el portafolio. Un IRR pondera cada
flujo por su propia fecha; esto no pondera ninguno, así que 99.000 dólares
invertidos ayer reciben la antigüedad de una posición de 1.000 de hace cinco años.
Un retorno ponderado por dinero es X-02 y está fuera de alcance, así que el arreglo
es la etiqueta — el mismo patrón que U1-9 ya había usado **dos líneas más arriba en
este mismo docstring**, para el ratio que no es un Sortino.

**La curva le daba a cada posición cinco años de historia a su tamaño de hoy.**
`_build_equity_curve` multiplicaba cinco años de precios por `pos.shares` —el conteo
de *ahora*— sin importar la fecha de compra, así que una acción comprada el mes
pasado aparecía en el drawdown de 2021 a tamaño completo. De esa serie salen
**cuatro** métricas: Sharpe, ratio bajista, máximo drawdown y beta; una sola
historia fabricada llegaba a las cuatro.

Sobre una cartera corriente de dos posiciones —KO desde siempre, NVDA comprada hace
tres meses:

| | curva fabricada | ventana real |
|---|---:|---:|
| Sharpe | 1,04 | **1,91** |
| máximo drawdown | −20,3 % | **−3,2 %** |

La curva ahora arranca en la **última fecha de compra**, así que toda posición que
figura estuvo efectivamente en cartera durante toda la ventana. Verificado de punta
a punta: esa misma cartera da 13 semanas y Sharpe 1,91, y moviendo la compra a hace
tres días la ventana se reduce a nada y las métricas **se suprimen en vez de
estimarse**.

**Poner en cero cada posición antes de su compra** es la otra forma de mantener
honestos los conteos, y es peor: la compra entraría en la serie como un escalón, y
una compra no es un retorno. Medido, esa alternativa reporta **60,8 % de volatilidad
contra 18,8 %**. Tiene test propio, porque es el arreglo equivocado obvio y el
próximo que pase va a intentarlo.

Contrato: `tests/test_tracker_curve_oracle.py`.

---

## U5-4 — Un REIT juzgado con bandas de REIT (2026-08-28)

U2-6 arregló **qué** payout se le juzga a un REIT —FFO, no ganancias contables— y
dejó los umbrales a propósito, diciéndolo en `config.py`: *"REIT-specific bands are
U5-4's call, not this one's."* Esta es esa decisión.

**Payout.** Bandas de 40 % (excelente) y 75 % (sostenible) son números de empresa
industrial. Un REIT distribuye más del 90 % de su renta gravable **por ley** y lo
paga desde el FFO, así que ≤40 % no es raro: es estructuralmente imposible.
Ninguno de los 13 REITs cacheados alcanzaba la banda superior (el más bajo es
49 %), y cuatro recibían el aviso *"puede cortar el dividendo"* con payouts
ordinarios sobre FFO — O 82 %, EXR 81 %, PSA y WPC 78 %. Las bandas de REIT son
**70/90**, ancladas en lo que la obligación de distribuir hace posible. Son una
elección de calibración, no un hallazgo empírico, y config lo dice.

**PEG.** El feed lo construye sobre ganancias contables, que la depreciación
deprime — el mismo error de categoría que P/E vs P/FFO ya había corregido. Las
lecturas son artefactos: **PLD 128,04**, EQR 16,1, DLR 13,9. Los REITs promediaban
**0,5 de 7 puntos contra 2,3** del resto. Ahora no se puntúa, y se nombra
*inaplicable* en vez de *faltante*, porque "no lo buscamos" y "esto no mide nada"
son afirmaciones distintas. Construir un múltiplo ajustado por crecimiento sobre
P/FFO requeriría una serie de crecimiento de FFO y una calibración que este
proyecto todavía no puede fundar — la misma razón que `company_type` da para no
shipear un scorer bancario.

**Alcance medido sobre 164 tickers: se mueven exactamente 13 scores, y son
exactamente los 13 REITs.** Cuatro señales cambian, **en las dos direcciones**:

| ticker | score | señal |
|---|---:|---|
| O | 66,0 → 68,0 | HOLD → **BUY** |
| WELL | 67,5 → 68,5 | HOLD → **BUY** |
| PSA | 54,7 → 56,7 | REDUCE → **HOLD** |
| WPC | 55,5 → **53,5** | HOLD → **REDUCE** |
| AMT | 73,5 → **72,5** | (pierde 2 puntos de PEG que cobraba sobre un artefacto) |

WPC y AMT **bajan**: eran los dos únicos que cobraban puntos de PEG, y esos puntos
estaban construidos sobre ganancias deprimidas. Esto no es un regalo a los REITs.

**El invariante de U2-6 se preserva, no se debilita:** la dimensión de dividendos y
el riesgo *"may cut dividend"* siguen leyendo un solo número, y ahora los dos lo
obtienen de `max_payout_for(basis)`. Cuatro de sus tests afirmaban ese invariante a
través de un corte literal único; ahora lo afirman a través del corte de FFO, y uno
—que elegía 78 % justamente por estar entre el corte de config y el literal viejo—
se reescribió para decir lo que ahora es cierto: 78 % sobre FFO es normal, 92 % no.

Contrato: `tests/test_reit_bands_oracle.py`.

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
