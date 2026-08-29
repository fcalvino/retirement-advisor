"""Oracle for N5 — un yield que no es un yield, y un None que no es un cero.

Dos caras de la misma cadena, ambas en el camino que resuelve el dividendo.

**(a) La derivación preferida se rompe cuando cambia la moneda.**
``normalize_dividend_yield_pct`` resuelve en tres pasos y el paso 1 gana
siempre: ``trailingAnnualDividendRate / price``. Su docstring lo justifica como
*"immune to the feed's unit choices"* — cierto para **unidades**, falso para
**monedas** y para el ratio ADR/ordinaria. En un ADR latinoamericano el
dividendo se declara en moneda local y el precio cotiza en USD, así que la
división produce un número sin ambigüedad de unidad y con el valor equivocado.

**(b) Un yield que no se pudo medir se cuenta como una empresa que no paga.**
Cuando el paso 1 supera el techo, la función devuelve ``None`` — su docstring
dice *"a loud None beats a confident wrong number"*. Pero el None no es loud
aguas abajo: ``_score_dividends`` hace ``or 0.0``, cae en la rama
``div_yield == 0`` y paga **+3 puntos** con la nota *"No dividend — growth
company reinvests FCF"*. Itaú, Telecom Argentina y Vale —tres pagadores
reales— le dicen al usuario que no pagan. Misma forma que U3-1: *"no pude
medirlo"* colapsado en *"no existe"*.

**Por qué el umbral del cross-check no es una calibración.** Medido sobre los
130 tickers cacheados que traen los tres campos, el ratio
``(rate/price) / dividendYield`` separa dos poblaciones **sin solapamiento**:

    122 tickers  <1.10x     <- sanos, el paso 1 coincide con el feed
      0 tickers  1.10-3.00x <- banda vacía
      8 tickers  >=3.12x    <- corruptos, 7 de ellos ADRs LatAm

Y el tercer campo arbitra: ``fiveYearAvgDividendYield`` le da la razón a
``dividendYield`` en **8 de 8** casos disputados. No es que se prefiera un campo
sobre otro por gusto — es que un testigo independiente coincide con uno de los
dos, siempre.

Sin red, sin Streamlit.
"""

from __future__ import annotations

import pytest

from analysis.fundamental import (
    FundamentalAnalyzer,
    FundamentalResult,
    normalize_dividend_yield_pct,
)

# --------------------------------------------------------------------------- #
#  Los 8 casos reales, con los cinco campos tal como los trae la caché         #
#  (2026-08-29). `tay` va incluido A PROPÓSITO: los fixtures que lo omitían    #
#  dejaban pasar la mutación «guardá sólo rate/price» — el paso 2 caía en el   #
#  vacío en vez de reponer el mismo número corrupto, y el test se volvía       #
#  verde por una ausencia del fixture y no por el arreglo.                     #
#  sym, rate, price, trailingAnnualDividendYield, dividendYield, 5yAvg, país   #
# --------------------------------------------------------------------------- #

CORRUPTOS = [
    ("TEO",  13.632, 14.390, 0.98568330, 0.31, 6.78, "Argentina"),
    ("SBS",  0.6640, 5.1950, 0.12504707, 0.63, 1.79, "Brazil"),
    ("ITUB", 2.9550, 7.8950, 0.37216625, 2.19, 4.32, "Brazil"),
    ("VALE", 5.4770, 14.825, 0.37233177, 8.12, 9.33, "Brazil"),
    ("ABEV", 0.7300, 2.9550, 0.24333334, 5.64, 5.19, "Brazil"),
    ("BAP",  50.000, 384.57, 0.12922235, 3.72, 3.02, "Peru"),
    ("HON",  9.4000, 215.24, 0.04265166, 1.27, 2.10, "United States"),
    ("BSBR", 1.0710, 5.7750, 0.18433735, 5.95, 6.75, "Brazil"),
]

#: Tickers donde los tres campos coinciden: el paso 1 es genuinamente el más
#: preciso y su valor NO se puede mover, o el arreglo sería una regresión sobre
#: los 122 que hoy resuelven bien.
SANOS = [
    ("KO",   2.0800, 68.000, 3.06),
    ("SPY",  5.6620, 775.37, 0.73),
    ("JNJ",  4.9600, 165.00, 3.01),
]


def _info(rate=None, price=None, dy=None, avg5=None, tay=None):
    d = {}
    if rate is not None:
        d["trailingAnnualDividendRate"] = rate
    if price is not None:
        d["currentPrice"] = price
    if tay is not None:
        d["trailingAnnualDividendYield"] = tay
    if dy is not None:
        d["dividendYield"] = dy
    if avg5 is not None:
        d["fiveYearAvgDividendYield"] = avg5
    return d


