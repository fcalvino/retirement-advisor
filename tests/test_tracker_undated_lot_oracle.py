"""AUDIT-RESIDUALES (tracker) — un lote sin fecha legible no se mide con historia que no se vivió.

El recorte de la curva de riesgo abre la ventana en la compra del lote MÁS NUEVO de cualquier posición
(U5-12: antes, la curva multiplicaba cinco años de precios por las acciones de hoy). Pero si un lote no
tenía fecha legible, ``_held_from`` devolvía ``None`` y la curva no se recortaba: justo el caso sin fecha,
el que no se puede acotar, volvía a la historia inventada, y Sharpe, Sortino, drawdown y beta salían como
medidos. «Fecha de compra (opcional)» hace que un lote sin fecha sea legal.

Decisión del usuario (2026-10-28): con un lote sin fecha esas cuatro métricas quedan en «no medido», con
el símbolo nombrado para que se cargue la fecha. Los esperados son los de la regla enunciada; los precios
son inyectados y no hay red.
"""

from __future__ import annotations

import pytest

from portfolio.tracker import Portfolio
from tests.test_tracker_lots_curve_oracle import _ago, _install, _no_feed, _prices  # noqa: F401

RISK = ("sharpe_ratio", "downside_vol_ratio", "max_drawdown_pct", "beta")


def _book(tmp_path, monkeypatch, *, undated_lot: bool, second_undated: bool = False) -> Portfolio:
    series = {"KO": _prices(60.0, 0.001), "NVDA": _prices(100.0, 0.010), "SPY": _prices(400.0, 0.002)}
    _install(monkeypatch, series)
    p = Portfolio(file_path=tmp_path / "p.json")
    p.add_position("KO", 100.0, 55.0, purchase_date=_ago(104))
    p.add_position("KO", 100.0, 70.0, purchase_date="" if undated_lot else _ago(60))
    p.add_position("NVDA", 50.0, 150.0, purchase_date="" if second_undated else _ago(80))
    return p


def test_a_book_with_an_undated_lot_has_no_equity_curve(tmp_path, monkeypatch):
    assert _book(tmp_path, monkeypatch, undated_lot=True)._build_equity_curve() is None


def test_its_risk_metrics_are_not_measured_and_the_symbol_is_named(tmp_path, monkeypatch):
    metrics = _book(tmp_path, monkeypatch, undated_lot=True).compute_metrics()
    assert [getattr(metrics, f) for f in RISK] == [None, None, None, None]
    assert metrics.risk_curve_points == 0
    assert metrics.risk_measurable_from is None
    assert metrics.risk_undated_symbols == ["KO"]


def test_every_symbol_with_an_undated_lot_is_named_once_and_sorted(tmp_path, monkeypatch):
    metrics = _book(tmp_path, monkeypatch, undated_lot=True, second_undated=True).compute_metrics()
    assert metrics.risk_undated_symbols == ["KO", "NVDA"]


def test_a_position_created_without_a_date_is_undated(tmp_path, monkeypatch):
    series = {"KO": _prices(60.0, 0.001)}
    _install(monkeypatch, series)
    p = Portfolio(file_path=tmp_path / "p.json")
    p.add_position("KO", 100.0, 55.0, purchase_date="")
    assert p.compute_metrics().risk_undated_symbols == ["KO"]


def test_a_fully_dated_book_is_unaffected(tmp_path, monkeypatch):
    p = _book(tmp_path, monkeypatch, undated_lot=False)
    assert p._build_equity_curve() is not None
    assert p.compute_metrics().risk_undated_symbols == []


def test_the_caption_asks_for_the_date_of_the_named_symbol(tmp_path, monkeypatch):
    from data.product_ux import risk_unmeasured_caption

    caption = risk_unmeasured_caption(_book(tmp_path, monkeypatch, undated_lot=True).compute_metrics())
    assert "KO" in caption and "fecha" in caption
    assert "semanas" not in caption          # no es una curva corta: es una curva que no se puede armar


def test_the_caption_of_a_short_curve_is_unchanged(tmp_path, monkeypatch):
    from data.product_ux import risk_unmeasured_caption

    series = {"KO": _prices(60.0, 0.001)}
    _install(monkeypatch, series)
    p = Portfolio(file_path=tmp_path / "p.json")
    p.add_position("KO", 100.0, 55.0, purchase_date=_ago(2))
    caption = risk_unmeasured_caption(p.compute_metrics())
    assert "semanas" in caption and "fecha de compra" not in caption


@pytest.mark.parametrize("undated", [["KO"], []])
def test_the_committee_is_told_why_it_has_no_risk_figures(undated):
    from analysis.committee_prompts import portfolio_committee_context_block

    ctx = {"realized": {"sharpe_ratio": None, "downside_vol_ratio": None, "beta": None,
                        "max_drawdown_pct": None, "risk_curve_points": 0, "risk_undated_symbols": undated}}
    block = portfolio_committee_context_block(ctx)
    assert ("sin fecha de compra" in block) == bool(undated)
    if undated:
        assert "KO" in block and "No las supongas" in block


def test_a_book_where_no_position_has_a_date_has_no_annualized_return_and_does_not_crash(tmp_path, monkeypatch):
    """Antes: ``datetime.fromisoformat('')`` lanzaba ValueError. El 0,0 por defecto se leería como medido."""
    series = {"KO": _prices(60.0, 0.001)}
    _install(monkeypatch, series)
    p = Portfolio(file_path=tmp_path / "p.json")
    p.add_position("KO", 100.0, 55.0, purchase_date="")
    metrics = p.compute_metrics()
    assert metrics.annualized_return_pct is None


def test_a_dated_book_keeps_its_annualized_return(tmp_path, monkeypatch):
    p = _book(tmp_path, monkeypatch, undated_lot=False)
    assert p.compute_metrics().annualized_return_pct is not None


def test_a_date_with_a_utc_offset_is_a_readable_date_and_does_not_break_the_metrics(tmp_path, monkeypatch):
    series = {"KO": _prices(60.0, 0.001), "SPY": _prices(400.0, 0.002)}
    _install(monkeypatch, series)
    p = Portfolio(file_path=tmp_path / "p.json")
    p.add_position("KO", 100.0, 55.0, purchase_date=_ago(104) + "T00:00:00+00:00")
    metrics = p.compute_metrics()
    assert metrics.risk_undated_symbols == []
    assert metrics.annualized_return_pct is not None
