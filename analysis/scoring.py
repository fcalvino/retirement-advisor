"""
Enhanced scoring: Consistency Score + Piotroski F-Score.

These are additive bonuses on top of the base fundamental score (0-100):
  Consistency Score  0-15 pts  — stability of ROE and net margins over time
  Piotroski F-Score  0-9  pts  — accounting quality signal; top scores add a bonus

The adjusted_score is capped at 100.
"""

from dataclasses import dataclass, field
from typing import List, Tuple

import pandas as pd

from config import ConsistencyThresholds, PiotroskiConfig


@dataclass
class EnhancedScore:
    fundamental_score: float
    consistency_score: float        # 0–15
    piotroski_score: int            # 0–9
    piotroski_bonus: float          # bonus pts applied to adjusted_score
    adjusted_score: float           # fundamental + consistency + piotroski_bonus, capped at 100
    recommendations: List[str] = field(default_factory=list)


class EnhancedScoring:
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
    ) -> EnhancedScore:
        consistency, recs = self._consistency_score(income_stmt, balance_sheet)
        piotroski = self._piotroski_score(info, income_stmt, balance_sheet)

        if piotroski >= self.pc.strong_threshold:
            bonus = self.pc.bonus_strong
            recs.append(f"Piotroski F-Score fuerte: {piotroski}/9 (+{bonus:.0f} pts)")
        elif piotroski >= 5:
            bonus = self.pc.bonus_good
            recs.append(f"Piotroski F-Score aceptable: {piotroski}/9 (+{bonus:.0f} pts)")
        else:
            bonus = 0.0
            if piotroski > 0:
                recs.append(f"Piotroski F-Score débil: {piotroski}/9 (sin bonus)")

        adjusted = min(fundamental_score + consistency + bonus, 100.0)

        return EnhancedScore(
            fundamental_score=fundamental_score,
            consistency_score=round(consistency, 1),
            piotroski_score=piotroski,
            piotroski_bonus=bonus,
            adjusted_score=round(adjusted, 1),
            recommendations=recs,
        )

    # ------------------------------------------------------------------ #
    #  Consistency Score — 0 to 15 pts                                    #
    # ------------------------------------------------------------------ #

    def _consistency_score(self, income_stmt: pd.DataFrame, balance_sheet: pd.DataFrame = None) -> Tuple[float, List[str]]:
        """
        Measures earnings quality via two signals:
          ROE stability    (0–8 pts)  — std of actual ROE (net income / equity) when available,
                                        falls back to net income CV
          Margin stability (0–7 pts)  — std of net margin over available years
        """
        recs: List[str] = []

        if income_stmt.empty or income_stmt.shape[1] < 2:
            return 7.0, ["Datos insuficientes para calcular consistencia (neutral: 7 pts)"]

        score = 0.0

        # --- ROE stability (8 pts): prefer actual ROE from statements ---
        ni = self._extract(income_stmt, ["Net Income"])
        roe_series = None

        if balance_sheet is not None and not balance_sheet.empty:
            equity = self._extract(
                balance_sheet,
                ["Stockholders Equity", "Total Stockholder Equity", "Common Stock Equity"],
            )
            if ni is not None and equity is not None:
                # Align on common dates
                common = ni.index.intersection(equity.index)
                if len(common) >= 2:
                    roe_series = (ni[common] / equity[common].replace(0, float("nan")) * 100).dropna()

        if roe_series is not None and len(roe_series) >= 2:
            roe_std = roe_series.std()
            if roe_std <= self.ct.roe_std_max_excellent:
                score += 8
            elif roe_std <= self.ct.roe_std_max_acceptable:
                score += 5
            else:
                score += 2
                recs.append(f"ROE volátil: desviación estándar {roe_std:.1f}%")
        elif ni is not None and len(ni) >= 2:
            # Fallback: coefficient of variation of net income
            mean = ni.mean()
            cv = abs(ni.std() / mean * 100) if mean != 0 else 999
            if cv <= self.ct.roe_std_max_excellent:
                score += 8
            elif cv <= self.ct.roe_std_max_acceptable:
                score += 5
            else:
                score += 2
                recs.append(f"Alta volatilidad en utilidades netas (CV={cv:.0f}%)")
        else:
            score += 4  # neutral

        # --- Net margin stability (7 pts) ---
        revenue = self._extract(income_stmt, ["Total Revenue", "Revenue"])
        ni2 = self._extract(income_stmt, ["Net Income"])
        if revenue is not None and ni2 is not None and len(revenue) >= 2:
            margins = (ni2 / revenue * 100).dropna()
            if len(margins) >= 2:
                margin_std = margins.std()
                if margin_std <= self.ct.margin_volatility_max:
                    score += 7
                elif margin_std <= self.ct.margin_volatility_max * 2:
                    score += 4
                else:
                    score += 1
                    recs.append(f"Márgenes inestables (std={margin_std:.1f}%)")
            else:
                score += 3
        else:
            score += 3  # neutral

        return min(score, 15.0), recs

    # ------------------------------------------------------------------ #
    #  Piotroski F-Score — 0 to 9                                         #
    # ------------------------------------------------------------------ #

    def _piotroski_score(
        self,
        info: dict,
        income_stmt: pd.DataFrame,
        balance_sheet: pd.DataFrame,
    ) -> int:
        score = 0

        try:
            # === Profitability (3 pts) ===
            # F1: ROA > 0
            if (info.get("returnOnAssets") or 0) > 0:
                score += 1

            # F2: Operating cash flow > 0
            if (info.get("operatingCashflow") or 0) > 0:
                score += 1

            # F3: Net income > 0
            ni = self._extract(income_stmt, ["Net Income"])
            if ni is not None and ni.iloc[0] > 0:
                score += 1

            # === Leverage & Liquidity (3 pts) ===
            # F4: Long-term debt decreased YoY
            ltd = self._extract(balance_sheet, ["Long Term Debt", "Long-Term Debt"])
            if ltd is not None and len(ltd) >= 2 and ltd.iloc[0] < ltd.iloc[1]:
                score += 1

            # F5: Current ratio improved YoY
            cr_now = info.get("currentRatio") or 0
            if cr_now > 1.2:
                score += 1

            # F6: No new shares issued (dilution check)
            shares_now = info.get("sharesOutstanding") or 0
            shares_prev = info.get("impliedSharesOutstanding") or shares_now
            if shares_now > 0 and shares_now <= shares_prev * 1.02:  # ≤2% dilution
                score += 1

            # === Operating Efficiency (3 pts) ===
            # F7: Gross margin improved
            gm = (info.get("grossMargins") or 0) * 100
            if gm > 20:
                score += 1

            # F8: Asset turnover > 0 (proxy: revenue / total assets)
            revenue = self._extract(income_stmt, ["Total Revenue", "Revenue"])
            total_assets = self._extract(balance_sheet, ["Total Assets"])
            if revenue is not None and total_assets is not None and total_assets.iloc[0] > 0:
                asset_turnover = revenue.iloc[0] / total_assets.iloc[0]
                if asset_turnover > 0.3:
                    score += 1

            # F9: Positive operating cash flow vs net income (accruals)
            ocf = info.get("operatingCashflow") or 0
            ni_val = float(ni.iloc[0]) if ni is not None and len(ni) > 0 else 0
            if ni_val != 0 and ocf > ni_val * 0.5:
                score += 1

        except Exception:
            pass

        return min(score, 9)

    # ------------------------------------------------------------------ #
    #  Helper                                                              #
    # ------------------------------------------------------------------ #

    def _extract(self, df: pd.DataFrame, candidates: list):
        for name in candidates:
            if name in df.index:
                series = df.loc[name].dropna()
                if not series.empty:
                    series.index = pd.to_datetime(series.index)
                    return series.sort_index(ascending=False).astype(float)
        return None