# --------------------------------------------------------------------------- #
#  (a) La derivación tiene que sobrevivir a una segunda opinión               #
# --------------------------------------------------------------------------- #


class TestElRateSobrePrecioNoEsInmuneALaMoneda:

    @pytest.mark.parametrize("sym,rate,price,tay,dy,avg5,pais", CORRUPTOS)
    def test_no_devuelve_el_numero_que_los_otros_dos_campos_desmienten(
        self, sym, rate, price, tay, dy, avg5, pais
    ):
        """El defecto, aislado: dos campos coinciden y el motor cree al tercero."""
        derivado = rate / price * 100
        got = normalize_dividend_yield_pct(_info(rate, price, dy, avg5, tay))

        assert got is not None, f"{sym}: descartar no es medir"
        assert got == pytest.approx(dy, rel=0.02), (
            f"{sym} ({pais}): el motor resolvió {got:.2f}%, pero dividendYield dice "
            f"{dy:.2f}% y el promedio de 5 años {avg5:.2f}%. "
            f"El derivado rate/price da {derivado:.2f}% — {derivado / dy:.1f}x."
        )

    @pytest.mark.parametrize("sym,rate,price,tay,dy,avg5,pais", CORRUPTOS)
    def test_el_promedio_de_cinco_anios_le_da_la_razon_al_feed(
        self, sym, rate, price, tay, dy, avg5, pais
    ):
        """El testigo independiente. Esto no es parte del arreglo: es el hecho
        sobre los datos que vuelve defendible preferir ``dividendYield``. Si
        alguna vez deja de valer, la regla de desempate hay que rediscutirla."""
        derivado = rate / price * 100
        assert abs(avg5 - dy) < abs(avg5 - derivado), (
            f"{sym}: el promedio de 5 años ({avg5}%) ya no arbitra a favor de "
            f"dividendYield ({dy}%) contra rate/price ({derivado:.2f}%)"
        )

    @pytest.mark.parametrize("sym,rate,price,dy", SANOS)
    def test_cuando_los_campos_coinciden_gana_el_derivado_sin_moverse(
        self, sym, rate, price, dy
    ):
        """Anti-cheat: el arreglo saca una corrupción, no la precisión.

        Para los 122 tickers donde los tres campos concuerdan, ``rate/price`` es
        la definición misma del yield y es más preciso que el redondeo del feed.
        Su valor tiene que quedar byte-idéntico."""
        got = normalize_dividend_yield_pct(_info(rate, price, dy, None))
        assert got == pytest.approx(rate / price * 100, rel=1e-12)

    def test_el_corte_cae_en_la_banda_vacia_medida(self):
        """El umbral no se calibra: separa dos poblaciones que no se tocan.

        Medido sobre los 130 tickers cacheados con los tres campos — los sanos
        llegan a 1.037x y los corruptos arrancan en 3.117x. Cualquier corte
        dentro de la banda vacía parte igual; lo que este test fija es que el
        elegido esté **adentro** de ella, no pegado a un borde."""
        from config import THRESHOLDS

        corte = THRESHOLDS.dividend_yield_crosscheck_ratio
        assert 1.10 < corte < 3.00, (
            f"el corte {corte} salió de la banda vacía 1.04x-3.12x: o los datos "
            f"cambiaron o el número se eligió por otra razón que hay que escribir"
        )

    @pytest.mark.parametrize("sym,rate,price,tay,dy,avg5,pais", CORRUPTOS)
    def test_se_descarta_la_familia_entera_no_solo_la_division(
        self, sym, rate, price, tay, dy, avg5, pais
    ):
        """El intento fallido que este PR hizo primero, fijado como test.

        ``trailingAnnualDividendRate / price`` y ``trailingAnnualDividendYield``
        son la MISMA magnitud —el importe del dividendo puesto contra el papel—
        y caen en la misma trampa de moneda: en ITUB dan 37.43 %% y 37.22 %%, en
        ABEV 24.70 %% y 24.33 %%. Guardar sólo la primera dejaba que la segunda
        repusiera el mismo número por la ventana, y la medición mostraba un
        arreglo que no arreglaba casi nada.

        Sin este test la mutación «guardá sólo rate/price» sobrevive: los
        fixtures que omitían ``tay`` la dejaban pasar.
        """
        por_division = rate / price * 100
        por_fraccion = tay * 100
        assert por_fraccion / dy > 2.0, (
            f"{sym}: el fixture ya no reproduce el caso — tay*100={por_fraccion:.2f}%% "
            f"no contradice a dividendYield={dy}%%"
        )
        got = normalize_dividend_yield_pct(_info(rate, price, dy, avg5, tay))
        assert got == pytest.approx(dy, rel=0.02), (
            f"{sym}: resolvió {got}, y las dos derivadas dicen "
            f"{por_division:.2f}%% y {por_fraccion:.2f}%%"
        )

    def test_sin_segunda_opinion_el_derivado_sigue_ganando(self):
        """Un ticker sin ``dividendYield`` no tiene con qué contrastarse. No
        inventamos una sospecha: se usa el derivado, como siempre."""
        got = normalize_dividend_yield_pct(_info(rate=2.08, price=68.0))
        assert got == pytest.approx(2.08 / 68.0 * 100, rel=1e-12)


