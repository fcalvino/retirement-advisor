# IDEA-5: ganancia de capital al vender, residente fiscal argentino (reglas)

- **Fecha**: 2026-10-10
- **Alcance**: resultado por venta de acciones, CEDEARs, ADRs, ETFs y cripto de una **persona humana residente fiscal argentina** que invierte a título personal (no empresa unipersonal ni sujeto del art. 53 de la ley). Afuera: dividendos, intereses, bienes personales, derivados, inmuebles, FCI argentinos.
- **Estado**: paso 1 de la fila IDEA-5 IMPUESTOS. Sólo reglas. Ninguna línea de código cambia por este documento.
- **No es asesoramiento fiscal.** Es una lectura de normas para decidir el diseño de una app personal; la liquidación real la hace un contador.

Convenciones:

- «LIG» = Ley de Impuesto a las Ganancias, texto ordenado 2019 (Decreto 824/2019), en el texto actualizado de InfoLEG consultado el 2026-10-10. La última modificación que muestra ese texto es la **Ley 27.802 (B.O. 6/3/2026)**.
- «DR» = reglamentación de la LIG aprobada por el Decreto 862/2019, en el texto de la Biblioteca Electrónica de ARCA consultado el 2026-10-10. La ficha de esa norma registra modificaciones hasta los Decretos 398/2026 y 406/2026; ninguna toca los artículos del DR que cita este documento (86 a 91, 160, 245 a 247, 262, 286).
- «ABC» = consultas frecuentes de ARCA (servicioscf.afip.gob.ar/publico/abc), citadas por su número de consulta y su fecha de publicación. Son criterio del organismo, no norma.
- «párr.» cuenta los párrafos del artículo tal como aparecen en el texto actualizado.
- Cada afirmación lleva su cita. Lo que es lectura mía de varias normas juntas dice **«Interpretación»**. Lo que no pude confirmar en una primaria dice **«NO CONFIRMADO»** y lleva un número `NC-n` que se repite en §5.

---

## §1 Reglas

### 1.0 Marco: qué está gravado y dónde se clasifica

- Son ganancias, cualquiera sea el sujeto, «los resultados derivados de la enajenación de acciones, valores representativos y certificados de depósito de acciones y demás valores, cuotas y participaciones sociales —incluidas cuotapartes de fondos comunes de inversión […]—, monedas digitales, títulos, bonos y demás valores». LIG art. 2, inc. 4. Sin nota de modificación en el texto actualizado: vigente desde el t.o. 2019.
- Enajenación es «la venta, permuta, cambio, expropiación, aporte a sociedades y, en general, todo acto de disposición por el que se transmita el dominio a título oneroso». LIG art. 3, 1er párr.
- Para una persona humana son ganancias de **segunda categoría**: LIG art. 48, inc. k). Sin nota de modificación.
- Se imputan al año fiscal en que se **perciben**: LIG art. 24, inc. b), 2º párr. («Las ganancias a que se refieren los artículos 95, 98 y 99 se imputarán al año fiscal en que hubiesen sido percibidas»). Año fiscal = año calendario: LIG art. 24, 1er párr.

**La fuente decide el régimen.** Es la pregunta que define todo lo demás:

- Acciones, cuotapartes, monedas digitales, títulos y demás valores son de **fuente argentina** «cuando el emisor se encuentre domiciliado, establecido o radicado en la REPÚBLICA ARGENTINA». LIG art. 7, 1er párr.
- Los «valores representativos o certificados de depósito de acciones y de demás valores» (CEDEARs, ADRs) son de fuente argentina «cuando el emisor de las acciones y de los demás valores se encuentre domiciliado, constituido o radicado en la REPÚBLICA ARGENTINA, cualquiera fuera la entidad emisora de los certificados, el lugar de emisión de estos últimos o el de depósito». LIG art. 7, 2º párr.
- **Interpretación**: un CEDEAR (certificado emitido en Argentina sobre una acción extranjera) es de **fuente extranjera**; un ADR de una empresa argentina (YPF, GGAL en Nueva York) es de **fuente argentina**. Las dos cosas salen del art. 7, 2º párr.: manda el domicilio del emisor de la acción subyacente, no dónde cotiza el certificado.
- Fuente argentina → impuesto cedular, LIG Título IV, Capítulo II (arts. 95 a 101; el de enajenación es el art. 98). Fuente extranjera → LIG Título VIII («Ganancias de fuente extranjera obtenidas por residentes en el país»), con la alícuota del art. 94, 3er párr.

### 1.1 Qué ventas gravan y cuáles están exentas

**La exención: LIG art. 26, inc. u).**

