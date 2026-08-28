# Contrato del prefiltro — el portero

> **Rol:** ideación / acuerdo de producto. No está implementado. No cambia scores, optimizer ni universos.
> **Para qué existe:** poder mirar un catálogo grande (cientos de nombres) sin hacerle a todos el examen largo que hoy corre el Screener.
> Las varas que cita son las que el producto **ya usa** en `config.py`. Este texto no inventa umbrales nuevos.

Orden de lectura = orden de decisión: **¿corre? → desvío C → preguntas 1–5 → embudo**.

---

## 1. Qué decide (y qué no)

Una sola pregunta:

> **¿Este nombre merece la entrevista larga de empresa?**

Nunca responde *¿lo compraría?*, *¿cuánto peso?* ni *¿es un gran negocio?*. Eso es la ronda 2 (score, moat, viento, señal) y el optimizer / el plan.

Un “sí” no es una tesis. Un “no” no es un SELL: es “no gastes la entrevista de empresa en esto, en esta corrida”.

---

## 2. Cuándo no corre

Una sola regla, sobre el **padrón crudo** (acciones + ETF + crypto, tal como viene la lista). El salto apaga **todo** el portero: C y las cinco preguntas.

| Entrada | Qué pasa |
|--------|----------|
| **&lt; 50** | El portero no existe en esa corrida. Cada nombre sigue el `full_analysis` de hoy (rama crypto por dentro; un ETF como SPY se sienta en el examen de empresa como ahora). |
| **≥ 50** | El portero corre — C primero, después 1–5 sobre acciones — aunque la lista no sea de “cientos”. |

Universos nombrados que ya cruzan el piso (`us_quality` 85, `dividend_focus` 66) no tienen atajo por ser “curados”. El default (`DEFAULT_TICKERS`, 39) queda bajo el salto: ahí no hay C ni preguntas.

“Cientos” es **para qué existe** el contrato, no un segundo piso.

El mismo ticker puede tomar camino distinto según el tamaño: SPY en 39 se entrevista como hoy; SPY en 85 es desvío C. No es un bug. El portero es una optimización de padrón grande; en padrón chico no se toca el pipeline que ya aguanta.

Hay **dos cincuentas**. Este salto cuenta el padrón crudo. El piso del embudo (§6) cuenta solo las acciones que se sentaron en 1–5, y solo cuando el portero corrió.

---

## 3. Dónde vive (y qué no es)

```
catálogo
    → ¿entrada < 50? sí → sin portero (full_analysis de hoy, sin C)
    → (solo si ≥ 50) puerta C (desvío ETF / índice / crypto reconocidos)
    → preguntas 1–5 (solo acciones)
    → entrevista de empresa: full_analysis (score, moat, viento, técnico, decisión)
    → eligible del optimizer (score ≥ 30, no poor)
    → pre_filter_top_k (20 / 30 / 45 según perfil)   ← ya existe; otro recorte
    → SLSQP → núcleo / plan
```

`pre_filter_top_k` vive en `ProfileConfig` y recorta **después** del score, antes de SLSQP. Este portero corre **antes** de la entrevista de empresa. No se llaman igual. Los 80 del embudo son la sala de **esa** corrida, no el plan.

**La sala es de una corrida, y una corrida tiene perfil.** Cambiar Conservador ↔ Agresivo es otra corrida: la puerta 5 puede haber dejado un set distinto. No se recicla una sala Conservadora para un plan Agresivo. Hoy el Screener cachea y el Optimizer elige perfil después; este contrato no cambia ese código. El acuerdo es: si el portero existe, la sala sigue al perfil de la corrida.

**Qué pide a la fuente.** Un `FundamentalResult` flaco: precio, barras semanales, las diez métricas clave, y el yield solo si la puerta 5 está prendida. Con eso también se clasifica C. No pide score, moat, Piotroski, técnico, viento, decisión, IA ni comité. El ahorro no es evitar la red: es no sentar a cientos de acciones en el examen largo. Cómo se cachea o se parte en lotes no es de este contrato.

