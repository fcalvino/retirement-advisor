"""
Fundamental analysis module.

Scoring model (0–100):
  Profitability     25 pts  — ROE, ROIC, net margin, gross margin
  Financial Health  20 pts  — D/E, current ratio, interest coverage
  Valuation         25 pts  — P/E, PEG, EV/EBITDA, P/B
  Growth            20 pts  — revenue CAGR, EPS CAGR, FCF growth
  Dividend Quality  10 pts  — yield, payout ratio, growth streak
"""

from dataclasses import dataclass, field
from typing import Dict, Optional

import numpy as np
import pandas as pd
from loguru import logger

from config import THRESHOLDS as T
from data.fetcher import (
    _safe_float,
    compute_cagr,
    get_dividends,
    get_financials,
    get_info,
)


@dataclass
class FundamentalResult:
    symbol: str
    company_name: str = ""
    sector: str = ""
    industry: str = ""
    market_cap: float = 0.0
    current_price: float = 0.0

    # Sub-scores (0–max_pts each)
    profitability_score: float = 0.0   # /25
    health_score: float = 0.0          # /20
    valuation_score: float = 0.0       # /25
    growth_score: float = 0.0          # /20
    dividend_score: float = 0.0        # /10
    total_score: float = 0.0           # /100

    # Key metrics (for display)
    roe: Optional[float] = None
    roic: Optional[float] = None
    net_margin: Optional[float] = None
    gross_margin: Optional[float] = None
    debt_equity: Optional[float] = None
    current_ratio: Optional[float] = None
    interest_coverage: Optional[float] = None
    pe_ratio: Optional[float] = None
    peg_ratio: Optional[float] = None
    ev_ebitda: Optional[float] = None
    pb_ratio: Optional[float] = None
    revenue_cagr_5y: Optional[float] = None
    eps_cagr_5y: Optional[float] = None
    fcf_yield: Optional[float] = None
    dividend_yield: Optional[float] = None
    payout_ratio: Optional[float] = None

    # Intrinsic value estimate (Graham formula)
    graham_value: Optional[float] = None
    margin_of_safety_pct: Optional[float] = None

    # Human-readable breakdown
    notes: Dict[str, str] = field(default_factory=dict)
    warnings: list = field(default_factory=list)

    def is_value_stock(self) -> bool:
        return (
            self.margin_of_safety_pct is not None
            and self.margin_of_safety_pct >= 10.0
        )


