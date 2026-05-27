"""
Crypto Asset Analyzer — Phase 4 (Bitcoin / Digital Assets).

Provides a fully separate analysis path for crypto assets.  The entry point
is CryptoAnalyzer.analyze(), which returns a standard FundamentalResult so
all downstream consumers (strategy.py, ai_analyzer.py, dashboard) need zero
changes.

SCORING MODEL (0–100 adjusted_score):
  base_score          35.0   floor — BTC is a recognized institutional asset class
  tech_pts            0–45   derived from TechnicalResult signal + strength
  vol_penalty         0–25   annualised 52-week volatility (BTC ~65–90%)
  drawdown_penalty    0–15   maximum historical peak-to-trough decline
  moat_bonus          0–5    AI qualitative crypto moat (cached 7 days)

  adjusted_score = clamp(base + tech - vol - dd + moat, 0, 100)

Calibration targets (Grok-approved):
  Bull market, Wide Moat  → ~55–65  (HOLD — correct for conservative retirement)
  Bear market, Narrow     → ~10–20  (SELL / REDUCE)
  Neutral, Narrow         → ~30–40  (HOLD)

CRYPTO MOAT FRAMEWORK (0–8 pts, AI qualitative only):
  network_adoption          0–2   Network effects + global adoption momentum
  monetary_scarcity         0–2   Fixed 21M supply cap + halving cycle dynamics
  security_decentralization 0–1.5 Hash rate, node count, attack resistance
  institutional_regulatory  0–1.5 ETF approvals, regulatory clarity, sovereign adoption
  tech_resilience           0–1   Lightning Network, L2 maturity, competition resistance
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

from config import CRYPTO_MOAT, AIConfig


# ---------------------------------------------------------------------------
# Crypto Moat data class
# ---------------------------------------------------------------------------

@dataclass
class CryptoMoatDetail:
    """
    AI-qualitative moat breakdown for a crypto asset.

    Five crypto-native dimensions with the same 0–8 total scale as the
    equity AI-moat (MoatDetail.ai_total), enabling consistent display in
    the dashboard moat section.

    Dimension max values:
        network_adoption          0–2
        monetary_scarcity         0–2
        security_decentralization 0–1.5
        institutional_regulatory  0–1.5
        tech_resilience           0–1
        ─────────────────────────────
        total                     0–8

    Classification thresholds (from CryptoMoatConfig):
        Wide    ≥ 6.0
        Narrow  ≥ 4.0
        Minimal ≥ 2.0
        None    < 2.0
    """

    # Five qualitative dimensions
    network_adoption: float = 0.0           # 0–2
    monetary_scarcity: float = 0.0          # 0–2
    security_decentralization: float = 0.0  # 0–1.5
    institutional_regulatory: float = 0.0   # 0–1.5
    tech_resilience: float = 0.0            # 0–1

    # AI metadata
    ai_total: float = 0.0
    ai_reasoning: str = ""
    ai_available: bool = False

    # Combined result
    total: float = 0.0
    classification: str = "None"
    bonus: float = 0.0                      # min(total × factor, max_bonus)

    # Grok-recommended allocation limit (% of portfolio, conservative profile)
    recommended_max_allocation_pct: float = 5.0

    # Additional fields from Grok final prompt (v2, May 2026)
    moat_durability_years: int = 10
    retirement_risk_summary: str = ""

    @property
    def color(self) -> str:
        return {
            "Wide":    "#00C851",
            "Narrow":  "#39b54a",
            "Minimal": "#ffbb33",
            "None":    "#888888",
        }.get(self.classification, "#888888")

    @property
    def emoji(self) -> str:
        return {
            "Wide":    "🏰",
            "Narrow":  "🟢",
            "Minimal": "🟡",
            "None":    "⚪",
        }.get(self.classification, "⚪")


# ---------------------------------------------------------------------------
# Crypto Analyzer
# ---------------------------------------------------------------------------

class CryptoAnalyzer:
    """
    Produce a FundamentalResult for a crypto asset (BTC-USD, ETH-USD …).

    All equity-specific fields (roe, roic, pe_ratio, debt_equity, etc.) are
    set to None.  The adjusted_score uses the crypto-native formula above.
    The result is a drop-in replacement for the equity FundamentalResult —
    callers require no changes.
    """

    _AI_CACHE_TTL_HOURS = CRYPTO_MOAT.ai_cache_ttl_hours

    def __init__(self) -> None:
        self._cache = None   # lazy-init — avoids import cycle at module load

    def _get_cache(self):
        if self._cache is None:
            from data.cache import DataCache
            self._cache = DataCache(ttl_hours=self._AI_CACHE_TTL_HOURS)
        return self._cache

    # ------------------------------------------------------------------ #
    #  Public entry point                                                  #
    # ------------------------------------------------------------------ #

    def analyze(self, symbol: str, ai_config: Optional[AIConfig] = None):
        """
        Full crypto analysis.  Returns a FundamentalResult with is_crypto=True.

        Steps:
          1. Fetch crypto info (yfinance)
          2. Fetch price history → compute vol / drawdown / CAGR / halving
          3. Run TechnicalAnalyzer on the same price series
          4. Optionally fetch AI crypto moat (if ai_config.enabled)
          5. Build FundamentalResult with the crypto scoring formula
        """
        # Lazy import to avoid circular deps at module load
        from analysis.fundamental import FundamentalResult
        from data.crypto_fetcher import get_crypto_info, compute_crypto_metrics
        from data.fetcher import get_history
        from analysis.technical import TechnicalAnalyzer

        result = FundamentalResult(symbol=symbol)
        result.is_crypto = True   # sentinel used by dashboard & ai_analyzer
        result.sector = "Crypto / Digital Asset"
        result.industry = "Store of Value / Monetary Asset"

        # 1. yfinance info
        info = get_crypto_info(symbol)
        if not info:
            result.warnings.append(f"{symbol}: crypto data unavailable (yfinance returned empty)")
            return result

        result.company_name = info.get("longName", symbol)
        result.market_cap   = info.get("marketCap", 0.0)
        result.current_price = info.get("currentPrice", 0.0)

        # 2. Price history + derived metrics
        price_df = get_history(symbol, period="10y", interval="1wk")
        metrics  = compute_crypto_metrics(symbol, info, price_df)

        # 3. Technical analysis (reuses existing TechnicalAnalyzer unchanged)
        try:
            tech = TechnicalAnalyzer().analyze(symbol)
        except Exception as exc:
            logger.warning(f"{symbol}: TechnicalAnalyzer failed — {exc}")
            from analysis.technical import TechnicalResult
            tech = TechnicalResult(symbol=symbol)

        # 4. AI crypto moat
        moat = CryptoMoatDetail()
        if ai_config and getattr(ai_config, "enabled", False):
            moat = self._analyze_crypto_moat(symbol, info, metrics, ai_config)

        # 5. Build result
        self._populate_result(result, info, metrics, tech, moat)

        logger.info(
            f"{symbol}: crypto analysis — vol={metrics.get('annualized_volatility_pct')}% "
            f"dd={metrics.get('max_drawdown_pct')}% tech={tech.signal} "
            f"moat={moat.classification} adjusted={result.adjusted_score}"
        )
        return result

    # ------------------------------------------------------------------ #
    #  Result builder                                                      #
    # ------------------------------------------------------------------ #

    def _populate_result(self, result, info: dict, metrics: dict, tech, moat: CryptoMoatDetail) -> None:
        """Fill FundamentalResult fields with crypto-appropriate values."""
        # All equity-specific metrics → None (suppressed in display)
        result.roe = None
        result.roic = None
        result.net_margin = None
        result.gross_margin = None
        result.debt_equity = None
        result.current_ratio = None
        result.interest_coverage = None
        result.pe_ratio = None
        result.peg_ratio = None
        result.ev_ebitda = None
        result.pb_ratio = None
        result.revenue_cagr_5y = None
        result.eps_cagr_5y = None
        result.fcf_yield = None
        result.dividend_yield = None
        result.payout_ratio = None
        result.graham_value = None
        result.margin_of_safety_pct = None

        # Enhanced scoring not applicable
        result.consistency_score = 0.0
        result.piotroski_score = 0
        result.piotroski_bonus = 0.0
        result.piotroski_detail = None
        result.consistency_detail = None

        # Sub-scores all zero — replaced by adjusted_score directly
        result.profitability_score = 0.0
        result.health_score = 0.0
        result.valuation_score = 0.0
        result.growth_score = 0.0
        result.dividend_score = 0.0
        result.total_score = 0.0

        # Moat
        result.moat_score = moat.total
        result.moat_bonus = moat.bonus
        result.moat_classification = moat.classification
        result.crypto_moat_detail = moat

        # Informational notes (shown in dashboard Crypto section)
        vol  = metrics.get("annualized_volatility_pct")
        dd   = metrics.get("max_drawdown_pct")
        cagr = metrics.get("cagr_4y_pct")
        sc   = metrics.get("supply_scarcity_pct")
        phase = metrics.get("halving_cycle_position", "unknown")
        d_since = metrics.get("days_since_last_halving")
        d_next  = metrics.get("days_to_next_halving")

        if vol is not None:
            result.notes["crypto_vol"] = f"Volatilidad anualizada (52s): {vol:.1f}%"
        if dd is not None:
            result.notes["crypto_dd"] = f"Drawdown máximo histórico: {dd:.1f}%"
        if cagr is not None:
            result.notes["crypto_cagr"] = f"CAGR precio 4 años: {cagr:.1f}%"
        if sc is not None:
            result.notes["crypto_supply"] = f"Suministro emitido: {sc:.1f}% del máximo"
        if phase != "unknown":
            halving_str = f"Ciclo halving: {phase}"
            if d_since is not None:
                halving_str += f" ({d_since}d desde último"
            if d_next is not None:
                halving_str += f" / {d_next}d al próximo)"
            result.notes["crypto_halving"] = halving_str

        # Volatility warning for conservative portfolios
        if vol is not None and vol > 70:
            result.warnings.append(
                f"⚠️ Volatilidad extrema ({vol:.0f}% anualizada) — inadecuado como posición principal en cartera de retiro conservadora"
            )
        if dd is not None and dd < -60:
            result.warnings.append(
                f"⚠️ Drawdown histórico de {dd:.0f}% — riesgo de pérdida permanente de capital en horizontes cortos"
            )

        # Crypto scoring formula
        result.adjusted_score = self._compute_score(
            tech=tech,
            vol=vol,
            max_drawdown=dd,
            moat_bonus=moat.bonus,
        )

    # ------------------------------------------------------------------ #
    #  Scoring formula                                                     #
    # ------------------------------------------------------------------ #

    def _compute_score(
        self,
        tech,
        vol: Optional[float],
        max_drawdown: Optional[float],
        moat_bonus: float,
    ) -> float:
        """
        Crypto-specific scoring formula (0–100).

        Calibrated so BTC in a strong bull market scores 55–65 (HOLD for
        conservative retirement profiles), not STRONG BUY.

        Components:
            base_score    = 35.0
            tech_pts      = 0–45    (signal + strength)
            vol_penalty   = 0–25    (annualised volatility)
            dd_penalty    = 0–15    (max historical drawdown)
            moat_bonus    = 0–5     (from CryptoMoatDetail)
        """
        base  = 35.0
        tech_pts  = self._tech_pts(tech)
        vol_pen   = self._vol_penalty(vol)
        dd_pen    = self._drawdown_penalty(max_drawdown)

        raw = base + tech_pts - vol_pen - dd_pen + moat_bonus
        return round(max(0.0, min(100.0, raw)), 1)

    @staticmethod
    def _tech_pts(tech) -> float:
        """
        Convert TechnicalResult → 0–45 pts.

            BULLISH + strength >  50  → 45
            BULLISH                   → 35
            NEUTRAL                   → 22
            BEARISH                   → 10
            BEARISH + strength < -50  →  5
        """
        signal   = getattr(tech, "signal", "NEUTRAL")
        strength = getattr(tech, "signal_strength", 0)
        if signal == "BULLISH":
            return 45.0 if strength > 50 else 35.0
        elif signal == "BEARISH":
            return 5.0 if strength < -50 else 10.0
        return 22.0   # NEUTRAL

    @staticmethod
    def _vol_penalty(vol: Optional[float]) -> float:
        """
        Annualised volatility → 0–25 pts penalty.

            < 40%   →  0  (impossible for BTC but future-proofs ETH/stables)
            40–60%  →  8
            60–80%  → 15
            80–100% → 20
            > 100%  → 25
        """
        if vol is None:
            return 15.0   # conservative default if unknown
        if vol < 40:
            return 0.0
        elif vol < 60:
            return 8.0
        elif vol < 80:
            return 15.0
        elif vol <= 100:
            return 20.0
        return 25.0

    @staticmethod
    def _drawdown_penalty(dd: Optional[float]) -> float:
        """
        Max historical drawdown (negative %) → 0–15 pts penalty.

            > -30%  →  0
            -30–50% →  5
            -50–70% → 10
            < -70%  → 15  (BTC: -77% 2022, -83% 2018)
        """
        if dd is None:
            return 10.0   # conservative default
        if dd > -30:
            return 0.0
        elif dd > -50:
            return 5.0
        elif dd > -70:
            return 10.0
        return 15.0

    # ------------------------------------------------------------------ #
    #  AI Crypto Moat                                                      #
    # ------------------------------------------------------------------ #

    def _analyze_crypto_moat(
        self,
        symbol: str,
        info: dict,
        metrics: dict,
        ai_config: AIConfig,
    ) -> CryptoMoatDetail:
        """
        Fetch (or reuse cached) AI qualitative crypto moat scores.

        Cache key: "crypto_moat_ai_{symbol}_{provider}_{model}"
        TTL: 168 h (7 days) — halving cycles don't change weekly.
        On any API or parse error: returns default zeros (graceful degradation).
        """
        cache_key = f"crypto_moat_ai_{symbol}_{ai_config.provider}_{ai_config.model}"
        moat = CryptoMoatDetail()

        # --- Cache hit ---
        cached = self._get_cache().get(cache_key)
        if cached:
            logger.debug(f"Crypto moat cache hit for {symbol}")
            self._apply_cached(moat, cached)
        else:
            # --- Fresh API call ---
            try:
                prompt = self._build_crypto_moat_prompt(symbol, info, metrics)
                from analysis.moat import call_ai_api, MoatAPIError, MoatParseError
                raw    = call_ai_api(prompt, ai_config)
                parsed = self._parse_crypto_moat_response(raw, symbol)

                moat.network_adoption          = parsed["network_adoption"]
                moat.monetary_scarcity         = parsed["monetary_scarcity"]
                moat.security_decentralization = parsed["security_decentralization"]
                moat.institutional_regulatory  = parsed["institutional_regulatory"]
                moat.tech_resilience           = parsed["tech_resilience"]
                moat.ai_reasoning              = parsed.get("reasoning", "")
                moat.ai_available              = True
                moat.recommended_max_allocation_pct = float(
                    parsed.get("recommended_max_allocation_conservative", 5)
                )
                moat.moat_durability_years   = parsed.get("moat_durability_years", 10)
                moat.retirement_risk_summary = parsed.get("retirement_risk_summary", "")
                moat.ai_total = round(
                    moat.network_adoption + moat.monetary_scarcity +
                    moat.security_decentralization + moat.institutional_regulatory +
                    moat.tech_resilience,
                    1,
                )

                # Cache for next 7 days
                self._get_cache().set(cache_key, {
                    "network_adoption":               moat.network_adoption,
                    "monetary_scarcity":              moat.monetary_scarcity,
                    "security_decentralization":      moat.security_decentralization,
                    "institutional_regulatory":       moat.institutional_regulatory,
                    "tech_resilience":                moat.tech_resilience,
                    "ai_total":                       moat.ai_total,
                    "ai_reasoning":                   moat.ai_reasoning,
                    "recommended_max_allocation_pct": moat.recommended_max_allocation_pct,
                    "moat_durability_years":          moat.moat_durability_years,
                    "retirement_risk_summary":        moat.retirement_risk_summary,
                })
                logger.info(
                    f"{symbol}: crypto moat AI={moat.ai_total:.1f}/8 "
                    f"(net={moat.network_adoption} scarcity={moat.monetary_scarcity} "
                    f"sec={moat.security_decentralization} reg={moat.institutional_regulatory} "
                    f"tech={moat.tech_resilience})"
                )

            except Exception as exc:
                logger.warning(f"{symbol}: crypto moat AI failed — {exc}")
                moat.ai_reasoning = f"[AI error: {exc}]"

        # Finalize
        moat.total          = round(moat.ai_total, 1)
        moat.classification = self._classify_crypto_moat(moat.total)
        moat.bonus          = round(min(moat.total * CRYPTO_MOAT.bonus_factor, CRYPTO_MOAT.max_bonus), 1)
        return moat

    @staticmethod
    def _apply_cached(moat: CryptoMoatDetail, cached: dict) -> None:
        moat.network_adoption                = float(cached.get("network_adoption", 0))
        moat.monetary_scarcity               = float(cached.get("monetary_scarcity", 0))
        moat.security_decentralization       = float(cached.get("security_decentralization", 0))
        moat.institutional_regulatory        = float(cached.get("institutional_regulatory", 0))
        moat.tech_resilience                 = float(cached.get("tech_resilience", 0))
        moat.ai_total                        = float(cached.get("ai_total", 0))
        moat.ai_reasoning                    = cached.get("ai_reasoning", "")
        moat.recommended_max_allocation_pct  = float(cached.get("recommended_max_allocation_pct", 5.0))
        moat.moat_durability_years           = int(cached.get("moat_durability_years", 10))
        moat.retirement_risk_summary         = cached.get("retirement_risk_summary", "")
        moat.ai_available                    = True

    @staticmethod
    def _classify_crypto_moat(total: float) -> str:
        cfg = CRYPTO_MOAT
        if total >= cfg.wide_threshold:
            return "Wide"
        elif total >= cfg.narrow_threshold:
            return "Narrow"
        elif total >= cfg.minimal_threshold:
            return "Minimal"
        return "None"

    # ------------------------------------------------------------------ #
    #  Prompt builder                                                      #
    # ------------------------------------------------------------------ #

    def _build_crypto_moat_prompt(self, symbol: str, info: dict, metrics: dict) -> str:
        """Delegate to the centralized prompt library."""
        from analysis.prompts import crypto_moat_prompt
        return crypto_moat_prompt(symbol, info, metrics)

    def _parse_crypto_moat_response(self, raw: str, symbol: str) -> dict:
        """
        Parse JSON from LLM response and clamp each field to its valid range.

        Field ranges:
            network_adoption          → [0.0, 2.0]
            monetary_scarcity         → [0.0, 2.0]
            security_decentralization → [0.0, 1.5]
            institutional_regulatory  → [0.0, 1.5]
            tech_resilience           → [0.0, 1.0]
        """
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(l for l in lines if not l.startswith("```")).strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r'\{.*?\}', text, re.DOTALL)
            if not match:
                raise ValueError(f"No JSON in crypto moat response for {symbol}: {text[:200]!r}")
            data = json.loads(match.group())

        clamp_rules = {
            "network_adoption":          (0.0, 2.0),
            "monetary_scarcity":         (0.0, 2.0),
            "security_decentralization": (0.0, 1.5),
            "institutional_regulatory":  (0.0, 1.5),
            "tech_resilience":           (0.0, 1.0),
        }
        for key, (lo, hi) in clamp_rules.items():
            raw_val = data.get(key, 0.0)
            try:
                data[key] = round(max(lo, min(hi, float(raw_val))), 1)
            except (TypeError, ValueError):
                logger.warning(f"{symbol}: crypto moat field {key!r} invalid ({raw_val!r}), defaulting to 0")
                data[key] = 0.0

        # Optional fields — graceful defaults if LLM omits them
        try:
            alloc_raw = data.get("recommended_max_allocation_conservative", 5)
            data["recommended_max_allocation_conservative"] = int(max(1, min(20, int(alloc_raw))))
        except (TypeError, ValueError):
            data["recommended_max_allocation_conservative"] = 5

        try:
            dur = int(data.get("moat_durability_years", 10))
            data["moat_durability_years"] = max(1, min(30, dur))
        except (TypeError, ValueError):
            data["moat_durability_years"] = 10

        # retirement_risk_summary — plain string, no clamping needed
        data["retirement_risk_summary"] = str(data.get("retirement_risk_summary", ""))

        # total_moat_score from LLM is cross-check only; we recompute ourselves
        return data