ROE, D/E y yield se leen como ya los guarda el producto: un 0 crudo de Yahoo en ROE o D/E es `None` (`compute_data_quality` / `FundamentalResult`). El portero no lo trata como “ROE = 0” ni como “sin deuda”. El yield de la puerta 5 es el del libro (`PortfolioOptimizer._clean_div_yield`: fuera de 0–15 % = 0).

---

## 4. Puerta C — desvío (solo si el portero corre)

Si el portero no está levantado, esta puerta no existe. Si está, se decide **antes** de las cinco preguntas. No es un gris del examen de empresa; es el tenedor del padrón.

¿Es una acción que rinde este examen, o un ladrillo / crypto que el producto ya trata aparte?

El producto no lee `quoteType`. Este contrato no inventa esa lectura ni una lista nueva. Un nombre es C **solo** si pega en uno de los tres ganchos del código:

- `is_crypto` / `CRYPTO_TICKERS`;
- `sector` en `("Crypto", "Index", "ETF")` — la misma rama de `compute_data_quality` que solo pide precio (hoy el fallback a `"Index"` cubre `SECTOR_MAP["ETF"]`: `SPY`, `QQQ`, `VTI`, `BND`);
- `_ETF_TICKERS` de `portfolio/optimizer.py` (hoy `SPY`, `QQQ`, `VTI`, `BND`, `GLD`, `SLV`, `TLT`, `IEF` — la lista vive en el código; si se suma uno, este texto no se reescribe para copiarlo).

**Desvío.** No se sienta en 1–5. No se cuenta como “no pasó” ni como finalista de empresa.

- Crypto reconocido sigue el camino que ya existe (`full_analysis` → `CryptoAnalyzer`). Son pocos; no son el problema de padrón.
- ETF reconocido no entra a SLSQP. Sirve para el núcleo (mercado, internacional, duration, inflación, oro), no para el concurso de moat.
- Un C **sin precio** sigue siendo C: no es rechazo de la pregunta 1, y no es ladrillo usable hasta que tenga precio.

**No es C.** Cualquier otro ticker —incluidos ETF de dividendos o país de universos nombrados (`SCHD`, `VGT`, `VYM`, `HDV`, `DGRO`, `NOBL`, `EWZ`, `EWW`, `ILF`) y los `custom_tickers` que no pegan en esos ganchos— se sienta en 1–5. Si no tiene estados, la pregunta 3 lo marca `poor` y lo echa. Eso no es desvío; si se acumula, el embudo lo lee como catálogo comido.

No hay clase “bono”. `BND`, `TLT` e `IEF` son C porque están en `_ETF_TICKERS`. Los `custom_tickers` no ganan atajo: C o el mismo examen (hoy ya se badgean como experimentales).

Contar un C como “no pasó el portero de acciones” y a la vez como “finalista de empresas” está prohibido: ensucia el embudo.

---

## 5. Las cinco preguntas (solo acciones)

Solo las responde quien no fue desvío C. En este orden. La primera que falla echa. No se promedian. No hay “casi pasa”, opinión, noticia ni modelo de lenguaje.

Un REIT o un banco que es equity cotizado rinde **este mismo examen**. No hay umbral por sector. Si un catálogo de bancos / REIT se come, es síntoma del embudo: se cambia el catálogo, no la vara.

Todo lo que no es sí/no limpio cae en **una** de dos: crítico vacío → afuera (no se adivina); secundario → pasa con marca “mirar con lupa en la ronda 2”. No hay una tercera de “lo veo después”. La marca viaja con el nombre; el portero no puntúa. C ya se decidió arriba: un desvío no se reetiqueta como rechazo por falta de precio o de estados.

La frescura es una dimensión **aparte** de la completitud. Datos más viejos que `DATA_QUALITY.stale_warning_hours = 48` no echan: marca “refrescar en la ronda 2”.

### Pregunta 1 — ¿Hay un precio usable y un símbolo que existe?

