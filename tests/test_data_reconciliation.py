"""Tests for multi-source reconciliation + the data-quality agent (Fase 3A).

Pure offline tests using fake sources — no network, no API keys.
"""

from __future__ import annotations

from analysis.data_reconciliation import (
    attach_cross_source_quality,
    data_quality_agent,
    reconcile,
    reconcile_sources,
)
from data.data_sources import DataSource, SourceValue


class _FakeSource(DataSource):
    def __init__(self, name, values: dict):
        self.name = name
        self._values = values  # field -> (value, as_of)

    def fetch_fundamentals(self, symbol):
        return {
            f: SourceValue(f, v[0], self.name, as_of=v[1])
            for f, v in self._values.items()
        }


def _sv(field, value, source, as_of=None):
    return SourceValue(field, value, source, as_of=as_of)


# --------------------------------------------------------------------------- #
#  Reconciliation                                                              #
# --------------------------------------------------------------------------- #

def test_agreement_no_conflict():
    results = {
        "yfinance": {"net_income": _sv("net_income", 100.0, "yfinance", "2025-12-31")},
        "sec_edgar": {"net_income": _sv("net_income", 101.0, "sec_edgar", "2025-12-31")},  # ~1%
    }
    report = reconcile("AAA", results)
    fld = report.fields[0]
    assert fld.conflict is False
    assert fld.comparable is True
    assert report.n_conflicts == 0
    assert report.agreement_pct == 100.0


def test_conflict_detected_above_threshold():
    """Same fiscal period, materially different numbers — a real discrepancy."""
    results = {
        "yfinance": {"net_income": _sv("net_income", 100.0, "yfinance", "2025-12-31")},
        "sec_edgar": {"net_income": _sv("net_income", 130.0, "sec_edgar", "2025-12-31")},  # 23%
    }
    report = reconcile("AAA", results)
    fld = report.fields[0]
    assert fld.conflict is True
    assert fld.comparable is True
    assert fld.period == "2025-12-31"
    assert report.n_conflicts == 1
    assert report.agreement_pct == 0.0


def test_chosen_value_follows_source_priority():
    # sec_edgar outranks yfinance in default priority.
    results = {
        "yfinance": {"total_revenue": _sv("total_revenue", 500.0, "yfinance")},
        "sec_edgar": {"total_revenue": _sv("total_revenue", 480.0, "sec_edgar")},
    }
    report = reconcile("AAA", results)
    fld = report.fields[0]
    assert fld.chosen_source == "sec_edgar"
    assert fld.chosen_value == 480.0


def test_single_source_field_is_not_a_conflict():
    results = {"yfinance": {"market_cap": _sv("market_cap", 1e12, "yfinance")}}
    report = reconcile("AAA", results)
    assert report.n_conflicts == 0
    assert report.agreement_pct is None  # nothing cross-checked
    assert report.fields[0].chosen_value == 1e12


def test_reconcile_sources_with_fake_sources():
    s1 = _FakeSource(
        "yfinance", {"net_income": (200.0, "2025-12-31"), "market_cap": (5e11, None)}
    )
    s2 = _FakeSource("sec_edgar", {"net_income": (260.0, "2025-12-31")})  # 23% diff -> conflict
    report = reconcile_sources("BBB", [s1, s2])
    assert set(report.sources_used) == {"yfinance", "sec_edgar"}
    assert report.n_conflicts == 1
    ni = next(f for f in report.fields if f.field == "net_income")
    assert ni.as_of["sec_edgar"] == "2025-12-31"


def test_failing_source_is_skipped():
    class _Boom(DataSource):
        name = "boom"

        def fetch_fundamentals(self, symbol):
            raise RuntimeError("network down")

    good = _FakeSource("yfinance", {"net_income": (100.0, None)})
    report = reconcile_sources("CCC", [good, _Boom()])
    assert report.sources_used == ["yfinance"]


# --------------------------------------------------------------------------- #
#  Data-quality agent                                                          #
# --------------------------------------------------------------------------- #

