"""Oráculo EO-2b: valuación (CAPE de Shiller, Tesoro a 10 años) e Historia por Clase.

Decisiones del usuario (2026-10-05):
- Del archivo de Shiller sólo se guardan números derivados, citados con la fecha de
  descarga y el sha256 del archivo: no trae licencia y el repo es público.
- CAPE → rendimiento esperado: 1/CAPE (real) compuesto con la inflación implícita a
  10 años (FRED T10YIE), nominal en USD.
- Al central entran todas las Fuentes: gestoras, valuación e Historia (ADR literal).
- La Historia de bonos es VBMFX (el agregado, como las gestoras), no el Tesoro de Shiller.

Los números esperados están hechos a mano en cada test.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

TODAY = date(2026, 10, 5)


def _src(value, *, kind="gestora", basis="nominal", name="X", cls="us_equity",
         period_start=None, as_of=date(2026, 6, 30)):
    from analysis.fuentes import Fuente

    return Fuente(
        name=name, kind=kind, asset_class=cls, value_pct=value, basis=basis,
        currency="USD", as_of=as_of, source="https://example.org", edition="e",
        period_start=period_start,
    )


# --------------------------------------------------------------------------- #
#  Aritmética                                                                  #
# --------------------------------------------------------------------------- #

def test_annualized_return_over_four_exact_years():
    from analysis.fuentes import annualized_pct, years_between

    years = years_between(date(2000, 1, 1), date(2004, 1, 1))
    assert years == pytest.approx(4.0)                  # 1461 días / 365,25
    assert annualized_pct(100.0, 146.41, years) == pytest.approx(10.0)   # 1,1⁴ = 1,4641


def test_real_to_nominal_compounds_with_inflation():
    from analysis.fuentes import real_to_nominal_pct

    assert real_to_nominal_pct(2.0, 3.0) == pytest.approx(5.06)   # 1,02 × 1,03 − 1


def test_cape_expected_return_is_the_earnings_yield_plus_breakeven():
    from analysis.fuentes import cape_expected_return_pct

    # CAPE 25 → rendimiento de las ganancias 4 % real; con 2 % de inflación implícita:
    # 1,04 × 1,02 − 1 = 6,08 %.
    assert cape_expected_return_pct(25.0, 2.0) == pytest.approx(6.08)


def test_a_price_series_is_cut_at_the_last_complete_month():
    from analysis.fuentes import cut_at_month_end

    obs = [(date(2026, 8, 31), 10.0), (date(2026, 9, 30), 11.0), (date(2026, 10, 2), 12.0)]
    assert cut_at_month_end(obs, today=TODAY) == [(date(2026, 8, 31), 10.0),
                                                  (date(2026, 9, 30), 11.0)]


# --------------------------------------------------------------------------- #
#  Shiller: números derivados de las filas de ie_data.xls                      #
# --------------------------------------------------------------------------- #

def _shiller_rows():
    from analysis.fuentes import ShillerRow

    return [
        ShillerRow(year=2000, month=1, cpi=100.0, real_tr_price=100.0, cape=20.0),
        ShillerRow(year=2001, month=1, cpi=102.0, real_tr_price=110.0, cape=22.0),
        ShillerRow(year=2002, month=1, cpi=104.04, real_tr_price=121.0, cape=25.0),
        # La última fila de Shiller es provisoria (precio del día 1, IPC estimado).
        ShillerRow(year=2002, month=2, cpi=999.0, real_tr_price=999.0, cape=99.0),
    ]


def test_shiller_skips_the_provisional_last_row_and_derives_the_cape_source():
    from analysis.fuentes import shiller_entries

    out = shiller_entries(_shiller_rows(), breakeven_pct=2.0, breakeven_as_of="2002-02-15",
                          file_note="test")
    cape = next(e for e in out if e["kind"] == "valuacion")
    assert cape["asset_class"] == "us_equity"
    assert cape["value_pct"] == pytest.approx(6.08)    # CAPE 25 de enero 2002, no el 99
    assert cape["as_of"] == "2002-01-31"
    assert cape["basis"] == "nominal"


def test_shiller_history_is_the_real_total_return_made_nominal_with_its_cpi():
    from analysis.fuentes import shiller_entries

    out = shiller_entries(_shiller_rows(), breakeven_pct=2.0, breakeven_as_of="2002-02-15",
                          file_note="test")
    hist = next(e for e in out if e["kind"] == "historia")
    # 24 meses: real 100 → 121 = 10 % anual; IPC 100 → 104,04 = 2 % anual;
    # nominal 1,10 × 1,02 − 1 = 12,2 %.
    assert hist["value_pct"] == pytest.approx(12.2)
    assert (hist["period_start"], hist["as_of"]) == ("2000-01-01", "2002-01-31")
    assert hist["asset_class"] == "us_equity"


# --------------------------------------------------------------------------- #
#  El central con todas las Fuentes, y una sola base                           #
# --------------------------------------------------------------------------- #

def test_valuation_and_history_enter_the_central_with_the_gestoras():
    from analysis.fuentes import summarize_class

    s = summarize_class("us_equity", [
        _src(6.7), _src(5.2), _src(8.97),
        _src(4.8, kind="valuacion"), _src(9.4, kind="historia", period_start=date(1871, 1, 1)),
    ], today=TODAY)
    assert s.central_pct == 6.7          # mediana de 4,8 · 5,2 · 6,7 · 8,97 · 9,4
    assert (s.low_pct, s.high_pct) == (4.8, 9.4)


def test_a_real_source_never_mixes_into_a_nominal_central():
    from analysis.fuentes import summarize_class

    with pytest.raises(ValueError, match="base"):
        summarize_class("us_equity", [_src(6.0), _src(3.0, basis="real")], today=TODAY)


# --------------------------------------------------------------------------- #
#  El archivo: carga el período y el contrato de lo versionado                 #
# --------------------------------------------------------------------------- #

def test_the_loader_reads_the_history_period(tmp_path):
    from analysis.fuentes import load_sources

    path = tmp_path / "p.json"
    path.write_text(json.dumps({"entries": [{
        "name": "H", "kind": "historia", "asset_class": "reits", "value_pct": 8.7,
        "basis": "nominal", "currency": "USD", "as_of": "2026-09-30",
        "period_start": "1996-05-13", "source": "https://example.org",
    }]}), encoding="utf-8")
    (f,) = load_sources(path)
    assert f.period_start == date(1996, 5, 13)


def test_every_class_but_crypto_ships_one_dated_history_and_the_valuations():
    from analysis.fuentes import load_shipped
    from config import FUENTES

    shipped = load_shipped()
    for cls in FUENTES.asset_classes:
        hist = [f for f in shipped if f.asset_class == cls and f.kind == "historia"]
        if cls in FUENTES.declared_absent:
            assert hist == [], cls
            continue
        assert len(hist) == 1, cls
        assert hist[0].period_start is not None and hist[0].period_start < hist[0].as_of
    vals = {(f.asset_class, f.name) for f in shipped if f.kind == "valuacion"}
    assert {c for c, _ in vals} == {"us_equity", "us_bonds"}
    assert all(f.basis == "nominal" for f in shipped)


def test_the_history_proxies_are_the_users():
    from config import FUENTES

    assert dict(FUENTES.history_proxies) == {
        "us_equity": "shiller", "developed_ex_us": "VTMGX", "emerging": "VEIEX",
        "us_bonds": "VBMFX", "reits": "VGSIX",
    }


def test_the_vtmgx_history_cites_its_index_changes():
    """VTMGX siguió el MSCI EAFE hasta 2013 y después índices FTSE: la Historia lo dice."""
    from analysis.fuentes import load_shipped

    (vtmgx,) = [f for f in load_shipped() if f.name == "VTMGX"]
    assert "MSCI EAFE hasta 2013-05-28" in vtmgx.note


def test_no_copy_of_the_shiller_file_is_versioned():
    """Sin licencia y con el repo público: el .xls queda en una carpeta ignorada."""
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    tracked = subprocess.run(["git", "ls-files", "*.xls", "*.xlsx"], cwd=root,
                             capture_output=True, text=True, check=True).stdout.split()
    assert not [t for t in tracked if "ie_data" in t], tracked


# --------------------------------------------------------------------------- #
#  La vista «Supuestos»                                                        #
# --------------------------------------------------------------------------- #

def test_the_supuestos_page_labels_kind_and_history_period(monkeypatch):
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    import analysis.fuentes as fuentes_mod

    fixture = [
        _src(6.0, name="Gestora A"),
        _src(4.8, kind="valuacion", name="CAPE de Shiller"),
        _src(9.4, kind="historia", name="S&P de Shiller", period_start=date(1871, 1, 1),
             as_of=date(2026, 8, 31)),
    ]
    monkeypatch.setattr(fuentes_mod, "load_shipped", lambda: fixture)
    monkeypatch.setattr(fuentes_mod, "today", lambda: TODAY)
    page = Path(__file__).resolve().parents[1] / "dashboard/views/21_Supuestos.py"
    at = AppTest.from_file(str(page), default_timeout=60)
    at.run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    text = "\n".join((getattr(e, "value", "") or "") for coll in (
        at.markdown, at.caption, at.info, at.warning) for e in coll)
    assert "Central 6.0%" in text and "4.8%–9.4%" in text      # mediana de 4,8 · 6,0 · 9,4
    assert "valuación" in text and "gestora" in text
    assert "historia 1871-01 → 2026-08" in text
