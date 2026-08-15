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
        "yfinance": {"net_income": _sv("net_income", 100.0, "yfinance")},
        "sec_edgar": {"net_income": _sv("net_income", 101.0, "sec_edgar")},  # ~1% diff
    }
    report = reconcile("AAA", results)
    fld = report.fields[0]
    assert fld.conflict is False
    assert report.n_conflicts == 0
    assert report.agreement_pct == 100.0


def test_conflict_detected_above_threshold():
    results = {
        "yfinance": {"net_income": _sv("net_income", 100.0, "yfinance")},
        "sec_edgar": {"net_income": _sv("net_income", 130.0, "sec_edgar")},  # 23% diff
    }
    report = reconcile("AAA", results)
    fld = report.fields[0]
    assert fld.conflict is True
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
    s1 = _FakeSource("yfinance", {"net_income": (200.0, None), "market_cap": (5e11, None)})
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
        "yfinance": {"net_income": _sv("net_income", 100.0, "yfinance")},
        "sec_edgar": {"net_income": _sv("net_income", 140.0, "sec_edgar")},
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
        "yfinance": {"net_income": _sv("net_income", 100.0, "yfinance")},
        "sec_edgar": {"net_income": _sv("net_income", 100.5, "sec_edgar")},
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
    s1 = _FakeSource("yfinance", {"net_income": (100.0, None)})
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
        "yfinance": {"net_income": _sv("net_income", 100.0, "yfinance")},
        "sec_edgar": {"net_income": _sv("net_income", 100.5, "sec_edgar")},
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


def test_yfinance_source_maps_equity_and_assets():
    from unittest.mock import patch

    from data.data_sources import YFinanceSource

    fake_info = {
        "totalRevenue": 100.0,
        "netIncomeToCommon": 10.0,
        "sharesOutstanding": 1e9,
        "currentPrice": 50.0,
        "marketCap": 5e10,
        "totalStockholderEquity": 2e10,
        "totalAssets": 5e10,
    }
    with patch("data.fetcher.get_info", return_value=fake_info):
        out = YFinanceSource().fetch_fundamentals("AAPL")
    assert "total_equity" in out and out["total_equity"].value == 2e10
    assert "total_assets" in out and out["total_assets"].value == 5e10
    assert "total_revenue" in out