- 1er párr.: exentos «los resultados provenientes de operaciones de compraventa, cambio, permuta o disposición de acciones, valores representativos de acciones y certificados de depósito de acciones, obtenidos por personas humanas residentes y sucesiones indivisas radicadas en el país», salvo que sean atribuibles a sujetos de los incs. d) y e) y del último párr. del art. 53.
- 2º párr.: la exención aplica sólo «en la medida en que (a) se trate de una colocación por oferta pública con autorización de la COMISIÓN NACIONAL DE VALORES […]; y/o (b) las operaciones hubieren sido efectuadas en mercados autorizados por ese organismo bajo segmentos que aseguren la prioridad precio tiempo y por interferencia de ofertas; y/o (c) sean efectuadas a través de una oferta pública de adquisición y/o canje autorizados por la COMISIÓN NACIONAL DE VALORES».
- Último párr., incorporado por la **Ley 27.541, art. 34** (B.O. 23/12/2019; el artículo dice «con aplicación a partir del periodo fiscal 2020»): para los valores del art. 98 «no comprendidos en el primer párrafo de este inciso», las personas humanas residentes «también quedan exentos por los resultados provenientes de su compraventa, cambio, permuta o disposición, en la medida que coticen en bolsas o mercados de valores autorizados por la Comisión Nacional de Valores».
- Para fuente extranjera: «Las exenciones otorgadas por el artículo 26 que, de acuerdo con el alcance dispuesto en cada caso puedan resultar aplicables a las ganancias de fuente extranjera, regirán respecto de las mismas» con las exclusiones que enumera (incs. h, i, m, t; **ninguna toca el inc. u)**). LIG art. 134.
- Reglamento: «Los resultados obtenidos con motivo de la enajenación de acciones emitidas por sociedades del exterior, que cumplan las condiciones del segundo párrafo del inciso u) del artículo 26 de la ley, resultan alcanzadas por las disposiciones del primer párrafo de ese inciso, cualquiera fueran los mercados donde la persona humana residente o sucesión indivisa radicada en el país las hubiese adquirido o suscripto». DR art. 89, 2º párr.
- Reglamento: si una persona humana convierte certificados de depósito que **no** cumplen el inc. u) 2º párr. en las acciones subyacentes que sí lo cumplen (o al revés), la conversión es «una transferencia gravada […] al valor de plaza a la fecha de su conversión». DR art. 87, 1er y 2º párr.
- **Criterio de ARCA sobre el mercado del exterior** (ABC 24755223, publicada el 17/06/2026, en la categoría «Impuesto Cedular - Ley 27.430 › Renta Financiera»): los resultados de compraventa de «acciones, valores representativos de acciones y certificados de depósito de acciones, obtenidos por personas humanas residentes […], que hubieran sido efectuadas en mercados bursátiles del exterior fuera del ámbito de la Comisión Nacional de Valores (CNV) se encuentran excluidos de la exención dispuesta en el art. 26), inciso u)», porque no cumplen el 2º párr. **Interpretación**: el DR art. 89 hace irrelevante dónde se **compró**; según ARCA, lo que decide es dónde se **vende**.
- La Ley 27.541, art. 33 (la otra norma de esa ley que se suele citar en esta discusión) sustituye el inc. h) del art. 26 (intereses de depósitos), no el inc. u). Ley 27.541, art. 33.

Caso por caso:

| Caso | Fuente | Resultado | Cita |
|---|---|---|---|
| Acción de emisor argentino con oferta pública CNV, vendida en BYMA | Argentina (art. 7, 1er párr.) | **Exenta**: cumple (a) y (b) del inc. u) 2º párr. | LIG art. 26 u), 1er y 2º párr. |
| Acción argentina que no cumple el inc. u) 2º párr. (sin oferta pública, o vendida fuera de mercado CNV con prioridad precio-tiempo) | Argentina | **Gravada** | LIG art. 98, 1er párr., inc. c) |
| CEDEAR vendido en BYMA | Extranjera (art. 7, 2º párr.) | **Exento según el texto**: el inc. u) 1er párr. nombra los «certificados de depósito de acciones», BYMA cumple (b), y el art. 134 extiende el inc. u) a fuente extranjera. **NO CONFIRMADO (NC-3)** que ARCA lo lea así: ver abajo | LIG arts. 7, 26 u), 134 |
| CEDEAR de un ETF (representa cuotapartes de un fondo, no acciones) | Extranjera | **NO CONFIRMADO (NC-4)**: no es «certificado de depósito de acciones» del 1er párr.; podría entrar por el último párr. (Ley 27.541 art. 34), que habla de valores «alcanzados por las disposiciones del artículo 98», y el art. 98 es de fuente argentina | LIG arts. 26 u) último párr., 98, 134 |
| Acción o ETF del exterior, comprado y vendido en un broker del exterior | Extranjera (art. 7, 1er párr.) | **Gravada**: vendida en un mercado del exterior fuera de la CNV, queda afuera de la exención (ABC 24755223) | LIG arts. 48 k), 94 3er párr.; ABC 24755223 |
| ADR de emisor argentino (p. ej. YPF en NYSE), vendido en el exterior | Argentina (art. 7, 2º párr.) | **Gravado según ARCA**, exención NO CONFIRMADA en una norma (NC-18): el ABC 24755223 nombra los «certificados de depósito de acciones» vendidos en mercados del exterior fuera de la CNV entre los excluidos. Cae en el cedular, art. 98, inc. c) | LIG arts. 7, 26 u), 98 c); ABC 24755223 |
| Cripto (monedas digitales) | **NO CONFIRMADO (NC-6)**: el art. 7 usa el domicilio del emisor y una cripto como bitcoin no tiene emisor | **Gravada** en cualquiera de las dos fuentes: el inc. u) no nombra monedas digitales, y su último párr. pide cotizar en mercados autorizados por la CNV | LIG arts. 2 inc. 4, 7, 26 u), 94 3er párr., 98 |

**Por qué se discute el CEDEAR.** El art. 98 grava sólo la ganancia «de fuente argentina» (1er párr.) y el CEDEAR es de fuente extranjera (art. 7, 2º párr.), así que su venta no cae en el cedular sino en el Título VIII, con el 15 % del art. 94, 3er párr. La exención sobrevive sólo si el inc. u) «puede resultar aplicable» a fuente extranjera (art. 134). El texto del inc. u) no la restringe a fuente argentina y el DR art. 89, 2º párr. exime acciones de sociedades del exterior que cumplen el 2º párr. «cualquiera fueran los mercados». Con eso el texto sostiene la exención de un CEDEAR operado en BYMA. Lo que **no** encontré es una norma o un pronunciamiento de ARCA que cierre la discusión (NC-3). El ABC 24755223 sólo excluye las ventas en mercados del exterior fuera de la CNV: no dice nada de un CEDEAR vendido en BYMA ni del carácter de fuente extranjera. Las búsquedas «CEDEAR», «CEDEARs», «certificados de depósito», «acciones del exterior» y «títulos del exterior» en el ABC de ARCA no devolvieron otra consulta sobre el tema. Una nota técnica del CPCECABA, que es fuente secundaria, concluye que la venta «se encuentra exenta en tanto se cumplan los requisitos previstos por el inciso u) del art. 26», pero no cita ninguna primaria además del inc. u).

### 1.2 Alícuota

