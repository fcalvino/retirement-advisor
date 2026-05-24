"""
Economic Moat Analysis — Phase 3.

Economic moat refers to a company's durable competitive advantage that protects
its market share and profitability over time (term coined by Warren Buffett).

This module evaluates moat in two independent layers:

  QUANTITATIVE (0–12 pts, always computed, no API cost):
    Derived entirely from financial statements via yfinance.
    Six dimensions, 0–2 pts each:
      gross_margin_level       — pricing power proxy (high GM = can charge premium)
      gross_margin_stability   — durability of pricing power (low std = structural, not cyclical)
      roic_sustained           — capital efficiency above cost of capital over multiple years
      revenue_defensiveness    — how many years had negative revenue growth (0 = defensive)
      fcf_conversion           — OCF / Net Income > 1 means earnings backed by real cash
      fcf_margin               — FCF / Revenue: scalability of the business model

  AI QUALITATIVE (0–8 pts, optional, cached 7 days per ticker):
    Four structural dimensions evaluated by an LLM with company context.
    0–2 pts each, valid values: 0.0, 0.5, 1.0, 1.5, 2.0:
      brand_strength           — pricing power via brand recognition and trust
      network_effects          — value increases with more users (Metcalfe's Law)
      switching_costs          — friction to change provider (time, money, operational risk)
      regulatory_ip            — patents, exclusive licenses, or regulatory barriers to entry

  CLASSIFICATION (total 0–20):
    Wide Moat   ≥ 14  — durable advantage for 20+ years (MSFT, AAPL, V)
    Narrow Moat ≥  8  — advantage for 10+ years, more vulnerable (MELI, HD)
    Minimal     ≥  4  — some protection but eroding or limited (most commodity cos.)
    None        <  4  — no identifiable sustainable advantage

  BONUS applied to FundamentalResult.adjusted_score:
    min(moat_total × 0.5, 10.0) → max +10 pts
    This rewards structural quality that short-term financials may not capture
    (e.g. MELI: expensive P/E but Wide Moat lifts it to BUY territory).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger

from config import AIConfig


# ------------------------------------------------------------------ #
#  Custom exceptions                                                   #
# ------------------------------------------------------------------ #

class MoatAIError(Exception):
    """Raised when the AI qualitative analysis fails (API or parse error)."""


class MoatAPIError(MoatAIError):
    """API call itself failed (network, auth, rate limit)."""


class MoatParseError(MoatAIError):
    """API responded but the JSON could not be parsed."""


# ------------------------------------------------------------------ #
#  Data classes                                                        #
# ------------------------------------------------------------------ #

@dataclass
class MoatDetail:
    """
    Full breakdown of a company's economic moat score.

    Quantitative fields (always populated, from financial statements):
      gross_margin_level      0–2  Gross margin % vs thresholds (≥50%=2, ≥35%=1, ≥20%=0.5)
      gross_margin_stability  0–2  Std of gross margin over 4Y (≤3pp=2, ≤8pp=1, ≤15pp=0.5)
      roic_sustained          0–2  Avg ROIC over available years (≥20%=2, ≥12%=1, ≥8%=0.5)
      revenue_defensiveness   0–2  Negative-revenue-growth years (0=2, 1=1, ≤2=0.5)
      fcf_conversion          0–2  Avg OCF/NI ratio (≥1.2=2, ≥0.9=1, ≥0.6=0.5)
      fcf_margin              0–2  Avg FCF/Revenue % (≥20%=2, ≥10%=1, ≥5%=0.5)
      quant_total             0–12 Sum of the six quantitative dimensions

    AI qualitative fields (populated only when ai_available=True):
      brand_strength          0–2  Brand recognition and pricing power
      network_effects         0–2  Value increasing with more users
      switching_costs         0–2  Cost/friction to change provider
      regulatory_ip           0–2  Patents, licenses, or regulatory barriers
      ai_total                0–8  Sum of the four AI dimensions
      ai_reasoning            str  LLM explanation (2–3 sentences)
      ai_available            bool True when AI was actually called (fresh or cached)

    Combined:
      total           0–20   quant_total + ai_total
      classification  str    Wide | Narrow | Minimal | None
      bonus           float  min(total × 0.5, 10.0) — added to adjusted_score
    """

    # Quantitative (0–2 each, total 0–12)
    gross_margin_level: float = 0.0
    gross_margin_stability: float = 0.0
    roic_sustained: float = 0.0
    revenue_defensiveness: float = 0.0
    fcf_conversion: float = 0.0
    fcf_margin: float = 0.0
    quant_total: float = 0.0

    # AI qualitative (0–2 each, total 0–8)
    brand_strength: float = 0.0
    network_effects: float = 0.0
    switching_costs: float = 0.0
    regulatory_ip: float = 0.0
    ai_total: float = 0.0
    ai_reasoning: str = ""
    ai_available: bool = False

    # Combined
    total: float = 0.0
    classification: str = "None"
    bonus: float = 0.0

    @property
    def color(self) -> str:
        """Hex color for dashboard display based on classification."""
        return {
            "Wide":    "#00C851",
            "Narrow":  "#39b54a",
            "Minimal": "#ffbb33",
            "None":    "#888888",
        }.get(self.classification, "#888888")

    @property
    def emoji(self) -> str:
        """Emoji prefix for dashboard display."""
        return {
            "Wide":    "🏰",
            "Narrow":  "🟢",
            "Minimal": "🟡",
            "None":    "⚪",
        }.get(self.classification, "⚪")

    @property
    def quant_pct(self) -> float:
        """Quantitative score as percentage of maximum (12 pts)."""
        return round(self.quant_total / 12 * 100, 1)

    @property
    def ai_pct(self) -> float:
        """AI qualitative score as percentage of maximum (8 pts)."""
        return round(self.ai_total / 8 * 100, 1) if self.ai_available else 0.0


# ------------------------------------------------------------------ #
#  Analyzer                                                            #
# ------------------------------------------------------------------ #

class MoatAnalyzer:
    """
    Evaluates the economic moat of a company in two independent layers.

    Usage:
        analyzer = MoatAnalyzer()

        # Quantitative only (fast, no API, always available):
        moat = analyzer.analyze(symbol, info, income_stmt, balance_sheet, cashflow)

        # Add AI qualitative layer (cached 7 days, requires ai_config.enabled):
        moat = analyzer.analyze_with_ai(moat, symbol, info, ai_config)

    The AI layer is intentionally separated so the screener can run the
    quantitative analysis on all tickers cheaply, while the detailed Stock
    Analysis page triggers the full AI evaluation only for the selected ticker.

    AI results are cached in SQLite for 7 days per (ticker, provider, model)
    to minimize API cost. A failed API call never corrupts the cache — the
    quantitative score is always returned as a valid fallback.
    """

    _AI_CACHE_TTL_HOURS = 168  # 7 days — moat is structural, doesn't change daily

    def __init__(self) -> None:
        self._cache = None  # lazy-init: avoids import cycle at module load time

    def _get_cache(self):
        """Return the 7-day DataCache instance, creating it on first access."""
        if self._cache is None:
            from data.cache import DataCache
            self._cache = DataCache(ttl_hours=self._AI_CACHE_TTL_HOURS)
        return self._cache

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def analyze(
        self,
        symbol: str,
        info: dict,
        income_stmt: pd.DataFrame,
        balance_sheet: pd.DataFrame,
        cashflow: pd.DataFrame,
    ) -> MoatDetail:
        """
        Compute the quantitative moat score from financial statements.

        Always fast (no API calls). Returns a valid MoatDetail even when
        financial data is missing or incomplete — missing dimensions default
        to 0 (conservative / unknown).

        Args:
            symbol:        Ticker symbol (used for logging only).
            info:          yfinance info dict (grossMargins, etc.).
            income_stmt:   Annual income statement DataFrame from yfinance.
            balance_sheet: Annual balance sheet DataFrame from yfinance.
            cashflow:      Annual cash flow statement DataFrame from yfinance.

        Returns:
            MoatDetail with quant_total, classification and bonus populated.
            ai_available=False; all AI fields default to 0.
        """
        detail = MoatDetail()
        self._score_quant(detail, info, income_stmt, balance_sheet, cashflow)
        detail.total = round(detail.quant_total, 1)
        detail.classification = self._classify(detail.total)
        detail.bonus = min(round(detail.total * 0.5, 1), 10.0)
        logger.debug(f"{symbol}: moat quant={detail.quant_total:.1f}/12 ({detail.classification})")
        return detail

    def analyze_with_ai(
        self,
        quant_result: MoatDetail,
        symbol: str,
        info: dict,
        ai_config: AIConfig,
    ) -> MoatDetail:
        """
        Enrich an existing quantitative MoatDetail with AI qualitative scores.

        Results are cached for 7 days per (symbol, provider, model). A cache hit
        skips the API call entirely. On any error (API failure, JSON parse error,
        auth issue), the function logs a warning and returns the quant_result
        unchanged — the score degrades gracefully to quantitative-only.

        Args:
            quant_result: Output from analyze() — modified in-place and returned.
            symbol:       Ticker symbol for cache key and logging.
            info:         yfinance info dict (passed to prompt builder).
            ai_config:    AIConfig with provider, model, api_key, enabled.

        Returns:
            The same quant_result object with AI fields populated (if successful).
            On failure: quant_result unchanged, ai_available=False, ai_reasoning
            set to a human-readable error message.
        """
        cache_key = f"moat_ai_{symbol}_{ai_config.provider}_{ai_config.model}"

        # --- Cache hit ---
        cached = self._get_cache().get(cache_key)
        if cached:
            logger.debug(f"Moat AI cache hit for {symbol} ({ai_config.model})")
            self._apply_cached(quant_result, cached)
        else:
            # --- Fresh API call ---
            try:
                prompt = self._build_prompt(quant_result, symbol, info)
                raw = self._call_api(prompt, ai_config)
                parsed = self._parse_ai_response(raw, symbol)

                quant_result.brand_strength = parsed["brand_strength"]
                quant_result.network_effects = parsed["network_effects"]
                quant_result.switching_costs = parsed["switching_costs"]
                quant_result.regulatory_ip = parsed["regulatory_ip"]
                quant_result.ai_total = round(
                    quant_result.brand_strength + quant_result.network_effects +
                    quant_result.switching_costs + quant_result.regulatory_ip, 1
                )
                quant_result.ai_reasoning = parsed.get("reasoning", "")
                quant_result.ai_available = True

                self._get_cache().set(cache_key, {
                    "brand_strength": quant_result.brand_strength,
                    "network_effects": quant_result.network_effects,
                    "switching_costs": quant_result.switching_costs,
                    "regulatory_ip": quant_result.regulatory_ip,
                    "ai_total": quant_result.ai_total,
                    "ai_reasoning": quant_result.ai_reasoning,
                })
                logger.info(
                    f"{symbol}: moat AI={quant_result.ai_total:.1f}/8 "
                    f"(brand={quant_result.brand_strength} "
                    f"network={quant_result.network_effects} "
                    f"switching={quant_result.switching_costs} "
                    f"reg={quant_result.regulatory_ip})"
                )

            except MoatAPIError as exc:
                logger.warning(f"{symbol}: moat API call failed — {exc}")
                quant_result.ai_reasoning = f"[API error: {exc}]"

            except MoatParseError as exc:
                logger.warning(f"{symbol}: moat AI response unparseable — {exc}")
                quant_result.ai_reasoning = f"[Parse error: {exc}]"

            except Exception as exc:
                logger.warning(f"{symbol}: moat AI unexpected error — {exc}")
                quant_result.ai_reasoning = f"[Error: {exc}]"

        # Recompute combined totals regardless of whether AI succeeded
        quant_result.total = round(quant_result.quant_total + quant_result.ai_total, 1)
        quant_result.classification = self._classify(quant_result.total)
        quant_result.bonus = min(round(quant_result.total * 0.5, 1), 10.0)
        return quant_result

    # ------------------------------------------------------------------ #
    #  Quantitative scoring — 6 dimensions × 2 pts = 0–12                 #
    # ------------------------------------------------------------------ #

    def _score_quant(
        self,
        d: MoatDetail,
        info: dict,
        income_stmt: pd.DataFrame,
        balance_sheet: pd.DataFrame,
        cashflow: pd.DataFrame,
    ) -> None:
        """Populate all 6 quantitative dimensions and set quant_total."""

        # 1. Gross Margin Level — pricing power vs. commodity competitors
        #    Software/pharma/luxury: typically ≥50%. Energy/retail: often <30%.
        gm = self._pct(info.get("grossMargins"))
        if gm >= 50:
            d.gross_margin_level = 2.0
        elif gm >= 35:
            d.gross_margin_level = 1.0
        elif gm >= 20:
            d.gross_margin_level = 0.5

        # 2. Gross Margin Stability — consistent GM = structural pricing power
        #    High std suggests margin is cyclical or under competitive pressure.
        gm_series = self._gm_series(income_stmt)
        if len(gm_series) >= 3:
            gm_std = float(gm_series.std())
            if gm_std <= 3:
                d.gross_margin_stability = 2.0
            elif gm_std <= 8:
                d.gross_margin_stability = 1.0
            elif gm_std <= 15:
                d.gross_margin_stability = 0.5

        # 3. ROIC Sustained — returns above cost of capital signal a moat
        #    Average ROIC over all available years (more conservative than peak).
        roic_avg = self._avg_roic(income_stmt, balance_sheet)
        if roic_avg is not None:
            if roic_avg >= 20:
                d.roic_sustained = 2.0
            elif roic_avg >= 12:
                d.roic_sustained = 1.0
            elif roic_avg >= 8:
                d.roic_sustained = 0.5

        # 4. Revenue Defensiveness — moat companies don't lose revenue in downturns
        #    Counts years with negative revenue growth out of the available history.
        rev_series = self._row_series(income_stmt, ["Total Revenue", "Revenue"])
        if len(rev_series) >= 3:
            growth = rev_series.sort_index().pct_change().dropna()
            negative_years = int((growth < 0).sum())
            if negative_years == 0:
                d.revenue_defensiveness = 2.0
            elif negative_years == 1:
                d.revenue_defensiveness = 1.0
            elif negative_years <= 2:
                d.revenue_defensiveness = 0.5

        # 5. FCF Conversion — OCF/NI > 1 means accounting earnings are backed by cash
        #    Low conversion (<0.6) can indicate aggressive revenue recognition.
        fcf_conv = self._fcf_conversion(income_stmt, cashflow)
        if fcf_conv is not None:
            if fcf_conv >= 1.2:
                d.fcf_conversion = 2.0
            elif fcf_conv >= 0.9:
                d.fcf_conversion = 1.0
            elif fcf_conv >= 0.6:
                d.fcf_conversion = 0.5

        # 6. FCF Margin — high FCF/revenue = scalable model (asset-light or software-like)
        #    Avg over available years is more conservative than a single peak year.
        fcf_margin_val = self._fcf_margin(income_stmt, cashflow)
        if fcf_margin_val is not None:
            if fcf_margin_val >= 20:
                d.fcf_margin = 2.0
            elif fcf_margin_val >= 10:
                d.fcf_margin = 1.0
            elif fcf_margin_val >= 5:
                d.fcf_margin = 0.5

        d.quant_total = round(
            d.gross_margin_level + d.gross_margin_stability +
            d.roic_sustained + d.revenue_defensiveness +
            d.fcf_conversion + d.fcf_margin,
            1,
        )

    # ------------------------------------------------------------------ #
    #  AI prompt + call + parse                                            #
    # ------------------------------------------------------------------ #

    def _build_prompt(self, quant: MoatDetail, symbol: str, info: dict) -> str:
        """
        Build the LLM prompt for qualitative moat evaluation.

        The prompt includes:
          - Company context (name, sector, country, business summary)
          - Quantitative scores already computed (to avoid redundancy)
          - A scoring rubric with concrete anchor examples per dimension
          - Explicit instruction to discount for emerging market macro risk
          - Strict JSON output schema (no markdown, no extra text)
        """
        name = info.get("longName", symbol)
        sector = info.get("sector", "Unknown")
        industry = info.get("industry", "Unknown")
        country = info.get("country", "Unknown")
        summary = (info.get("longBusinessSummary") or "")[:600]

        return f"""Sos un analista senior de inversiones especializado en ventajas competitivas duraderas (economic moat).