**Qué mira.** Si el nombre existe y tiene un precio con el que anotar un renglón. No mira quality, market cap ni volumen: el producto no tiene ese piso; este contrato no lo inventa.

**Vara.** Sin `current_price` > 0 el nombre es inutilizable (la misma regla de calidad de datos para ETF / índice / crypto). Un símbolo que la fuente no reconoce no tiene precio usable: es el mismo fallo.

`OPTIMIZER.min_weight_pct = 1.0` y los techos `max_position_pct` (Conservador 8 %, Moderado 12 %, Agresivo 18 %) explican *para qué* el producto quiere renglones reales. No son un test del ticker: cualquier nombre con precio puede ser el 1 % de un plan.

| | |
|--|--|
| **Pasa** | `current_price` > 0 y el símbolo es uno que la fuente reconoce. |
| **No pasa** | No hay precio usable, o el símbolo no resuelve. |

---

### Pregunta 2 — ¿Hay historial de precios suficiente para pensar en décadas?

**Qué mira.** Barras semanales de **este** nombre (`hist[close].dropna()`), no la calidad del negocio y no el `n_weeks` del libro (filas de retorno del portafolio). El portero no arma el libro.

**Vara.**

- Inclusión por ticker en el MC: `_load_returns` en `portfolio/monte_carlo.py` solo mete a quien tiene `len(s) >= 52` barras semanales. Por debajo, ese nombre no entra a la simulación.
- `MONTE_CARLO.min_history_weeks = 104` es un aviso de *libro*. El portero lo reutiliza **por nombre**, igual que la puerta 5 reutiliza el 3.5 % de libro. No afirma que este ticker apague el aviso del portafolio.
- El `n_weeks < 52` que cancela el MC es métrica de libro, no test de este ticker.
- `BACKTEST.min_history_weeks = 52` existe en `config.py` y hoy **no** es un gate. El backtest no es puerta.

| | |
|--|--|
| **Pasa** | 104 barras semanales o más. |
| **No pasa** | Menos de 52 barras (el MC ni lo incluye). |
| **Gris** | 52–103 barras: incluible en el MC; marca “historial corto: menos de dos años de barras”. El aviso del libro depende de quién más esté en la cartera. |

---

### Pregunta 3 — ¿Los números financieros son usables? (no es un score)

**Qué mira.** Si hay con qué hablar en la entrevista, y un piso grosero reutilizado de `THRESHOLDS.roe_min`. No calcula el 0–100. No mira moat, Piotroski, técnico ni IA.

**Vara.**

- Completitud, misma política de calidad de datos:
  - `DATA_QUALITY.poor_missing_fields = 6` — 6 o más métricas clave vacías, o sin estados, es `poor`.
  - `DATA_QUALITY.partial_missing_fields = 3` — 3 a 5 vacías es `partial`.
  - Métricas clave fijas: ROE, ROIC, margen neto, margen bruto, deuda/equity, current ratio, P/E, P/B, CAGR de ventas 5Y, CAGR de EPS 5Y. El dividendo **no** está: un growth sin yield no es un hueco.
- `DATA_QUALITY.exclude_poor_from_optimizer = True` y, en decisiones, un `poor` no puede sostener un BUY. El portero no entrevista a quien el producto ya declara inútil para elegir cartera.
- `THRESHOLDS.roe_min = 8 %` es una **banda de scoring** (0 de 8 puntos de ROE y un warning). El examen largo **no** echa ni bloquea por ROE &lt; 8 %: no hay safety block; el optimizer pide `adjusted_score ≥ 30` y no-`poor`. Un ROE 6 % puede terminar BUY y entrar a SLSQP. El portero reutiliza el 8 % como puerta grosera **por nombre**, más estricta que el scoring, a propósito.
- `OPTIMIZER.min_score_threshold = 30` es el piso de la *entrevista*, no de esta puerta. Se cita para no inventar otro número de “calidad mínima”.