- **Fuente argentina, acciones y certificados de depósito no exentos**: «QUINCE POR CIENTO (15 %)» para acciones y certificados que «(i) cotizan en bolsas o mercados de valores autorizados por la COMISIÓN NACIONAL DE VALORES que no cumplen los requisitos a que hace referencia el inciso u) del artículo 26 de esta ley, o que (ii) no cotizan». LIG art. 98, 1er párr., inc. c). Sin nota de modificación. El DR art. 245 lo repite en su tabla.
- **Fuente argentina, títulos, bonos, cuotapartes de FCI y «demás valores»**: 5 % en moneda nacional sin cláusula de ajuste (art. 98, inc. a), con facultad del PEN de subirla hasta la del inc. b); 15 % en moneda nacional con cláusula de ajuste o en moneda extranjera (inc. b). Fuera de este alcance; se cita porque ahí cae la cripto de fuente argentina.
- **Fuente argentina, monedas digitales**: la ley las pone en el inc. b), **15 %**, sin distinguir moneda (art. 98, 1er párr., inc. b). El DR art. 245 las pone en el grupo que paga 5 % «en moneda nacional sin cláusula de ajuste» y 15 % en moneda extranjera o con cláusula. La ley y el reglamento no dicen lo mismo: **NO CONFIRMADO (NC-7)** cuál aplica a una cripto cotizada en pesos.
- **Fuente extranjera** (acción o ETF del exterior, CEDEAR si no estuviera exento, cripto si fuera extranjera): «Cuando la determinación de la ganancia neta de los sujetos a que hace referencia el primer párrafo de este artículo, incluya resultados comprendidos en el Título VIII de esta ley, provenientes de operaciones de enajenación de acciones, valores representativos y certificados de depósito de acciones y demás valores, cuotas y participaciones sociales — incluidas cuotapartes de fondos comunes de inversión […]—, monedas digitales, títulos, bonos y demás valores […], éstos quedarán alcanzados por el impuesto a la alícuota del QUINCE POR CIENTO (15 %)». LIG art. 94, 3er párr. Sin nota de modificación (los párrafos 4º y 5º del art. 94 fueron derogados por la Ley 27.743, art. 70 inc. e; el 3º sigue).
- **No es la escala progresiva.** La escala del 5 % al 35 % del art. 94, 1er párr. (sustituida por la Ley 27.743, art. 73, B.O. 08/07/2024; montos ajustados por IPC semestralmente desde 2025, art. 94, 2º párr.) no se aplica a estos resultados: el cedular tiene alícuota propia (art. 98) y el 3er párr. del art. 94 fija 15 % para los de fuente extranjera.

### 1.3 Moneda de medición y conversión

**Fuente argentina, acciones y certificados (art. 98, inc. c):** la ganancia bruta se determina «deduciendo del precio de transferencia el costo de adquisición actualizado, mediante la aplicación del índice mencionado en el segundo párrafo del artículo 93, desde la fecha de adquisición hasta la fecha de transferencia». LIG art. 98, 4º párr., pauta (ii).

- El índice es el IPC nivel general del INDEC, «conforme las tablas que a esos fines elabore la ADMINISTRACIÓN FEDERAL DE INGRESOS PÚBLICOS», para adquisiciones hechas «en los ejercicios fiscales que se inicien a partir del 1° de enero de 2018». LIG art. 93, 2º párr. Las adquisiciones anteriores se actualizan por el art. 39 de la Ley 24.073 (art. 93, 1er párr.); no verifiqué qué efecto tiene eso hoy (**NO CONFIRMADO, NC-10**, junto con las tablas de ARCA).
- **Interpretación**: el resultado se mide en **pesos**, con costo indexado por inflación. Para un ADR comprado en dólares hay que llevar precio y costo a pesos.
- Conversión, criterio de ARCA (ABC 22913172, 22/05/2018, categoría «Impuesto Cedular - Ley 27.430 › Renta Financiera › Situaciones Especiales»): «Las operaciones en moneda extranjera se convertirán al tipo de cambio comprador o vendedor, según corresponda, conforme la cotización del Banco de la Nación Argentina al cierre del día en que se concrete la operación […]. En caso de que la operación se liquide antes del cierre de las operaciones cambiarias, deberá utilizarse el tipo de cambio vigente al día hábil cambiario anterior».
- **Interpretación**: en fuente argentina cada operación se convierte con el tipo de cambio **de su propia fecha**: la compra con el de la fecha de compra y la venta con el de la fecha de venta. Es lo opuesto a fuente extranjera (ver abajo), y es lo que hace falta para indexar el costo en pesos desde la adquisición.
- **NO CONFIRMADO (NC-19)**: qué cotización corresponde a cada punta («según corresponda») y si ese criterio, publicado en 2018 en una sección sobre retenciones, rige la liquidación de una persona humana. El texto del ABC es igual al del DR art. 160, pero ese artículo está en el Capítulo IV del DR («Ganancias de la tercera categoría»), así que no rige por sí mismo el cedular de una persona humana. La remisión supletoria del LIG art. 101 es a los Títulos I y II de la **ley**, no al reglamento.

**Fuente argentina, títulos y demás valores en moneda extranjera (art. 98, incs. a y b):** «De tratarse de valores en moneda nacional con cláusula de ajuste o en moneda extranjera, las actualizaciones y diferencias de cambio no serán consideradas como integrantes de la ganancia bruta». LIG art. 98, 4º párr., pauta (i). Es la exclusión explícita de la diferencia de cambio; **no** alcanza a las acciones del inc. c), que en cambio indexan el costo.

**Fuente extranjera (acción o ETF del exterior; CEDEAR si estuviera gravado):**

