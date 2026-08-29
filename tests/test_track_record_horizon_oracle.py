"""An annual horizon lasts a year, and a HOLD band scales with it (backlog U5-15).

Two defects in the only evidence the engine has about itself.

**The "annual" horizon lasted 8.3 months.** ``horizons_days`` shipped
``(30, 90, 252)`` and the config docstring described 252 as "≈ 12 trading
months" while the scorer does plain calendar arithmetic —
``rec.created_at + timedelta(days=horizon)``. 252 *calendar* days is 8.3 months.
The number 252 is the count of *trading* days in a year, so it was correct in a
unit the code never used.

**One HOLD band served every horizon.** ``hold_band_pct = 5.0`` decided whether a
HOLD was right over 30 days and over a year alike. Dispersion grows with the
square root of time, so a band that is reasonable at a month is far too tight at
a year: almost any equity moves more than 5 % over twelve months, so a HOLD was
close to automatically wrong at the long horizon — a bias baked into the record
rather than a finding drawn from it.

This matters more than a screen: the track record is the only judge the engine
has of its own calls, it only grows with time, and every month it runs
uncorrected is a month of contaminated sample.

Migration cost is zero, and that is why now is the moment: measured on the live
database, **only the 30-day horizon has ever been scored** (22 outcomes), and the
oldest recommendation is 73 days old, so nothing has been graded at 90 or 252.

No network, no Streamlit.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from analysis.track_record_scorer import compute_hit, hold_band_for
from config import TRACK_RECORD

TRADING_DAYS_PER_YEAR = 252
CALENDAR_DAYS_PER_YEAR = 365


class TestTheAnnualHorizonLastsAYear:
    def test_the_long_horizon_is_a_calendar_year(self):
        assert max(TRACK_RECORD.horizons_days) >= CALENDAR_DAYS_PER_YEAR - 5

    def test_it_is_no_longer_the_trading_day_count(self):
        """252 is right in a unit the scorer never used."""
        assert TRADING_DAYS_PER_YEAR not in TRACK_RECORD.horizons_days

    def test_the_horizon_the_scorer_waits_is_the_horizon_it_names(self):
        """The scorer adds calendar days, so the config must be calendar days."""
        created = datetime(2026, 1, 1)
        for horizon in TRACK_RECORD.horizons_days:
            elapsed = (created + timedelta(days=horizon)) - created
            assert elapsed.days == horizon

    def test_the_annual_horizon_really_is_about_twelve_months(self):
        annual = max(TRACK_RECORD.horizons_days)
        assert 11.5 <= annual / 30.44 <= 12.5

    def test_the_horizons_are_ordered_and_distinct(self):
        h = list(TRACK_RECORD.horizons_days)
        assert h == sorted(h) and len(set(h)) == len(h)


class TestTheHoldBandScalesWithTheHorizon:
    def test_a_longer_horizon_gets_a_wider_band(self):
        bands = [hold_band_for(h) for h in sorted(TRACK_RECORD.horizons_days)]
        assert bands == sorted(bands)
        assert bands[0] < bands[-1]

    def test_the_shortest_horizon_keeps_the_shipped_band(self):
        """The calibrated anchor is not moved; the others are derived from it."""
        assert hold_band_for(min(TRACK_RECORD.horizons_days)) == pytest.approx(5.0)

    def test_the_widening_follows_the_square_root_of_time(self):
        """Dispersion grows with √t — that is the reason the band must widen.

        Checked loosely: the ratio of bands should track the ratio of √horizons,
        not the ratio of horizons. A linear scale would make the annual band
        ~61 %, which grades nothing.
        """
        short, long_ = min(TRACK_RECORD.horizons_days), max(TRACK_RECORD.horizons_days)
        observed = hold_band_for(long_) / hold_band_for(short)
        expected = (long_ / short) ** 0.5
        assert observed == pytest.approx(expected, rel=0.15)

    def test_an_unknown_horizon_falls_back_rather_than_raising(self):
        assert hold_band_for(7) > 0

    def test_a_hold_is_graded_against_its_own_horizon(self):
        """The defect, at the only place it is observable.

        A 9 % move over a year is well inside normal dispersion, so a HOLD was
        the right call. Over 30 days the same move is not.
        """
        annual = max(TRACK_RECORD.horizons_days)
        short = min(TRACK_RECORD.horizons_days)
        assert compute_hit("HOLD", 9.0, None, horizon_days=annual) is True
        assert compute_hit("HOLD", 9.0, None, horizon_days=short) is False

    def test_a_directional_call_is_unaffected_by_the_band(self):
        """Anti-cheat: only HOLD is graded on an absolute band."""
        for horizon in TRACK_RECORD.horizons_days:
            assert compute_hit("BUY", 40.0, 2.0, horizon_days=horizon) is True
            assert compute_hit("SELL", 40.0, 2.0, horizon_days=horizon) is False

    def test_an_ungradable_benchmark_is_still_ungradable(self):
        """U2-4 must survive: no market, no answer for a directional call."""
        assert compute_hit("BUY", 10.0, None, horizon_days=365) is None

    def test_the_band_is_config_driven_not_a_literal(self):
        from pathlib import Path

        src = (Path(__file__).resolve().parents[1] / "analysis" /
               "track_record_scorer.py").read_text(encoding="utf-8")
        assert "TRACK_RECORD.hold_band_pct" not in src.split("def hold_band_for")[0]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