| | |
|--|--|
| **Pasa** | No es `poor`, y si `FundamentalResult.roe` está (no es `None`), es ≥ 8 %. |
| **No pasa** | Es `poor` (6+ huecos o sin estados), o el ROE **conocido** (campo no-`None`) es &lt; 8 %. |
| **Gris** | `partial` (3–5 huecos) y el ROE, si está, cumple el 8 %: marca “mirar con lupa”. Un hueco suelto —incluido `roe is None` (Yahoo mandó 0 o vacío; el analizador lo colapsa)— también se marca; no se adivina el 8 %. |

---

### Pregunta 4 — ¿La deuda es un ancla?

**Qué mira.** Solo `FundamentalResult.debt_equity`. No arma el score de salud.

**Vara.**

- `THRESHOLDS.max_debt_equity_acceptable = 2.0` — `de <= 2.0` sigue siendo “aceptable” en el scoring.
- `STRATEGY.max_debt_equity = 3.0` — bloqueo duro del motor cuando `debt_equity > 3.0`. Si la entrevista ya lo bloquearía, el portero no lo hace esperar.

Si el campo es `None` (incluido el 0 crudo colapsado), no se inventa: es un hueco de la pregunta 3. Un hueco solo de deuda no echa; un `poor` por acumulación, sí. Un D/E conocido &gt; 3.0 echa aunque “la deuda sea el negocio”.

| | |
|--|--|
| **Pasa** | Deuda/equity conocida ≤ 2.0. |
| **No pasa** | Deuda/equity conocida &gt; 3.0. |
| **Gris** | `2.0 < D/E ≤ 3.0`: marca “deuda alta; la entrevista tiene que verla”. El 2.0 exacto es pasa limpio. El 3.0 exacto es gris (`>` 3.0, no `≥`). |

---

### Pregunta 5 — ¿Aporta ingreso, *solo si esta corrida es Conservadora*?

**Qué mira.** El yield, y únicamente cuando el perfil de **esta corrida** ya exige un piso de libro de 3.5 %. Si no lo exige, **esta puerta no existe**: el nombre ya pasó si cruzó las cuatro anteriores.

**Se enciende** solo si el perfil es Conservador (`OPTIMIZER_PROFILES["conservative"]` / `CONSERVATIVE_PROFILE.min_dividend_yield_pct = 3.5`). Ese es el único perfil cuyo piso de libro es 3.5 % siempre. Como la sala es de esa corrida, no envenena un plan Moderado o Agresivo: esos son otra corrida, con esta puerta apagada.

**No se enciende** (aunque alguien lo pida de palabra):

- Moderado (piso de libro 2.5 %) y Agresivo (1.5 %). Esos pisos viven en el optimizer.
- `UserPreferences.dividend_preference`. Se guarda y se muestra en el onboarding; **el motor no la usa para ningún piso ni constraint**. El portero no inventa ese acoplamiento. Si un día el código la usa para subir el piso de libro a 3.5 %, este contrato se reescribe; no al revés.
- El glide path que sube el piso de libro a 3.5 % cuando la meta más cercana tiene horizonte ≤ 3 años (`_derive_constraints_from_goals`). Es restricción de *libro*, no puerta por nombre.

**Conservador + preferencia “crecimiento”.** La puerta sigue prendida. El perfil no se deshace. Quien no quiere filtro de cupón cambia de perfil (otra corrida).

**Vara.**

- `CONSERVATIVE_PROFILE.min_dividend_yield_pct = 3.5` — piso ponderado del *libro*. El portero lo reutiliza por nombre. No se inventa un 4 % ni el sweet spot de scoring (`div_yield_sweet_spot_low/high` 1.5 / 4.0).
- El número es el mismo que el optimizer mete al libro: `PortfolioOptimizer._clean_div_yield` (fuera de 0–15 % = 0). Un 20 % impreso no “pasa como ingreso”.
- El yield vacío no es hueco de calidad (`FundamentalResult.dividend_yield` es `None` si el crudo no es &gt; 0). Puerta apagada: no echa. Puerta prendida: vacío, cero o limpiado a 0 no aporta al 3.5 %.