- La ganancia neta no atribuible a un establecimiento permanente «se determinará en moneda argentina», con las fechas y tipos de cambio que fije la reglamentación. LIG art. 129, 2º párr.
- Los costos de bienes de segunda categoría expresados en moneda extranjera «deberán convertirse al tipo de cambio vendedor que considera el artículo 155, correspondiente a la fecha en que se produzca su enajenación». LIG art. 143.
- El tipo de cambio del art. 155 es «comprador o vendedor, según corresponda, conforme a la cotización del BANCO DE LA NACIÓN ARGENTINA al cierre del día en el que se concreten las operaciones». LIG art. 155, 1er párr.
- Reglamento: ingresos en moneda extranjera «al tipo de cambio comprador […] correspondiente al día en que aquellos ingresos […] se devenguen, perciban o paguen, según corresponda» (DR art. 286, inc. 1); costos de bienes enajenados «al tipo de cambio vendedor que considera el artículo 155, correspondiente a la fecha en que se produzca la enajenación de esos bienes» (DR art. 286, inc. 2).
- **Interpretación**: precio y costo se pasan a pesos con el tipo de cambio de la **fecha de venta** (precio al comprador BNA, costo al vendedor BNA). El tipo de cambio de la fecha de compra **no interviene**, así que la devaluación del peso entre compra y venta no genera ganancia: el resultado es, en la práctica, la ganancia en dólares convertida al cambio del día de venta, achicada por la brecha comprador-vendedor del BNA. El costo en dólares no se indexa.
- El art. 155, 2º y 3er párr., computa como ganancia de fuente extranjera las diferencias de cambio de «operaciones […] o créditos» en moneda extranjera y las que surjan cuando las divisas «son ingresadas al territorio nacional o dispuestas en cualquier forma en el exterior». **NO CONFIRMADO (NC-12)** cómo se aplica a una persona humana que vende y deja los dólares en el broker del exterior.

### 1.4 Costo cuando hay varias compras de la misma especie

- **Fuente argentina, acciones y certificados (inc. c): PEPS.** «A tales fines se considerará, sin admitir prueba en contrario, que los valores enajenados corresponden a las adquisiciones más antiguas de su misma especie y calidad». LIG art. 98, 4º párr., pauta (ii), última oración. No admite promedio ponderado ni elección de lote.
- **Fuente argentina, títulos y demás valores (incs. a y b, incluida la cripto de fuente argentina): PEPS por remisión.** La pauta (i) del art. 98, 4º párr. sólo dice «deduciendo del precio de transferencia el costo de adquisición». Lo no regulado en el Capítulo II se rige «supletoriamente» por los Títulos I y II de la ley (LIG art. 101), y el art. 67, que está en el Título II, dispone para «monedas digitales, títulos públicos, bonos y demás valores» que «se considerará sin admitir prueba en contrario que los bienes enajenados corresponden a las adquisiciones más antiguas de su misma especie y calidad» (LIG art. 67, 2º párr.). Interpretación: PEPS.
- **Fuente extranjera (acciones, ETFs, CEDEARs): PEPS por remisión, sin actualización.** El costo computable de bienes «adquiridos […] en el exterior por residentes en el país, para afectarlos a la producción de ganancias de fuente extranjera» se determina «de acuerdo con las disposiciones de los artículos 62, 63, 64, 65, 67 y 69, sin considerar las actualizaciones que los mismos puedan contemplar» (LIG art. 149, 1er párr.). El art. 65 es el de acciones y cuotapartes de FCI: «se considerará, sin admitir prueba en contrario, que los bienes enajenados corresponden a las adquisiciones más antiguas de su misma especie y calidad» (LIG art. 65, 1er párr.), y lo extiende a los «valores representativos y certificados de depósito de acciones y demás valores» (3er párr.). Interpretación: PEPS, con el costo en dólares sin indexar, convertido al cambio del día de venta (§1.3).
- Para acciones vale el art. 65 y no el 67. ARCA dice que «demás valores» comprende «los títulos valores no mencionados explícitamente en la enumeración que devenguen un interés o rendimiento» (ABC 24269610, 30/01/2025, ante la pregunta de si incluye «acciones, cedear»). Interpretación: las acciones y los CEDEARs no son «demás valores» del art. 67.
- **Regla anti-venta-ficticia (fuente argentina, cedular):** si una venta da quebranto y la persona compra «dentro de las SETENTA Y DOS (72) horas previas o posteriores, un valor de naturaleza sustancialmente similar», el quebranto no es computable y se suma al costo del valor nuevo. DR art. 246.
- **Gastos:** contra las ganancias del Capítulo II sólo se computan «los costos de adquisición y gastos directa o indirectamente relacionados con ellas». LIG art. 100, 3er párr. Interpretación: comisiones y derechos de mercado entran al costo o restan del precio.

### 1.5 Quebrantos (pérdidas)

**Fuente argentina (cedular):**

- Los quebrantos de las inversiones del Capítulo II del Título IV (incluidas las monedas digitales) son «de naturaleza específica debiendo, por lo tanto, compensarse exclusivamente con ganancias futuras de su misma fuente y clase. Se entiende por clase, al conjunto de ganancias comprendidas en cada uno de los artículos del citado Capítulo II». LIG art. 25, 2º párr. (1ª oración sustituida por la Ley 27.743, art. 68, B.O. 08/07/2024, efecto desde el año fiscal 2024).
- **Interpretación**: una pérdida por venta de acciones (art. 98) sólo compensa ganancias del art. 98 de fuente argentina; no compensa intereses (art. 95), dividendos (art. 97) ni el sueldo. ARCA lo dice igual: el quebranto «resultará de naturaleza específica debiendo, por lo tanto, compensarse exclusivamente con ganancias futuras de su misma fuente y clase […]. Los quebrantos podrán ser trasladados durante los 5 años siguientes» (ABC 23904888, 12/02/2020).
- Al revés: «No serán compensables los quebrantos impositivos con ganancias que deban tributar el impuesto con carácter único y definitivo ni con aquellas comprendidas en el capítulo II del título IV de esta ley». LIG art. 25, 8º párr. (sustituido por la Ley 27.743, art. 69).
- Plazo: los quebrantos de naturaleza específica se computan «en el año fiscal en el que se experimentaron las pérdidas o en los CINCO (5) años inmediatos siguientes». LIG art. 25, 10º párr.
- Actualización: «Los quebrantos generados en los ejercicios fiscales que se inicien a partir del 1° de enero de 2025, inclusive, se actualizarán» por IPC del INDEC. LIG art. 25, 11º párr. (sustituido por la **Ley 27.802, art. 190, B.O. 6/3/2026**). **NO CONFIRMADO (NC-13)** que alcance a los quebrantos cedulares de una persona humana: el párrafo habla de «ejercicios fiscales» y la persona humana liquida por «año fiscal».
- Los quebrantos de fuente argentina del Capítulo II «no podrán imputarse contra ganancias netas de fuente extranjera provenientes de la enajenación del mismo tipo de inversiones y operaciones». LIG art. 132, último párr.

