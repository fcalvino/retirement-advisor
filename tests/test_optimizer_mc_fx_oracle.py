"""Oracle tests for the Optimizer and the Monte Carlo over tickers in another currency
(#154, PR C).

Both read raw closes. The Optimizer built its covariance from them and the Monte Carlo
— the retirement projection — bootstrapped their weekly returns, so a Tokyo listing
entered both as a **yen** return. The Optimizer only warned about it; the Monte Carlo
said nothing, and it receives whatever the Optimizer produced. With the primitive of
PR A (``data/fx.py``) every series is taken to ``PORTFOLIO.base_currency`` first.

The Monte Carlo is built from six places (Simulaciones, the sensitivity lab, goals, the
savings solver, the chat tool, the cache wrapper) and none of them knows a currency, so
the simulator resolves it itself with ``data.fx.quote_currency``: a symbol without an
exchange suffix is a US listing, quoted in dollars by Yahoo's convention; a suffixed one
is read from ``get_info``. A suffixed symbol whose currency cannot be confirmed, or
whose rate cannot be fetched, is left out and named — never projected as dollars.

References from the definition: a stock flat in yen while the yen appreciates at a
constant weekly rate g returned exactly g every week to a dollar investor.

No network: ``get_history`` / ``get_info`` are stubbed where the modules call them.
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

import data.fx as fx_mod
import portfolio.monte_carlo as mc_mod
import portfolio.optimizer as opt_mod
from config import PORTFOLIO
from portfolio.monte_carlo import MonteCarloSimulator
from portfolio.optimizer import PortfolioOptimizer

N = 600  # > 10y of weekly bars: covers the MC and Optimizer windows


def _frame(start: float, annual_rate: float) -> pd.DataFrame:
    idx = pd.date_range(end=pd.Timestamp.now().normalize(), periods=N, freq="W-MON")
    weekly = (1.0 + annual_rate) ** (1.0 / 52.0)
    return pd.DataFrame({"close": start * weekly ** np.arange(N)}, index=idx)


def _g(annual_rate: float) -> float:
    return (1.0 + annual_rate) ** (1.0 / 52.0) - 1.0


PRICES = {
    "AAA": _frame(100.0, 0.12),
    "BBB": _frame(50.0, 0.06),
    "JPX.T": _frame(3000.0, 0.0),
    "LDN.L": _frame(3580.0, 0.0),
    "NOFX.SW": _frame(90.0, 0.0),
    "UNK.XX": _frame(10.0, 0.0),
}
FX = {"JPYUSD=X": _frame(0.0064, 0.10), "GBPUSD=X": _frame(1.30, -0.05)}
INFO = {"JPX.T": {"currency": "JPY"}, "LDN.L": {"currency": "GBp"},
        "NOFX.SW": {"currency": "CHF"}, "UNK.XX": {}}


@pytest.fixture
def stub(monkeypatch):
    info_calls: list[str] = []

    def _prices(symbol, period="10y", interval="1wk"):
        return PRICES.get(symbol, pd.DataFrame()).copy()

    def _fx(symbol, period="10y", interval="1wk"):
        return FX.get(symbol, pd.DataFrame()).copy()

    def _info(symbol):
        info_calls.append(symbol)
        return dict(INFO.get(symbol, {}))

    monkeypatch.setattr(mc_mod, "get_history", _prices)
    monkeypatch.setattr(opt_mod, "get_history", _prices)
    monkeypatch.setattr(fx_mod, "get_history", _fx)
    monkeypatch.setattr(fx_mod, "get_info", _info)
    return info_calls


# --------------------------------------------------------------------------- #
#  Resolving the quote currency                                                #
# --------------------------------------------------------------------------- #


class TestQuoteCurrency:
    @pytest.mark.parametrize("sym", ["AAPL", "BRK-B", "BTC-USD", "YPF"])
    def test_a_symbol_without_exchange_suffix_is_a_us_listing_in_the_base_currency(
        self, stub, sym
    ):
        assert fx_mod.quote_currency(sym) == PORTFOLIO.base_currency
        assert stub == []  # no lookup, no network

    def test_a_suffixed_symbol_is_read_from_the_feed(self, stub):
        assert fx_mod.quote_currency("JPX.T") == "JPY"
        assert fx_mod.quote_currency("LDN.L") == "GBp"

    def test_a_suffixed_symbol_the_feed_does_not_describe_is_unknown(self, stub):
        assert fx_mod.quote_currency("UNK.XX") is None

    def test_a_failing_lookup_is_unknown_not_dollars(self, monkeypatch):
        def _boom(symbol):
            raise RuntimeError("feed down")
        monkeypatch.setattr(fx_mod, "get_info", _boom)
        assert fx_mod.quote_currency("JPX.T") is None


# --------------------------------------------------------------------------- #
#  Monte Carlo                                                                 #
# --------------------------------------------------------------------------- #


def _returns(symbols, weights=None, currencies=None):
    sim = MonteCarloSimulator(symbols, weights=weights, seed=1, currencies=currencies)
    rets, n, used, warnings = sim._load_returns()
    return rets, used, warnings


class TestMonteCarloReturnsAreInDollars:
    def test_flat_in_yen_with_the_yen_up_is_the_yen_rate_every_week(self, stub):
        rets, used, _ = _returns(["JPX.T"])
        assert used == ["JPX.T"]
        assert rets == pytest.approx(np.full(len(rets), _g(0.10)), abs=1e-12)

    def test_pence_with_a_falling_pound(self, stub):
        rets, _, _ = _returns(["LDN.L"])
        assert rets == pytest.approx(np.full(len(rets), _g(-0.05)), abs=1e-12)

    def test_a_mixed_portfolio_is_the_weighted_dollar_return(self, stub):
        rets, used, _ = _returns(["AAA", "JPX.T"], weights=np.array([0.25, 0.75]))
        assert used == ["AAA", "JPX.T"]
        expected = 0.25 * _g(0.12) + 0.75 * _g(0.10)
        assert rets == pytest.approx(np.full(len(rets), expected), abs=1e-12)

    def test_dollar_tickers_are_untouched_and_look_nothing_up(self, stub):
        rets, _, _ = _returns(["AAA", "BBB"], weights=np.array([0.5, 0.5]))
        assert stub == []
        assert rets == pytest.approx(np.full(len(rets), 0.5 * _g(0.12) + 0.5 * _g(0.06)),
                                     abs=1e-12)

    def test_an_explicit_currency_map_skips_the_lookup(self, stub):
        rets, _, _ = _returns(["JPX.T"], currencies={"JPX.T": "JPY"})
        assert stub == []
        assert rets == pytest.approx(np.full(len(rets), _g(0.10)), abs=1e-12)


class TestMonteCarloNeverProjectsAnUnconvertedSeries:
    def test_a_ticker_without_a_rate_is_left_out_and_named(self, stub):
        rets, used, warnings = _returns(["AAA", "NOFX.SW"], weights=np.array([0.5, 0.5]))
        assert used == ["AAA"]
        assert rets == pytest.approx(np.full(len(rets), _g(0.12)), abs=1e-12)
        assert any("NOFX.SW" in w and "CHF" in w for w in warnings)

    def test_a_suffixed_ticker_with_unknown_currency_is_left_out_and_named(self, stub):
        _, used, warnings = _returns(["AAA", "UNK.XX"], weights=np.array([0.5, 0.5]))
        assert used == ["AAA"]
        assert any("UNK.XX" in w for w in warnings)

    def test_the_run_reports_the_warning(self, stub):
        sim = MonteCarloSimulator(["AAA", "NOFX.SW"], weights=np.array([0.5, 0.5]), seed=1)
        res = sim.run(horizon_years=5, n_sims=200, initial_value=100_000)
        assert any("NOFX.SW" in w for w in res.warnings)


# --------------------------------------------------------------------------- #
#  Optimizer                                                                   #
# --------------------------------------------------------------------------- #


def _t(symbol, score, currency=None, sector="Technology"):
    d = {"symbol": symbol, "adjusted_score": score, "total_score": score,
         "dividend_yield": 1.0, "moat_score": 6.0, "moat_classification": "Narrow",
         "sector": sector, "country": "", "company_name": symbol,
         "data_quality_level": "good"}
    if currency is not None:
        d["currency"] = currency
    return d


class TestOptimizerPricesAreInDollars:
    def test_the_price_matrix_column_is_price_times_rate(self, stub):
        opt = PortfolioOptimizer("aggressive")
        m = opt._build_price_matrix(["JPX.T", "AAA"], {"JPX.T": "JPY", "AAA": "USD"})
        fx = FX["JPYUSD=X"]["close"].reindex(m.index)
        assert m["JPX.T"].to_numpy() == pytest.approx((3000.0 * fx).to_numpy(), rel=1e-12)
        aaa = PRICES["AAA"]["close"].reindex(m.index)
        assert m["AAA"].to_numpy() == pytest.approx(aaa.to_numpy(), rel=1e-12)

    def test_without_the_currency_key_it_is_resolved_like_the_monte_carlo(self, stub):
        opt = PortfolioOptimizer("aggressive")
        m = opt._build_price_matrix(["JPX.T"], None)
        fx = FX["JPYUSD=X"]["close"].reindex(m.index)
        assert m["JPX.T"].to_numpy() == pytest.approx((3000.0 * fx).to_numpy(), rel=1e-12)

    def test_optimize_leaves_out_a_ticker_without_a_rate_and_says_so(self, stub):
        tickers = [_t("AAA", 85, "USD"), _t("BBB", 80, "USD", "Healthcare"),
                   _t("JPX.T", 82, "JPY", "Industrials"),
                   _t("NOFX.SW", 90, "CHF", "Consumer Defensive")]
        res = PortfolioOptimizer("aggressive").optimize(tickers)
        held = {a.symbol for a in res.tickers}
        assert "NOFX.SW" not in held
        assert any("NOFX.SW" in w and "CHF" in w for w in res.warnings)
        assert res.converted_currencies == {"JPX.T": "JPY"}

    def test_a_dollar_universe_converts_nothing(self, stub):
        tickers = [_t("AAA", 85, "USD"), _t("BBB", 80, "USD", "Healthcare")]
        res = PortfolioOptimizer("aggressive").optimize(tickers)
        assert res.converted_currencies == {}
        assert stub == []


def test_the_scored_dict_of_the_optimizer_page_carries_the_currency():
    """The page builds the dicts; without the key the Optimizer would have to look it up."""
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "dashboard" / "views" / "5_Optimizer.py").read_text(
        encoding="utf-8"
    )
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_to_scored_dict")
    keys = {k.value for n in ast.walk(fn) if isinstance(n, ast.Dict)
            for k in n.keys if isinstance(k, ast.Constant)}
    assert "currency" in keys


def test_the_rate_is_fetched_with_the_prices_period(stub):
    with patch.object(fx_mod, "get_history", wraps=fx_mod.get_history) as spy:
        MonteCarloSimulator(["JPX.T"], seed=1)._load_returns()
    assert spy.call_args.args[0] == "JPYUSD=X"
    assert spy.call_args.kwargs == {"period": MonteCarloSimulator.HISTORY_PERIOD,
                                    "interval": "1wk"}