Tu tarea es evaluar los 4 factores CUALITATIVOS de moat con criterio riguroso y conservador.

EMPRESA: {name} ({symbol})
SECTOR: {sector} | INDUSTRIA: {industry} | PAÍS: {country}
DESCRIPCIÓN: {summary}

MOAT CUANTITATIVO (ya calculado con datos financieros reales):
  Gross Margin nivel:       {quant.gross_margin_level}/2
  Gross Margin estabilidad: {quant.gross_margin_stability}/2
  ROIC sostenido:           {quant.roic_sustained}/2
  Revenue defensividad:     {quant.revenue_defensiveness}/2
  FCF Conversion:           {quant.fcf_conversion}/2
  FCF Margin:               {quant.fcf_margin}/2
  TOTAL CUANTITATIVO:       {quant.quant_total}/12

RÚBRICA DE SCORING (usá solo estos valores: 0.0, 0.5, 1.0, 1.5, 2.0):
  2.0 = Ventaja claramente dominante, duradera y reconocible a nivel global
  1.5 = Ventaja real y sólida, con alguna limitación o riesgo específico
  1.0 = Ventaja moderada, presente pero no dominante ni única
  0.5 = Ventaja incipiente o débil, podría erosionarse en 5 años
  0.0 = Sin ventaja identificable en esta dimensión