def test_quality_agent_downgrades_on_conflict():
    base = {"level": "good", "warnings": [], "missing_fields": []}
    results = {
        "yfinance": {"net_income": _sv("net_income", 100.0, "yfinance", "2025-12-31")},
        "sec_edgar": {"net_income": _sv("net_income", 140.0, "sec_edgar", "2025-12-31")},
    }
    report = reconcile("AAA", results)
    merged = data_quality_agent(base, report)
    assert merged["n_source_conflicts"] == 1
    assert merged["level"] == "partial"  # downgraded from good
    assert any("Discrepancia entre fuentes" in w for w in merged["warnings"])
    # input not mutated
    assert base["level"] == "good"


def test_quality_agent_no_conflict_keeps_level():
    base = {"level": "good", "warnings": []}
    results = {
        "yfinance": {"net_income": _sv("net_income", 100.0, "yfinance", "2025-12-31")},
        "sec_edgar": {"net_income": _sv("net_income", 100.5, "sec_edgar", "2025-12-31")},
    }
    merged = data_quality_agent(base, reconcile("AAA", results))
    assert merged["level"] == "good"
    assert merged["cross_source_agreement_pct"] == 100.0


def test_quality_agent_single_source_notes_no_cross_check():
    base = {"level": "good", "warnings": []}
    results = {"yfinance": {"net_income": _sv("net_income", 100.0, "yfinance")}}
    merged = data_quality_agent(base, reconcile("AAA", results))
    assert merged["n_source_conflicts"] == 0
    assert any("sin verificación cruzada" in w for w in merged["warnings"])


# --------------------------------------------------------------------------- #
#  attach_cross_source_quality (wiring into the analysis result)              #
# --------------------------------------------------------------------------- #

class _FakeResult:
    def __init__(self, symbol):
        self.symbol = symbol
        self.is_crypto = False
        self.data_quality = {"level": "good", "warnings": []}
        self.warnings = []


def test_attach_folds_conflict_into_result():
    res = _FakeResult("AAA")
    s1 = _FakeSource("yfinance", {"net_income": (100.0, "2025-12-31")})
    s2 = _FakeSource("sec_edgar", {"net_income": (140.0, "2025-12-31")})  # conflict
    report = attach_cross_source_quality(res, sources=[s1, s2])
    assert report is not None and report.n_conflicts == 1
    assert res.data_quality["level"] == "partial"  # downgraded
    assert res.data_quality["n_source_conflicts"] == 1
    assert any("Discrepancia entre fuentes" in w for w in res.warnings)


def test_attach_skips_crypto():
    res = _FakeResult("BTC-USD")
    res.is_crypto = True
    assert attach_cross_source_quality(res, sources=[_FakeSource("yfinance", {})]) is None


def test_quality_agent_marks_raw_facts_scope():
    base = {"level": "good", "warnings": []}
    results = {
        "yfinance": {"net_income": _sv("net_income", 100.0, "yfinance", "2025-12-31")},
        "sec_edgar": {"net_income": _sv("net_income", 100.5, "sec_edgar", "2025-12-31")},
    }
    merged = data_quality_agent(base, reconcile("AAA", results))
    assert merged.get("cross_check_scope") == "raw_facts"
    assert any("hechos crudos" in w for w in merged["warnings"])


def test_fundamental_analyzer_wires_attach_when_enabled():
    """P0.1: analyze path calls attach_cross_source_quality when gated on."""
    from unittest.mock import MagicMock, patch

    from analysis.fundamental import FundamentalAnalyzer

    result = MagicMock()
    result.symbol = "AAPL"
    result.is_crypto = False
    result.data_quality = {"level": "good", "warnings": []}

    with patch("config.MULTI_SOURCE") as ms:
        ms.enabled = True
        ms.attach_in_pipeline = True
        with patch(
            "analysis.data_reconciliation.attach_cross_source_quality",
            return_value=None,
        ) as attach:
            FundamentalAnalyzer._attach_cross_source_quality(result)
            attach.assert_called_once_with(result)


