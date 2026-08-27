"""Oracle tests for the drawdown / SORR metrics of the Monte Carlo engine.

Backlog row U2-2 (oleada 2 · P0 · fuente P2)
--------------------------------------------
  hallazgo : Drawdown/SORR sobre paths post-retiro.
  evidencia: mercado plano + 4% retiro -> DD alto -> badge 🔴 + mail SORR_HIGH.
  fix      : DD sobre el retorno de mercado (pre-retiro); badge/alerta usan esa
             serie.
  oraculo  : mercado plano + retiro 4% -> DD ~ 0.

Why this file exists
--------------------
``MonteCarloSimulator.run`` used to measure drawdown on ``paths_usd`` — the
*wealth* series, i.e. after economic drags and after every cash flow. Planned
spending therefore entered the metric as if it were a market crash: on a market
that never moves, a 4 % annual withdrawal over 30 years drags the pot to
``0.96**30 = 0.294`` and the engine reported a ~70 % "drawdown", which is enough
for ``sorr_risk_badge`` to paint 🔴 Alto and (at higher withdrawal rates) for
``AlertEngine.check_sorr`` to send a CRITICAL ``SORR_HIGH`` e-mail.

SORR means *sequence of returns* risk, so it must be measured on the market
series. Cash-flow depletion is already reported — correctly — by
``prob_ruin_pct``, ``p10_intra_min``, ``prob_sustain_real_pct`` and
``expected_depletion_year``.

The reference used here is an **independently written, deliberately slow,
sequential drawdown accumulator** derived from the definition of a peak-to-trough
decline — not the engine's own vectorised implementation (``docs/CONTEXT.md §5``:
tests of the engine are oracles, not self-consistency checks).

Pure NumPy + mocked fetcher — no network, no Streamlit.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from alerts.engine import AlertEngine
from alerts.store import AlertSeverity, AlertType
from config import ALERTS, GOAL_CARD
from portfolio.goals import sorr_risk_badge
from portfolio.monte_carlo import MonteCarloSimulator

INIT = 100_000.0
N_WEEKS_HIST = 260          # ~5 years of weekly bars


# ------------------------------------------------------------------ #
#  Deterministic price histories (patched into get_history)            #
# ------------------------------------------------------------------ #

def _history_from_prices(prices: np.ndarray) -> pd.DataFrame:
    dates = pd.date_range("2018-01-01", periods=len(prices), freq="W")
    return pd.DataFrame({"close": prices}, index=dates)


def _flat_history(symbol: str, period: str = "10y", interval: str = "1wk") -> pd.DataFrame:
    """A market that never moves: every weekly return is exactly 0.0.

    ``_conservative_adjustment`` leaves a zero-mean, zero-vol series untouched
    (``(r - 0) * vol_adj + 0 * haircut == 0``), so every simulated path is a
    flat line at 1.0 and the ONLY thing that can bend it is a cash flow.
    """
    return _history_from_prices(np.full(N_WEEKS_HIST, 100.0))


def _volatile_history(symbol: str, period: str = "10y", interval: str = "1wk") -> pd.DataFrame:
    """Real market noise with a mild upward drift — genuine drawdowns exist."""
    rng = np.random.default_rng(seed=7)
    prices = 100.0 * np.cumprod(1 + rng.normal(0.001, 0.02, N_WEEKS_HIST))
    return _history_from_prices(prices)


# ------------------------------------------------------------------ #
#  Independent reference implementation                                #
# ------------------------------------------------------------------ #

def oracle_max_drawdown(path) -> float:
    """Deepest peak-to-trough decline of one path, as a fraction of the peak.

    Deliberately a slow Python loop straight off the definition: walk forward,
    remember the highest value seen, and keep the worst relative fall from it.
    No cummax, no vectorisation — nothing shared with the engine.
    """
    peak = float(path[0])
    worst = 0.0
    for value in path:
        v = float(value)
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak
            if dd > worst:
                worst = dd
    return worst


def _market_paths_twin(symbols, n_sims: int, horizon_years: int, seed: int = 42) -> np.ndarray:
    """Rebuild the market series a ``run()`` of the same seed would have drawn.

    ``MonteCarloSimulator`` seeds a fresh generator in ``__init__`` and
    ``_simulate_paths`` is the first consumer of it inside ``run()``, so a twin
    simulator replaying the same call reproduces the same block draws.
    """
    twin = MonteCarloSimulator(symbols=symbols, seed=seed)
    port_hist, _n, _syms, _warn = twin._load_returns()
    adjusted = twin._conservative_adjustment(port_hist)
    return twin._simulate_paths(adjusted, n_sims, horizon_years * 52)


def _dd_metrics(result) -> tuple:
    """The six drawdown/SORR numbers that must depend on the market only."""
    return (
        result.sorr_early_drawdown_pct,
        result.median_max_drawdown_pct,
        result.pct_paths_severe_drawdown,
        result.median_year_of_max_dd,
        result.p25_year_of_max_dd,
        result.p75_year_of_max_dd,
    )


def _sim(symbols=None, **kwargs):
    return MonteCarloSimulator(symbols=symbols or ["AAPL"], seed=42, **kwargs)


# ------------------------------------------------------------------ #
#  Minimal alert store stub (check_sorr only touches these four)       #
# ------------------------------------------------------------------ #

class _StubStore:
    def __init__(self):
        self.recorded: list = []
        self._cooldowns: set = set()

    def is_on_cooldown(self, alert_type, symbol) -> bool:
        return f"{alert_type}:{symbol}" in self._cooldowns

    def set_cooldown(self, alert_type, symbol) -> None:
        self._cooldowns.add(f"{alert_type}:{symbol}")

    def is_muted(self, symbol, alert_type) -> bool:
        return False

    def record(self, alert_type, symbol, message, severity, explanation: str = "") -> None:
        self.recorded.append((alert_type, symbol, message, severity))


def _alert_engine(store) -> AlertEngine:
    eng = AlertEngine.__new__(AlertEngine)
    eng._store = store
    eng._notifier = MagicMock()
    eng._min_severity = AlertSeverity.INFO
    return eng


# ------------------------------------------------------------------ #
#  The row's oracle: flat market + withdrawals => no drawdown           #
# ------------------------------------------------------------------ #

class TestFlatMarketHasNoDrawdown:
    """U2-2: a market with zero volatility cannot produce a drawdown, no matter
    how much the retiree spends out of the pot."""

    @patch("portfolio.monte_carlo.get_history", side_effect=_flat_history)
    def test_flat_market_with_4pct_withdrawal_has_no_drawdown(self, _mock):
        r = _sim().run(
            horizon_years=30, n_sims=200, initial_value=INIT,
            annual_withdrawal=0.04 * INIT,
        )

        assert r.median_max_drawdown_pct == pytest.approx(0.0, abs=1e-9), (
            "Un mercado plano no tiene caídas: el 4% anual es gasto planificado, "
            "no un derrumbe. Antes del fix esto daba 100%: el retiro fixed_real "
            "saca 0.04 del capital INICIAL cada año, así que sobre un mercado "
            "plano el pozo baja linealmente y toca cero en el año 25."
        )
        assert r.sorr_early_drawdown_pct == pytest.approx(0.0, abs=1e-9)
        assert r.pct_paths_severe_drawdown == pytest.approx(0.0, abs=1e-9)

    @patch("portfolio.monte_carlo.get_history", side_effect=_flat_history)
    def test_flat_market_badge_is_green(self, _mock):
        """The traffic light reads the same series, so it must go 🟢 Bajo."""
        r = _sim().run(
            horizon_years=30, n_sims=200, initial_value=INIT,
            annual_withdrawal=0.04 * INIT,
        )
        label, _colour = sorr_risk_badge(
            r.sorr_early_drawdown_pct, r.median_max_drawdown_pct
        )
        assert label == "🟢 Bajo", (
            f"DD={r.median_max_drawdown_pct:.1f}% vs high_dd_pct="
            f"{GOAL_CARD.high_dd_pct} — el badge se pintaba 🔴 con volatilidad cero."
        )

    @patch("portfolio.monte_carlo.get_history", side_effect=_flat_history)
    def test_flat_market_does_not_fire_sorr_alert(self, _mock):
        """An 8% withdrawal rate used to push the 5-year window past the 30%
        alert threshold (1 - 0.92**5 = 34%) and mail a CRITICAL SORR_HIGH."""
        r = _sim().run(
            horizon_years=30, n_sims=200, initial_value=INIT,
            annual_withdrawal=0.08 * INIT,
        )
        assert r.sorr_early_drawdown_pct < ALERTS.sorr_high_threshold_pct

        store = _StubStore()
        fired = _alert_engine(store).check_sorr(
            sorr_early_drawdown_pct=r.sorr_early_drawdown_pct,
            horizon_years=30,
            initial_value=INIT,
        )
        assert fired is None
        assert not [rec for rec in store.recorded if rec[0] == AlertType.SORR_HIGH]


# ------------------------------------------------------------------ #
#  Against an independent sequential reference                         #
# ------------------------------------------------------------------ #

class TestAgainstIndependentOracle:
    @patch("portfolio.monte_carlo.get_history", side_effect=_volatile_history)
    def test_drawdown_matches_independent_market_path_oracle(self, _mock):
        """With withdrawals ON, the reported DD must equal the DD of the market
        series computed by the slow reference loop."""
        horizon, n_sims = 12, 300
        r = _sim().run(
            horizon_years=horizon, n_sims=n_sims, initial_value=INIT,
            annual_withdrawal=0.05 * INIT,
        )

        market = _market_paths_twin(["AAPL"], n_sims, horizon)
        expected_dds = np.array([oracle_max_drawdown(p) for p in market])

        assert r.median_max_drawdown_pct == pytest.approx(
            float(np.median(expected_dds) * 100), abs=1e-6
        )
        assert r.pct_paths_severe_drawdown == pytest.approx(
            float((expected_dds >= 0.50).mean() * 100), abs=1e-6
        )

    @patch("portfolio.monte_carlo.get_history", side_effect=_volatile_history)
    def test_sorr_window_matches_independent_oracle(self, _mock):
        """Same for the 5-year SORR window, sliced by the reference loop."""
        horizon, n_sims = 12, 300
        r = _sim().run(
            horizon_years=horizon, n_sims=n_sims, initial_value=INIT,
            annual_withdrawal=0.05 * INIT,
        )

        market = _market_paths_twin(["AAPL"], n_sims, horizon)
        early = market[:, : min(5 * 52, market.shape[1])]
        early_dds = np.array([oracle_max_drawdown(p) for p in early])

        assert r.sorr_early_drawdown_pct == pytest.approx(
            float((early_dds >= 0.30).mean() * 100), abs=1e-6
        )


# ------------------------------------------------------------------ #
#  Invariance: cash flows and drags must not move the DD metrics       #
# ------------------------------------------------------------------ #

class TestCashFlowsDoNotMoveDrawdown:
    @patch("portfolio.monte_carlo.get_history", side_effect=_volatile_history)
    def test_withdrawals_do_not_change_drawdown_metrics(self, _mock):
        base = _sim().run(horizon_years=20, n_sims=400, initial_value=INIT)
        with_wd = _sim().run(
            horizon_years=20, n_sims=400, initial_value=INIT,
            annual_withdrawal=0.04 * INIT,
        )
        assert _dd_metrics(with_wd) == _dd_metrics(base)

    @patch("portfolio.monte_carlo.get_history", side_effect=_volatile_history)
    def test_contributions_do_not_change_drawdown_metrics(self, _mock):
        """GoalPlanner models Goal.annual_contribution as a NEGATIVE withdrawal;
        inflows used to lift the running peak and distort the metric too."""
        base = _sim().run(horizon_years=20, n_sims=400, initial_value=INIT)
        with_contrib = _sim().run(
            horizon_years=20, n_sims=400, initial_value=INIT,
            annual_withdrawal=-6_000.0,
        )
        assert _dd_metrics(with_contrib) == _dd_metrics(base)

    @patch("portfolio.monte_carlo.get_history", side_effect=_volatile_history)
    def test_drags_do_not_change_drawdown_metrics(self, _mock):
        """A deterministic 1.5%/yr bleed has no *sequence*; leaving it in would
        re-create the same mechanical decline through the other door."""
        base = _sim().run(horizon_years=30, n_sims=400, initial_value=INIT)
        with_drags = _sim().run(
            horizon_years=30, n_sims=400, initial_value=INIT,
            drags={"total_annual_drag_pct": 1.5},
        )
        assert _dd_metrics(with_drags) == _dd_metrics(base)


# ------------------------------------------------------------------ #
#  Anti-cheat: the metric must still see a real crash                  #
# ------------------------------------------------------------------ #

class TestRealMarketRiskStillRegisters:
    @patch("portfolio.monte_carlo.get_history", side_effect=_volatile_history)
    def test_real_crash_still_registers(self, _mock):
        """Guards against 'fixing' the finding by zeroing the metric."""
        r = _sim().run(
            horizon_years=20, n_sims=500, initial_value=INIT,
            annual_withdrawal=0.04 * INIT,
        )
        assert r.median_max_drawdown_pct > 15.0
        assert r.sorr_early_drawdown_pct > 0.0


# ------------------------------------------------------------------ #
#  The dollar floor keeps watching the real pot                        #
# ------------------------------------------------------------------ #

class TestP10IntraMinStillTracksTheRealPot:
    @patch("portfolio.monte_carlo.get_history", side_effect=_volatile_history)
    def test_p10_intra_min_still_tracks_the_real_pot(self, _mock):
        """``p10_intra_min`` is a USD floor of the actual portfolio, so it MUST
        still fall when the retiree spends — that is the metric that answers
        'how low does my money get', and it is the one we did not move."""
        base = _sim().run(horizon_years=20, n_sims=400, initial_value=INIT)
        with_wd = _sim().run(
            horizon_years=20, n_sims=400, initial_value=INIT,
            annual_withdrawal=0.04 * INIT,
        )
        assert with_wd.p10_intra_min < base.p10_intra_min