FACTORES A EVALUAR:

1. brand_strength — reconocimiento, confianza y poder de pricing de la marca
   Anclas: Apple/Coca-Cola = 2.0 | Marca regional sólida = 1.0 | Producto genérico = 0.0

2. network_effects — el valor del servicio aumenta con más usuarios (Ley de Metcalfe)
   Anclas: Visa/Meta/LinkedIn = 2.0 | Marketplace con masa crítica regional = 1.0 | Sin red = 0.0

3. switching_costs — fricción real para cambiar de proveedor (tiempo, dinero, riesgo operativo)
   Anclas: SAP/Bloomberg Terminal = 2.0 | CRM con integraciones complejas = 1.0 | Commodity = 0.0

4. regulatory_ip — patentes, licencias exclusivas o regulaciones que protegen la posición
   Anclas: Farmacéutica con patentes clave = 2.0 | Licencia bancaria única = 1.5 | Sin barreras = 0.0

REGLA DE DESCUENTO PARA MERCADOS EMERGENTES:
Si la empresa opera principalmente en países con riesgo político o macro significativo
(Argentina, Venezuela, Turquía, etc.), aplicá un descuento de -0.5 en las dimensiones
afectadas por ese riesgo y mencionalo explícitamente en el reasoning.

Respondé SOLO con JSON válido. Sin markdown, sin texto antes ni después:
{{
  "brand_strength": 0.0,
  "network_effects": 0.0,
  "switching_costs": 0.0,
  "regulatory_ip": 0.0,
  "reasoning": "2-3 oraciones concisas: fortalezas clave del moat, limitaciones relevantes y contexto macro si aplica."
}}"""

    def _call_api(self, prompt: str, ai_config: AIConfig) -> str:
        """
        Dispatch the prompt to the configured AI provider.

        Raises MoatAPIError on any network/auth/rate-limit failure so the
        caller can distinguish API problems from JSON parse problems.
        """
        provider = ai_config.provider.lower()

        try:
            if provider == "claude":
                import anthropic
                client = anthropic.Anthropic(api_key=ai_config.api_key)
                msg = client.messages.create(
                    model=ai_config.model,
                    max_tokens=512,
                    temperature=0,
                    messages=[{"role": "user", "content": prompt}],
                )
                return msg.content[0].text

            elif provider == "openai":
                import openai
                client = openai.OpenAI(api_key=ai_config.api_key)
                resp = client.chat.completions.create(
                    model=ai_config.model,
                    temperature=0,
                    max_tokens=512,
                    messages=[{"role": "user", "content": prompt}],
                )
                return resp.choices[0].message.content

            elif provider in ("xai", "nous"):
                import sys
                from pathlib import Path
                hermes_path = Path.home() / ".hermes" / "hermes-agent"
                if str(hermes_path) not in sys.path:
                    sys.path.insert(0, str(hermes_path))
                try:
                    from hermes_cli.auth import resolve_xai_oauth_runtime_credentials
                except ImportError as e:
                    raise MoatAPIError(
                        "Hermes OAuth not installed. Run: pip install hermes-agent"
                    ) from e
                creds = resolve_xai_oauth_runtime_credentials()
                import openai as _openai
                client = _openai.OpenAI(
                    api_key=creds.get("api_key") or "hermes-oauth",
                    base_url=creds.get("base_url", "https://api.x.ai/v1"),
                )
                resp = client.chat.completions.create(
                    model=ai_config.model,
                    temperature=0,
                    max_tokens=512,
                    messages=[{"role": "user", "content": prompt}],
                )
                return resp.choices[0].message.content

            else:
                raise MoatAPIError(f"Unknown AI provider: {provider!r}")

        except MoatAPIError:
            raise
        except Exception as exc:
            raise MoatAPIError(f"{provider} API error: {exc}") from exc

    def _parse_ai_response(self, raw: str, symbol: str) -> dict:
        """
        Parse the JSON payload from an AI response.

        Handles two common failure modes:
          1. Response wrapped in markdown fences (```json ... ```)
          2. Response contains extra prose before/after the JSON object

        All four score fields are clamped to [0.0, 2.0] after parsing.

        Raises MoatParseError if no valid JSON object can be extracted.
        """
        text = raw.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(line for line in lines if not line.startswith("```")).strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Fallback: extract first {...} block from the response
            match = re.search(r'\{.*?\}', text, re.DOTALL)
            if not match:
                raise MoatParseError(
                    f"No JSON object found in response for {symbol}: {text[:200]!r}"
                )
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError as exc:
                raise MoatParseError(
                    f"JSON decode failed for {symbol}: {exc} — raw: {text[:200]!r}"
                ) from exc

        # Clamp all score fields to valid range
        for key in ("brand_strength", "network_effects", "switching_costs", "regulatory_ip"):
            raw_val = data.get(key, 0.0)
            try:
                data[key] = round(max(0.0, min(2.0, float(raw_val))), 1)
            except (TypeError, ValueError):
                logger.warning(f"{symbol}: moat field {key!r} has invalid value {raw_val!r}, defaulting to 0")
                data[key] = 0.0

        return data

    # ------------------------------------------------------------------ #
    #  Cache helpers                                                        #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _apply_cached(detail: MoatDetail, cached: dict) -> None:
        """Apply a cached AI result to a MoatDetail object."""
        detail.brand_strength = float(cached.get("brand_strength", 0))
        detail.network_effects = float(cached.get("network_effects", 0))
        detail.switching_costs = float(cached.get("switching_costs", 0))
        detail.regulatory_ip = float(cached.get("regulatory_ip", 0))
        detail.ai_total = float(cached.get("ai_total", 0))
        detail.ai_reasoning = cached.get("ai_reasoning", "")
        detail.ai_available = True

    # ------------------------------------------------------------------ #
    #  Classification                                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _classify(total: float) -> str:
        """Map a total moat score (0–20) to a classification label."""
        if total >= 14:
            return "Wide"
        elif total >= 8:
            return "Narrow"
        elif total >= 4:
            return "Minimal"
        return "None"

    # ------------------------------------------------------------------ #
    #  Data extraction helpers                                             #
    # ------------------------------------------------------------------ #

    def _pct(self, val) -> float:
        """Convert a yfinance decimal ratio (e.g. 0.65) to percentage (65.0)."""
        try:
            return float(val or 0) * 100
        except (TypeError, ValueError):
            return 0.0

    def _row_series(self, df: pd.DataFrame, candidates: list) -> pd.Series:
        """
        Extract a time series for the first matching row name, sorted ascending by date.
        Returns an empty Series if df is None/empty or no candidate matches.
        """
        if df is None or df.empty:
            return pd.Series(dtype=float)
        for name in candidates:
            if name in df.index:
                s = df.loc[name].dropna()
                s.index = pd.to_datetime(s.index)
                return s.sort_index().astype(float)
        return pd.Series(dtype=float)

    def _gm_series(self, income_stmt: pd.DataFrame) -> pd.Series:
        """Return a time series of gross margin % (Gross Profit / Revenue × 100)."""
        gross = self._row_series(income_stmt, ["Gross Profit"])
        rev = self._row_series(income_stmt, ["Total Revenue", "Revenue"])
        if gross.empty or rev.empty:
            return pd.Series(dtype=float)
        common = gross.index.intersection(rev.index)
        if len(common) < 2:
            return pd.Series(dtype=float)
        rev_c = rev[common].replace(0, np.nan)
        return (gross[common] / rev_c * 100).dropna()

    def _avg_roic(
        self, income_stmt: pd.DataFrame, balance_sheet: pd.DataFrame
    ) -> Optional[float]:
        """
        Compute average ROIC = NOPAT / Invested Capital over available years.
        NOPAT = EBIT × (1 − 0.21). Invested Capital = Equity + Long-term Debt.
        Returns None if insufficient data.
        """
        try:
            ebit_s = self._row_series(income_stmt, ["EBIT", "Operating Income"])
            equity_s = self._row_series(
                balance_sheet,
                ["Stockholders Equity", "Total Stockholder Equity", "Common Stock Equity"],
            )
            ltd_s = self._row_series(balance_sheet, ["Long Term Debt", "Long-Term Debt"])
            if ebit_s.empty or equity_s.empty:
                return None
            common = ebit_s.index.intersection(equity_s.index)
            if len(common) < 1:
                return None
            nopat = ebit_s[common] * 0.79  # NOPAT = EBIT × (1 − tax rate)
            ic = equity_s[common].copy()
            if not ltd_s.empty:
                ic = ic + ltd_s.reindex(common).fillna(0)
            ic = ic.replace(0, np.nan)
            roic = (nopat / ic * 100).dropna()
            return float(roic.mean()) if not roic.empty else None
        except Exception:
            return None

    def _fcf_conversion(
        self, income_stmt: pd.DataFrame, cashflow: pd.DataFrame
    ) -> Optional[float]:
        """
        Average OCF / Net Income ratio over available years.
        Values > 1.0 indicate earnings are fully backed by operating cash flow.
        """
        try:
            ni = self._row_series(income_stmt, ["Net Income"])
            ocf = self._row_series(
                cashflow,
                ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"],
            )
            if ni.empty or ocf.empty:
                return None
            common = ni.index.intersection(ocf.index)
            if len(common) < 1:
                return None
            ni_v = ni[common].replace(0, np.nan)
            return float((ocf[common] / ni_v).dropna().mean())
        except Exception:
            return None

    def _fcf_margin(
        self, income_stmt: pd.DataFrame, cashflow: pd.DataFrame
    ) -> Optional[float]:
        """
        Average Free Cash Flow / Revenue ratio (%) over available years.
        High FCF margin (≥20%) indicates a scalable, asset-light business model.
        """
        try:
            rev = self._row_series(income_stmt, ["Total Revenue", "Revenue"])
            fcf = self._row_series(cashflow, ["Free Cash Flow"])
            if rev.empty or fcf.empty:
                return None
            common = rev.index.intersection(fcf.index)
            if len(common) < 1:
                return None
            rev_v = rev[common].replace(0, np.nan)
            return float((fcf[common] / rev_v * 100).dropna().mean())
        except Exception:
            return None