class FundamentalAnalyzer:
    """
    Analyze a stock's fundamentals and return a FundamentalResult with
    a weighted 0–100 score. All data sourced from yfinance.
    """

    def analyze(self, symbol: str) -> FundamentalResult:
        symbol = symbol.upper()
        result = FundamentalResult(symbol=symbol)

        info = get_info(symbol)
        if not info:
            result.warnings.append("No data available from yfinance.")
            return result

        financials = get_financials(symbol)
        income_stmt = financials.get("income_stmt", pd.DataFrame())
        balance_sheet = financials.get("balance_sheet", pd.DataFrame())
        cashflow = financials.get("cashflow", pd.DataFrame())

        # Basic info
        result.company_name = info.get("longName", symbol)
        from config import SECTOR_MAP
        _etf_tickers = set(SECTOR_MAP.get("ETF", []))
        raw_sector = info.get("sector", "")
        result.sector = raw_sector if raw_sector else ("Index" if symbol in _etf_tickers else "Unknown")
        result.industry = info.get("industry", "") or ("Index" if symbol in _etf_tickers else "Unknown")
        result.market_cap = _safe_float(info.get("marketCap"))
        result.current_price = _safe_float(
            info.get("currentPrice") or info.get("regularMarketPrice")
        )

        # Run each scoring dimension
        result.profitability_score = self._score_profitability(info, income_stmt, balance_sheet, result)
        result.health_score = self._score_financial_health(info, balance_sheet, income_stmt, result)
        result.valuation_score = self._score_valuation(info, result)
        result.growth_score = self._score_growth(info, income_stmt, cashflow, result)
        result.dividend_score = self._score_dividends(info, result)

        result.total_score = (
            result.profitability_score
            + result.health_score
            + result.valuation_score
            + result.growth_score
            + result.dividend_score
        )

        # Graham intrinsic value: V = EPS × (8.5 + 2g) × 4.4 / Y
        # where g = expected growth %, Y = current AAA bond yield (proxy 4.5%)
        eps = _safe_float(info.get("trailingEps"))
        growth_estimate = _safe_float(info.get("earningsGrowth", 0)) * 100
        if eps > 0 and growth_estimate > 0:
            graham = eps * (8.5 + 2 * growth_estimate) * 4.4 / 4.5
            result.graham_value = round(graham, 2)
            if result.current_price > 0:
                mos = (graham - result.current_price) / graham * 100
                result.margin_of_safety_pct = round(mos, 1)

        logger.info(f"{symbol}: total score = {result.total_score:.1f}/100")
        return result

    # ------------------------------------------------------------------ #
    #  Profitability — 25 pts                                              #
    # ------------------------------------------------------------------ #

    def _score_profitability(
        self,
        info: dict,
        income_stmt: pd.DataFrame,
        balance_sheet: pd.DataFrame,
        result: FundamentalResult,
    ) -> float:
        score = 0.0

        # ROE (8 pts)
        roe = _safe_float(info.get("returnOnEquity")) * 100
        result.roe = roe if roe != 0 else None
        if roe >= T.roe_excellent:
            score += 8
            result.notes["roe"] = f"Excellent ROE {roe:.1f}%"
        elif roe >= T.roe_good:
            score += 5
            result.notes["roe"] = f"Good ROE {roe:.1f}%"
        elif roe >= T.roe_min:
            score += 2
            result.notes["roe"] = f"Acceptable ROE {roe:.1f}%"
        else:
            result.warnings.append(f"Low ROE: {roe:.1f}%")

        # ROIC (7 pts) — approximated if not directly available
        roic_raw = _safe_float(info.get("returnOnAssets")) * 100
        # Improve with ROIC proxy = NOPAT / Invested Capital
        roic = self._compute_roic(income_stmt, balance_sheet) or roic_raw
        result.roic = roic if roic != 0 else None
        if roic >= T.roic_excellent:
            score += 7
            result.notes["roic"] = f"Excellent ROIC {roic:.1f}%"
        elif roic >= T.roic_good:
            score += 4
            result.notes["roic"] = f"Good ROIC {roic:.1f}%"
        elif roic >= T.roic_min:
            score += 2
            result.notes["roic"] = f"Acceptable ROIC {roic:.1f}%"

        # Net Margin (5 pts)
        nm = _safe_float(info.get("profitMargins")) * 100
        result.net_margin = nm if nm != 0 else None
        if nm >= T.net_margin_excellent:
            score += 5
        elif nm >= T.net_margin_good:
            score += 3
        elif nm >= T.net_margin_min:
            score += 1
        else:
            result.warnings.append(f"Thin net margin: {nm:.1f}%")

        # Gross Margin (5 pts)
        gm = _safe_float(info.get("grossMargins")) * 100
        result.gross_margin = gm if gm != 0 else None
        if gm >= T.gross_margin_excellent:
            score += 5
        elif gm >= T.gross_margin_good:
            score += 3
        elif gm > 0:
            score += 1

        return min(score, 25.0)

    def _compute_roic(self, income_stmt: pd.DataFrame, balance_sheet: pd.DataFrame) -> Optional[float]:
        """ROIC = NOPAT / (Total Equity + Long-term Debt). Returns %."""
        try:
            if income_stmt.empty or balance_sheet.empty:
                return None
            ebit = self._row(income_stmt, ["EBIT", "Operating Income"])
            tax_rate = 0.21  # US corporate tax rate
            nopat = ebit * (1 - tax_rate)

            equity = self._row(balance_sheet, ["Stockholders Equity", "Total Stockholder Equity", "Common Stock Equity"])
            ltd = self._row(balance_sheet, ["Long Term Debt", "Long-Term Debt"])
            invested_capital = equity + ltd
            if invested_capital <= 0:
                return None
            return float(nopat / invested_capital * 100)
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    #  Financial Health — 20 pts                                           #
    # ------------------------------------------------------------------ #

    def _score_financial_health(
        self,
        info: dict,
        balance_sheet: pd.DataFrame,
        income_stmt: pd.DataFrame,
        result: FundamentalResult,
    ) -> float:
        score = 0.0

        # Debt/Equity (7 pts)
        de = _safe_float(info.get("debtToEquity"))
        if de > 0:
            de = de / 100  # yfinance returns it *100 (e.g., 45 means 0.45)
        result.debt_equity = de if de != 0 else None
        if de <= T.max_debt_equity_excellent:
            score += 7
            result.notes["debt_equity"] = f"Very low debt D/E={de:.2f}"
        elif de <= T.max_debt_equity_good:
            score += 5
        elif de <= T.max_debt_equity_acceptable:
            score += 2
        else:
            result.warnings.append(f"High leverage D/E={de:.2f}")

        # Current Ratio (5 pts)
        cr = _safe_float(info.get("currentRatio"))
        result.current_ratio = cr if cr != 0 else None
        if cr >= T.min_current_ratio_good:
            score += 5
        elif cr >= T.min_current_ratio_ok:
            score += 3
        elif cr > 0:
            score += 1
            result.warnings.append(f"Current ratio low: {cr:.2f}")

        # Interest Coverage (5 pts) — EBIT / Interest Expense
        ic = self._compute_interest_coverage(income_stmt)
        result.interest_coverage = ic
        if ic is not None:
            if ic >= T.min_interest_coverage_excellent:
                score += 5
            elif ic >= T.min_interest_coverage_good:
                score += 3
            elif ic >= T.min_interest_coverage_ok:
                score += 1
            else:
                result.warnings.append(f"Interest coverage thin: {ic:.1f}x")

        # Quick Ratio (3 pts)
        qr = _safe_float(info.get("quickRatio"))
        if qr >= 1.5:
            score += 3
        elif qr >= 1.0:
            score += 2
        elif qr > 0:
            score += 1

        return min(score, 20.0)

    def _compute_interest_coverage(self, income_stmt: pd.DataFrame) -> Optional[float]:
        try:
            if income_stmt.empty:
                return None
            ebit = self._row(income_stmt, ["EBIT", "Operating Income"])
            interest = self._row(income_stmt, ["Interest Expense"])
            if interest == 0:
                return None
            return float(ebit / abs(interest))
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    #  Valuation — 25 pts                                                  #
    # ------------------------------------------------------------------ #

    def _score_valuation(self, info: dict, result: FundamentalResult) -> float:
        score = 0.0

        # P/E (8 pts)
        pe = _safe_float(info.get("trailingPE") or info.get("forwardPE"))
        result.pe_ratio = pe if pe > 0 else None
        if 0 < pe <= T.pe_excellent:
            score += 8
        elif pe <= T.pe_good:
            score += 5
        elif pe <= T.pe_acceptable:
            score += 2
        elif pe > T.pe_acceptable:
            result.warnings.append(f"Expensive P/E: {pe:.1f}x")

        # PEG (7 pts)
        peg = _safe_float(info.get("pegRatio"))
        result.peg_ratio = peg if peg > 0 else None
        if 0 < peg <= T.peg_excellent:
            score += 7
            result.notes["peg"] = f"Attractive PEG {peg:.2f}"
        elif peg <= T.peg_good:
            score += 4
        elif peg <= T.peg_acceptable:
            score += 2

        # EV/EBITDA (5 pts)
        ev_ebitda = _safe_float(info.get("enterpriseToEbitda"))
        result.ev_ebitda = ev_ebitda if ev_ebitda > 0 else None
        if 0 < ev_ebitda <= T.ev_ebitda_excellent:
            score += 5
        elif ev_ebitda <= T.ev_ebitda_good:
            score += 3
        elif ev_ebitda <= T.ev_ebitda_acceptable:
            score += 1

        # P/B (5 pts)
        pb = _safe_float(info.get("priceToBook"))
        result.pb_ratio = pb if pb > 0 else None
        if 0 < pb <= T.pb_excellent:
            score += 5
        elif pb <= T.pb_good:
            score += 3
        elif pb <= T.pb_acceptable:
            score += 1

        return min(score, 25.0)

    # ------------------------------------------------------------------ #
    #  Growth — 20 pts                                                     #
    # ------------------------------------------------------------------ #

    def _score_growth(
        self,
        info: dict,
        income_stmt: pd.DataFrame,
        cashflow: pd.DataFrame,
        result: FundamentalResult,
    ) -> float:
        score = 0.0

        # Revenue CAGR 5Y (7 pts)
        rev_series = self._extract_annual_series(income_stmt, ["Total Revenue", "Revenue"])
        rev_cagr = compute_cagr(rev_series, years=5)
        if rev_cagr is not None:
            result.revenue_cagr_5y = round(rev_cagr * 100, 1)
            pct = result.revenue_cagr_5y
            if pct >= T.revenue_cagr_excellent:
                score += 7
            elif pct >= T.revenue_cagr_good:
                score += 4
            elif pct >= T.revenue_cagr_ok:
                score += 2
            else:
                result.warnings.append(f"Slow revenue growth: {pct:.1f}% CAGR")

        # EPS CAGR 5Y (7 pts) — use yfinance estimate or compute from net income
        eps_growth = _safe_float(info.get("earningsGrowth")) * 100
        if eps_growth > 0:
            result.eps_cagr_5y = round(eps_growth, 1)
            if eps_growth >= T.eps_cagr_excellent:
                score += 7
            elif eps_growth >= T.eps_cagr_good:
                score += 4
            elif eps_growth >= T.eps_cagr_ok:
                score += 2
        else:
            # Fallback: net income CAGR
            ni_series = self._extract_annual_series(income_stmt, ["Net Income"])
            ni_cagr = compute_cagr(ni_series, years=5)
            if ni_cagr is not None:
                result.eps_cagr_5y = round(ni_cagr * 100, 1)
                pct = result.eps_cagr_5y
                if pct >= T.eps_cagr_excellent:
                    score += 7
                elif pct >= T.eps_cagr_good:
                    score += 4
                elif pct >= T.eps_cagr_ok:
                    score += 2

        # FCF Yield + Growth (6 pts)
        fcf_series = self._extract_annual_series(cashflow, ["Free Cash Flow"])
        market_cap = result.market_cap
        if not fcf_series.empty and market_cap > 0:
            fcf_latest = fcf_series.iloc[0]
            fcf_yield = fcf_latest / market_cap * 100
            result.fcf_yield = round(fcf_yield, 2)
            if fcf_yield >= 4:
                score += 3
            elif fcf_yield >= 2:
                score += 2
            elif fcf_yield > 0:
                score += 1

            fcf_cagr = compute_cagr(fcf_series, years=3)
            if fcf_cagr is not None:
                if fcf_cagr * 100 >= T.fcf_growth_excellent:
                    score += 3
                elif fcf_cagr * 100 >= T.fcf_growth_good:
                    score += 2
                elif fcf_cagr > 0:
                    score += 1

        return min(score, 20.0)

    # ------------------------------------------------------------------ #
    #  Dividend Quality — 10 pts                                           #
    # ------------------------------------------------------------------ #

    def _score_dividends(self, info: dict, result: FundamentalResult) -> float:
        score = 0.0

        # Compute yield from annual rate / price (most reliable across yfinance versions)
        annual_rate = _safe_float(info.get("trailingAnnualDividendRate"))
        price = _safe_float(info.get("currentPrice") or info.get("regularMarketPrice"))
        if annual_rate > 0 and price > 0:
            div_yield = annual_rate / price * 100
        else:
            # Fallback: dividendYield is a decimal in yfinance (0.004 = 0.4%)
            div_yield = _safe_float(info.get("trailingAnnualDividendYield") or info.get("dividendYield")) * 100
        result.dividend_yield = round(div_yield, 2) if div_yield > 0 else None

        payout = _safe_float(info.get("payoutRatio")) * 100
        result.payout_ratio = payout if payout > 0 else None

        # Non-dividend stocks: neutral (growth companies reinvest instead)
        if div_yield == 0:
            score += 3  # partial credit — not a flaw for growth stocks
            result.notes["dividend"] = "No dividend — growth company reinvests FCF"
            return score

        # Yield in sweet spot (4 pts)
        if T.div_yield_sweet_spot_low <= div_yield <= T.div_yield_sweet_spot_high:
            score += 4
            result.notes["dividend"] = f"Healthy yield {div_yield:.2f}%"
        elif div_yield > T.div_yield_sweet_spot_high:
            score += 1
            result.warnings.append(f"High yield may signal risk: {div_yield:.2f}%")
        else:
            score += 2

        # Payout ratio (3 pts)
        if 0 < payout <= 40:
            score += 3
        elif payout <= T.max_payout_ratio:
            score += 2
        elif payout > T.max_payout_ratio:
            result.warnings.append(f"High payout ratio {payout:.0f}% — dividend may not be sustainable")

        # Dividend growth streak (3 pts) — use dividends history
        divs = get_dividends(result.symbol)
        if not divs.empty:
            annual = divs.resample("YE").sum()
            annual = annual[annual > 0]
            streak = self._consecutive_growth_streak(annual)
            if streak >= 10:
                score += 3
                result.notes["div_growth"] = f"Dividend Aristocrat — {streak} years of growth"
            elif streak >= 5:
                score += 2
            elif streak >= 2:
                score += 1

        return min(score, 10.0)

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _row(self, df: pd.DataFrame, candidates: list) -> float:
        """Extract the most recent annual value for a row matching any candidate name."""
        for name in candidates:
            if name in df.index:
                val = df.loc[name].iloc[0]
                return _safe_float(val)
        return 0.0

    def _extract_annual_series(self, df: pd.DataFrame, candidates: list) -> pd.Series:
        """Return a Series of annual values (most recent first) for a matching row."""
        for name in candidates:
            if name in df.index:
                series = df.loc[name].dropna()
                series.index = pd.to_datetime(series.index)
                return series.sort_index(ascending=False)
        return pd.Series(dtype=float)

    def _consecutive_growth_streak(self, annual: pd.Series) -> int:
        """Count how many consecutive years the dividend grew."""
        annual = annual.sort_index(ascending=False)
        streak = 0
        for i in range(len(annual) - 1):
            if annual.iloc[i] > annual.iloc[i + 1]:
                streak += 1
            else:
                break
        return streak
