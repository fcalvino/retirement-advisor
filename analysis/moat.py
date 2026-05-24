"""
Economic Moat Analysis — Phase 3.

Quantitative moat (0–12 pts, always computed — no API cost):
  gross_margin_level       0–2  — pricing power proxy
  gross_margin_stability   0–2  — consistency of pricing power
  roic_sustained           0–2  — capital efficiency over years
  revenue_defensiveness    0–2  — negative-growth years
  fcf_conversion           0–2  — OCF / Net Income (cash quality)
  fcf_margin               0–2  — free cash flow / revenue

AI qualitative moat (0–8 pts, optional, cached 7 days per ticker):
  brand_strength           0–2
  network_effects          0–2
  switching_costs          0–2
  regulatory_ip            0–2

Classification (total 0–20):
  Wide Moat   ≥ 14
  Narrow Moat ≥  8
  Minimal     ≥  4
  None        <  4

Moat bonus applied to adjusted_score: min(total × 0.5, 10.0) → max +10 pts
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger

from config import AIConfig


@dataclass
class MoatDetail:
    # Quantitative (0–2 each, total 0–12)
    gross_margin_level: float = 0.0
    gross_margin_stability: float = 0.0
    roic_sustained: float = 0.0
    revenue_defensiveness: float = 0.0
    fcf_conversion: float = 0.0
    fcf_margin: float = 0.0
    quant_total: float = 0.0      # sum of above, 0–12

    # AI qualitative (0–2 each, total 0–8)
    brand_strength: float = 0.0
    network_effects: float = 0.0
    switching_costs: float = 0.0
    regulatory_ip: float = 0.0
    ai_total: float = 0.0         # sum of above, 0–8
    ai_reasoning: str = ""
    ai_available: bool = False    # True when AI was actually called

    # Combined
    total: float = 0.0            # quant + ai, 0–20
    classification: str = "None"  # Wide | Narrow | Minimal | None
    bonus: float = 0.0            # min(total * 0.5, 10.0)


class MoatAnalyzer:
    """
    Evaluates economic moat quantitatively (always) and qualitatively via AI (optional).
    AI results are cached for 7 days per ticker to minimize API cost.
    """

    _AI_CACHE_TTL_HOURS = 168  # 7 days

    def __init__(self):
        self._cache = None   # lazy-init to avoid import cycle at module load

    def _get_cache(self):
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
        """Quantitative moat only — no AI calls, always fast."""
        detail = MoatDetail()
        self._score_quant(detail, info, income_stmt, balance_sheet, cashflow)
        detail.total = round(detail.quant_total, 1)
        detail.classification = self._classify(detail.total)
        detail.bonus = min(round(detail.total * 0.5, 1), 10.0)
        return detail

    def analyze_with_ai(
        self,
        quant_result: MoatDetail,
        symbol: str,
        info: dict,
        ai_config: AIConfig,
    ) -> MoatDetail:
        """Add AI qualitative layer on top of existing quant result (with 7-day cache)."""
        cache_key = f"moat_ai_{symbol}_{ai_config.provider}_{ai_config.model}"

        cached = self._get_cache().get(cache_key)
        if cached:
            logger.debug(f"Moat AI cache hit for {symbol}")
            quant_result.brand_strength = float(cached.get("brand_strength", 0))
            quant_result.network_effects = float(cached.get("network_effects", 0))
            quant_result.switching_costs = float(cached.get("switching_costs", 0))
            quant_result.regulatory_ip = float(cached.get("regulatory_ip", 0))
            quant_result.ai_total = float(cached.get("ai_total", 0))
            quant_result.ai_reasoning = cached.get("ai_reasoning", "")
            quant_result.ai_available = True
        else:
            try:
                prompt = self._build_prompt(quant_result, symbol, info)
                raw = self._call_api(prompt, ai_config)
                parsed = self._parse_ai_response(raw)

                quant_result.brand_strength = parsed.get("brand_strength", 0.0)
                quant_result.network_effects = parsed.get("network_effects", 0.0)
                quant_result.switching_costs = parsed.get("switching_costs", 0.0)
                quant_result.regulatory_ip = parsed.get("regulatory_ip", 0.0)
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
                logger.info(f"Moat AI analysis for {symbol}: {quant_result.ai_total}/8")
            except Exception as exc:
                logger.warning(f"Moat AI analysis failed for {symbol}: {exc}")
                quant_result.ai_reasoning = f"[AI analysis unavailable: {exc}]"

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
        # 1. Gross Margin Level (0–2) — high GM = pricing power
        gm = self._pct(info.get("grossMargins"))
        if gm >= 50:
            d.gross_margin_level = 2.0
        elif gm >= 35:
            d.gross_margin_level = 1.0
        elif gm >= 20:
            d.gross_margin_level = 0.5

        # 2. Gross Margin Stability (0–2) — low std = durable pricing power
        gm_series = self._gm_series(income_stmt)
        if len(gm_series) >= 3:
            gm_std = float(gm_series.std())
            if gm_std <= 3:
                d.gross_margin_stability = 2.0
            elif gm_std <= 8:
                d.gross_margin_stability = 1.0
            elif gm_std <= 15:
                d.gross_margin_stability = 0.5

        # 3. ROIC Sustained (0–2) — high average ROIC = capital allocation moat
        roic_avg = self._avg_roic(income_stmt, balance_sheet)
        if roic_avg is not None:
            if roic_avg >= 20:
                d.roic_sustained = 2.0
            elif roic_avg >= 12:
                d.roic_sustained = 1.0
            elif roic_avg >= 8:
                d.roic_sustained = 0.5

        # 4. Revenue Defensiveness (0–2) — zero negative-growth years = resilient demand
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

        # 5. FCF Conversion (0–2) — OCF / Net Income > 1 means earnings backed by cash
        fcf_conv = self._fcf_conversion(income_stmt, cashflow)
        if fcf_conv is not None:
            if fcf_conv >= 1.2:
                d.fcf_conversion = 2.0
            elif fcf_conv >= 0.9:
                d.fcf_conversion = 1.0
            elif fcf_conv >= 0.6:
                d.fcf_conversion = 0.5

        # 6. FCF Margin (0–2) — FCF / Revenue: high = scalable business model
        fcf_margin = self._fcf_margin(income_stmt, cashflow)
        if fcf_margin is not None:
            if fcf_margin >= 20:
                d.fcf_margin = 2.0
            elif fcf_margin >= 10:
                d.fcf_margin = 1.0
            elif fcf_margin >= 5:
                d.fcf_margin = 0.5

        d.quant_total = round(
            d.gross_margin_level + d.gross_margin_stability +
            d.roic_sustained + d.revenue_defensiveness +
            d.fcf_conversion + d.fcf_margin, 1
        )

    # ------------------------------------------------------------------ #
    #  AI prompt + call + parse                                            #
    # ------------------------------------------------------------------ #

    def _build_prompt(self, quant: MoatDetail, symbol: str, info: dict) -> str:
        name = info.get("longName", symbol)
        sector = info.get("sector", "Unknown")
        industry = info.get("industry", "Unknown")
        country = info.get("country", "Unknown")
        summary = (info.get("longBusinessSummary") or "")[:600]

        return f"""Sos un analista de inversiones especializado en ventajas competitivas (economic moat).

