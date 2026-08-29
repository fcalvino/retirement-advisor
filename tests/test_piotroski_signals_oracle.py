"""Two Piotroski signals that answer the wrong question (backlog U5-2, U5-3).

Both are **latent** on today's data, and both are cheap to close before they are
not. Measured over the 150 cached balance sheets: neither fires. Nothing about a
score moves here.

**U5-2 — a debt-free company fails the leverage check.** F4 asks whether the
long-term-debt ratio *decreased*, with a strict ``<``. A company carrying no
long-term debt in either year gives ``0 < 0 = False`` and loses the point. It
cannot reduce what it does not have, and zero leverage is not a failure to
improve — it is the terminal best state of the thing being measured. Piotroski's
original F_LEVER is strict, and strictness is right everywhere else: a company
holding leverage flat at 30 % genuinely did not improve. Only the zero case is
degenerate, so only the zero case is exempted.

**U5-3 — the dilution check could compare dollars.** F6 asks whether the share
count grew, and reads ``["Ordinary Shares Number", "Share Issued", "Common
Stock"]``. The third is a **currency amount**, not a count. Proof from the cache:

    AAPL   shares 14,773,260,000   Common Stock 93,568,000,000   ratio 6.33
    KO     shares  4,301,608,845   Common Stock  1,760,000,000   ratio 0.41

Different magnitudes, and in opposite directions — so the fallback would not even
fail consistently. It never fires today because ``Ordinary Shares Number`` is
present in **150 of 150** balance sheets, which is exactly what makes it worth
removing now rather than discovering later.

The ±2 % dilution tolerance was a literal in the middle of the check; it moves to
config with the other Piotroski thresholds.

No network.
"""

from __future__ import annotations

import pandas as pd
import pytest

from analysis.scoring import EnhancedScoring
from config import PIOTROSKI

COLS = ["2025-12-31", "2024-12-31"]


def _balance(**rows) -> pd.DataFrame:
    return pd.DataFrame(rows, index=COLS).T


def _detail(balance_sheet: pd.DataFrame, income=None, cashflow=None):
    return EnhancedScoring()._piotroski_score(
        {}, income if income is not None else pd.DataFrame(),
        balance_sheet, cashflow if cashflow is not None else pd.DataFrame(),
    )


class TestLeverageF4:
    def test_a_debt_free_company_is_not_penalised(self):
        """0 < 0 is False, and losing a point for it is the defect."""
        d = _detail(_balance(**{
            "Long Term Debt": [0.0, 0.0],
            "Total Assets": [1000.0, 900.0],
        }))
        assert d.f4_leverage_decreasing is True

    def test_reducing_leverage_still_passes(self):
        d = _detail(_balance(**{
            "Long Term Debt": [100.0, 200.0],
            "Total Assets": [1000.0, 1000.0],
        }))
        assert d.f4_leverage_decreasing is True

    def test_flat_leverage_still_fails(self):
        """Anti-cheat: strictness is right everywhere except zero.

        A company holding debt steady at 20 % of assets genuinely did not
        improve, which is what Piotroski's F_LEVER asks.
        """
        d = _detail(_balance(**{
            "Long Term Debt": [200.0, 200.0],
            "Total Assets": [1000.0, 1000.0],
        }))
        assert d.f4_leverage_decreasing is False

    def test_rising_leverage_still_fails(self):
        d = _detail(_balance(**{
            "Long Term Debt": [300.0, 200.0],
            "Total Assets": [1000.0, 1000.0],
        }))
        assert d.f4_leverage_decreasing is False

    def test_taking_on_debt_from_zero_fails(self):
        """Only *staying* debt-free is exempt, not leaving that state."""
        d = _detail(_balance(**{
            "Long Term Debt": [100.0, 0.0],
            "Total Assets": [1000.0, 1000.0],
        }))
        assert d.f4_leverage_decreasing is False


class TestDilutionF6:
    def test_a_currency_amount_is_never_used_as_a_share_count(self):
        """Only ``Common Stock`` is present: no count, so no answer.

        The amounts are chosen so the dollar comparison would **pass** — par value
        fell, which says nothing about dilution. A test whose numbers happened to
        fail either way would not detect the fallback at all.
        """
        d = _detail(_balance(**{"Common Stock": [90_000.0, 93_568.0]}))
        assert d.f6_no_dilution is False

    def test_a_real_share_count_still_works(self):
        d = _detail(_balance(**{"Ordinary Shares Number": [1_000.0, 1_000.0]}))
        assert d.f6_no_dilution is True

    def test_share_issued_remains_a_valid_source(self):
        d = _detail(_balance(**{"Share Issued": [990.0, 1_000.0]}))
        assert d.f6_no_dilution is True

    def test_dilution_beyond_the_tolerance_fails(self):
        over = 1_000.0 * (1 + PIOTROSKI.max_dilution_pct / 100.0) + 1
        d = _detail(_balance(**{"Ordinary Shares Number": [over, 1_000.0]}))
        assert d.f6_no_dilution is False

    def test_dilution_within_the_tolerance_passes(self):
        under = 1_000.0 * (1 + PIOTROSKI.max_dilution_pct / 100.0) - 1
        d = _detail(_balance(**{"Ordinary Shares Number": [under, 1_000.0]}))
        assert d.f6_no_dilution is True

    def test_the_tolerance_is_config_driven(self):
        from pathlib import Path

        src = (Path(__file__).resolve().parents[1] / "analysis" /
               "scoring.py").read_text(encoding="utf-8")
        body = src.split("=== F6")[1].split("=== F7")[0]
        assert "1.02" not in body
        assert "max_dilution_pct" in body


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