def test_fundamental_analyzer_skips_attach_when_pipeline_flag_off():
    from unittest.mock import MagicMock, patch

    from analysis.fundamental import FundamentalAnalyzer

    result = MagicMock()
    with patch("config.MULTI_SOURCE") as ms:
        ms.enabled = True
        ms.attach_in_pipeline = False
        with patch(
            "analysis.data_reconciliation.attach_cross_source_quality"
        ) as attach:
            FundamentalAnalyzer._attach_cross_source_quality(result)
            attach.assert_not_called()


def _fake_financials():
    """Two annual columns, newest first — the shape data.fetcher.get_financials returns."""
    import pandas as pd

    cols = ["2025-12-31", "2024-12-31"]
    return {
        "income_stmt": pd.DataFrame(
            {cols[0]: [100.0, 10.0], cols[1]: [90.0, 8.0]},
            index=["Total Revenue", "Net Income"],
        ),
        "balance_sheet": pd.DataFrame(
            {cols[0]: [2e10, 5e10], cols[1]: [1.8e10, 4.6e10]},
            index=["Stockholders Equity", "Total Assets"],
        ),
    }


def test_yfinance_source_maps_equity_and_assets():
    from unittest.mock import patch

    from data.data_sources import YFinanceSource

    fake_info = {"sharesOutstanding": 1e9, "currentPrice": 50.0, "marketCap": 5e10}
    with patch("data.fetcher.get_info", return_value=fake_info), \
         patch("data.fetcher.get_financials", return_value=_fake_financials()):
        out = YFinanceSource().fetch_fundamentals("AAPL")
    assert out["total_equity"].value == 2e10
    assert out["total_assets"].value == 5e10
    assert out["total_revenue"].value == 100.0


def test_yfinance_periodic_facts_carry_as_of_and_point_in_time_ones_do_not():
    """The whole fix rests on this: a periodic fact must declare its period.

    Price / market cap / share count are "now" by definition and SEC does not
    publish them, so they stay undated and are never cross-checked.
    """
    from unittest.mock import patch

    from data.data_sources import YFinanceSource

    fake_info = {"sharesOutstanding": 1e9, "currentPrice": 50.0, "marketCap": 5e10}
    with patch("data.fetcher.get_info", return_value=fake_info), \
         patch("data.fetcher.get_financials", return_value=_fake_financials()):
        out = YFinanceSource().fetch_fundamentals("AAPL")

    for fld in ("total_revenue", "net_income", "total_equity", "total_assets"):
        assert out[fld].as_of == "2025-12-31", f"{fld} must declare its fiscal period"
    for fld in ("current_price", "market_cap", "shares_outstanding"):
        assert out[fld].as_of is None


def test_yfinance_uses_newest_annual_column_not_an_older_one():
    from unittest.mock import patch

    from data.data_sources import YFinanceSource

    with patch("data.fetcher.get_info", return_value={}), \
         patch("data.fetcher.get_financials", return_value=_fake_financials()):
        out = YFinanceSource().fetch_fundamentals("AAPL")
    assert out["net_income"].value == 10.0   # 2025, not the 8.0 of 2024


# --------------------------------------------------------------------------- #
#  Period alignment — the rule the false "Parcial" epidemic came from          #
# --------------------------------------------------------------------------- #

def test_mismatched_periods_are_not_a_conflict():
    """The MSFT case: yfinance TTM vs a `Revenues` tag MSFT retired in FY2010.

    A 5x gap between two numbers that measure different years is not a
    discrepancy — it is a failed comparison, and it must not move the badge.
    """
    results = {
        "yfinance": {"total_revenue": _sv("total_revenue", 331_840.0, "yfinance", "2026-06-30")},
        "sec_edgar": {"total_revenue": _sv("total_revenue", 62_480.0, "sec_edgar", "2010-06-30")},
    }
    report = reconcile("MSFT", results)
    fld = report.fields[0]
    assert fld.comparable is False
    assert fld.conflict is False
    assert report.n_conflicts == 0
    assert report.agreement_pct is None          # nothing was actually cross-checked
    assert report.uncomparable_fields == [fld]

    merged = data_quality_agent({"level": "good", "warnings": []}, report)
    assert merged["level"] == "good"             # not downgraded
    assert merged["n_uncomparable_fields"] == 1
    assert any("períodos" in w for w in merged["warnings"])
    assert not any("Discrepancia entre fuentes" in w for w in merged["warnings"])


