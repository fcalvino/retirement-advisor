"""Tests for analysis/backtesting.py (audit D4).

The backtest is what tells the user "the scoring model would have beaten SPY".
It had no coverage at all, so nothing checked that the portfolio it builds is
the portfolio it claims to build, or that alpha is measured against the same
window as the return it is subtracted from.

Price history is stubbed; the maths is checked in
``tests/test_engine_oracles.py`` against independent references. This file
covers the orchestration: ranking, alignment, alpha, persistence and the
failure paths that must degrade rather than crash.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pytest

import analysis.backtesting as bt_mod
from analysis.backtesting import BacktestEngine, BacktestResult, TickerPerformance


@dataclass
class _Scored:
    """Duck-typed stand-in for a FundamentalResult."""
    symbol: str
    adjusted_score: float


def _price_frame(start: float, annual_rate: float, n_bars: int = 320) -> pd.DataFrame:
    """Weekly closes growing at a steady annual rate, ending today."""
    idx = pd.date_range(end=pd.Timestamp.now().normalize(), periods=n_bars, freq="W")
    weekly = (1.0 + annual_rate) ** (1.0 / 52.0)
    return pd.DataFrame({"close": start * weekly ** np.arange(n_bars)}, index=idx)


RATES = {"SPY": 0.08, "AAA": 0.15, "BBB": 0.10, "CCC": 0.02}


@pytest.fixture
def stub_history(monkeypatch):
    def _get_history(symbol, period="5y", interval="1wk"):
        if symbol not in RATES:
            return pd.DataFrame()
        return _price_frame(100.0, RATES[symbol])
    monkeypatch.setattr(bt_mod, "get_history", _get_history)
    return _get_history


# ------------------------------------------------------------------ #
#  Ranking & portfolio construction                                    #
# ------------------------------------------------------------------ #

class TestRanking:
    def test_top_n_is_selected_by_score(self, stub_history):
        scored = [_Scored("CCC", 40.0), _Scored("AAA", 90.0), _Scored("BBB", 70.0)]
        result = BacktestEngine().run(scored, period_years=5, top_n=2)
        picked = [n for n in result.notes if n.startswith("Portfolio:")][0]
        assert "AAA" in picked and "BBB" in picked
        assert "CCC" not in picked

    def test_unscored_tickers_are_excluded(self, stub_history):
        scored = [_Scored("AAA", 90.0), _Scored("BBB", 0.0)]
        result = BacktestEngine().run(scored, period_years=5, top_n=5)
        picked = [n for n in result.notes if n.startswith("Portfolio:")][0]
        assert "BBB" not in picked

    def test_universe_size_counts_everything_supplied(self, stub_history):
        scored = [_Scored("AAA", 90.0), _Scored("BBB", 70.0), _Scored("CCC", 40.0)]
        assert BacktestEngine().run(scored, top_n=1).universe_size == 3

    def test_tickers_without_price_history_are_noted_and_skipped(self, stub_history):
        scored = [_Scored("AAA", 90.0), _Scored("GHOST", 80.0)]
        result = BacktestEngine().run(scored, top_n=2)
        assert any("GHOST" in n for n in result.notes)
        assert result.portfolio_cagr_pct != 0.0     # still ran on AAA


# ------------------------------------------------------------------ #
#  Metrics reported to the user                                        #
# ------------------------------------------------------------------ #

class TestReportedMetrics:
    def test_single_holding_reproduces_its_own_growth_rate(self, stub_history):
        """A one-stock portfolio must report that stock's actual CAGR."""
        result = BacktestEngine().run([_Scored("AAA", 90.0)], period_years=5, top_n=1)
        assert result.portfolio_cagr_pct == pytest.approx(15.0, abs=0.3)

    def test_benchmark_cagr_matches_the_benchmark(self, stub_history):
        result = BacktestEngine().run([_Scored("AAA", 90.0)], period_years=5, top_n=1)
        assert result.benchmark_cagr_pct == pytest.approx(8.0, abs=0.3)

    def test_alpha_is_portfolio_minus_benchmark(self, stub_history):
        result = BacktestEngine().run([_Scored("AAA", 90.0)], period_years=5, top_n=1)
        assert result.alpha_pct == pytest.approx(
            round(result.portfolio_cagr_pct - result.benchmark_cagr_pct, 2)
        )

    def test_a_laggard_produces_negative_alpha(self, stub_history):
        result = BacktestEngine().run([_Scored("CCC", 90.0)], period_years=5, top_n=1)
        assert result.alpha_pct < 0

    def test_curves_are_normalised_to_100(self, stub_history):
        result = BacktestEngine().run([_Scored("AAA", 90.0)], top_n=1)
        assert next(iter(result.portfolio_curve.values())) == pytest.approx(100.0)
        assert next(iter(result.benchmark_curve.values())) == pytest.approx(100.0)

    def test_monotonic_series_never_draws_down(self, stub_history):
        result = BacktestEngine().run([_Scored("AAA", 90.0)], top_n=1)
        assert result.portfolio_max_drawdown_pct == pytest.approx(0.0, abs=1e-6)
        assert all(v <= 1e-6 for v in result.drawdown_curve.values())

    def test_per_ticker_breakdown_covers_the_whole_universe(self, stub_history):
        scored = [_Scored("AAA", 90.0), _Scored("BBB", 70.0), _Scored("CCC", 40.0)]
        result = BacktestEngine().run(scored, top_n=1)
        assert {t.symbol for t in result.ticker_results} == {"AAA", "BBB", "CCC"}
        assert len(result.score_vs_return) == 3

    def test_lookahead_bias_is_always_disclosed(self, stub_history):
        """The scores use current financials — the caveat must never be dropped."""
        result = BacktestEngine().run([_Scored("AAA", 90.0)], top_n=1)
        assert any("lookahead" in n.lower() for n in result.notes)