# --------------------------------------------------------------------------- #
#  (b) No haber podido medir no es no tener                                    #
# --------------------------------------------------------------------------- #


def _dividend_score(info: dict) -> tuple[float, str]:
    analyzer = FundamentalAnalyzer()
    result = FundamentalResult(symbol="X", company_name="X")
    score = analyzer._score_dividends(info, result)
    return score, result.notes.get("dividend", "")


class TestUnYieldQueNoSePudoMedirNoEsUnaEmpresaSinDividendo:

    def test_una_pagadora_inmensurable_no_se_describe_como_growth(self):
        """El defecto: la empresa reporta $2/acción de dividendo y el producto
        le dice al usuario que no paga y reinvierte el flujo."""
        info = _info(rate=2.0)          # paga, pero sin precio no hay yield
        assert normalize_dividend_yield_pct(info) is None

        _, nota = _dividend_score(info)
        assert "No dividend" not in nota, (
            f"una empresa que reporta un dividendo de $2/acción no puede ser "
            f"descrita como que no paga: {nota!r}"
        )
        assert "growth" not in nota.lower(), nota

    def test_una_pagadora_inmensurable_no_cobra_el_credito_de_no_pagar(self):
        """Los +3 puntos son un crédito por reinvertir. Una empresa que reparte
        no lo puede cobrar sólo porque el feed no dejó medir cuánto reparte."""
        medible, _ = _dividend_score(_info(rate=2.08, price=68.0, dy=3.06))
        inmensurable, _ = _dividend_score(_info(rate=2.0))
        no_pagadora, _ = _dividend_score({})

        assert inmensurable < no_pagadora, (
            f"inmensurable ({inmensurable}) cobra igual o más que una empresa "
            f"que efectivamente no paga ({no_pagadora})"
        )
        assert inmensurable < medible

    def test_la_que_de_verdad_no_paga_conserva_su_credito(self):
        """Anti-cheat: el arreglo separa dos casos, no castiga a las growth.

        Una empresa sin ningún campo de dividendo no está ocultando nada — no
        paga, y reinvertir el flujo no es un defecto."""
        score, nota = _dividend_score({})
        assert score == pytest.approx(3.0)
        assert "No dividend" in nota

    @pytest.mark.parametrize("sym,last_val,ultimo_pago", [
        ("ADBE", 0.0065, "2005-03-24"),
        ("MELI", 0.1500, "2017-12-28"),
        ("PAM",  0.0750, "2012-01-12"),
        ("YPF",  0.1380, "2019-07-09"),
        ("LOMA", 0.4650, "2023-06-30"),
        ("CEPU", 0.3500, "2024-11-29"),
    ])
    def test_haber_pagado_alguna_vez_no_es_pagar(self, sym, last_val, ultimo_pago):
        """Anti-cheat en la dirección contraria, y un falso positivo que este PR
        se comió antes de medir.

        ``lastDividendValue`` es el registro del último dividendo que la empresa
        pagó **alguna vez**, no una señal de que siga pagando: Adobe lo trae en
        0.0065 con fecha 2005. Si cuenta como evidencia de reparto, seis growth
        genuinas pierden su crédito de +3 — el mismo defecto que N5 arregla, en
        espejo. Los tres campos que sí valen son de los últimos doce meses.
        """
        info = {"lastDividendValue": last_val}
        score, nota = _dividend_score(info)
        assert score == pytest.approx(3.0), (
            f"{sym} no paga desde {ultimo_pago}: es growth, no una pagadora "
            f"inmensurable"
        )
        assert "No dividend" in nota

    def test_el_caso_queda_marcado_para_que_el_usuario_lo_vea(self):
        """Un dato que no se pudo medir tiene que dejar rastro donde se lee, no
        sólo en el log — que es la diferencia entre U3-1 y su versión previa."""
        analyzer = FundamentalAnalyzer()
        result = FundamentalResult(symbol="X", company_name="X")
        analyzer._score_dividends(_info(rate=2.0), result)

        rastro = (result.notes.get("dividend", "") + " " + " ".join(result.warnings)).lower()
        assert "medir" in rastro or "desconocid" in rastro, (
            f"no queda rastro legible de que el yield no se pudo medir: "
            f"notes={result.notes} warnings={result.warnings}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