Esta puerta es más estricta que el optimizer (él pide 3.5 % *promedio del libro*). Está bien: el portero es grosero. Un libro puede mezclar 2.8 % y 5 %; el portero echa al 2.8 %. Si Conservador deja ~15 en un catálogo de growth, no se baja el 3.5 %: se cambia el catálogo. El embudo diagnostica; no se negocia la vara en caliente.

| | |
|--|--|
| **Pasa (prendida)** | Yield limpio ≥ 3.5 %. |
| **No pasa (prendida)** | Yield limpio &lt; 3.5 %, o vacío / cero. |
| **Pasa (apagada)** | No se pregunta. |

---

## 6. Cómo leer el embudo

El portero llena una sala de entrevista **de esta corrida**. Esa sala **no es el plan**: después, el optimizer recorta con `min_score_threshold`, `exclude_poor_from_optimizer` y `pre_filter_top_k` (20 / 30 / 45) hasta un núcleo de ~10–15.

Se cuenta **solo sobre acciones que rindieron 1–5**. Los desvíos C no suman.

| Señal | Número | Qué significa |
|-------|-------:|---------------|
| Piso | **50** finalistas | La vara o el catálogo se comieron la diversidad. |
| Blanco | **~80** | Sala razonable: cabe el examen largo y todavía sobra después del recorte del optimizer. |
| Techo | **120** | Por encima, la ronda 2 vuelve a ser el problema que este contrato quiere evitar. |

Lectura del resultado, no negociación de la vara:

- **~300.** Vara blanda, o el catálogo ya era de quality. No se suben umbrales nuevos. Se revisa si 3–4 se aplican, o se acepta que no hacía falta portero (entrada &lt; 50, o “85 curados, pasan 70”).
- **~15.** Universo comido. Misma respuesta siempre (cambiar el catálogo o no correr esa puerta sobre esa lista; nunca bajar la vara):
  - puerta 5 (Conservador, 3.5 % por nombre) sobre growth;
  - bancos / REIT frente al ROE 8 % o al D/E 3.0;
  - nombres sin historia o sin estados;
  - ETF que el código no reconoce como C y mueren `poor` en la pregunta 3.
- **50–120.** El acuerdo se cumplió. Esos nombres van a la entrevista de **esta** corrida. Los lotes, si algún día existen, son logística; no cambian las puertas.

85 curados que pasan 70 no es un fracaso del techo: ese universo no necesitaba portero. El salto de §2 no se lo ahorra (85 ≥ 50); el embudo lo diagnostica después.

---

## 7. Qué se deja anotado (memoria, no implementación)

De cada nombre, una línea:

- pasó / no pasó / desvío (puerta C);
- qué puerta lo decidió (C primero; si es acción, cuál de las cinco);
- las pocas cifras usadas (precio sí/no, barras de historia, nivel de calidad, ROE, deuda/equity, yield limpio si la puerta 5 estaba prendida);
- las marcas de gris, si las hay;
- fecha, perfil de la corrida, y si la puerta 5 estaba prendida.

Alcanza para explicar “¿por qué no está esta utility?” y para no volver a preguntarle a la fuente las mismas 500. Cómo se guarda (archivo, lotes, cache) **no es parte de este contrato**.

Un C sin precio se anota como desvío, no como “no pasó pregunta 1”.

---

## 8. Qué queda explícitamente afuera

- Implementar el portero, los lotes, más workers o un catálogo de 500.
- Cambiar un número de `config.py`. Si una vara se mueve en config, este contrato se reescribe; no al revés.
- Inventar un piso de market cap o de volumen.
- Inventar un examen distinto para bancos, REIT o cualquier sector.
- Inventar un detector de ETF/bono/`quoteType` más ancho que `is_crypto`, `sector` y `_ETF_TICKERS`.
- Acoplar `UserPreferences.dividend_preference` a una puerta. El motor hoy no la usa.
- Encender la puerta 5 por el glide path (horizonte ≤ 3 años). Es constraint de libro.
- Confundir este portero con `pre_filter_top_k`.
- Reciclar la sala de una corrida Conservadora para un perfil que no es Conservador.
- Lentes de cartera (“sin Magnificent 7”, techo de tech, mínimo internacional). Eso es *después* de la entrevista.
- Una segunda pasada de IA o de comité. Eso es sobre los elegidos, no sobre el padrón.
- Elegir cuáles son las 500.