**Fuente extranjera:**

- «Los quebrantos provenientes de actividades cuyos resultados se consideren de fuente extranjera, sólo podrán compensarse con ganancias de esa misma fuente». LIG art. 25, 12º párr. (último). ARCA repite la regla y el plazo de cinco años en el ABC 5462188 (12/12/2019).
- Los derivados de la enajenación de acciones, certificados de depósito, cuotapartes, monedas digitales, títulos y demás valores «serán considerados de naturaleza específica y sólo podrán computarse contra las utilidades netas de la misma fuente y que provengan de igual tipo de operaciones, en los ejercicios o años fiscales que se experimentaron las pérdidas o en los CINCO (5) años inmediatos siguientes». LIG art. 132, 1er párr. Se actualizan según el 11º párr. del art. 25 (art. 132, 2º párr.).
- Quebranto de una venta exenta: **NO CONFIRMADO (NC-14)** que sea computable. Interpretación: si el resultado está exento (CEDEAR o acción argentina en BYMA), la pérdida tampoco es computable.

### 1.6 Mínimo no imponible o deducción especial

- **Deducción especial del art. 100**: aplica a las ganancias del art. 95 (intereses y rendimientos) y de los **incs. a) y b)** del 1er párr. del art. 98, «en tanto se trate de ganancias de fuente argentina», por un monto igual a la ganancia no imponible del art. 30, inc. a), por período fiscal, prorrateado por concepto. LIG art. 100, 1er párr. No puede generar quebranto ni trasladarse a períodos siguientes (2º párr.). El DR art. 262 dice cómo se prorratea.
- **Interpretación**: **no** alcanza a las acciones ni a los certificados de depósito (inc. c del art. 98) ni a ninguna ganancia de fuente extranjera. Sí alcanzaría a la cripto de fuente argentina, que está en el inc. b), si se confirmara que es de fuente argentina (NC-6).
- No se deducen los conceptos de los arts. 29, 30 y 85 (gastos de sepelio, mínimo no imponible, cargas de familia, deducciones generales) contra estas ganancias. LIG art. 100, 3er párr.
- Monto del art. 30, inc. a) vigente para 2026: **NO CONFIRMADO (NC-11)**. No consulté la tabla de ARCA.

### 1.7 Resumen por tipo de activo

| Activo | Grava / exento | Alícuota | Moneda de medición | Fuente normativa |
|---|---|---|---|---|
| Acción argentina con oferta pública, vendida en BYMA | **Exenta** | — | — | LIG art. 26 u), 1er y 2º párr. |
| Acción argentina que no cumple el inc. u) | Grava | 15 % | Pesos; costo actualizado por IPC; PEPS | LIG arts. 98 1er párr. c) y 4º párr. (ii), 93 2º párr. |
| CEDEAR (acción extranjera) vendido en BYMA | **Exento según el texto**; NO CONFIRMADO criterio de ARCA (NC-3) | Si gravara: 15 % | Si gravara: dólares pasados a pesos al cambio del día de venta | LIG arts. 7 2º párr., 26 u), 134, 94 3er párr.; DR art. 89 |
| CEDEAR de ETF | NO CONFIRMADO (NC-4) | Si gravara: 15 % | Ídem | LIG arts. 26 u) último párr., 94 3er párr. |
| Acción o ETF del exterior, broker del exterior | **Grava** | 15 % | Dólares pasados a pesos el día de venta: precio al comprador BNA, costo al vendedor BNA; sin diferencia de cambio sobre el costo | LIG arts. 48 k), 94 3er párr., 129, 143, 155; DR art. 286 |
| ADR de emisor argentino | NO CONFIRMADO exención (NC-18); si grava, fuente argentina | 15 % | Pesos; costo actualizado por IPC; PEPS; conversión NO CONFIRMADA (NC-19) | LIG arts. 7 2º párr., 98 c); DR art. 87 |
| Cripto | **Grava**; fuente NO CONFIRMADA (NC-6) | 15 %, o 5 % en pesos según el DR (NC-7) | Según la fuente | LIG arts. 2 inc. 4, 7, 94 3er párr., 98 b); DR art. 245 |

Quebrantos en todos los casos: específicos, sólo contra ganancias de la misma fuente y clase, cinco años (LIG arts. 25 y 132). Deducción especial: no aplica a acciones ni a fuente extranjera (LIG art. 100).

---

## §2 Lo que falta en los datos del Portfolio

Hoy el Portfolio guarda una fila por ticker:

- `Position` (`portfolio/tracker.py:61-71`): `symbol`, `shares`, `avg_cost` («USD per share», `:64`), `purchase_date` (ISO, `:65`), `sector`, `notes`; `cost_basis` es una propiedad, `shares × avg_cost` (`:69-71`).
- Una compra nueva del mismo ticker **promedia**: `add_position` suma acciones y costo y pisa `avg_cost` con el promedio (`portfolio/tracker.py:134-140`). La `purchase_date` se escribe sólo al crear la posición (`:147`): la segunda compra no la cambia y su fecha se pierde.
- Sólo entra la moneda de la cartera, USD (`position_currency_skip_reason`, `portfolio/tracker.py:31-49`; `PortfolioConfig.base_currency = "USD"`, `config.py:2904`). Un ticker de BYMA, que cotiza en pesos, no se puede cargar.
- Una venta no se registra: `remove_position` baja acciones o borra la fila sin precio, sin fecha y sin resultado (`portfolio/tracker.py:189-200`), y la página sólo la usa para borrar la posición entera (`dashboard/views/3_Portfolio.py:484`).
- Se guarda a JSON con `asdict` de cada posición (`portfolio/tracker.py:374-376`): no hay historial.

