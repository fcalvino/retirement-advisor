"""AUDIT-NUMB-6 — el retorno anualizado no se calcula para una cartera de menos de un año.

``compute_metrics`` anualizaba con un piso de 0,1 años: una cartera de una semana con +10 % salía con
``1,10 ** (1 / 0,1) - 1`` = +159 %/año, una tasa que nadie obtuvo, en la tarjeta «Retorno anual».
Regla (GIPS: no se anualizan períodos de menos de un año; ``PORTFOLIO.min_annualize_years = 1.0``):
con menos de un año desde la primera compra el retorno anualizado queda en ``None`` («no medido»,
nunca 0), el P&L total ya es el retorno del período, y la pantalla y el comité dicen desde cuándo.

Los esperados salen de la definición ``(valor / costo) ** (365,25 / días) - 1`` escrita a mano. Precios
inyectados, sin red; la edad se cuenta desde el reloj (una fecha fija envejece).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from config import PORTFOLIO
from portfolio.tracker import Portfolio


def _days_ago(days: int) -> str:
    return (datetime.now() - timedelta(days=days)).date().isoformat()


@pytest.fixture(autouse=True)
def _feed(monkeypatch):
    """Today's price is 110 for a cost of 100, and the weekly history is empty (no risk curve)."""
    import pandas as pd

    monkeypatch.setattr("portfolio.tracker.get_info", lambda sym: {"currentPrice": 110.0})
    monkeypatch.setattr("portfolio.tracker.get_history", lambda *a, **k: pd.DataFrame())


def _metrics(tmp_path, days: int):
    p = Portfolio(file_path=tmp_path / "p.json")
    p.add_position("KO", 10.0, 100.0, purchase_date=_days_ago(days))
    return p.compute_metrics()


def test_the_minimum_age_is_one_year():
    assert PORTFOLIO.min_annualize_years == 1.0


def test_a_week_old_book_is_not_annualized_and_says_when_it_will_be(tmp_path):
    m = _metrics(tmp_path, 7)
    assert m.total_pnl_pct == pytest.approx(10.0)             # el retorno del período sigue ahí
    assert m.annualized_return_pct is None                    # y no 1,10 ** (365,25 / 7) - 1 = +159 %
    assert m.annualized_measurable_from == (datetime.now() + timedelta(days=366 - 7)).date().isoformat()


@pytest.mark.parametrize("days, measured", [(364, False), (365, False), (366, True), (400, True)])
def test_the_boundary_is_a_year_of_whole_days(tmp_path, days, measured):
    m = _metrics(tmp_path, days)
    assert (m.annualized_return_pct is not None) is measured
    assert (m.annualized_measurable_from is None) is measured


def test_an_old_enough_book_gets_the_textbook_figure(tmp_path):
    days = 400
    expected = (1.10 ** (365.25 / days) - 1) * 100            # de la definición, no del tracker
    m = _metrics(tmp_path, days)
    assert m.annualized_return_pct == pytest.approx(expected, rel=1e-9)
    assert m.annualized_measurable_from is None


def test_the_age_is_the_oldest_purchase_so_one_new_lot_does_not_hide_an_old_book(tmp_path):
    p = Portfolio(file_path=tmp_path / "p.json")
    p.add_position("KO", 10.0, 100.0, purchase_date=_days_ago(800))
    p.add_position("PEP", 10.0, 100.0, purchase_date=_days_ago(3))
    assert p.compute_metrics().annualized_return_pct is not None


def test_a_book_with_no_readable_date_has_neither_a_figure_nor_a_date(tmp_path):
    p = Portfolio(file_path=tmp_path / "p.json")
    p.add_position("KO", 10.0, 100.0, purchase_date="")
    m = p.compute_metrics()
    assert m.annualized_return_pct is None
    assert m.annualized_measurable_from is None


# --- las superficies -----------------------------------------------------------------------------

def test_the_page_caption_names_the_day_and_points_to_the_period_return(tmp_path):
    from data.product_ux import annualized_unmeasured_caption

    m = _metrics(tmp_path, 7)
    caption = annualized_unmeasured_caption(m)
    assert m.annualized_measurable_from in caption
    assert "P&L total" in caption


@pytest.mark.parametrize("days", [400, 7])
def test_no_caption_when_the_figure_exists_or_there_is_nothing_to_say(tmp_path, days):
    from data.product_ux import annualized_unmeasured_caption

    if days == 400:
        assert annualized_unmeasured_caption(_metrics(tmp_path, days)) == ""
    else:
        assert annualized_unmeasured_caption(SimpleNamespace()) == ""
        assert annualized_unmeasured_caption(SimpleNamespace(annualized_return_pct=None)) == ""


def _prompt_for(metrics) -> str:
    from analysis.committee import build_holdings_committee_context
    from analysis.committee_prompts import portfolio_committee_context_block

    ctx = build_holdings_committee_context(
        metrics=metrics,
        sector_weights={"Consumer Defensive": 100.0},
        position_weights={"KO": 100.0},
        total_value=1100.0,
    )
    return portfolio_committee_context_block(ctx)


def test_the_committee_is_told_why_the_annualized_return_is_missing_and_gets_no_figure(tmp_path):
    text = _prompt_for(_metrics(tmp_path, 7))
    assert "Retorno anualizado: n/d" in text
    assert "Retorno anualizado en n/d" in text and "menos de un año" in text
    assert "159" not in text


def test_the_committee_gets_the_figure_and_no_warning_when_the_book_is_old_enough(tmp_path):
    text = _prompt_for(_metrics(tmp_path, 400))
    assert "Retorno anualizado en n/d" not in text
    assert "Retorno anualizado: n/d" not in text


def test_the_committee_prompt_version_moved_with_the_prompt():
    from config import COMMITTEE

    assert COMMITTEE.prompt_version >= "2026-10-30a"
