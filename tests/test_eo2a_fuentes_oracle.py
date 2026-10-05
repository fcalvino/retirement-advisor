"""Oráculo EO-2a: Fuentes por Clase de activo, su central y su Desacuerdo (ADR 0001).

La Estimación objetiva sale de Fuentes declaradas, cada una con fecha y procedencia.
Por Clase de activo: central = mediana de las Fuentes vigentes, Desacuerdo = su
rango. Una Fuente de más de 12 meses avisa; de más de 24 sale del central pero
sigue en el desglose, marcada. Cripto es Fuente declarada ausente: sin central.

Decisiones del usuario (2026-10-04): seis Clases —acciones EE.UU., desarrolladas
ex-EE.UU., emergentes (incluye Argentina), bonos EE.UU., REITs y cripto—.

Los números esperados están hechos a mano en cada test.
"""

from __future__ import annotations

from datetime import date

import pytest

TODAY = date(2026, 10, 4)


def _src(value, *, as_of=date(2026, 1, 15), name="X", basis="nominal"):
    from analysis.fuentes import Fuente

    return Fuente(
        name=name, kind="gestora", asset_class="us_equity", value_pct=value,
        basis=basis, currency="USD", as_of=as_of, source="https://example.org",
        edition="test",
    )


# --------------------------------------------------------------------------- #
#  Central y Desacuerdo                                                        #
# --------------------------------------------------------------------------- #

def test_the_central_is_the_median_and_the_disagreement_the_range():
    from analysis.fuentes import summarize_class

    s = summarize_class("us_equity", [_src(5.0), _src(7.0), _src(6.5)], today=TODAY)
    assert s.central_pct == 6.5          # mediana de 5,0 · 6,5 · 7,0
    assert (s.low_pct, s.high_pct) == (5.0, 7.0)


def test_an_even_number_of_sources_averages_the_middle_two():
    from analysis.fuentes import summarize_class

    s = summarize_class("us_equity", [_src(4.0), _src(9.0), _src(5.0), _src(6.0)], today=TODAY)
    assert s.central_pct == 5.5          # (5,0 + 6,0) / 2
    assert (s.low_pct, s.high_pct) == (4.0, 9.0)


# --------------------------------------------------------------------------- #
#  Antigüedad: aviso a los 12 meses, fuera del central a los 24                #
# --------------------------------------------------------------------------- #

def test_a_13_month_old_source_warns_but_counts():
    from analysis.fuentes import summarize_class

    old = _src(9.0, as_of=date(2025, 9, 1), name="Vieja")      # 13 meses antes
    s = summarize_class("us_equity", [_src(5.0), old], today=TODAY)
    assert s.central_pct == 7.0                                  # (5,0 + 9,0) / 2
    assert [f.name for f in s.stale] == ["Vieja"]
    assert s.excluded == []


def test_a_25_month_old_source_leaves_the_central_but_stays_listed():
    from analysis.fuentes import summarize_class

    ancient = _src(9.0, as_of=date(2024, 9, 1), name="Vencida")  # 25 meses antes
    s = summarize_class("us_equity", [_src(5.0), _src(6.0), ancient], today=TODAY)
    assert s.central_pct == 5.5                                  # sólo 5,0 y 6,0
    assert (s.low_pct, s.high_pct) == (5.0, 6.0)
    assert [f.name for f in s.excluded] == ["Vencida"]
    assert "Vencida" in [f.name for f in s.all_sources]


# --------------------------------------------------------------------------- #
#  Cripto: Fuente declarada ausente                                            #
# --------------------------------------------------------------------------- #

def test_crypto_is_a_declared_absent_source_without_a_central():
    from analysis.fuentes import summarize_class

    s = summarize_class("crypto", [], today=TODAY)
    assert s.declared_absent is True
    assert s.central_pct is None and s.low_pct is None


def test_the_six_classes_are_the_users():
    from config import FUENTES

    assert set(FUENTES.asset_classes) == {
        "us_equity", "developed_ex_us", "emerging", "us_bonds", "reits", "crypto",
    }
    assert FUENTES.declared_absent == ("crypto",)


# --------------------------------------------------------------------------- #
#  Ticker → Clase                                                              #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("symbol, country, sector, kind, expected", [
    ("AAPL", "United States", "Technology", "equity", "us_equity"),
    ("O", "United States", "Real Estate", "equity", "reits"),
    ("PLD", "United States", "Real Estate", "equity", "reits"),
    ("SAP.DE", "Germany", "Technology", "equity", "developed_ex_us"),
    ("7203.T", "Japan", "Consumer Cyclical", "equity", "developed_ex_us"),
    ("YPF", "Argentina", "Energy", "equity", "emerging"),      # ADR argentino
    ("TEO", "Argentina", "Communication Services", "equity", "emerging"),
    ("TSM", "Taiwan", "Technology", "equity", "emerging"),
    ("VALE3.SA", "Brazil", "Basic Materials", "equity", "emerging"),
    ("SPY", None, None, "fund", "us_equity"),
    ("SCHD", None, None, "fund", "us_equity"),
    ("BND", None, None, "fund", "us_bonds"),
    ("EWZ", None, None, "fund", "emerging"),
    ("BTC-USD", None, None, "crypto", "crypto"),
])
def test_a_sample_of_the_universes_maps_to_its_class(symbol, country, sector, kind, expected):
    from analysis.fuentes import asset_class_for

    assert asset_class_for(symbol, country=country, sector=sector, kind=kind) == expected


