"""Oráculo PORTFOLIO-RISK-CERO: una métrica de riesgo que no se midió no es 0 ni beta 1.

U5-12 hizo honesta la curva de la cartera: empieza donde todas las posiciones ya
estaban compradas. Con una compra reciente esa curva es corta y ``compute_metrics``
no calcula nada, pero deja los defaults del dataclass —Sharpe 0, ratio bajista 0,
max drawdown 0 % y **beta 1.0**—, y la página y el comité de cartera los leen como
medidos. En la cartera real (ADBE comprada el 2026-08-19) la página mostraba
«Sharpe 0.00 · Max Drawdown 0.0 % · Beta 1.00» con +26,6 % de P&L, y el comité
escribió «beta 1.0 frente a SPY, lo que aumenta la vulnerabilidad…».

Independiente del código bajo prueba: los precios se inyectan (sin red) y lo que
se afirma es la ausencia de un número, no el valor de una fórmula.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from config import PORTFOLIO
from portfolio.tracker import Portfolio

RISK_FIELDS = ("sharpe_ratio", "downside_vol_ratio", "max_drawdown_pct", "beta")


def _weekly(n: int, start_price: float, weekly_drift: float, *, flat: bool = False) -> pd.DataFrame:
    """``n`` weekly bars ending a week from now, so any purchase up to today is inside."""
    last = (datetime.now() + timedelta(weeks=1)).date()
    idx = pd.date_range(end=last, periods=n, freq="W")
    prices = [start_price if flat else start_price * (1 + weekly_drift) ** i for i in range(n)]
    # A little noise so the returns have a spread (flat=False) — deterministic.
    if not flat:
        prices = [p * (1 + (0.01 if i % 3 == 0 else -0.004)) for i, p in enumerate(prices)]
    return pd.DataFrame({"close": prices}, index=idx)


@pytest.fixture(autouse=True)
def _no_feed(monkeypatch):
    monkeypatch.setattr("portfolio.tracker.get_info", lambda sym: {})


def _book(tmp_path, monkeypatch, positions, histories) -> Portfolio:
    monkeypatch.setattr(
        "portfolio.tracker.get_history",
        lambda sym, period="5y", interval="1wk": histories[sym],
    )
    p = Portfolio(file_path=tmp_path / "portfolio.json")
    for sym, (shares, cost, when) in positions.items():
        p.add_position(sym, shares, cost, purchase_date=when)
    return p


def _ago(**kw) -> str:
    return (datetime.now() - timedelta(**kw)).date().isoformat()


@pytest.fixture
def recent_buy(tmp_path, monkeypatch):
    """The real book's shape: an old holding and a buy from three weeks ago."""
    hist = {
        "GOOGL": _weekly(130, 170.0, 0.006),
        "ADBE": _weekly(130, 270.0, -0.002),
        "SPY": _weekly(130, 500.0, 0.003),
    }
    return _book(tmp_path, monkeypatch,
                 {"GOOGL": (23.0, 177.0, _ago(weeks=60)), "ADBE": (12.0, 274.0, _ago(weeks=3))},
                 hist)


# --------------------------------------------------------------------------- #
#  El tracker                                                                  #
# --------------------------------------------------------------------------- #

def test_a_short_shared_window_measures_nothing(recent_buy):
    m = recent_buy.compute_metrics()
    assert {f: getattr(m, f) for f in RISK_FIELDS} == {f: None for f in RISK_FIELDS}


def test_it_says_when_the_window_will_be_long_enough(recent_buy):
    m = recent_buy.compute_metrics()
    assert 0 < m.risk_curve_points < PORTFOLIO.min_risk_curve_points
    last_buy = datetime.fromisoformat(_ago(weeks=3))
    expected = (last_buy + timedelta(weeks=PORTFOLIO.min_risk_curve_points - 1)).date()
    assert m.risk_measurable_from == expected.isoformat()


def test_flat_prices_have_no_sharpe(tmp_path, monkeypatch):
    """Zero volatility makes the ratio undefined, not zero."""
    hist = {"KO": _weekly(80, 60.0, 0.0, flat=True), "SPY": _weekly(80, 500.0, 0.003)}
    p = _book(tmp_path, monkeypatch, {"KO": (10.0, 60.0, _ago(weeks=60))}, hist)
    m = p.compute_metrics()
    assert m.sharpe_ratio is None
    assert m.max_drawdown_pct == 0  # a flat curve did measure a 0 % drawdown


def test_control_a_long_window_still_measures(tmp_path, monkeypatch):
    hist = {"KO": _weekly(130, 60.0, 0.002), "SPY": _weekly(130, 500.0, 0.003)}
    p = _book(tmp_path, monkeypatch, {"KO": (100.0, 55.0, _ago(weeks=100))}, hist)
    m = p.compute_metrics()
    assert all(getattr(m, f) is not None for f in RISK_FIELDS)
    assert m.risk_curve_points >= PORTFOLIO.min_risk_curve_points
    assert m.risk_measurable_from is None


# --------------------------------------------------------------------------- #
#  Lo que ve el comité de cartera                                              #
# --------------------------------------------------------------------------- #

def test_the_portfolio_committee_is_not_told_a_default(recent_buy):
    from analysis.committee import build_holdings_committee_context
    from analysis.committee_prompts import portfolio_committee_context_block

    m = recent_buy.compute_metrics()
    ctx = build_holdings_committee_context(
        metrics=m, sector_weights={"Technology": 100.0},
        position_weights={"GOOGL": 55.0, "ADBE": 45.0}, total_value=m.total_value,
    )
    block = portfolio_committee_context_block(ctx)
    assert "Beta vs SPY: 1.0" not in block
    assert "Sharpe: 0.0" not in block
    assert "Max drawdown: 0.0%" not in block
    assert "no medible" in block.lower()


# --------------------------------------------------------------------------- #
#  Lo que ve el usuario                                                        #
# --------------------------------------------------------------------------- #

def test_an_unmeasured_metric_is_a_dash():
    from data.product_ux import risk_metric_text

    assert risk_metric_text(None, "{:.2f}") == "—"
    assert risk_metric_text(0.0, "{:.2f}") == "0.00"
    assert risk_metric_text(-12.34, "{:.1f}%") == "-12.3%"


def test_the_caption_names_the_window_and_the_date(recent_buy):
    from data.product_ux import risk_unmeasured_caption

    m = recent_buy.compute_metrics()
    cap = risk_unmeasured_caption(m)
    assert m.risk_measurable_from in cap
    assert f"{m.risk_curve_points} de {PORTFOLIO.min_risk_curve_points}" in cap


def test_no_caption_when_everything_was_measured(tmp_path, monkeypatch):
    from data.product_ux import risk_unmeasured_caption

    hist = {"KO": _weekly(130, 60.0, 0.002), "SPY": _weekly(130, 500.0, 0.003)}
    p = _book(tmp_path, monkeypatch, {"KO": (100.0, 55.0, _ago(weeks=100))}, hist)
    assert risk_unmeasured_caption(p.compute_metrics()) == ""
