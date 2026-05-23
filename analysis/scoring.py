"""
Enhanced scoring — Phase 1.5

Consistency Score (0–15 pts): stability of ROE, EPS and net margins over 4+ years.
Piotroski F-Score (0–9 pts): true year-over-year accounting quality checks.

Both are additive bonuses on top of the base fundamental score.
adjusted_score = min(fundamental + consistency + piotroski_bonus, 100).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from config import ConsistencyThresholds, PiotroskiConfig


@dataclass
class ConsistencyDetail:
    roe_score: float        # 0–5
    eps_score: float        # 0–5
    margin_score: float     # 0–5
    total: float            # 0–15
    notes: List[str] = field(default_factory=list)


@dataclass
class PiotroskiDetail:
    # Profitability
    f1_roa_positive: bool = False
    f2_ocf_positive: bool = False
    f3_roa_improving: bool = False
    # Leverage & Liquidity
    f4_leverage_decreasing: bool = False
    f5_liquidity_improving: bool = False
    f6_no_dilution: bool = False
    # Operating Efficiency
    f7_gross_margin_improving: bool = False
    f8_asset_turnover_improving: bool = False
    f9_accruals_quality: bool = False

    @property
    def score(self) -> int:
        return sum([
            self.f1_roa_positive, self.f2_ocf_positive, self.f3_roa_improving,
            self.f4_leverage_decreasing, self.f5_liquidity_improving, self.f6_no_dilution,
            self.f7_gross_margin_improving, self.f8_asset_turnover_improving, self.f9_accruals_quality,
        ])

    def summary(self) -> str:
        checks = {
            "F1 ROA>0": self.f1_roa_positive,
            "F2 OCF>0": self.f2_ocf_positive,
            "F3 ROA↑": self.f3_roa_improving,
            "F4 Deuda↓": self.f4_leverage_decreasing,
            "F5 Liquidez↑": self.f5_liquidity_improving,
            "F6 Sin dilución": self.f6_no_dilution,
            "F7 Margen↑": self.f7_gross_margin_improving,
            "F8 Activos↑": self.f8_asset_turnover_improving,
            "F9 Accruals": self.f9_accruals_quality,
        }
        passed = [k for k, v in checks.items() if v]
        failed = [k for k, v in checks.items() if not v]
        return f"✅ {', '.join(passed)} | ❌ {', '.join(failed)}"


@dataclass
class EnhancedScore:
    fundamental_score: float
    consistency_score: float = 0.0      # 0–15
    consistency_detail: ConsistencyDetail = field(default_factory=lambda: ConsistencyDetail(0, 0, 0, 0))
    piotroski_score: int = 0            # 0–9
    piotroski_detail: PiotroskiDetail = field(default_factory=PiotroskiDetail)
    piotroski_bonus: float = 0.0
    adjusted_score: float = 0.0        # capped at 100
    recommendations: List[str] = field(default_factory=list)


class EnhancedScoring:
    """
    Computes Consistency Score and Piotroski F-Score from yfinance financial statements.
    Designed to be robust against missing/partial data — always returns a valid score.
    """

    def __init__(
        self,
        consistency_thresholds: ConsistencyThresholds = None,
        piotroski_config: PiotroskiConfig = None,
    ):
        self.ct = consistency_thresholds or ConsistencyThresholds()
        self.pc = piotroski_config or PiotroskiConfig()

    def get_enhanced_score(
        self,
        fundamental_score: float,
        info: dict,
        income_stmt: pd.DataFrame,
        balance_sheet: pd.DataFrame,
        cashflow: pd.DataFrame = None,
    ) -> EnhancedScore:
        result = EnhancedScore(fundamental_score=fundamental_score)
        recs: List[str] = []

        # --- Consistency ---
        c_detail = self._consistency_score(income_stmt, balance_sheet)
        result.consistency_score = round(c_detail.total, 1)
        result.consistency_detail = c_detail
        recs.extend(c_detail.notes)

        # --- Piotroski ---
        p_detail = self._piotroski_score(info, income_stmt, balance_sheet, cashflow)
        result.piotroski_score = p_detail.score
        result.piotroski_detail = p_detail

        if p_detail.score >= self.pc.strong_threshold:
            result.piotroski_bonus = self.pc.bonus_strong
            recs.append(f"Piotroski fuerte {p_detail.score}/9 (+{self.pc.bonus_strong:.0f} pts) — {p_detail.summary()}")
        elif p_detail.score >= 5:
            result.piotroski_bonus = self.pc.bonus_good
            recs.append(f"Piotroski aceptable {p_detail.score}/9 (+{self.pc.bonus_good:.0f} pts) — {p_detail.summary()}")
        else:
            result.piotroski_bonus = 0.0
            recs.append(f"Piotroski débil {p_detail.score}/9 — {p_detail.summary()}")

        result.adjusted_score = round(
            min(fundamental_score + result.consistency_score + result.piotroski_bonus, 100.0), 1
        )
        result.recommendations = recs
        return result

    # ------------------------------------------------------------------ #
    #  Consistency Score — 0 to 15 pts (3 signals × 5 pts each)           #
    # ------------------------------------------------------------------ #

    def _consistency_score(
        self,
        income_stmt: pd.DataFrame,
        balance_sheet: pd.DataFrame,
    ) -> ConsistencyDetail:
        """
        Three signals, 5 pts each:
          ROE stability   — actual ROE (NI/Equity) std over available years
          EPS stability   — growth rate CV of net income (EPS proxy)
          Margin stability — net margin std over available years
        """
        roe_score = self._roe_stability(income_stmt, balance_sheet)
        eps_score = self._eps_stability(income_stmt)
        margin_score = self._margin_stability(income_stmt)
        total = min(roe_score + eps_score + margin_score, 15.0)

        notes: List[str] = []
        if roe_score < 3:
            notes.append("ROE inconsistente entre años")
        if eps_score < 3:
            notes.append("Crecimiento de utilidades volátil")
        if margin_score < 3:
            notes.append("Márgenes netos inestables")

        return ConsistencyDetail(
            roe_score=round(roe_score, 1),
            eps_score=round(eps_score, 1),
            margin_score=round(margin_score, 1),
            total=round(total, 1),
            notes=notes,
        )

    def _roe_stability(self, income_stmt: pd.DataFrame, balance_sheet: pd.DataFrame) -> float:
        """ROE = Net Income / Stockholders Equity. Scores stability (std) over years."""
        ni = self._extract(income_stmt, ["Net Income"])
        equity = self._extract(
            balance_sheet,
            ["Stockholders Equity", "Total Stockholder Equity", "Common Stock Equity"],
        )
        if ni is None or equity is None:
            return 2.5  # neutral

        common = ni.index.intersection(equity.index)
        if len(common) < 2:
            return 2.5

        eq_clean = equity[common].replace(0, np.nan)
        roe = (ni[common] / eq_clean * 100).dropna()
        if len(roe) < 2:
            return 2.5

        std = roe.std()
        if std <= self.ct.roe_std_max_excellent:
            return 5.0
        elif std <= self.ct.roe_std_max_acceptable:
            return 3.0
        elif std <= self.ct.roe_std_max_acceptable * 2:
            return 1.5
        return 0.5

    def _eps_stability(self, income_stmt: pd.DataFrame) -> float:
        """Stability of net income growth rates (EPS proxy). CV of YoY growth."""
        ni = self._extract(income_stmt, ["Net Income"])
        if ni is None or len(ni) < 3:
            return 2.5  # neutral — need at least 3 years for 2 growth rates

        ni_sorted = ni.sort_index()  # ascending for pct_change
        growth = ni_sorted.pct_change().dropna()
        if len(growth) < 2:
            return 2.5

        # Remove outliers (> 500% change) that skew std
        growth = growth[growth.abs() <= 5.0]
        if len(growth) < 2:
            return 2.5

        cv = growth.std() / (growth.abs().mean() + 1e-9)

        if cv <= 0.3:    # very stable growth
            return 5.0
        elif cv <= 0.6:
            return 3.5
        elif cv <= 1.0:
            return 2.0
        elif cv <= 2.0:
            return 1.0
        return 0.0

    def _margin_stability(self, income_stmt: pd.DataFrame) -> float:
        """Net margin = Net Income / Revenue. Scores std of margin over years."""
        ni = self._extract(income_stmt, ["Net Income"])
        rev = self._extract(income_stmt, ["Total Revenue", "Revenue"])
        if ni is None or rev is None:
            return 2.5

        common = ni.index.intersection(rev.index)
        if len(common) < 2:
            return 2.5

        rev_clean = rev[common].replace(0, np.nan)
        margins = (ni[common] / rev_clean * 100).dropna()
        if len(margins) < 2:
            return 2.5

        std = margins.std()
        if std <= self.ct.margin_volatility_max:
            return 5.0
        elif std <= self.ct.margin_volatility_max * 2:
            return 3.0
        elif std <= self.ct.margin_volatility_max * 3:
            return 1.5
        return 0.5

    # ------------------------------------------------------------------ #
    #  Piotroski F-Score — 0 to 9, true YoY comparisons                   #
    # ------------------------------------------------------------------ #

    def _piotroski_score(
        self,
        info: dict,
        income_stmt: pd.DataFrame,
        balance_sheet: pd.DataFrame,
        cashflow: pd.DataFrame = None,
    ) -> PiotroskiDetail:
        d = PiotroskiDetail()

        # Pre-extract series once (descending: iloc[0]=current, iloc[1]=prior year)
        ni = self._extract(income_stmt, ["Net Income"])
        rev = self._extract(income_stmt, ["Total Revenue", "Revenue"])
        gross_profit = self._extract(income_stmt, ["Gross Profit"])
        total_assets = self._extract(balance_sheet, ["Total Assets"])
        ltd = self._extract(balance_sheet, ["Long Term Debt", "Long-Term Debt"])
        current_assets = self._extract(balance_sheet, ["Current Assets"])
        current_liab = self._extract(balance_sheet, ["Current Liabilities"])
        shares = self._extract(balance_sheet, ["Ordinary Shares Number", "Share Issued", "Common Stock"])
        ocf = self._extract(cashflow, ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"]) if cashflow is not None and not cashflow.empty else None

        # === F1: ROA > 0 (current year) ===
        d.f1_roa_positive = self._safe(lambda: (
            ni is not None and total_assets is not None
            and len(ni) >= 1 and total_assets.iloc[0] > 0
            and ni.iloc[0] / total_assets.iloc[0] > 0
        ))

        # === F2: Operating Cash Flow > 0 ===
        if ocf is not None and len(ocf) >= 1:
            d.f2_ocf_positive = self._safe(lambda: float(ocf.iloc[0]) > 0)
        else:
            d.f2_ocf_positive = self._safe(lambda: (info.get("operatingCashflow") or 0) > 0)

        # === F3: ROA improved YoY ===
        d.f3_roa_improving = self._safe(lambda: (
            ni is not None and total_assets is not None
            and len(ni) >= 2 and len(total_assets) >= 2
            and total_assets.iloc[0] > 0 and total_assets.iloc[1] > 0
            and (ni.iloc[0] / total_assets.iloc[0]) > (ni.iloc[1] / total_assets.iloc[1])
        ))

        # === F4: Leverage (LTD/TotalAssets) decreased YoY ===
        d.f4_leverage_decreasing = self._safe(lambda: (
            ltd is not None and total_assets is not None
            and len(ltd) >= 2 and len(total_assets) >= 2
            and total_assets.iloc[0] > 0 and total_assets.iloc[1] > 0
            and (ltd.iloc[0] / total_assets.iloc[0]) < (ltd.iloc[1] / total_assets.iloc[1])
        ))

        # === F5: Current Ratio improved YoY ===
        d.f5_liquidity_improving = self._safe(lambda: (
            current_assets is not None and current_liab is not None
            and len(current_assets) >= 2 and len(current_liab) >= 2
            and current_liab.iloc[0] > 0 and current_liab.iloc[1] > 0
            and (current_assets.iloc[0] / current_liab.iloc[0]) > (current_assets.iloc[1] / current_liab.iloc[1])
        ))

        # === F6: No new shares issued (≤2% dilution YoY) ===
        d.f6_no_dilution = self._safe(lambda: (
            shares is not None and len(shares) >= 2
            and shares.iloc[1] > 0
            and shares.iloc[0] <= shares.iloc[1] * 1.02
        ))

        # === F7: Gross Margin improved YoY ===
        d.f7_gross_margin_improving = self._safe(lambda: (
            gross_profit is not None and rev is not None
            and len(gross_profit) >= 2 and len(rev) >= 2
            and rev.iloc[0] > 0 and rev.iloc[1] > 0
            and (gross_profit.iloc[0] / rev.iloc[0]) > (gross_profit.iloc[1] / rev.iloc[1])
        ))

        # === F8: Asset Turnover improved YoY ===
        d.f8_asset_turnover_improving = self._safe(lambda: (
            rev is not None and total_assets is not None
            and len(rev) >= 2 and len(total_assets) >= 2
            and total_assets.iloc[0] > 0 and total_assets.iloc[1] > 0
            and (rev.iloc[0] / total_assets.iloc[0]) > (rev.iloc[1] / total_assets.iloc[1])
        ))

        # === F9: OCF > Net Income (accruals quality — cash earnings beat accounting earnings) ===
        if ocf is not None and len(ocf) >= 1 and ni is not None and len(ni) >= 1:
            d.f9_accruals_quality = self._safe(lambda: float(ocf.iloc[0]) > float(ni.iloc[0]))
        else:
            ocf_info = info.get("operatingCashflow") or 0
            ni_val = float(ni.iloc[0]) if ni is not None and len(ni) >= 1 else 0
            d.f9_accruals_quality = self._safe(lambda: ocf_info > ni_val)

        return d

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _extract(self, df: pd.DataFrame, candidates: List[str]) -> Optional[pd.Series]:
        """Return a float Series sorted descending (current year first), or None."""
        if df is None or df.empty:
            return None
        for name in candidates:
            if name in df.index:
                series = df.loc[name].dropna()
                if not series.empty:
                    series.index = pd.to_datetime(series.index)
                    return series.sort_index(ascending=False).astype(float)
        return None

    @staticmethod
    def _safe(fn, default: bool = False) -> bool:
        """Evaluate a boolean lambda, returning default on any exception."""
        try:
            return bool(fn())
        except Exception:
            return default