def test_undated_value_is_never_comparable():
    """A number with no period could be TTM, a quarter or a restatement."""
    results = {
        "yfinance": {"net_income": _sv("net_income", 100.0, "yfinance")},           # no as_of
        "sec_edgar": {"net_income": _sv("net_income", 140.0, "sec_edgar", "2025-12-31")},
    }
    report = reconcile("AAA", results)
    assert report.fields[0].comparable is False
    assert report.n_conflicts == 0


def test_fiscal_calendar_slack_still_compares():
    """52/53-week calendars shift the period end by days, not quarters."""
    results = {
        "yfinance": {"total_revenue": _sv("total_revenue", 100.0, "yfinance", "2025-12-28")},
        "sec_edgar": {"total_revenue": _sv("total_revenue", 130.0, "sec_edgar", "2025-12-31")},
    }
    report = reconcile("AAA", results)
    assert report.fields[0].comparable is True
    assert report.n_conflicts == 1


def test_agreement_pct_ignores_uncomparable_fields():
    """One real match + one failed comparison must read 100%, not 50%."""
    results = {
        "yfinance": {
            "net_income": _sv("net_income", 100.0, "yfinance", "2025-12-31"),
            "total_revenue": _sv("total_revenue", 900.0, "yfinance", "2025-12-31"),
        },
        "sec_edgar": {
            "net_income": _sv("net_income", 100.5, "sec_edgar", "2025-12-31"),
            "total_revenue": _sv("total_revenue", 300.0, "sec_edgar", "2016-12-31"),
        },
    }
    report = reconcile("AAA", results)
    assert report.agreement_pct == 100.0
    assert len(report.cross_checked_fields) == 1
    assert len(report.uncomparable_fields) == 1


def test_conflict_payload_reports_only_the_compared_period():
    results = {
        "yfinance": {"net_income": _sv("net_income", 100.0, "yfinance", "2025-12-31")},
        "sec_edgar": {"net_income": _sv("net_income", 140.0, "sec_edgar", "2025-12-31")},
    }
    merged = data_quality_agent({"level": "good", "warnings": []}, reconcile("AAA", results))
    payload = merged["conflicts"][0]
    assert payload["period"] == "2025-12-31"
    assert set(payload["values"]) == {"yfinance", "sec_edgar"}


def test_quality_agent_honours_injected_config():
    """Config is injectable, so a test never depends on the live singleton."""
    from dataclasses import replace

    from config import MULTI_SOURCE

    results = {
        "yfinance": {"net_income": _sv("net_income", 100.0, "yfinance", "2025-12-31")},
        "sec_edgar": {"net_income": _sv("net_income", 140.0, "sec_edgar", "2025-12-31")},
    }
    report = reconcile("AAA", results)
    off = replace(MULTI_SOURCE, conflict_downgrades_quality=False)
    merged = data_quality_agent({"level": "good", "warnings": []}, report, config=off)
    assert merged["n_source_conflicts"] == 1     # still reported
    assert merged["level"] == "good"             # but the badge does not move


# --------------------------------------------------------------------------- #
#  SEC EDGAR extraction — offline fixtures, no network                        #
# --------------------------------------------------------------------------- #

def _usd(rows):
    return {"units": {"USD": rows}}


def _row(val, start, end, form="10-K", fp="FY"):
    return {"val": val, "start": start, "end": end, "form": form, "fp": fp}


