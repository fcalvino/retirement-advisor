"""Tests for portfolio/tracker.py — the user's REAL positions (audit D4).

This module had zero coverage, which is the worst place to have none: every
other engine works on hypothetical portfolios, but ``Portfolio`` is the ledger
of what the user actually owns. A wrong cost basis here misstates their P&L and
feeds a wrong sector concentration into the committee and the drift alerts.

All network access (``get_info`` / ``get_history``) is stubbed — the tests are
about the accounting, and the accounting is checked against explicit arithmetic
rather than against the implementation.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

import portfolio.tracker as tracker_mod
from portfolio.tracker import Portfolio, Position

# ------------------------------------------------------------------ #
#  Fixtures                                                            #
# ------------------------------------------------------------------ #

PRICES = {"AAPL": 200.0, "MSFT": 400.0, "KO": 60.0}
SECTORS = {"AAPL": "Technology", "MSFT": "Technology", "KO": "Consumer Staples"}


@pytest.fixture
def portfolio(tmp_path, monkeypatch):
    """An empty Portfolio backed by a temp file, with prices/sectors stubbed."""
    monkeypatch.setattr(
        tracker_mod, "get_info",
        lambda sym: {"currentPrice": PRICES.get(sym, 0.0),
                     "sector": SECTORS.get(sym, "Unknown")},
    )
    monkeypatch.setattr(
        tracker_mod, "get_history", lambda *a, **k: pd.DataFrame()
    )
    return Portfolio(file_path=tmp_path / "portfolio.json")


# ------------------------------------------------------------------ #
#  Position                                                            #
# ------------------------------------------------------------------ #

class TestPosition:
    def test_cost_basis_is_shares_times_price(self):
        assert Position("AAPL", 10, 150.0, "2024-01-15").cost_basis == 1_500.0

    def test_fractional_shares(self):
        assert Position("BTC-USD", 0.25, 40_000.0, "2024-01-15").cost_basis == 10_000.0


# ------------------------------------------------------------------ #
#  CRUD                                                                #
# ------------------------------------------------------------------ #

class TestAddPosition:
    def test_adds_with_sector_from_info(self, portfolio):
        portfolio.add_position("AAPL", 10, 150.0, "2024-01-15")
        assert portfolio.positions["AAPL"].sector == "Technology"
        assert portfolio.positions["AAPL"].cost_basis == 1_500.0

    def test_symbol_is_upper_cased(self, portfolio):
        portfolio.add_position("aapl", 5, 100.0, "2024-01-15")
        assert "AAPL" in portfolio.positions

    def test_second_buy_averages_the_cost(self, portfolio):
        """Averaging in must weight by shares, not take a plain mean."""
        portfolio.add_position("AAPL", 10, 100.0, "2024-01-15")
        portfolio.add_position("AAPL", 30, 200.0, "2024-06-15")
        pos = portfolio.positions["AAPL"]
        assert pos.shares == 40
        # (10×100 + 30×200) / 40 = 175 — NOT the unweighted mean of 150.
        assert pos.avg_cost == pytest.approx(175.0)
        assert pos.cost_basis == pytest.approx(7_000.0)

    def test_averaging_down_lowers_the_basis(self, portfolio):
        portfolio.add_position("AAPL", 10, 200.0, "2024-01-15")
        portfolio.add_position("AAPL", 10, 100.0, "2024-06-15")
        assert portfolio.positions["AAPL"].avg_cost == pytest.approx(150.0)


class TestUpdatePosition:
    def test_overwrites_rather_than_averaging(self, portfolio):
        """"Editar posición" must SET the values, not average them in."""
        portfolio.add_position("AAPL", 10, 100.0, "2024-01-15")
        assert portfolio.update_position("AAPL", shares=3, avg_cost=250.0) is True
        pos = portfolio.positions["AAPL"]
        assert (pos.shares, pos.avg_cost) == (3, 250.0)

    def test_unknown_symbol_returns_false(self, portfolio):
        assert portfolio.update_position("NFLX", 1, 1.0) is False

    def test_optional_fields_are_left_alone_when_omitted(self, portfolio):
        portfolio.add_position("AAPL", 10, 100.0, "2024-01-15", notes="core")
        portfolio.update_position("AAPL", shares=11, avg_cost=101.0)
        assert portfolio.positions["AAPL"].purchase_date == "2024-01-15"
        assert portfolio.positions["AAPL"].notes == "core"


class TestRemovePosition:
    def test_full_removal(self, portfolio):
        portfolio.add_position("AAPL", 10, 100.0, "2024-01-15")
        portfolio.remove_position("AAPL")
        assert "AAPL" not in portfolio.positions

    def test_partial_sale_keeps_the_rest(self, portfolio):
        portfolio.add_position("AAPL", 10, 100.0, "2024-01-15")
        portfolio.remove_position("AAPL", shares=4)
        assert portfolio.positions["AAPL"].shares == 6

    def test_selling_everything_closes_the_position(self, portfolio):
        portfolio.add_position("AAPL", 10, 100.0, "2024-01-15")
        portfolio.remove_position("AAPL", shares=10)
        assert "AAPL" not in portfolio.positions

    def test_overselling_closes_rather_than_going_negative(self, portfolio):
        portfolio.add_position("AAPL", 10, 100.0, "2024-01-15")
        portfolio.remove_position("AAPL", shares=999)
        assert "AAPL" not in portfolio.positions

    def test_removing_an_absent_symbol_is_a_no_op(self, portfolio):
        portfolio.remove_position("NFLX")          # must not raise
        assert portfolio.positions == {}


# ------------------------------------------------------------------ #
#  Persistence                                                         #
# ------------------------------------------------------------------ #

class TestPersistence:
    def test_survives_a_reload(self, portfolio, tmp_path, monkeypatch):
        portfolio.add_position("AAPL", 10, 150.0, "2024-01-15", notes="núcleo")
        monkeypatch.setattr(
            tracker_mod, "get_info",
            lambda sym: {"currentPrice": PRICES.get(sym, 0.0), "sector": "Technology"},
        )
        reloaded = Portfolio(file_path=tmp_path / "portfolio.json")
        assert reloaded.positions["AAPL"].shares == 10
        assert reloaded.positions["AAPL"].notes == "núcleo"

    def test_corrupt_file_does_not_crash_the_app(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tracker_mod, "get_info", lambda sym: {})
        bad = tmp_path / "portfolio.json"
        bad.write_text("{ this is not json")
        assert Portfolio(file_path=bad).positions == {}

    def test_written_file_is_valid_json(self, portfolio, tmp_path):
        portfolio.add_position("AAPL", 10, 150.0, "2024-01-15")
        data = json.loads((tmp_path / "portfolio.json").read_text())
        assert data["AAPL"]["shares"] == 10


# ------------------------------------------------------------------ #
#  Valuation                                                           #
# ------------------------------------------------------------------ #

class TestValuation:
    def test_market_value_and_pnl_against_explicit_arithmetic(self, portfolio):
        portfolio.add_position("AAPL", 10, 150.0, "2024-01-15")   # now $200
        v = portfolio.get_current_values()["AAPL"]
        assert v["market_value"] == pytest.approx(2_000.0)
        assert v["cost_basis"] == pytest.approx(1_500.0)
        assert v["pnl"] == pytest.approx(500.0)
        assert v["pnl_pct"] == pytest.approx(500.0 / 1_500.0 * 100)

    def test_falls_back_to_cost_when_no_price_is_available(self, portfolio, monkeypatch):
        """A missing quote must not show the position as a 100% loss."""
        monkeypatch.setattr(tracker_mod, "get_info", lambda sym: {"sector": "Unknown"})
        portfolio.positions["ZZZ"] = Position("ZZZ", 4, 25.0, "2024-01-15")
        v = portfolio.get_current_values()["ZZZ"]
        assert v["current_price"] == 25.0
        assert v["pnl"] == pytest.approx(0.0)

    def test_totals_across_positions(self, portfolio):
        portfolio.add_position("AAPL", 10, 150.0, "2024-01-15")   # 2000 / cost 1500
        portfolio.add_position("KO", 100, 50.0, "2024-01-15")     # 6000 / cost 5000
        m = portfolio.compute_metrics()
        assert m.num_positions == 2
        assert m.total_value == pytest.approx(8_000.0)
        assert m.total_cost == pytest.approx(6_500.0)
        assert m.total_pnl == pytest.approx(1_500.0)
        assert m.total_pnl_pct == pytest.approx(1_500.0 / 6_500.0 * 100)

    def test_empty_portfolio_reports_zeros_not_errors(self, portfolio):
        m = portfolio.compute_metrics()
        assert (m.num_positions, m.total_value, m.total_pnl_pct) == (0, 0.0, 0.0)


class TestWeights:
    def test_position_weights_sum_to_100(self, portfolio):
        portfolio.add_position("AAPL", 10, 150.0, "2024-01-15")   # 2000
        portfolio.add_position("KO", 100, 50.0, "2024-01-15")     # 6000
        w = portfolio.get_position_weights()
        assert w["AAPL"] == pytest.approx(25.0)
        assert w["KO"] == pytest.approx(75.0)
        assert sum(w.values()) == pytest.approx(100.0, abs=0.2)

    def test_sector_weights_aggregate_same_sector_positions(self, portfolio):
        portfolio.add_position("AAPL", 10, 150.0, "2024-01-15")   # Tech, 2000
        portfolio.add_position("MSFT", 5, 300.0, "2024-01-15")    # Tech, 2000
        portfolio.add_position("KO", 100, 50.0, "2024-01-15")     # Staples, 6000
        s = portfolio.get_sector_weights()
        assert s["Technology"] == pytest.approx(40.0)
        assert s["Consumer Staples"] == pytest.approx(60.0)

    def test_weights_are_empty_without_positions(self, portfolio):
        assert portfolio.get_position_weights() == {}
        assert portfolio.get_sector_weights() == {}


class TestEquityCurve:
    def test_missing_history_yields_no_curve_instead_of_raising(self, portfolio):
        portfolio.add_position("AAPL", 10, 150.0, "2024-01-15")
        assert portfolio._build_equity_curve() is None

    def test_curve_is_the_share_weighted_sum_of_prices(self, portfolio, monkeypatch):
        idx = pd.date_range("2024-01-07", periods=12, freq="W")
        monkeypatch.setattr(
            tracker_mod, "get_history",
            lambda sym, **k: pd.DataFrame({"close": [100.0] * 12}, index=idx),
        )
        portfolio.positions["AAPL"] = Position("AAPL", 3, 90.0, "2024-01-15")
        portfolio.positions["MSFT"] = Position("MSFT", 2, 90.0, "2024-01-15")
        curve = portfolio._build_equity_curve()
        assert curve is not None
        assert curve.iloc[0] == pytest.approx(500.0)      # (3 + 2) shares × $100

    def test_a_broken_history_source_degrades_quietly(self, portfolio, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("network down")
        monkeypatch.setattr(tracker_mod, "get_history", boom)
        portfolio.positions["AAPL"] = Position("AAPL", 3, 90.0, "2024-01-15")
        assert portfolio._build_equity_curve() is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
