"""Where the peso rate comes from, per leg (backlog N1).

U2-5 closed the *conversion* — deflate to today's dollars before applying a spot
— and built the vocabulary for provenance: ``rate_source`` already distinguished
``placeholder`` / ``env`` / ``manual``, the brecha was already withheld on
placeholders, and the UI already printed the source. What it left open, and what
N1 is, is where the numbers actually come from.

Measured: the placeholder official rate is **1 000 pesos/USD against a real
1 512** — 51 % low — and ``manual`` was unreachable, because nothing in the
product could set a rate. The "20 % brecha" the config implies is the difference
between two invented numbers.

The two legs are not the same problem and no longer share an answer:

  * **official** — quoted as ``ARS=X`` through the yfinance dependency the
    project already has, with the same cache and TTL as every other price. It
    gets a date, and a fetch that fails falls back to the placeholder and says so
    rather than inventing freshness.
  * **parallel** — has no free feed. It is the user's number, entered and
    persisted, and labelled as theirs.

So provenance becomes **per leg**. A single ``rate_source`` could not say
"official from the market this morning, parallel is what you typed", and that
sentence is the whole point of the row.

**The brecha needs both legs real.** A market official against a placeholder
parallel is not a market observation either — it is one real number minus one
invented one, which is the same defect wearing half a disguise.

No network: the quote lookup is injected.
"""

from __future__ import annotations

import pytest

from config import AR_FX_PLACEHOLDER_OFICIAL, AR_FX_PLACEHOLDER_PARALLEL, ArFxConfig
from data.product_ux import ar_dual_amounts


def _fx(**kw) -> ArFxConfig:
    return ArFxConfig(**kw)


class TestProvenanceIsPerLeg:
    def test_each_leg_reports_its_own_source(self):
        fx = _fx(usd_ars_oficial=1512.0, source_oficial="market",
                 usd_ars_parallel=1600.0, source_parallel="manual")
        assert fx.source_oficial == "market"
        assert fx.source_parallel == "manual"

    def test_untouched_config_is_placeholder_on_both(self):
        fx = _fx()
        assert fx.usd_ars_oficial == AR_FX_PLACEHOLDER_OFICIAL
        assert fx.usd_ars_parallel == AR_FX_PLACEHOLDER_PARALLEL
        assert fx.source_oficial == "placeholder"
        assert fx.source_parallel == "placeholder"

    def test_the_legacy_single_source_still_answers(self):
        """``rate_source`` is read by existing surfaces; it must stay truthful.

        With the legs disagreeing it reports the weaker of the two, because a
        pair is only as sourced as its least sourced half.
        """
        fx = _fx(usd_ars_oficial=1512.0, source_oficial="market")
        assert fx.rate_source == "placeholder"

        both = _fx(usd_ars_oficial=1512.0, source_oficial="market",
                   usd_ars_parallel=1600.0, source_parallel="manual")
        assert both.rate_source != "placeholder"


class TestTheBrechaNeedsBothLegsReal:
    def _dual(self, fx: ArFxConfig) -> dict:
        return ar_dual_amounts(
            1000.0,
            usd_ars_oficial=fx.usd_ars_oficial,
            usd_ars_parallel=fx.usd_ars_parallel,
            rate_source=fx.rate_source,
        )

    def test_two_placeholders_yield_no_brecha(self):
        """Unchanged from U2-5, and still the baseline case."""
        out = self._dual(_fx())
        assert out["brecha_pct"] is None
        assert out["brecha_omitted_reason"]

    def test_a_real_official_against_a_placeholder_parallel_yields_no_brecha(self):
        """The half-disguise: one real number minus one invented one."""
        out = self._dual(_fx(usd_ars_oficial=1512.0, source_oficial="market"))
        assert out["brecha_pct"] is None
        assert out["brecha_omitted_reason"]

    def test_both_real_yields_the_brecha(self):
        out = self._dual(_fx(usd_ars_oficial=1512.0, source_oficial="market",
                             usd_ars_parallel=1814.4, source_parallel="manual"))
        assert out["brecha_pct"] == pytest.approx(20.0, abs=0.1)
        assert out["brecha_omitted_reason"] is None


class TestTheOfficialLegCanComeFromTheMarket:
    def test_a_quote_is_used_and_dated(self):
        from config import ar_fx_from_market

        fx = ar_fx_from_market(quote_lookup=lambda sym: (1512.25, "2026-08-29"))
        assert fx.usd_ars_oficial == pytest.approx(1512.25)
        assert fx.source_oficial == "market"
        assert "2026-08-29" in fx.rate_asof

    def test_a_failed_quote_falls_back_and_says_so(self):
        """A lookup that fails must not invent freshness."""
        from config import ar_fx_from_market

        fx = ar_fx_from_market(quote_lookup=lambda sym: None)
        assert fx.usd_ars_oficial == AR_FX_PLACEHOLDER_OFICIAL
        assert fx.source_oficial == "placeholder"

    def test_a_nonsense_quote_is_refused(self):
        """Anti-cheat: a zero or negative rate is not a rate."""
        from config import ar_fx_from_market

        for bad in (0.0, -5.0):
            fx = ar_fx_from_market(quote_lookup=lambda sym, v=bad: (v, "2026-08-29"))
            assert fx.source_oficial == "placeholder"

    def test_the_users_parallel_survives_the_market_official(self):
        from config import ar_fx_from_market

        fx = ar_fx_from_market(
            quote_lookup=lambda sym: (1512.25, "2026-08-29"),
            usd_ars_parallel=1700.0,
        )
        assert fx.usd_ars_parallel == pytest.approx(1700.0)
        assert fx.source_parallel == "manual"
        assert fx.source_oficial == "market"


class TestTheUserCanActuallySetIt:
    def test_preferences_persist_the_parallel_rate(self):
        from data.preferences import UserPreferences

        prefs = UserPreferences()
        assert hasattr(prefs, "usd_ars_parallel")
        assert hasattr(prefs, "usd_ars_parallel_asof")

    def test_settings_exposes_an_input(self):
        from pathlib import Path

        page = (Path(__file__).resolve().parents[1] / "dashboard" / "pages" /
                "9_Settings.py").read_text(encoding="utf-8")
        assert "usd_ars_parallel" in page


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