---

## 9. Acuerdos que este texto ya cerró

No se reabren. Si el código cambia, se enmienda el texto; no se vuelve a discutir el principio.

| Tema | Acuerdo |
|------|---------|
| Puerta 1 y el 1 % | El test es precio usable + símbolo que existe. `min_weight_pct` y `max_position_pct` son contexto, no un chequeo del ticker. |
| Costo de las puertas 2–4 | El portero pide precio, historia y las 10 métricas. El ahorro es saltar score / moat / técnico / IA / comité, no evitar la red. |
| Puerta 5 más estricta que el libro | Aceptado. 3.5 % por nombre cuando la corrida es Conservadora. ~15 finalistas es síntoma de catálogo. |
| Conservador + “crecimiento” | La puerta 5 sigue prendida. El perfil no se deshace. |
| `dividend_preference` | No enciende la puerta 5. El motor no la usa. |
| Glide path (horizonte ≤ 3 años) | No enciende la puerta 5. Es constraint de libro. |
| Bancos y REIT | Mismo examen. Sin umbral por sector. Un catálogo de bancos comido es síntoma del embudo. |
| Universo default (39) | No activa el portero (padrón crudo &lt; 50). |
| Salto &lt; 50 vs “cientos” | El salto es solo padrón crudo &lt; 50 y apaga **todo** el portero (C incluida). ≥ 50 corre, también en universos curados de 66 u 85. “Cientos” es para qué existe el contrato, no un segundo piso. En padrón chico rige el `full_analysis` de hoy; el mismo ETF puede desviar solo cuando N ≥ 50. |
| Dos cincuentas | Salto = largo del padrón crudo. Embudo = solo acciones que se sentaron en 1–5. |
| Lista de ETF / C | C son solo `is_crypto`, `sector` ∈ {Crypto, Index, ETF} y `_ETF_TICKERS`. El resto rinde 1–5. No hay clase “bono”. Este texto no congela la lista. |
| C va primero | Clasificar C antes de 1–5. Un C sin precio es desvío, no un rechazo de pregunta 1. |
| C y la entrevista | C salta el examen de empresa. Crypto reconocido sigue `CryptoAnalyzer`. ETF reconocido no se entrevista como empresa. |
| Sala por corrida | El portero y la sala son del perfil de esa corrida. Cambiar de perfil es otra corrida. |
| Pregunta 2 y el MC | Cuenta barras semanales de **este** nombre. Fallo &lt; 52 porque `_load_returns` no lo incluye. Gris 52–103. Pasa ≥ 104 reutilizando `MONTE_CARLO.min_history_weeks` por nombre. No se cita el `n_weeks` del libro ni se afirma que este ticker calle el aviso del portafolio. El backtest no es puerta. |
| ROE 8 % | Puerta grosera más estricta que el scoring. El examen largo no echa por `roe_min`. |
| 0 vs `None` | Q3/Q4 leen `FundamentalResult` como `compute_data_quality` (0 crudo → `None`). No se trata un 0 colapsado como ROE conocido ni como D/E = 0. |
| D/E = 2.0 | Pasa limpio si ≤ 2.0. Gris si 2.0 &lt; D/E ≤ 3.0. Falla si &gt; 3.0. |
| Yield de la puerta 5 | El mismo que el libro: `_clean_div_yield` (fuera de 0–15 % = 0). |
| Dos recortes | Portero (antes de la entrevista de empresa) ≠ `pre_filter_top_k` (después del score). Los 80 son la sala de esa corrida, no el plan. |

---

*Acuerdo de producto. Las cifras las manda `config.py`; si este texto y el código discrepan, gana el código y hay que enmendar el texto.*