def test_a_ticker_without_a_class_is_reported_not_defaulted():
    from analysis.fuentes import asset_class_for, unmapped

    assert asset_class_for("XYZ", country=None, sector=None, kind="fund") is None
    assert asset_class_for("ACME", country="Atlantis", sector="Industrials", kind="equity") is None
    rows = [
        {"symbol": "AAPL", "country": "United States", "sector": "Technology", "kind": "equity"},
        {"symbol": "XYZ", "country": None, "sector": None, "kind": "fund"},
    ]
    assert unmapped(rows) == ["XYZ"]


# --------------------------------------------------------------------------- #
#  El archivo curado                                                           #
# --------------------------------------------------------------------------- #

def test_the_loader_reads_a_cited_entry_and_keeps_a_published_range(tmp_path):
    import json

    from analysis.fuentes import load_sources

    path = tmp_path / "p.json"
    path.write_text(json.dumps({"_doc": ["x"], "entries": [{
        "name": "Vanguard VCMM", "kind": "gestora", "asset_class": "us_equity",
        "value_pct": 5.2, "range_pct": [4.2, 6.2], "basis": "nominal",
        "currency": "USD", "as_of": "2026-06-30", "edition": "VCMM 2026-06",
        "source": "https://corporate.vanguard.com/…",
    }]}), encoding="utf-8")
    [f] = load_sources(path)
    assert (f.value_pct, f.range_pct, f.as_of) == (5.2, (4.2, 6.2), date(2026, 6, 30))


def test_an_entry_for_an_unknown_class_is_refused(tmp_path):
    import json

    from analysis.fuentes import load_sources

    path = tmp_path / "p.json"
    path.write_text(json.dumps({"entries": [{
        "name": "X", "kind": "gestora", "asset_class": "gold", "value_pct": 3.0,
        "basis": "nominal", "currency": "USD", "as_of": "2026-06-30", "source": "s",
    }]}), encoding="utf-8")
    with pytest.raises(ValueError, match="gold"):
        load_sources(path)


def test_every_shipped_entry_is_cited_dated_and_nominal_or_real():
    """Contrato del archivo versionado: sin cita, sin fecha o sin base no entra."""
    from pathlib import Path

    from analysis.fuentes import load_sources
    from config import FUENTES

    shipped = load_sources(Path(__file__).resolve().parents[1] / FUENTES.data_file)
    assert shipped, "el archivo curado está vacío"
    for f in shipped:
        assert f.source.startswith("http"), f
        assert f.basis in ("nominal", "real"), f
        assert f.asset_class not in FUENTES.declared_absent, f


# --------------------------------------------------------------------------- #
#  Las seis Clases a la vez, y la vista «Supuestos»                            #
# --------------------------------------------------------------------------- #

def _fixture_sources():
    from analysis.fuentes import Fuente

    def f(cls, v, as_of, name):
        return Fuente(name=name, kind="gestora", asset_class=cls, value_pct=v, basis="nominal",
                      currency="USD", as_of=as_of, source="https://example.org", edition="e")

    return [
        f("us_equity", 5.0, date(2026, 6, 30), "A"),
        f("us_equity", 6.0, date(2026, 6, 30), "B"),
        f("us_equity", 9.0, date(2024, 9, 1), "Vencida"),      # 25 meses: fuera
        f("us_bonds", 4.0, date(2025, 9, 1), "Vieja"),         # 13 meses: avisa
    ]


def test_summarize_all_covers_the_six_classes_even_without_sources():
    from analysis.fuentes import summarize_all

    out = summarize_all(_fixture_sources(), today=TODAY)
    assert list(out) == ["us_equity", "developed_ex_us", "emerging", "us_bonds", "reits", "crypto"]
    assert out["us_equity"].central_pct == 5.5                  # (5,0 + 6,0) / 2
    assert out["reits"].central_pct is None and not out["reits"].declared_absent
    assert out["crypto"].declared_absent


def test_the_supuestos_page_shows_central_range_age_and_crypto(monkeypatch):
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    import analysis.fuentes as fuentes_mod

    monkeypatch.setattr(fuentes_mod, "load_shipped", lambda: _fixture_sources())
    monkeypatch.setattr(fuentes_mod, "today", lambda: TODAY)
    page = Path(__file__).resolve().parents[1] / "dashboard/views/21_Supuestos.py"
    at = AppTest.from_file(str(page), default_timeout=60)
    at.run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    text = "\n".join((getattr(e, "value", "") or "") for coll in (
        at.markdown, at.caption, at.info, at.warning) for e in coll)
    assert "5.5%" in text and "5.0%–6.0%" in text            # central y Desacuerdo
    assert "fuera del central" in text and "Vencida" in text  # 25 meses
    assert "vieja" in text.lower() and "Vieja" in text        # 13 meses
    assert "sin Fuente externa" in text                       # cripto


@pytest.mark.parametrize("symbol, country", [("MELI", "Uruguay"), ("GLOB", "Luxembourg")])
def test_meli_and_glob_go_to_emerging_by_the_users_decision(symbol, country):
    """Domicilio fuera de las listas de MSCI, negocio en América Latina: emergentes
    (decisión del usuario, 2026-10-05, al validar EO-2a). Un país sin lista sigue sin Clase."""
    from analysis.fuentes import asset_class_for

    assert asset_class_for(symbol, country=country, sector="Technology", kind="equity") == "emerging"
    assert asset_class_for("OTRA", country=country, sector="Technology", kind="equity") is None
