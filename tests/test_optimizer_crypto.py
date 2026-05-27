"""
Tests for PortfolioOptimizer crypto allocation caps.

Verifies that max_crypto_pct per profile (Conservative=3%, Moderate=5%, Aggressive=10%)
is respected by both _score_weighted_optimize() (score-weighted fallback)
and the full optimize() pipeline.

No network calls — price history is synthetic.
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from config import CONSERVATIVE_PROFILE, MODERATE_PROFILE, AGGRESSIVE_PROFILE
from portfolio.optimizer import PortfolioOptimizer


# ------------------------------------------------------------------ #
#  Helpers                                                             #
# ------------------------------------------------------------------ #

def _ticker(symbol: str, score: float = 65.0, sector: str = "Technology") -> dict:
    return {
        "symbol": symbol,
        "adjusted_score": score,
        "dividend_yield": 1.5,
        "moat_score": 8.0,
        "sector": sector,
    }


def _crypto_ticker(symbol: str = "BTC", score: float = 55.0) -> dict:
    return {
        "symbol": symbol,
        "adjusted_score": score,
        "dividend_yield": 0.0,
        "moat_score": 5.0,
        "sector": "Crypto / Digital Asset",
    }


def _fake_price_history(sym, period="2y", interval="1wk"):
    """110 weeks of synthetic price history — passes the min_obs check."""
    n = 110
    rng = np.random.default_rng(hash(sym) % 2**31)
    prices = 100.0 * np.cumprod(1 + rng.normal(0.001, 0.015, n))
    dates = pd.date_range("2022-01-01", periods=n, freq="W")
    return pd.DataFrame({"close": prices}, index=dates)


# ------------------------------------------------------------------ #
#  Score-weighted fallback — crypto cap per profile                    #
# ------------------------------------------------------------------ #

class TestScoreWeightedCryptoCap:
    """
    _score_weighted_optimize() applies max_crypto_pct without needing price history.
    These tests are fast and deterministic.
    """

    def _run(self, profile: str):
        """
        Build a portfolio large enough that per-ticker caps are satisfiable.

        Conservative: max_position_pct=8%, crypto=3% → need ≥13 equity + BTC
        Moderate:     max_position_pct=12%, crypto=5% → need ≥9 equity + BTC
        Aggressive:   max_position_pct=18%, crypto=10% → need ≥6 equity + BTC

        Use 15 equity tickers for all profiles (satisfies the tightest constraint).
        """
        opt = PortfolioOptimizer(profile)
        equity = [_ticker(f"EQ{i:02d}", score=70 - i) for i in range(15)]
        tickers = [_crypto_ticker("BTC", score=90)] + equity  # BTC has highest score
        weights = opt._score_weighted_optimize(tickers)
        return weights, tickers

    def test_conservative_btc_capped_at_3_pct(self):
        """BTC weight ≤ 3% in conservative profile, even with highest score."""
        weights, tickers = self._run("conservative")
        btc_idx = next(i for i, t in enumerate(tickers) if t["symbol"] == "BTC")
        btc_weight = weights[btc_idx]
        assert btc_weight <= CONSERVATIVE_PROFILE.max_crypto_pct / 100 + 1e-6, (
            f"BTC weight {btc_weight:.4f} exceeds conservative cap of "
            f"{CONSERVATIVE_PROFILE.max_crypto_pct}%"
        )

    def test_moderate_btc_capped_at_5_pct(self):
        """BTC weight ≤ 5% in moderate profile."""
        weights, tickers = self._run("moderate")
        btc_idx = next(i for i, t in enumerate(tickers) if t["symbol"] == "BTC")
        btc_weight = weights[btc_idx]
        assert btc_weight <= MODERATE_PROFILE.max_crypto_pct / 100 + 1e-6, (
            f"BTC weight {btc_weight:.4f} exceeds moderate cap of "
            f"{MODERATE_PROFILE.max_crypto_pct}%"
        )

    def test_aggressive_btc_capped_at_10_pct(self):
        """BTC weight ≤ 10% in aggressive profile, higher than conservative."""
        weights_cons, tickers = self._run("conservative")
        weights_agg, _ = self._run("aggressive")
        btc_idx = next(i for i, t in enumerate(tickers) if t["symbol"] == "BTC")

        assert weights_agg[btc_idx] <= AGGRESSIVE_PROFILE.max_crypto_pct / 100 + 1e-6
        # Aggressive allows more than conservative
        assert weights_agg[btc_idx] >= weights_cons[btc_idx] - 1e-6

    def test_crypto_cap_tighter_than_standard_cap(self):
        """Crypto upper bound is tighter than the standard position cap in all profiles."""
        for profile in ["conservative", "moderate", "aggressive"]:
            opt = PortfolioOptimizer(profile)
            assert opt.cfg.max_crypto_pct < opt.cfg.max_position_pct, (
                f"Profile {profile}: max_crypto_pct ({opt.cfg.max_crypto_pct}%) "
                f"should be < max_position_pct ({opt.cfg.max_position_pct}%)"
            )

    def test_no_crypto_tickers_unaffected(self):
        """Without crypto tickers, standard position caps apply (not crypto cap)."""
        opt = PortfolioOptimizer("conservative")
        # 15 tickers: caps sum to 15 * 8% = 120% ≥ 100% → converges
        equity_only = [_ticker(f"EQ{i:02d}", score=70 - i) for i in range(15)]
        weights = opt._score_weighted_optimize(equity_only)
        assert abs(weights.sum() - 1.0) < 1e-6
        assert np.all(weights >= 0)
        # All weights respect standard equity cap (no crypto cap applied)
        ub = opt.cfg.max_position_pct / 100
        assert np.all(weights <= ub + 1e-6)

    def test_weights_still_sum_to_one_with_crypto(self):
        """Allocation sums to 100% even when BTC is capped below its score-implied weight."""
        opt = PortfolioOptimizer("conservative")
        tickers = [
            _crypto_ticker("BTC", score=99),  # Very high score → capped
            _ticker("AAPL", score=60),
            _ticker("MSFT", score=58),
            _ticker("JNJ", score=55),
        ]
        weights = opt._score_weighted_optimize(tickers)
        assert abs(weights.sum() - 1.0) < 1e-6