def test_sec_rejects_quarterly_rows_inside_a_10k():
    """The KLAC case: a 10-Q half-year from 2011 was being read as 'latest annual'."""
    from data.data_sources import SecEdgarSource

    us_gaap = {
        "Revenues": _usd([
            _row(1.45e9, "2010-07-01", "2010-12-31", form="10-Q", fp="Q2"),   # 183d
            _row(0.9e9, "2011-01-01", "2011-03-31"),                          # 89d, 10-K/FY
        ])
    }
    assert SecEdgarSource._latest_annual(us_gaap, ["Revenues"]) is None


def test_sec_scans_all_tags_and_takes_the_most_recent():
    """The MA case: NetIncomeLoss died in 2013, ProfitLoss carries today's figure."""
    from data.data_sources import SecEdgarSource

    us_gaap = {
        "NetIncomeLoss": _usd([_row(3.116e9, "2013-01-01", "2013-12-31")]),
        "ProfitLoss": _usd([_row(14.97e9, "2025-01-01", "2025-12-31")]),
    }
    value, as_of = SecEdgarSource._latest_annual(us_gaap, ["NetIncomeLoss", "ProfitLoss"])
    assert value == 14.97e9
    assert as_of == "2025-12-31"


def test_sec_tag_order_is_only_the_tie_break():
    """Same period under two tags — list order decides, recency decided already."""
    from data.data_sources import SecEdgarSource

    us_gaap = {
        "NetIncomeLoss": _usd([_row(10.0, "2025-01-01", "2025-12-31")]),
        "ProfitLoss": _usd([_row(11.0, "2025-01-01", "2025-12-31")]),
    }
    value, _ = SecEdgarSource._latest_annual(us_gaap, ["NetIncomeLoss", "ProfitLoss"])
    assert value == 10.0


def test_sec_keeps_instant_facts_without_start():
    """Balance-sheet facts are instants — no duration to check."""
    from data.data_sources import SecEdgarSource

    us_gaap = {"Assets": _usd([
        {"val": 5e11, "end": "2024-12-31", "form": "10-K", "fp": "FY"},
        {"val": 6e11, "end": "2025-12-31", "form": "10-K", "fp": "FY"},
    ])}
    value, as_of = SecEdgarSource._latest_annual(us_gaap, ["Assets"])
    assert value == 6e11 and as_of == "2025-12-31"


def test_sec_53_week_year_is_accepted():
    from data.data_sources import SecEdgarSource

    us_gaap = {"Revenues": _usd([_row(50.0, "2025-01-01", "2026-01-03")])}   # 367d
    value, _ = SecEdgarSource._latest_annual(us_gaap, ["Revenues"])
    assert value == 50.0


def test_sec_ticker_map_is_downloaded_once_across_instances():
    """default_fundamental_sources() builds a fresh adapter per ticker.

    With an instance-level cache that meant re-downloading the ~1 MB ticker map
    once per ticker, six screener threads at a time.
    """
    from unittest.mock import patch

    from data.data_sources import SecEdgarSource

    SecEdgarSource._cik_map = None  # start cold
    fake_map = {"0": {"ticker": "AAPL", "cik_str": 320193}}
    try:
        with patch.object(SecEdgarSource, "_http_json", return_value=fake_map) as http:
            assert SecEdgarSource()._resolve_cik("AAPL") == 320193
            assert SecEdgarSource()._resolve_cik("AAPL") == 320193   # new instance
            assert SecEdgarSource()._resolve_cik("MSFT") is None     # absent, still no refetch
        assert http.call_count == 1
    finally:
        SecEdgarSource._cik_map = None


def test_sec_ticker_map_failure_stays_retryable():
    from unittest.mock import patch

    from data.data_sources import SecEdgarSource

    SecEdgarSource._cik_map = None
    try:
        with patch.object(SecEdgarSource, "_http_json", return_value=None):
            assert SecEdgarSource()._resolve_cik("AAPL") is None
        assert SecEdgarSource._cik_map is None      # a network blip must not be cached
    finally:
        SecEdgarSource._cik_map = None
