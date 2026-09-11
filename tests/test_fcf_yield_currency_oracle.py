"""Oracle for the FCF-yield currency fix — un yield sólo existe si las dos patas
comparten moneda.

``analysis/fundamental.py`` computaba ``fcf_yield = fcf_latest / market_cap * 100``
dividiendo el free cash flow —que yfinance publica en ``financialCurrency``, la
moneda de los estados contables— por el market cap —que publica en ``currency``,
la moneda de cotización—. Para un ADR latinoamericano el numerador viene en
COP/ARS/BRL/MXN y el denominador en USD, así que el cociente es dimensionalmente
incoherente: Bancolombia (CIB) llegó a **41 122 %** de FCF yield medido, CEPU a
**5 331 %**, América Móvil a **207 %**.

Es la misma trampa de moneda que N5 arregló para el dividendo
(``tests/test_dividend_yield_provenance_oracle.py``), pero acá **no hay un campo
independiente** contra el cual contrastar: ``freeCashflow`` arrastra idéntica
corrupción de moneda. La única señal disponible es que las dos monedas difieren,
así que el motor se niega a medir en vez de convertir.

**Este oráculo NO compara contra el motor viejo** (eso "congela el bug", CONTEXT
§5). Compara contra una implementación de referencia **derivada de la
definición**: un yield es un flujo sobre un valor y sólo está definido cuando
ambas patas comparten unidad. Fixtures hardcodeadas de la medición real
(``data/universes/latam_adrs.json``, yfinance en vivo 2026-09-10).

**El punto que un techo de plausibilidad no puede hacer.** ABEV corrupta da 42 %,
por debajo de cualquier techo razonable (``max_plausible_fcf_yield_pct = 50``),
y aun así es un número fabricado. El discriminador correcto es la moneda, no la
magnitud — y por eso el gate va primero. Ese caso está fijado abajo como test.

Sin red, sin Streamlit.
"""

from __future__ import annotations

import pytest

from analysis.fundamental import financial_currency_mismatch

# --------------------------------------------------------------------------- #
#  Los ADR con FCF yield corrupto. El market cap cotiza en USD; el FCF viene   #
#  en la moneda de los estados. `raw_yield_pct` es fcf/market_cap*100, el      #
#  número absurdo que el motor reportaba. `fin_ccy` es lo único que decide.    #
#  sym, fcf (fin_ccy), market_cap (USD), fin_ccy, raw_yield_pct, país          #
# --------------------------------------------------------------------------- #

CORRUPTOS = [
    ("CIB",  3_495_413_350_000, 8_500_000_000,  "COP", 41122.51, "Colombia"),
    ("CEPU",   106_637_200_000, 2_000_000_000,  "ARS",  5331.86, "Argentina"),
    ("AMX",    153_238_798_336, 73_895_000_000, "MXN",   207.38, "Mexico"),
    ("ABEV",    19_859_091_456, 46_900_000_000, "BRL",    42.34, "Brazil"),
]

#: El control. Emisor estadounidense: estados y cotización en la misma moneda,
#: así que el yield SÍ está definido y no se puede descartar sin una regresión.
#: sym, fcf (USD), market_cap (USD), fin_ccy, yield_pct
SANOS = [
    ("KO", 9_520_000_000, 680_000_000_000, "USD", 1.40),
]


def _info(fin_ccy=None, quote_ccy=None):
    d = {}
    if fin_ccy is not None:
        d["financialCurrency"] = fin_ccy
    if quote_ccy is not None:
        d["currency"] = quote_ccy
    return d


def fcf_yield_defined(fcf, market_cap, fin_ccy, quote_ccy):
    """Referencia derivada de la definición, no del motor viejo.

    Un yield es flujo sobre valor y sólo tiene sentido cuando las dos patas están
    en la misma unidad. Si las monedas difieren el yield es *indefinido* (no cero,
    no el cociente crudo): devuelve ``None``. Loop lento y obvio a propósito.
    """
    if str(fin_ccy).upper() != str(quote_ccy).upper():
        return None
    if market_cap <= 0:
        return None
    return fcf / market_cap * 100


class TestElYieldSoloExisteSiLasMonedasCoinciden:

    @pytest.mark.parametrize("sym,fcf,mcap,fin_ccy,raw,pais", CORRUPTOS)
    def test_el_gate_marca_el_mismatch_de_moneda(self, sym, fcf, mcap, fin_ccy, raw, pais):
        """El defecto, aislado: el FCF y el market cap están en monedas distintas."""
        got = financial_currency_mismatch(_info(fin_ccy, "USD"))
        assert got == (fin_ccy, "USD"), (
            f"{sym} ({pais}): el FCF viene en {fin_ccy} y el market cap en USD; "
            f"el cociente crudo da {raw:.2f}% y hay que negarse a medirlo."
        )

    @pytest.mark.parametrize("sym,fcf,mcap,fin_ccy,raw,pais", CORRUPTOS)
    def test_la_referencia_deja_el_yield_indefinido(self, sym, fcf, mcap, fin_ccy, raw, pais):
        """La definición coincide con el gate: monedas distintas ⇒ yield indefinido."""
        assert fcf_yield_defined(fcf, mcap, fin_ccy, "USD") is None
        # Y el crudo que el motor reportaba reproduce la medición real de §2.
        assert fcf / mcap * 100 == pytest.approx(raw, rel=0.01)

    def test_el_gate_discrimina_donde_un_techo_no_puede(self):
        """ABEV corrupta da 42 %, por debajo de cualquier techo razonable, y aun
        así es un número fabricado. La moneda lo caza; una cota de magnitud no."""
        abev = next(f for f in CORRUPTOS if f[0] == "ABEV")
        _, _, _, fin_ccy, raw, _ = abev
        assert raw < 50.0, "el fixture dejó de probar el caso sub-techo"
        assert financial_currency_mismatch(_info(fin_ccy, "USD")) is not None

    @pytest.mark.parametrize("sym,fcf,mcap,fin_ccy,y", SANOS)
    def test_el_control_en_la_misma_moneda_no_se_toca(self, sym, fcf, mcap, fin_ccy, y):
        """Anti-cheat: el arreglo saca una corrupción, no borra un yield legítimo."""
        assert financial_currency_mismatch(_info(fin_ccy, "USD")) is None
        assert fcf_yield_defined(fcf, mcap, fin_ccy, "USD") == pytest.approx(y, rel=0.02)


class TestSinLasDosMonedasNoSePuedeAfirmarElMismatch:

    def test_falta_financial_currency_devuelve_none(self):
        """Info cacheada vieja sin la clave: no se puede *afirmar* el mismatch.
        Ese hueco lo cubre aparte el techo de plausibilidad, no este gate."""
        assert financial_currency_mismatch(_info(quote_ccy="USD")) is None

    def test_falta_currency_devuelve_none(self):
        assert financial_currency_mismatch(_info(fin_ccy="COP")) is None

    def test_dict_vacio_devuelve_none(self):
        assert financial_currency_mismatch({}) is None

    def test_misma_moneda_devuelve_none(self):
        assert financial_currency_mismatch(_info("USD", "USD")) is None

    def test_la_comparacion_es_case_insensitive(self):
        assert financial_currency_mismatch(_info("usd", "USD")) is None
        assert financial_currency_mismatch(_info("brl", "USD")) == ("brl", "USD")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