# ------------------------------------------------------------------ #
#  Rebalancing plumbing                                                #
# ------------------------------------------------------------------ #

class TestRebalanceDates:
    IDX = pd.date_range("2020-01-05", periods=52 * 5, freq="W")

    def test_buy_and_hold_has_no_rebalance_dates(self):
        assert BacktestEngine()._rebalance_dates(self.IDX, "buy_and_hold") == set()

    def test_unknown_frequency_is_treated_as_no_rebalancing(self):
        assert BacktestEngine()._rebalance_dates(self.IDX, "fortnightly") == set()

    @pytest.mark.parametrize("freq,expected", [("annual", 5), ("quarterly", 20), ("monthly", 60)])
    def test_cadence_produces_the_expected_number_of_dates(self, freq, expected):
        dates = BacktestEngine()._rebalance_dates(self.IDX, freq)
        assert abs(len(dates) - expected) <= 1        # calendar-edge tolerance

    def test_dates_land_on_real_bars(self):
        dates = BacktestEngine()._rebalance_dates(self.IDX, "annual")
        assert all(d in self.IDX for d in dates)

    @pytest.mark.parametrize("freq", ["buy_and_hold", "annual", "quarterly", "monthly"])
    def test_every_frequency_produces_a_usable_curve(self, stub_history, freq):
        result = BacktestEngine().run(
            [_Scored("AAA", 90.0), _Scored("BBB", 70.0)], top_n=2, rebalance_freq=freq
        )
        assert result.rebalance_freq == freq
        assert len(result.portfolio_curve) > 10


# ------------------------------------------------------------------ #
#  Failure paths                                                       #
# ------------------------------------------------------------------ #

class TestDegradesGracefully:
    def test_missing_benchmark_reports_an_error_note(self, monkeypatch):
        monkeypatch.setattr(bt_mod, "get_history", lambda *a, **k: pd.DataFrame())
        result = BacktestEngine().run([_Scored("AAA", 90.0)], top_n=1)
        assert any("ERROR" in n for n in result.notes)
        assert result.portfolio_cagr_pct == 0.0

    def test_no_portfolio_price_data_reports_an_error_note(self, monkeypatch):
        def only_spy(symbol, **k):
            return _price_frame(100.0, 0.08) if symbol == "SPY" else pd.DataFrame()
        monkeypatch.setattr(bt_mod, "get_history", only_spy)
        result = BacktestEngine().run([_Scored("GHOST", 90.0)], top_n=1)
        assert any("ERROR" in n for n in result.notes)

    def test_empty_universe_does_not_raise(self, stub_history):
        result = BacktestEngine().run([], top_n=5)
        assert result.universe_size == 0


# ------------------------------------------------------------------ #
#  Persistence                                                        #
# ------------------------------------------------------------------ #

class TestPersistence:
    def test_save_then_load_roundtrips(self, tmp_path, monkeypatch):
        monkeypatch.setattr(bt_mod, "RESULTS_DIR", tmp_path)
        result = BacktestResult(
            run_date="2026-08-14T10:00:00", period_years=5,
            start_date="2021-08-14", end_date="2026-08-14",
            benchmark="SPY", top_n=2, universe_size=10,
            portfolio_cagr_pct=12.5, alpha_pct=4.5,
        )
        result.ticker_results = [
            TickerPerformance("AAA", 90.0, 15.0, 1.1, 1.4, -12.0, 18.0, 55.0, 110.0, 7.0)
        ]
        path = BacktestEngine().save(result, filename="rt.json")
        loaded = BacktestEngine.load(path)

        assert loaded.portfolio_cagr_pct == 12.5
        assert loaded.alpha_pct == 4.5
        assert loaded.ticker_results[0].symbol == "AAA"
        assert loaded.ticker_results[0].cagr_pct == 15.0

    def test_list_saved_returns_newest_first(self, tmp_path, monkeypatch):
        monkeypatch.setattr(bt_mod, "RESULTS_DIR", tmp_path)
        for name in ("backtest_a.json", "backtest_b.json", "ignore_me.json"):
            (tmp_path / name).write_text("{}")
        found = [p.name for p in BacktestEngine.list_saved()]
        assert found == ["backtest_b.json", "backtest_a.json"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