Contra las reglas de §1:

| Dato que piden las reglas | Para qué | Hoy | Cita del código |
|---|---|---|---|
| **Lotes** (cantidad y costo por compra) | PEPS obligatorio en fuente argentina (LIG art. 98, 4º párr. (ii)) | No: el promedio destruye los lotes, y no se puede reconstruir después | `tracker.py:134-140` |
| **Fecha de compra por lote** | IPC desde la adquisición (art. 98 (ii)); orden PEPS; regla de 72 h (DR art. 246) | Una sola fecha por ticker, la de la primera compra | `tracker.py:65`, `:147` |
| **Tipo de cambio de compra** | Costo en pesos de un ADR o una acción argentina gravada (NC-19) | No existe | `tracker.py:61-67` |
| **Tipo de cambio comprador y vendedor BNA del día de venta** | Fuente extranjera (LIG arts. 143, 155; DR art. 286) | No existe. `data/fx.py` baja `ARS=X` de yfinance, que no es la cotización del BNA, y `ArFxConfig` se declara «Not a tax/compliance engine» | `config.py:3412-3417` |
| **Mercado donde se operó** (BYMA u otro mercado CNV / broker del exterior) | Condición (b) del inc. u): decide exento o gravado | No existe | `tracker.py:61-67` |
| **Tipo de instrumento** (acción, CEDEAR, ADR, ETF, cripto) | Fuente (art. 7) y exención (inc. u) | No existe; sólo `sector`. `analysis/asset_class.py` distingue equity, fund y crypto por `quoteType`, pero no CEDEAR de subyacente ni ADR de acción | `tracker.py:66` |
| **País del emisor de la acción subyacente** | Fuente (art. 7, 1er y 2º párr.) | No se guarda; `get_info` lo trae y `TaxConfig` ya lo usa | `config.py:1478-1527` |
| **Oferta pública CNV** del valor | Condición (a) del inc. u); DR art. 89 | No existe | — |
| **Venta**: fecha, cantidad, precio, gastos, fecha de cobro | Resultado; imputación por lo percibido (art. 24 b) | No existe | `tracker.py:189-200` |
| **Quebrantos acumulados** por fuente, clase y año de origen | Compensación de cinco años (arts. 25, 132) | No existe | — |
| **Comisiones y gastos** | Costo computable (art. 100, 3er párr.) | No existe | — |

**El impuesto personal tampoco existe en la configuración.** `TaxConfig` (`config.py:1478-1527`) modela sólo la alícuota corporativa por país para el NOPAT del ROIC: su docstring dice «Statutory corporate income-tax rates» (`:1479`), y sus dos campos son `corporate_tax_rate_pct` (`:1499`) y `default_corporate_tax_rate_pct` (`:1527`). El singleton `TAXES` (`config.py:3803`) se usa sólo en `analysis/utils.py:170-172` y en tests del ROIC. Lo más parecido a un impuesto del inversor es `EconomicDragConfig.dividend_tax_drag_pct` (`config.py:2421`, `:2456`, en 0,0), un drag anual sobre dividendos, no una ganancia de capital.

**Dónde iría el número.** `docs/CONTEXT.md:133`: «**Thresholds**: nunca hardcodear números en el código de análisis — usar las constantes de `config.py`». Las alícuotas, el plazo de cinco años y las 72 horas irían en una dataclass de `config.py`, con norma y vigencia por campo.

**La paradoja del alcance.** Los dos casos exentos (acción argentina y CEDEAR en BYMA) cotizan en pesos, y hoy el Portfolio no los admite (`tracker.py:31-49`). Lo que el Portfolio sí admite (tickers en dólares) son acciones y ETFs del exterior, que gravan al 15 %, y ADRs argentinos, que quedan en NC-18.

---

## §3 Superficies candidatas

### 3.1 Venta registrada en Portfolio

- **Qué haría falta**: un flujo «Registrar venta» (fecha, cantidad, precio, gastos, mercado), lotes en vez de promedio, los datos de §2 por lote, el cálculo de §1 por tipo de activo, y un registro de ventas y quebrantos que persista. Migrar el `portfolio.json` existente (posiciones sin lotes).
- **Riesgo**: que se lea como liquidación para la declaración jurada. Una exención mal resuelta (CEDEAR, ADR) da un número con apariencia de dato. La migración puede inventar lotes que no existieron: hay que rotular el lote migrado como «costo promedio».
- **A favor**: es la única superficie donde la regla se aplica a un hecho, con fecha, precio y tipo de cambio reales.

### 3.2 Mi Plan

- **Qué haría falta**: al proponer ventas para alinear la cartera con el plan (`data/plan_context.compute_alignment_trades`), estimar el impuesto de cada venta con los lotes del Portfolio. Mostrarlo en la página y en el PDF.
- **Riesgo**: depende de 3.1, porque sin lotes no hay costo PEPS. Los planes guardados no tienen el dato, así que hay que decidir qué pasa con ellos. Agrega un número más a una página que ya mezcla muchos.

### 3.3 Proyección de Simulaciones (Monte Carlo)

- **Qué haría falta**: cobrar impuesto en cada retiro de la decumulación (`portfolio/decumulation.py`), lo que pide el costo de lo que se vende en cada camino. Para fuente argentina, además, un camino de IPC y de tipo de cambio para indexar el costo en pesos. Lo más simple es un drag anual, como `EconomicDragConfig`, que ya es opt-in en el motor.
- **Riesgo**: precisión falsa: la mezcla de instrumentos futura, la exención del CEDEAR y el cambio de normas en 30 años pesan más que el cálculo. Hay que subir `ENGINE_VERSION`, con el aviso de plan desactualizado que eso trae. Puede contarse dos veces con `dividend_tax_drag_pct`. Un drag anual sobre el valor no es una ganancia de capital: el impuesto se paga al vender y sobre la ganancia, no sobre el pozo.

