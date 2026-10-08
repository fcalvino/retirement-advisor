"""Oráculo EO-6b-2: un dato faltante del Consistency Score recibe la mediana de su sector.

Decisiones del usuario (2026-10-08, sobre lo medido en el universo cacheado: 189 equities
en 11 sectores de 4 a 34 tickers, y sólo 1 equity —ISRG— con datos faltantes):

- el 0 de ``missing_data_score`` deja de ser lo que recibe un equity sin historia: recibe
  la mediana de esa dimensión (ROE, EPS, márgenes; 0–5) entre los equities de su sector
  que sí la tienen, tomada del universo cacheado y sin red;
- con menos de 5 datos en el sector (``sector_median_min_tickers``) vale la mediana de
  todos los equities;
- fondos y cripto no se imputan: puntúan en otra escala (medido: los 5 ETF tienen las tres
  dimensiones faltantes y recibir la mediana de un equity los subiría ~10 puntos);
- la mediana es una tabla derivada y versionada (``scripts/refresh_sector_medians.py``).

Los números esperados están hechos a mano. Sin red.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import analysis.sector_medians as sm
from analysis.scoring import EnhancedScoring
from config import CONSISTENCY, ENGINE_VERSION, SIGNAL_METHOD_VERSION
from tests.conftest import _make_balance_sheet, _make_income_stmt

ROOT = Path(__file__).resolve().parents[1]

# Una tabla a mano: Healthcare con 24 datos; Real Estate con 4 (bajo el mínimo de 5).
TABLE = sm.SectorMedians(
    as_of="2026-10-08", universe_n=189,
    sectors={
        "Healthcare": {"roe": {"median": 1.5, "n": 24}, "eps": {"median": 1.0, "n": 24},
                       "margin": {"median": 4.0, "n": 24}},
        "Real Estate": {"roe": {"median": 4.0, "n": 4}, "eps": {"median": 1.0, "n": 4},
                        "margin": {"median": 4.0, "n": 4}},
    },
    all_equity={"roe": {"median": 5.0, "n": 188}, "eps": {"median": 1.0, "n": 188},
                "margin": {"median": 5.0, "n": 188}},
)


@pytest.fixture
def tabla(monkeypatch):
    monkeypatch.setattr(sm, "load_shipped", lambda: TABLE)


def _sin_historia():
    """Un solo año: ni ROE ni márgenes (≥2) ni EPS (≥3) se pueden medir."""
    return (_make_income_stmt(net_income=[500], revenue=[1000]),
            _make_balance_sheet(stockholders_equity=[2000], total_assets=[4000]))


def _detail(sector, asset_class="equity"):
    income, balance = _sin_historia()
    return EnhancedScoring().get_enhanced_score(
        50.0, {}, income, balance, sector=sector, asset_class=asset_class
    ).consistency_detail


# --------------------------------------------------------------------------- #
#  La imputación                                                               #
# --------------------------------------------------------------------------- #

def test_a_healthcare_equity_without_history_gets_the_sector_medians(tabla):
    d = _detail("Healthcare")
    assert (d.roe_score, d.eps_score, d.margin_score) == (1.5, 1.0, 4.0)
    assert d.total == 6.5                                   # 1,5 + 1,0 + 4,0
    assert d.missing == ["roe", "eps", "margin"]
    assert d.imputed == {"roe": 1.5, "eps": 1.0, "margin": 4.0}
    assert any("mediana de Healthcare (n=24)" in n for n in d.notes)


def test_the_adjusted_score_moves_by_exactly_the_imputed_points(tabla, monkeypatch):
    income, balance = _sin_historia()
    scorer = EnhancedScoring()
    con = scorer.get_enhanced_score(50.0, {}, income, balance, sector="Healthcare",
                                    asset_class="equity")
    monkeypatch.setattr(CONSISTENCY, "impute_from_sector_median", False)
    sin = scorer.get_enhanced_score(50.0, {}, income, balance, sector="Healthcare",
                                    asset_class="equity")
    assert sin.consistency_score == 0.0
    assert con.adjusted_score - sin.adjusted_score == pytest.approx(6.5)


def test_a_sector_under_the_minimum_uses_the_median_of_all_equities(tabla):
    d = _detail("Real Estate")                              # n=4 < 5
    assert (d.roe_score, d.eps_score, d.margin_score) == (5.0, 1.0, 5.0)
    assert any("mediana de todos los equities (n=188)" in n for n in d.notes)


def test_a_ticker_without_sector_uses_the_median_of_all_equities(tabla):
    assert _detail(None).total == 11.0                      # 5,0 + 1,0 + 5,0


@pytest.mark.parametrize("asset_class", ["fund", "crypto", None])
def test_funds_crypto_and_unknown_class_are_not_imputed(tabla, asset_class):
    d = _detail("Healthcare", asset_class)
    assert d.total == 0.0 and d.imputed == {}
    assert d.missing == ["roe", "eps", "margin"]


def test_without_a_table_the_old_zero_stays(monkeypatch):
    monkeypatch.setattr(sm, "load_shipped", lambda: None)
    assert _detail("Healthcare").total == 0.0


def test_a_measured_dimension_is_never_replaced(tabla, stable_income_stmt, stable_balance_sheet):
    d = EnhancedScoring().get_enhanced_score(
        50.0, {}, stable_income_stmt, stable_balance_sheet, sector="Healthcare",
        asset_class="equity").consistency_detail
    assert d.missing == [] and d.imputed == {}


def test_without_sector_and_class_the_scorer_is_the_old_one():
    """Los callers que no pasan contexto (tests, point-in-time) no cambian."""
    income, balance = _sin_historia()
    d = EnhancedScoring().get_enhanced_score(50.0, {}, income, balance).consistency_detail
    assert d.total == 0.0 and d.imputed == {}


# --------------------------------------------------------------------------- #
#  La tabla                                                                    #
# --------------------------------------------------------------------------- #

def test_lookup_applies_the_minimum_from_config():
    assert CONSISTENCY.sector_median_min_tickers == 5
    hit = TABLE.lookup("margin", "Healthcare", min_tickers=5)
    assert (hit.value, hit.source, hit.n) == (4.0, "Healthcare", 24)
    assert TABLE.lookup("margin", "Real Estate", min_tickers=5).source == sm.ALL_EQUITY
    assert TABLE.lookup("margin", "Real Estate", min_tickers=4).source == "Real Estate"
    with pytest.raises(ValueError):
        TABLE.lookup("ebitda", "Healthcare", min_tickers=5)


def test_build_table_by_hand_skips_missing_and_splits_by_sector():
    rows = [
        {"sector": "A", "roe": 5.0, "eps": 1.0, "margin": 3.0},
        {"sector": "A", "roe": 1.0, "eps": None, "margin": 5.0},
        {"sector": "A", "roe": 3.0, "eps": 2.0, "margin": None},
        {"sector": "B", "roe": 4.0, "eps": 4.0, "margin": 4.0},
        {"sector": "", "roe": 0.5, "eps": None, "margin": None},
    ]
    t = sm.build_table(rows, as_of="2026-10-08")
    assert t["universe_n"] == 5
    assert t["sectors"]["A"] == {"roe": {"median": 3.0, "n": 3}, "eps": {"median": 1.5, "n": 2},
                                 "margin": {"median": 4.0, "n": 2}}
    assert t["sectors"]["B"]["roe"] == {"median": 4.0, "n": 1}
    assert "" not in t["sectors"]
    # todos: roe [5,1,3,4,0.5] → 3,0 · eps [1,2,4] → 2,0 · margin [3,5,4] → 4,0
    assert t["all_equity"] == {"roe": {"median": 3.0, "n": 5}, "eps": {"median": 2.0, "n": 3},
                               "margin": {"median": 4.0, "n": 3}}


def test_the_shipped_table_is_well_formed():
    data = json.loads((ROOT / CONSISTENCY.sector_medians_file).read_text(encoding="utf-8"))
    table = sm.load(ROOT / CONSISTENCY.sector_medians_file)
    assert table.as_of == data["as_of"] and table.universe_n >= 100
    for dim in sm.DIMENSIONS:
        assert 0.0 <= table.all_equity[dim]["median"] <= 5.0
        assert table.all_equity[dim]["n"] <= table.universe_n
    for sector, dims in table.sectors.items():
        for dim, cell in dims.items():
            assert 0.0 <= cell["median"] <= 5.0 and cell["n"] >= 1, (sector, dim)
    # El respaldo siempre alcanza el mínimo: ningún equity cae al 0 con la tabla puesta.
    for dim in sm.DIMENSIONS:
        assert table.lookup(dim, "Sector inexistente",
                            min_tickers=CONSISTENCY.sector_median_min_tickers) is not None


def test_the_shipped_table_matches_what_was_measured():
    """Los números que se midieron en el sandbox el 2026-10-08, en las tres cuentas a mano."""
    t = sm.load(ROOT / CONSISTENCY.sector_medians_file)
    assert t.sectors["Healthcare"]["roe"]["median"] == 1.5 and t.sectors["Healthcare"]["roe"]["n"] == 24
    assert t.sectors["Real Estate"]["roe"]["n"] == 4
    assert t.all_equity["roe"] == {"median": 5.0, "n": 188}


# --------------------------------------------------------------------------- #
#  Versiones                                                                   #
# --------------------------------------------------------------------------- #

def test_the_signal_method_version_moves_and_the_engine_does_not():
    assert SIGNAL_METHOD_VERSION == "2026.10-senales3"
    # El μ del Optimizer sale de la Clase (EO-4b) y el Monte Carlo no lee el score: el
    # score sólo ordena el pool del Optimizer. No hay μ ni Monte Carlo que se mueva.
    assert ENGINE_VERSION == "2026.10-tier23"
