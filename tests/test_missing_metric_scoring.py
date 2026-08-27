"""A metric the feed does not report scores zero (oracle-first, CONTEXT §5).

The defect: every valuation and leverage band in ``analysis/fundamental.py`` is an
*upper* bound (``elif pe <= T.pe_good``), and the value fed into them came from
``_safe_float(info.get(...))``, which turns a missing field into ``0.0``. Zero is
below every upper bound, so **absent data fell into the second band and got paid**:

    P/E +5 of 8 · PEG +4 of 7 · EV/EBITDA +3 of 5 · P/B +3 of 5 · D/E +7 of 20

Measured on the cached universe (2026-08-22): 24 companies collected points for
data nobody had. The nine banks took +10 each — a bank has no EV/EBITDA and no
meaningful ``debtToEquity``, so yfinance omits both. MCD, SBUX, ABBV, YUM and LOW
took +7 apiece with the note "Very low debt D/E=0.00" while carrying negative
shareholders' equity (MCD: $54.8B of debt against −$1.79B of equity). A ticker
with no multiples at all scored 15 of 25 on valuation — better than a real company
with mediocre-but-honest numbers.

Per CONTEXT §5 the oracle is a reference scorer written from the *definition* of a
scoring band — "a band is earned only when the metric exists and falls inside it" —
walking ``THRESHOLDS`` with a plain loop. It shares no code with the engine.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import patch

import pandas as pd
import pytest

from analysis.fundamental import (
    FundamentalAnalyzer,
    FundamentalResult,
    reported_metric,
    reported_positive_metric,
)
from config import THRESHOLDS as T

# --------------------------------------------------------------------------- #
#  Oracle                                                                     #
# --------------------------------------------------------------------------- #

def oracle_band_score(value: Optional[float], bands: List[Tuple[float, float]]) -> float:
    """Points for *value* given ``[(upper_bound, points), ...]`` ascending.

    Written from the definition: with no value there is no band, hence no points.
    With a value, the first band whose upper bound it does not exceed pays out.
    """
    if value is None:
        return 0.0
    for upper, points in bands:
        if value <= upper:
            return points
    return 0.0


VALUATION_BANDS = {
    "P/E": ([(T.pe_excellent, 8.0), (T.pe_good, 5.0), (T.pe_acceptable, 2.0)], 8.0),
    "PEG": ([(T.peg_excellent, 7.0), (T.peg_good, 4.0), (T.peg_acceptable, 2.0)], 7.0),
    "EV/EBITDA": ([(T.ev_ebitda_excellent, 5.0), (T.ev_ebitda_good, 3.0),
                   (T.ev_ebitda_acceptable, 1.0)], 5.0),
    "P/B": ([(T.pb_excellent, 5.0), (T.pb_good, 3.0), (T.pb_acceptable, 1.0)], 5.0),
}

DE_BANDS = [(T.max_debt_equity_excellent, 7.0), (T.max_debt_equity_good, 5.0),
            (T.max_debt_equity_acceptable, 2.0)]


# --------------------------------------------------------------------------- #
#  Fixtures                                                                   #
# --------------------------------------------------------------------------- #

def _info(**overrides: Any) -> Dict[str, Any]:
    base = {
        "longName": "Test Co",
        "sector": "Technology",
        "industry": "Software",
        "country": "United States",
        "currentPrice": 100.0,
        "regularMarketPrice": 100.0,
        "marketCap": 1e9,
    }
    base.update(overrides)
    return base


def _score_valuation(info: Dict[str, Any]) -> Tuple[float, FundamentalResult]:
    result = FundamentalResult(symbol="TEST")
    score = FundamentalAnalyzer()._score_valuation(info, result)
    return score, result


def _score_health(info: Dict[str, Any]) -> Tuple[float, FundamentalResult]:
    result = FundamentalResult(symbol="TEST")
    empty = pd.DataFrame()
    score = FundamentalAnalyzer()._score_financial_health(info, empty, empty, result)
    return score, result


def _score_profitability(info: Dict[str, Any]) -> Tuple[float, FundamentalResult]:
    result = FundamentalResult(symbol="TEST")
    empty = pd.DataFrame()
    score = FundamentalAnalyzer()._score_profitability(info, empty, empty, result)
    return score, result


def _score_dividends(info: Dict[str, Any]) -> Tuple[float, FundamentalResult]:
    result = FundamentalResult(symbol="TEST")
    empty = pd.Series(dtype=float)
    with patch("analysis.fundamental.get_dividends", return_value=empty):
        score = FundamentalAnalyzer()._score_dividends(info, result)
    return score, result


def oracle_payout_score(payout: Optional[float]) -> float:
    """Independent of `_score_dividends`: missing pays 0; reported 0 still scores."""
    if payout is None:
        return 0.0
    if 0 < payout <= T.payout_excellent:
        return 3.0
    if payout <= T.max_payout_ratio:
        return 2.0
    return 0.0


# --------------------------------------------------------------------------- #
#  Oracle self-check                                                          #
# --------------------------------------------------------------------------- #

class TestOracle:
    def test_no_value_earns_no_band(self):
        assert oracle_band_score(None, VALUATION_BANDS["P/E"][0]) == 0.0

    def test_bands_pay_in_order(self):
        bands = VALUATION_BANDS["P/E"][0]
        assert oracle_band_score(T.pe_excellent - 1, bands) == 8.0
        assert oracle_band_score(T.pe_good - 1, bands) == 5.0
        assert oracle_band_score(T.pe_acceptable - 1, bands) == 2.0
        assert oracle_band_score(T.pe_acceptable + 100, bands) == 0.0


# --------------------------------------------------------------------------- #
#  The defect: missing data must not pay                                      #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("key,label", [
    ("trailingPE", "P/E"),
    ("pegRatio", "PEG"),
    ("enterpriseToEbitda", "EV/EBITDA"),
    ("priceToBook", "P/B"),
])
def test_a_single_missing_valuation_metric_pays_nothing(key, label):
    """Isolate one metric: present-and-good pays, absent pays zero."""
    good = {"trailingPE": 10.0, "pegRatio": 0.8, "enterpriseToEbitda": 8.0, "priceToBook": 1.2}
    with_all, _ = _score_valuation(_info(**good))

    without = dict(good)
    without.pop(key)
    partial, result = _score_valuation(_info(**without))

    lost = with_all - partial
    assert lost == VALUATION_BANDS[label][1], f"{label} debe costar sus puntos completos"
    assert label in result.notes.get("valuation_missing", "")


def test_no_valuation_data_at_all_scores_zero():
    """Was 15 of 25 — five of them for a P/E nobody reported."""
    score, result = _score_valuation(_info())
    assert score == 0.0
    for label in ("P/E", "PEG", "EV/EBITDA", "P/B"):
        assert label in result.notes["valuation_missing"]


def test_missing_debt_to_equity_scores_zero_and_claims_nothing():
    """The `Very low debt D/E=0.00` note was the tell: it fired on absent data."""
    score, result = _score_health(_info())
    assert score == 0.0
    assert result.debt_equity is None
    assert "debt_equity" not in result.notes
    assert "D/E" in result.notes.get("health_missing", "")


@pytest.mark.parametrize("raw,expected_de", [
    (45.0, 0.45),      # yfinance reports D/E ×100
    (0.0, 0.0),        # a genuinely debt-free balance sheet
    (310.0, 3.10),
])
def test_present_debt_to_equity_still_scores_as_before(raw, expected_de):
    score, result = _score_health(_info(debtToEquity=raw))
    assert result.debt_equity == pytest.approx(expected_de)
    assert score == oracle_band_score(expected_de, DE_BANDS)


# --------------------------------------------------------------------------- #
#  Engine agrees with the oracle across the grid                              #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("pe", [None, 0.0, -12.0, 8.0, 20.0, 30.0, 80.0])
@pytest.mark.parametrize("pb", [None, 0.0, -3.0, 1.0, 2.5, 4.0, 40.0])
def test_valuation_matches_the_oracle(pe, pb):
    info = _info()
    if pe is not None:
        info["trailingPE"] = pe
    if pb is not None:
        info["priceToBook"] = pb
    score, _ = _score_valuation(info)

    expected = (
        oracle_band_score(pe if (pe or 0) > 0 else None, VALUATION_BANDS["P/E"][0])
        + oracle_band_score(pb if (pb or 0) > 0 else None, VALUATION_BANDS["P/B"][0])
    )
    assert score == expected


def test_negative_multiples_are_not_cheap():
    """A negative P/E means no earnings — it used to buy the second band."""
    score, result = _score_valuation(_info(trailingPE=-15.0, priceToBook=-2.0))
    assert score == 0.0
    assert result.pe_ratio is None and result.pb_ratio is None


# --------------------------------------------------------------------------- #
#  Real shapes from the audit                                                 #
# --------------------------------------------------------------------------- #

def test_bank_shaped_feed_loses_exactly_ten_points():
    """JPM/BAC/WFC shape: no EV/EBITDA, no debtToEquity → the +10 disappears."""
    bank = _info(trailingPE=15.3, pegRatio=1.77, priceToBook=2.69)  # no EV/EBITDA, no D/E
    val, _ = _score_valuation(bank)
    health, _ = _score_health(bank)

    complete = dict(bank)
    complete.update({"enterpriseToEbitda": 12.0, "debtToEquity": 138.0})
    val_full, _ = _score_valuation(complete)
    health_full, _ = _score_health(complete)

    assert val_full - val == 3.0      # EV/EBITDA band it never earned
    assert health_full - health == 2.0  # D/E 1.38 → "acceptable", not "excellent"


def test_a_complete_feed_is_untouched_by_the_fix():
    """No regression: everything reported ⇒ the score is what it always was."""
    complete = _info(trailingPE=31.6, pegRatio=4.56, enterpriseToEbitda=19.5,
                     priceToBook=7.7, debtToEquity=57.7, currentRatio=1.1,
                     quickRatio=0.8)
    val, _ = _score_valuation(complete)
    health, _ = _score_health(complete)

    assert val == (oracle_band_score(31.6, VALUATION_BANDS["P/E"][0])
                   + oracle_band_score(4.56, VALUATION_BANDS["PEG"][0])
                   + oracle_band_score(19.5, VALUATION_BANDS["EV/EBITDA"][0])
                   + oracle_band_score(7.7, VALUATION_BANDS["P/B"][0]))
    # D/E 0.577 → "good" band; current ratio 1.1 and quick ratio 0.8 each land in
    # their lowest positive band (+1), untouched by this fix.
    assert health == oracle_band_score(0.577, DE_BANDS) + 1 + 1


# --------------------------------------------------------------------------- #
#  Helper contract                                                            #
# --------------------------------------------------------------------------- #

class TestReportedMetric:
    def test_absent_is_none_but_zero_is_zero(self):
        assert reported_metric({}, "x") is None
        assert reported_metric({"x": 0.0}, "x") == 0.0

    def test_nan_and_garbage_are_none(self):
        assert reported_metric({"x": float("nan")}, "x") is None
        assert reported_metric({"x": "n/a"}, "x") is None
        assert reported_metric({"x": None}, "x") is None
        assert reported_metric({"x": float("inf")}, "x") is None

    def test_falls_through_to_the_next_key(self):
        assert reported_metric({"a": None, "b": 7.0}, "a", "b") == 7.0

    def test_positive_variant_rejects_zero_and_negatives(self):
        assert reported_positive_metric({"x": 0.0}, "x") is None
        assert reported_positive_metric({"x": -4.0}, "x") is None
        assert reported_positive_metric({"x": 4.0}, "x") == 4.0


# --------------------------------------------------------------------------- #
#  Payout / ROE / net margin — same "missing is not a good upper bound"        #
# --------------------------------------------------------------------------- #

def _payer(**overrides: Any) -> Dict[str, Any]:
    """A dividend payer in the yield sweet spot so payout is the only moving part."""
    base = _info(currentPrice=100.0, trailingAnnualDividendRate=2.5)
    base.update(overrides)
    return base


@pytest.mark.parametrize("raw,pct", [
    (None, None),
    (0.0, 0.0),
    (0.40, 40.0),
    (0.50, 50.0),
    (0.80, 80.0),
])
def test_payout_band_matches_the_oracle(raw, pct):
    info = _payer()
    if raw is not None:
        info["payoutRatio"] = raw
    score, result = _score_dividends(info)
    # Sweet-spot yield is +4; streak is 0 on an empty series.
    assert score == pytest.approx(4.0 + oracle_payout_score(pct))
    if pct is None:
        assert result.payout_ratio_effective is None
        assert "Payout" in result.notes.get("dividend_missing", "")
    else:
        assert result.payout_ratio_effective == pytest.approx(pct)
        assert "Payout" not in result.notes.get("dividend_missing", "")


def test_missing_payout_does_not_pay_the_acceptable_band():
    """`payout or 0.0` used to collect 2 of 3 payout points for an omitted ratio."""
    with_payout, _ = _score_dividends(_payer(payoutRatio=0.50))
    without, result = _score_dividends(_payer())
    assert with_payout - without == oracle_payout_score(50.0)
    assert without == pytest.approx(4.0)
    assert "Payout" in result.notes["dividend_missing"]


def test_reported_zero_payout_is_scored():
    score, result = _score_dividends(_payer(payoutRatio=0.0))
    assert result.payout_ratio == pytest.approx(0.0)
    assert result.payout_ratio_effective == pytest.approx(0.0)
    assert score == pytest.approx(4.0 + oracle_payout_score(0.0))
    assert "Payout" not in result.notes.get("dividend_missing", "")


def test_payout_excellent_cut_lives_in_config():
    from pathlib import Path

    assert T.payout_excellent == 40.0
    fund = Path(__file__).resolve().parents[1] / "analysis" / "fundamental.py"
    text = fund.read_text(encoding="utf-8")
    body = text.split("def _score_dividends")[1].split("def ")[0]
    assert "payout or 0.0" not in body
    assert "T.payout_excellent" in body
    assert "<= 40" not in body


def test_omitted_roe_does_not_warn_low_zero():
    score, result = _score_profitability(_info())
    assert result.roe is None
    assert not any("Low ROE" in w for w in result.warnings)
    assert "ROE" in result.notes.get("profitability_missing", "")
    # Gross margin / ROIC may still run; ROE itself must contribute 0.
    assert score >= 0.0


def test_reported_zero_roe_still_warns():
    _, result = _score_profitability(_info(returnOnEquity=0.0))
    assert result.roe == pytest.approx(0.0)
    assert any("Low ROE: 0.0%" in w for w in result.warnings)
    assert "ROE" not in result.notes.get("profitability_missing", "")


def test_omitted_net_margin_does_not_warn_thin_zero():
    _, result = _score_profitability(_info())
    assert result.net_margin is None
    assert not any("Thin net margin" in w for w in result.warnings)
    assert "Net margin" in result.notes.get("profitability_missing", "")


def test_reported_zero_net_margin_still_warns():
    _, result = _score_profitability(_info(profitMargins=0.0))
    assert result.net_margin == pytest.approx(0.0)
    assert any("Thin net margin: 0.0%" in w for w in result.warnings)
    assert "Net margin" not in result.notes.get("profitability_missing", "")


def test_omitted_roic_does_not_warn_low_zero():
    with_roic, _ = _score_profitability(_info(returnOnAssets=0.20))
    without, result = _score_profitability(_info())
    assert result.roic is None
    assert not any("Low ROIC" in w for w in result.warnings)
    assert "ROIC" in result.notes.get("profitability_missing", "")
    assert with_roic - without == 7.0


def test_reported_zero_roic_still_warns():
    _, result = _score_profitability(_info(returnOnAssets=0.0))
    assert result.roic == pytest.approx(0.0)
    assert any("Low ROIC: 0.0%" in w for w in result.warnings)
    assert "ROIC" not in result.notes.get("profitability_missing", "")


def test_omitted_gross_margin_does_not_warn_thin_zero():
    with_gm, _ = _score_profitability(_info(grossMargins=0.55))
    without, result = _score_profitability(_info())
    assert result.gross_margin is None
    assert not any("Thin gross margin" in w for w in result.warnings)
    assert "Gross margin" in result.notes.get("profitability_missing", "")
    assert with_gm - without == 5.0


def test_reported_zero_gross_margin_still_warns():
    _, result = _score_profitability(_info(grossMargins=0.0))
    assert result.gross_margin == pytest.approx(0.0)
    assert any("Thin gross margin: 0.0%" in w for w in result.warnings)
    assert "Gross margin" not in result.notes.get("profitability_missing", "")