---

## §4 Decisiones que te tocan

1. **Primera superficie**: recomiendo la venta registrada en Portfolio (3.1), porque es la única donde la regla se aplica a datos reales y las otras dos dependen de sus lotes.
2. **Instrumentos del primer alcance**: recomiendo acciones y ETFs del exterior (fuente extranjera, 15 %), porque son lo que el Portfolio ya admite y su fuente, su alícuota y su conversión están confirmadas (arts. 7, 94, 143, 155; DR art. 286); el método de costo con varias compras es PEPS por interpretación y no por criterio de ARCA (NC-8), y las diferencias de cambio si los dólares quedan afuera (NC-12) y el crédito por impuesto del exterior (NC-15) no lo están.
3. **CEDEAR**: recomiendo tratarlo como exento con el rótulo «según LIG arts. 26 u) y 134; criterio de ARCA no confirmado», porque el texto lo sostiene pero la discusión no está cerrada en una primaria (NC-3).
4. **ADR argentino**: recomiendo dejarlo «no determinado» y no calcular, hasta resolver NC-18 y NC-19, porque la exención y la conversión a pesos no están confirmadas.
5. **Cripto**: recomiendo dejarla afuera del primer alcance, porque la fuente (NC-6) y la alícuota (NC-7) no están confirmadas.
6. **Lotes**: recomiendo reemplazar el promedio por lotes con fecha, cantidad, precio en dólares y tipo de cambio, porque PEPS es obligatorio en fuente argentina y el promedio pierde información que no se recupera.
7. **Posiciones existentes**: recomiendo migrarlas a un lote único con la `purchase_date` actual, rotulado «costo promedio migrado», porque no hay de dónde reconstruir los lotes reales.
8. **Tipo de cambio**: recomiendo que lo cargues vos, rotulado «BNA comprador/vendedor», y no usar `ARS=X` de yfinance para el impuesto, porque la ley pide la cotización del BNA (art. 155) y la de yfinance es otra.
9. **Mercado e instrumento**: recomiendo que se declaren por lote y no se infieran del ticker, porque deciden la exención y un ticker no dice dónde se operó.
10. **Moneda que se muestra**: recomiendo mostrar el impuesto en pesos y su equivalente en dólares al cambio del día de venta, porque el impuesto se liquida en pesos y la app piensa en dólares.
11. **Quebrantos**: recomiendo registrar las pérdidas por fuente y clase con su vencimiento a cinco años, pero sin actualizarlas por IPC hasta resolver NC-13, porque la compensación cambia el impuesto neto y la actualización no está confirmada para personas humanas.
12. **Monte Carlo**: recomiendo no meter el impuesto en la proyección en este paso, porque pide un costo por camino y supuestos de normas a 30 años que darían precisión falsa.
13. **Configuración**: recomiendo una dataclass nueva para el impuesto personal en `config.py`, separada de `TaxConfig`, con norma y vigencia en cada campo, porque `TaxConfig` es la alícuota corporativa del NOPAT y mezclarlas confunde dos impuestos distintos.
14. **Rótulo**: recomiendo que todo número de impuesto diga «estimación, no liquidación» y cite la norma, porque la app no reemplaza la declaración jurada.
15. **Validación externa**: recomiendo que un contador revise NC-3, NC-18 y NC-19 antes de escribir código, porque son los casos que más probablemente estén en tu cartera (CEDEARs y ADRs argentinos).

---

## §5 Lo no confirmado y las preguntas abiertas

| # | Qué falta | Qué lo resolvería |
|---|---|---|
| NC-1 | Normas entre el 6/3/2026 (Ley 27.802, lo último que muestra InfoLEG) y el 2026-10-10 que modifiquen los arts. 7, 25, 26, 94, 98, 100, 129, 132, 143 o 155 | Buscar en el Boletín Oficial leyes y decretos de ganancias de marzo a octubre de 2026 |
| NC-2 | Fecha de última actualización del texto del DR en la Biblioteca de ARCA, y si los arts. 87, 89, 160, 245, 246 y 286 tienen modificaciones posteriores (p. ej. Decreto 652/2024) | La nota de modificaciones de cada artículo en la Biblioteca de ARCA o en InfoLEG |
| NC-3 | Criterio oficial de ARCA sobre la exención del CEDEAR (fuente extranjera + art. 134) | Un dictamen, una RG o el micrositio de ARCA sobre ganancias cedulares |
| NC-4 | CEDEAR de ETF: si entra por el inc. u), 1er o último párr. | Ídem NC-3 |
| NC-5 | Acción del exterior con oferta pública CNV comprada en el exterior (DR art. 89, 2º párr.): cómo se acredita la condición | Normas de la CNV / ARCA |
| NC-6 | Fuente de una cripto sin emisor (art. 7 usa el domicilio del emisor) | DR o pronunciamiento de ARCA sobre monedas digitales |
| NC-7 | Cripto de fuente argentina en pesos: 15 % (ley, art. 98 b) o 5 % (DR art. 245) | Ídem NC-6 |
| NC-8 | Método de costo para varias compras en fuente extranjera: §1.4 lo resuelve como PEPS **por interpretación** (art. 149 → art. 65); falta un criterio de ARCA que lo confirme | DR del Título VIII / criterio de ARCA |
| NC-9 | Método de costo para varias compras en fuente argentina, incs. a) y b) del art. 98: §1.4 lo resuelve como PEPS **por interpretación** (art. 101 → art. 67) | DR del art. 98 / criterio de ARCA |
| NC-10 | Tablas de IPC de ARCA del art. 93, y efecto actual del art. 39 de la Ley 24.073 para compras anteriores a 2018 | Micrositio de ARCA; texto de la Ley 24.073 |
| NC-11 | Monto del art. 30, inc. a) para 2026 (base de la deducción especial) | Tabla de deducciones de ARCA 2026 |
| NC-12 | Diferencias de cambio del art. 155, 2º y 3er párr., cuando el producido de la venta queda en dólares en el exterior | DR del art. 155 / criterio de ARCA |
| NC-13 | Si la actualización por IPC de quebrantos (art. 25, 11º párr., Ley 27.802) alcanza a quebrantos cedulares de personas humanas | DR o criterio de ARCA |
| NC-14 | Si una pérdida en una venta exenta es computable | Criterio de ARCA |
| NC-15 | Crédito por impuesto análogo pagado en el exterior (arts. 165–167) sobre una ganancia de capital de acción extranjera | Leer arts. 165–167 y su DR; ver si el país de la fuente cobra algo |
| NC-16 | Obligación de presentar declaración jurada por ganancias cedulares y forma de liquidarlas | RG y micrositio de ARCA |
| NC-17 | Texto del art. 33 de la Ley 27.541 (el art. 34 sí está reflejado en el inc. u) | Texto de la Ley 27.541 en InfoLEG |
| NC-18 | Exención de un ADR argentino vendido en el exterior | Criterio de ARCA / DR art. 87 |
| NC-19 | Tipo de cambio para pasar a pesos precio y costo en dólares en el cedular (fuente argentina); si rige el DR art. 160 | DR del art. 98 / criterio de ARCA |

