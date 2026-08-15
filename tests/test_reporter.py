"""Tests for alerts/reporter.py (audit D4).

The monthly PDF is generated unattended by the scheduler and emailed out. With
no coverage, a malformed ticker dict from the screener would raise inside a cron
job — the user simply stops receiving reports and nothing says why.

These tests build real PDFs into a temp directory. They assert the document is
produced and well-formed, and that the legally required disclaimer is present;
they do not assert on visual layout.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from reportlab.platypus import Paragraph, Table

import alerts.reporter as reporter_mod
from alerts.reporter import ReportGenerator, _score_color, _signal_color

TICKERS = [
    {"symbol": "AAPL", "company_name": "Apple Inc.", "adjusted_score": 82.0,
     "total_score": 74.0, "moat_bonus": 8.0, "signal": "STRONG_BUY",
     "dividend_yield": 0.5, "moat_classification": "Wide", "sector": "Technology"},
    {"symbol": "KO", "company_name": "Coca-Cola", "adjusted_score": 63.0,
     "total_score": 58.0, "moat_bonus": 5.0, "signal": "BUY",
     "dividend_yield": 3.1, "moat_classification": "Wide", "sector": "Consumer Staples"},
    {"symbol": "T", "company_name": "AT&T", "adjusted_score": 38.0,
     "total_score": 38.0, "moat_bonus": 0.0, "signal": "SELL",
     "dividend_yield": 6.4, "moat_classification": "None", "sector": "Communication"},
]

POSITIONS = [
    {"symbol": "AAPL", "quantity": 10, "avg_price": 150.0, "current_price": 200.0},
    {"symbol": "KO", "quantity": 100, "avg_price": 55.0, "current_price": 60.0},
]


@pytest.fixture
def generator(tmp_path, monkeypatch):
    """A ReportGenerator writing into a temp dir instead of ./reports."""
    monkeypatch.setattr(reporter_mod.REPORT, "output_dir", str(tmp_path))
    return ReportGenerator()


# ------------------------------------------------------------------ #
#  Colour helpers                                                      #
# ------------------------------------------------------------------ #

class TestColourCoding:
    @pytest.mark.parametrize("score", [75.0, 90.0, 100.0])
    def test_high_scores_are_green(self, score):
        assert _score_color(score) == reporter_mod._GREEN

    @pytest.mark.parametrize("score", [55.0, 60.0, 74.9])
    def test_mid_scores_are_amber(self, score):
        assert _score_color(score) == reporter_mod._AMBER

    @pytest.mark.parametrize("score", [0.0, 30.0, 54.9])
    def test_low_scores_are_red(self, score):
        assert _score_color(score) == reporter_mod._RED

    def test_strong_buy_and_sell_are_visually_distinct(self):
        assert _signal_color("STRONG_BUY") != _signal_color("SELL")
        assert _signal_color("SELL") == reporter_mod._RED

    def test_signal_matching_is_case_insensitive(self):
        assert _signal_color("strong buy") == _signal_color("STRONG_BUY")

    def test_hold_is_amber(self):
        assert _signal_color("HOLD") == reporter_mod._AMBER


# ------------------------------------------------------------------ #
#  Document generation                                                 #
# ------------------------------------------------------------------ #

class TestGenerate:
    def test_produces_a_real_pdf(self, generator):
        path = Path(generator.generate(TICKERS))
        assert path.exists()
        assert path.stat().st_size > 1_000
        assert path.read_bytes().startswith(b"%PDF")

    def test_filename_carries_the_year_and_month(self, generator):
        from datetime import datetime
        path = Path(generator.generate(TICKERS))
        assert datetime.now().strftime("%Y-%m") in path.name

    def test_includes_the_portfolio_section_when_positions_are_given(self, generator):
        with_pos = Path(generator.generate(TICKERS, POSITIONS)).stat().st_size
        without = Path(generator.generate(TICKERS)).stat().st_size
        assert with_pos > without

    def test_an_explicit_period_label_is_used(self, generator):
        assert Path(generator.generate(TICKERS, period="Agosto 2026")).exists()

    def test_empty_universe_still_produces_a_document(self, generator):
        """A screener that returned nothing must not break the cron job."""
        path = Path(generator.generate([]))
        assert path.exists() and path.read_bytes().startswith(b"%PDF")

    def test_missing_optional_fields_do_not_raise(self, generator):
        sparse = [{"symbol": "XYZ", "adjusted_score": 50.0}]
        assert Path(generator.generate(sparse)).exists()

    def test_none_dividend_yield_is_tolerated(self, generator):
        """yfinance returns None here often enough that it must not crash."""
        rows = [{**TICKERS[0], "dividend_yield": None}]
        assert Path(generator.generate(rows)).exists()

    def test_output_directory_is_created_if_absent(self, tmp_path, monkeypatch):
        target = tmp_path / "nested" / "reports"
        monkeypatch.setattr(reporter_mod.REPORT, "output_dir", str(target))
        ReportGenerator()
        assert target.is_dir()


# ------------------------------------------------------------------ #
#  Section content                                                     #
# ------------------------------------------------------------------ #

def _text_of(elements) -> str:
    return " ".join(
        e.text for e in elements if isinstance(e, Paragraph) and hasattr(e, "text")
    )


class TestSections:
    def test_leaderboard_is_sorted_by_score_descending(self, generator):
        elements = generator._section_score_leaderboard(reporter_mod._styles(), TICKERS)
        table = next(e for e in elements if isinstance(e, Table))
        symbols = [row[1] for row in table._cellvalues[1:]]
        assert symbols == ["AAPL", "KO", "T"]

    def test_buy_section_lists_only_buys(self, generator):
        text = _text_of(generator._section_opportunities(reporter_mod._styles(), TICKERS))
        assert "AAPL" in text and "KO" in text
        assert "AT&T" not in text

    def test_buy_section_is_omitted_when_there_are_no_buys(self, generator):
        only_sells = [t for t in TICKERS if t["signal"] == "SELL"]
        assert generator._section_opportunities(reporter_mod._styles(), only_sells) == []

    def test_risk_section_lists_only_sells(self, generator):
        text = _text_of(generator._section_risk_alerts(reporter_mod._styles(), TICKERS))
        assert "AT&T" in text
        assert "Apple" not in text

    def test_risk_section_is_omitted_when_there_are_no_sells(self, generator):
        no_sells = [t for t in TICKERS if t["signal"] != "SELL"]
        assert generator._section_risk_alerts(reporter_mod._styles(), no_sells) == []

    def test_portfolio_table_computes_pnl_percent(self, generator):
        elements = generator._section_portfolio(reporter_mod._styles(), POSITIONS, TICKERS)
        table = next(e for e in elements if isinstance(e, Table))
        pnl_column = [row[4] for row in table._cellvalues[1:]]
        assert pnl_column[0] == "+33.3%"        # 150 → 200
        assert pnl_column[1] == "+9.1%"         # 55 → 60

    def test_portfolio_table_survives_a_zero_cost_basis(self, generator):
        rows = [{"symbol": "GIFT", "quantity": 5, "avg_price": 0.0, "current_price": 30.0}]
        elements = generator._section_portfolio(reporter_mod._styles(), rows, TICKERS)
        table = next(e for e in elements if isinstance(e, Table))
        assert table._cellvalues[1][4] == "+0.0%"      # no division by zero

    def test_disclaimer_is_always_present(self, generator):
        """Legally required — this section must never become conditional."""
        text = _text_of(generator._section_disclaimer(reporter_mod._styles()))
        assert "no constituye asesoramiento financiero" in text.lower()
        assert "rendimientos pasados" in text.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
