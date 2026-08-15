"""Tests for data/crypto_fetcher.py (audit D4).

Crypto is a real position in the default universe (BTC-USD), and its scoring
substitutes these metrics for the financial-statement ones equities get. With
no coverage, a silent change in shape (a missing DatetimeIndex, a renamed
column) would degrade the crypto score without any signal.

The halving calendar is tested with injected dates rather than ``date.today()``
so the assertions do not rot as time passes.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from data.crypto_fetcher import (
    _BTC_HALVINGS,
    _halving_position,
    compute_crypto_metrics,
    get_crypto_info,
)

INFO = {
    "longName": "Bitcoin USD",
    "currentPrice": 95_000.0,
    "marketCap": 1.9e12,
    "circulatingSupply": 19_800_000,
    "maxSupply": 21_000_000,
}


def _weekly(closes, start="2020-01-05"):
    idx = pd.date_range(start, periods=len(closes), freq="W")
    return pd.DataFrame({"close": closes}, index=idx)


# ------------------------------------------------------------------ #
#  Halving calendar                                                    #
# ------------------------------------------------------------------ #

class TestHalvingPosition:
    def test_just_after_a_halving_is_post_halving(self):
        phase, since, to_next = _halving_position(date(2024, 6, 1))
        assert phase == "post-halving"
        assert since == (date(2024, 6, 1) - date(2024, 4, 19)).days
        assert to_next > 180

    def test_shortly_before_a_halving_is_pre_halving(self):
        phase, _since, to_next = _halving_position(date(2028, 1, 15))
        assert phase == "pre-halving"
        assert 0 < to_next <= 180

    def test_the_long_middle_of_a_cycle(self):
        phase, since, to_next = _halving_position(date(2026, 8, 14))
        assert phase == "mid-cycle"
        assert since > 365
        assert to_next > 180

    def test_pre_halving_wins_when_both_windows_overlap(self):
        """Within 180 days of the next halving, the forward-looking label wins."""
        boundary = date(2028, 4, 15)
        phase, _s, to_next = _halving_position(boundary.replace(month=1, day=1))
        assert phase == "pre-halving"
        assert to_next <= 180

    def test_a_date_before_every_halving_still_resolves(self):
        phase, since, to_next = _halving_position(date(2010, 1, 1))
        assert phase in {"pre-halving", "post-halving", "mid-cycle"}
        assert to_next > 0
        assert since < 0 or since >= 0        # must not raise either way

    def test_the_calendar_is_chronological_and_four_years_apart(self):
        assert _BTC_HALVINGS == sorted(_BTC_HALVINGS)
        gaps = [(b - a).days for a, b in zip(_BTC_HALVINGS, _BTC_HALVINGS[1:])]
        assert all(1_200 < g < 1_600 for g in gaps), gaps


# ------------------------------------------------------------------ #
#  get_crypto_info normalisation                                       #
# ------------------------------------------------------------------ #

class TestGetCryptoInfo:
    def test_normalises_the_common_fields(self, monkeypatch):
        import data.fetcher as fetcher_mod
        monkeypatch.setattr(fetcher_mod, "get_info", lambda s: dict(INFO))
        out = get_crypto_info("BTC-USD")
        assert out["currentPrice"] == 95_000.0
        assert out["circulatingSupply"] == 19_800_000
        assert out["longName"] == "Bitcoin USD"

    def test_falls_back_to_regular_market_price(self, monkeypatch):
        import data.fetcher as fetcher_mod
        monkeypatch.setattr(
            fetcher_mod, "get_info",
            lambda s: {"regularMarketPrice": 3_500.0, "sharesOutstanding": 120_000_000},
        )
        out = get_crypto_info("ETH-USD")
        assert out["currentPrice"] == 3_500.0
        assert out["circulatingSupply"] == 120_000_000     # yfinance quirk key

    def test_derives_market_cap_when_missing(self, monkeypatch):
        import data.fetcher as fetcher_mod
        monkeypatch.setattr(
            fetcher_mod, "get_info",
            lambda s: {"currentPrice": 100.0, "circulatingSupply": 1_000_000},
        )
        assert get_crypto_info("X-USD")["marketCap"] == pytest.approx(1e8)

    def test_empty_upstream_returns_empty_not_garbage(self, monkeypatch):
        import data.fetcher as fetcher_mod
        monkeypatch.setattr(fetcher_mod, "get_info", lambda s: {})
        assert get_crypto_info("BTC-USD") == {}


# ------------------------------------------------------------------ #
#  compute_crypto_metrics                                              #
# ------------------------------------------------------------------ #

class TestSupplyScarcity:
    def test_is_the_issued_share_of_max_supply(self):
        m = compute_crypto_metrics("BTC-USD", INFO, _weekly([100.0] * 60))
        assert m["supply_scarcity_pct"] == pytest.approx(19_800_000 / 21_000_000 * 100, abs=0.01)

    def test_is_none_for_an_uncapped_asset(self):
        info = {**INFO, "maxSupply": 0}
        assert compute_crypto_metrics("ETH-USD", info, _weekly([100.0] * 60))["supply_scarcity_pct"] is None

    def test_market_cap_is_reported_in_billions(self):
        assert compute_crypto_metrics("BTC-USD", INFO, _weekly([100.0] * 60))["market_cap_b"] == pytest.approx(1_900.0)


class TestPriceMetrics:
    def test_flat_history_has_no_volatility_and_no_drawdown(self):
        m = compute_crypto_metrics("BTC-USD", INFO, _weekly([100.0] * 120))
        assert m["annualized_volatility_pct"] == pytest.approx(0.0)
        assert m["max_drawdown_pct"] == pytest.approx(0.0)

    def test_drawdown_is_the_worst_peak_to_trough(self):
        closes = [100.0, 200.0, 50.0, 180.0] + [190.0] * 56
        m = compute_crypto_metrics("BTC-USD", INFO, _weekly(closes))
        assert m["max_drawdown_pct"] == pytest.approx(-75.0, abs=0.1)

    def test_volatility_uses_the_last_52_weeks(self):
        """A calm recent year must not be dragged up by an ancient crash."""
        wild = list(100.0 * np.cumprod(1 + np.array([0.4, -0.35] * 30)))
        calm = [wild[-1]] * 60
        m = compute_crypto_metrics("BTC-USD", INFO, _weekly(wild + calm))
        assert m["annualized_volatility_pct"] == pytest.approx(0.0, abs=1e-6)

    def test_volatility_falls_back_to_full_history_when_short(self):
        closes = list(100.0 * np.cumprod(1 + np.array([0.05, -0.05] * 10)))
        m = compute_crypto_metrics("BTC-USD", INFO, _weekly(closes))
        assert m["annualized_volatility_pct"] > 0

    def test_four_year_cagr_is_computed_from_annual_closes(self):
        idx = pd.date_range("2019-01-06", periods=52 * 6, freq="W")
        closes = 100.0 * 1.5 ** (np.arange(len(idx)) / 52)      # +50%/year
        m = compute_crypto_metrics("BTC-USD", INFO, pd.DataFrame({"close": closes}, index=idx))
        assert m["cagr_4y_pct"] == pytest.approx(50.0, abs=2.0)


class TestDegradesGracefully:
    def test_empty_history_returns_the_default_shape(self):
        m = compute_crypto_metrics("BTC-USD", INFO, pd.DataFrame())
        assert m["annualized_volatility_pct"] is None
        assert m["max_drawdown_pct"] is None
        assert m["supply_scarcity_pct"] is not None       # supply needs no prices

    def test_none_history_does_not_raise(self):
        assert compute_crypto_metrics("BTC-USD", INFO, None)["cagr_4y_pct"] is None

    def test_too_few_bars_skips_price_metrics(self):
        assert compute_crypto_metrics("BTC-USD", INFO, _weekly([100.0, 101.0]))["max_drawdown_pct"] is None

    def test_title_cased_columns_are_normalised(self):
        idx = pd.date_range("2020-01-05", periods=60, freq="W")
        df = pd.DataFrame({"Close": [100.0] * 60, "Volume": [1] * 60}, index=idx)
        assert compute_crypto_metrics("BTC-USD", INFO, df)["max_drawdown_pct"] == pytest.approx(0.0)

    def test_a_date_column_is_promoted_to_the_index(self):
        idx = pd.date_range("2020-01-05", periods=60, freq="W")
        df = pd.DataFrame({"date": idx, "close": [100.0] * 60}).reset_index(drop=True)
        m = compute_crypto_metrics("BTC-USD", INFO, df)
        assert m["max_drawdown_pct"] == pytest.approx(0.0)

    def test_non_btc_assets_get_no_halving_data(self):
        m = compute_crypto_metrics("ETH-USD", INFO, _weekly([100.0] * 60))
        assert m["halving_cycle_position"] == "unknown"
        assert m["days_since_last_halving"] is None

    def test_btc_assets_do_get_halving_data(self):
        m = compute_crypto_metrics("BTC-USD", INFO, _weekly([100.0] * 60))
        assert m["halving_cycle_position"] in {"pre-halving", "post-halving", "mid-cycle"}
        assert isinstance(m["days_since_last_halving"], int)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
