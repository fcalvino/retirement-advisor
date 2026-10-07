# Glosario — Retirement Advisor

El vocabulario del dominio: qué significa cada término cuando lo usa la app, el
código o la documentación. No describe implementación; para eso está
`docs/CONTEXT.md`.

## Estimación y postura

**Estimación**:
Lo que la app cree que es probable que pase — cuánto puede rendir un activo,
cuánto puede oscilar, qué probabilidad de éxito tiene una meta. Es la misma para cualquier inversor que mire
el mismo activo o el mismo plan.
_Evitar_: proyección conservadora, escenario ajustado

**Postura**:
Lo que el inversor decide hacer con una Estimación según cuánto riesgo tolera:
cuánto concentrar, qué Exigencia ponerle al plan, cuándo vender. Vive en el
Perfil y nunca modifica una Estimación.
_Evitar_: sesgo, haircut, filosofía conservadora

**Objetiva** (dicho de una Estimación):
Sin ajuste deliberado hacia arriba ni hacia abajo, derivada de Fuentes declaradas
y sometida a Calibración donde el horizonte lo permite. No significa «más
optimista»: puede salir más pesimista que una Estimación conservadora.
_Evitar_: neutral, realista

**Exigencia**:
La probabilidad de éxito que el inversor le pide a su plan («que funcione en el
80 % de los futuros»). Es Postura, no Estimación.
_Evitar_: meta de éxito, objetivo de éxito

**Perfil**:
El conjunto de la Postura de un inversor: topes de posición, aversión al riesgo
al optimizar, Exigencia. Dos inversores con Perfiles distintos ven la misma
Estimación y deciden distinto.
_Evitar_: perfil de retorno, perfil de proyección

**Margen de seguridad**:
El descuento sobre el valor estimado que un inversor exige antes de comprar. Es
Postura: vive en el Perfil, no en la Estimación del valor.

**Señal**:
La acción sugerida para un activo (STRONG BUY … SELL). Es un ranking relativo
dentro del universo, no una probabilidad: no está calibrada hasta que el track
record alcance para hacerlo.
_Evitar_: predicción, probabilidad de suba

## Incertidumbre

**Azar**:
La variación de resultados que existe aunque la Estimación sea correcta: el
rango de futuros posibles de una misma Estimación.
_Evitar_: escenario, riesgo (a secas)

**Mala racha** / **Buena racha**:
El p10 y el p90 de una proyección: el Azar dentro de un mismo Escenario, 1 de cada
10 caminos termina debajo / arriba. En pantalla, «Mala racha (p10)» y «Buena racha
(p90)» (`BAD_RUN_LABEL` / `GOOD_RUN_LABEL`, EO-4c-2).
_Evitar_: escenario pesimista / optimista (eso es Desacuerdo entre Fuentes)

**Escenario**:
Una Estimación tomada desde la Fuente más pesimista, la central o la más
optimista. Los Escenarios expresan Desacuerdo, no Azar; cada uno tiene el suyo.
_Evitar_: referencia realista, proyección conservadora

**Escenario de planificación**:
El Escenario sobre el que se calculan las cifras de un plan (ahorro necesario,
semáforo, salud). Es Postura: lo fija el Perfil — el pesimista para Conservador,
el central para los demás — y el inversor puede cambiarlo.

**Clase de activo**:
El grupo en el que las Fuentes externas estiman rendimientos (acciones de EE.UU.,
emergentes, bonos…). La Estimación de un activo parte de la de su Clase y se
aparta de ella sólo en la medida de su propia evidencia.

## Evidencia

**Fuente**:
Un origen declarado de evidencia que alimenta una Estimación — la historia de
precios, la valuación actual, las proyecciones publicadas de gestoras, el comité.
Toda Fuente tiene fecha y procedencia.

**Fuente declarada ausente**:
La admisión explícita de que una Clase de activo no tiene Fuente externa creíble
(hoy, cripto). No se inventa un central: sólo hay Escenarios, y la interfaz lo
rotula «sin Fuente externa».
_Evitar_: supuesto genérico, valor por defecto

**Desacuerdo**:
El rango entre lo que dicen las Fuentes sobre una misma Estimación. Se muestra
siempre junto a la Estimación central; esconderlo es una forma de sesgo.
_Evitar_: dispersión, incertidumbre (a secas)

**Trazabilidad**:
La propiedad de que todo ajuste numérico sobre una Estimación tenga una Fuente
o un dato que lo respalde.

**Calibración**:
La medida de si las probabilidades que la app declaró se cumplieron con esa
frecuencia. Sólo es medible en horizontes cortos (señales, rangos anuales); en
horizontes de retiro rige la Trazabilidad.