EMPRESA: {name} ({symbol})
SECTOR: {sector} | INDUSTRIA: {industry} | PAÍS: {country}
DESCRIPCIÓN: {summary}

MOAT CUANTITATIVO (ya calculado):
  Gross Margin nivel:       {quant.gross_margin_level}/2
  Gross Margin estabilidad: {quant.gross_margin_stability}/2
  ROIC sostenido:           {quant.roic_sustained}/2
  Revenue defensividad:     {quant.revenue_defensiveness}/2
  FCF Conversion:           {quant.fcf_conversion}/2
  FCF Margin:               {quant.fcf_margin}/2
  TOTAL CUANTITATIVO:       {quant.quant_total}/12

TAREA: Evaluá los 4 factores cualitativos de moat.
Usá solo estos valores: 0.0, 0.5, 1.0, 1.5 o 2.0 para cada uno.
  - brand_strength:   fuerza y reconocimiento de marca (ej: Apple=2.0, empresa local=0.0)
  - network_effects:  valor que aumenta con más usuarios (ej: Visa=2.0, commodity=0.0)
  - switching_costs:  costo de cambiar de proveedor (ej: SAP=2.0, genérico=0.0)
  - regulatory_ip:    patentes, licencias o regulación protectora (ej: farmacéutica con patentes=2.0)

Considerá el contexto del país (regulación local, riesgo macro) si aplica.

Respondé SOLO con JSON válido (sin markdown, sin texto extra):
{{
  "brand_strength": 0.0,
  "network_effects": 0.0,
  "switching_costs": 0.0,
  "regulatory_ip": 0.0,
  "reasoning": "Párrafo conciso explicando los factores cualitativos del moat de {symbol}"
}}"""

    def _call_api(self, prompt: str, ai_config: AIConfig) -> str:
        provider = ai_config.provider.lower()

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
            try:
                import sys
                from pathlib import Path
                hermes_path = Path.home() / ".hermes" / "hermes-agent"
                if str(hermes_path) not in sys.path:
                    sys.path.insert(0, str(hermes_path))
                from hermes_cli.auth import resolve_xai_oauth_runtime_credentials
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
            except ImportError:
                raise RuntimeError(
                    "Hermes OAuth not available. Install hermes-agent or use a different provider."
                )

        raise ValueError(f"Unknown AI provider: {provider}")

    def _parse_ai_response(self, raw: str) -> dict:
        """Parse JSON from AI response, stripping markdown fences if present."""
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(line for line in lines if not line.startswith("```"))
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                data = json.loads(match.group())
            else:
                raise ValueError(f"Could not parse JSON from AI response: {text[:200]}")
        for key in ("brand_strength", "network_effects", "switching_costs", "regulatory_ip"):
            if key in data:
                data[key] = max(0.0, min(2.0, float(data[key])))
        return data

    # ------------------------------------------------------------------ #
    #  Classification                                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _classify(total: float) -> str:
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
        try:
            return float(val or 0) * 100
        except (TypeError, ValueError):
            return 0.0

    def _row_series(self, df: pd.DataFrame, candidates: list) -> pd.Series:
        if df is None or df.empty:
            return pd.Series(dtype=float)
        for name in candidates:
            if name in df.index:
                s = df.loc[name].dropna()
                s.index = pd.to_datetime(s.index)
                return s.sort_index().astype(float)
        return pd.Series(dtype=float)

    def _gm_series(self, income_stmt: pd.DataFrame) -> pd.Series:
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
            nopat = ebit_s[common] * 0.79  # (1 − 0.21 tax)
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