---

## §6 Decisiones tomadas (2026-10-10)

Respuestas del usuario a §4, por rondas. Lo de acá manda sobre las recomendaciones de §4.

| # | Decisión | Respuesta |
|---|---|---|
| D1 | Cómo están hoy ADBE, GOOGL e INTU | Acciones en un broker del exterior: fuente extranjera, gravan al 15 % (LIG art. 94, 3er párr.; ABC 24755223) |
| D2 | Primera superficie | La venta registrada en Portfolio (§3.1) |
| D3 | Monte Carlo | Fuera de este alcance; opción diferida |
| D4 | Contador | Sólo si un caso abierto toca la cartera; con D1, el primer alcance no toca NC-3, NC-18 ni NC-19 |
| D5 | Rótulo y configuración | Todo número dice «estimación, no liquidación» y cita la norma; alícuotas y plazos en una dataclass nueva de `config.py`, separada de `TaxConfig`, con norma y vigencia por campo |
| D6 | Instrumentos | Se calculan acciones y ETFs del exterior vendidos en broker del exterior. CEDEAR, ADR argentino y cripto se registran pero muestran «no determinado» con el motivo y su NC |
| D7 | Lotes | Todas las posiciones pasan a lotes (fecha, cantidad, precio en USD); la pantalla puede seguir mostrando el promedio, calculado de los lotes |
| D8 | Posiciones existentes | Un lote único con su `purchase_date`, rotulado «costo promedio migrado», reemplazable por los lotes reales |
| D9 | Tipo de cambio | El usuario carga BNA comprador y vendedor del día de venta; no se propone `ARS=X`. Bajarlo del BNA es un PR aparte |
| D10 | Mercado e instrumento | Se declaran por lote; para lo ya cargado, por defecto «broker del exterior / acción» |
| D11 | Moneda que se muestra | El impuesto en pesos y su equivalente en USD al tipo de cambio del día de venta |
| D12 | Quebrantos | Por fuente y clase, con vencimiento a cinco años, compensados contra la misma fuente y clase; sin actualizar por IPC mientras siga NC-13 |
| D13 | Diferencia de cambio si los dólares quedan afuera | Se calcula sólo lo de los arts. 143 y 155, 1er párr., con un aviso de que no incluye la posible diferencia de cambio del art. 155, 2º y 3er párr. (NC-12) |

---

## Fuentes

Primarias, consultadas el 2026-10-10:

- Ley de Impuesto a las Ganancias, t.o. 2019 (Decreto 824/2019), texto actualizado de InfoLEG: <https://servicios.infoleg.gob.ar/infolegInternet/anexos/330000-334999/332890/texact.htm>. Artículos leídos: 2, 3, 7, 24, 25, 26 inc. u), 28, 48 inc. k), 93, 94, 97, 98, 99, 100, 101, 129, 131, 132, 134, 137, 143, 149, 155, 167.
- Decreto 862/2019, reglamentación de la LIG, Biblioteca Electrónica de ARCA: <https://biblioteca.afip.gob.ar/dcp/DEC_C_000862_2019_12_06>. Artículos leídos: 86, 87, 88, 89, 90, 91, 160, 245, 246, 247, 262, 286.
- Decreto 824/2019 en argentina.gob.ar (aparece en la búsqueda; no se usó para citar): <https://www.argentina.gob.ar/normativa/nacional/decreto-824-2019-332890/texto>.
- Decreto 862/2019 en el Boletín Oficial, 09/12/2019 (aparece en la búsqueda; no se usó para citar): <https://www.boletinoficial.gob.ar/detalleAviso/primera/223342/20191209?anexos=1>.

- Consultas frecuentes (ABC) de ARCA, <https://servicioscf.afip.gob.ar/publico/abc>: 24755223 (17/06/2026), 22913172 (22/05/2018), 23904888 (12/02/2020), 5462188 (12/12/2019) y 24269610 (30/01/2025). Son criterio del organismo, no norma.
- Leyes modificatorias, en el texto actualizado de la LIG: Ley 27.541 (arts. 33 y 34), Ley 27.743 (arts. 68, 69, 70 y 73) y Ley 27.802 (art. 190).

Secundarias, sólo para ubicar las primarias, consultadas el 2026-10-10:

- <https://www.cira.org.ar/?p=2681>, <https://www.consejo.org.ar/noticias/2019/ley-impuesto-ganancias-se-aprobo-reglamentacion-texto-ordenado>, <https://aldiaargentina.microjuris.com/2019/12/09/ley-de-impuesto-a-las-ganancias-se-reglamenta-el-texto-ordenado-2019/>.
