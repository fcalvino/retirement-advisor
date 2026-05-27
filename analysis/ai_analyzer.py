"""
AI-powered investment decision engine.

Replaces the rule-based RetirementStrategy with an LLM that receives all
fundamental + technical data as context and returns a structured decision
with free-form qualitative reasoning.

Supports Claude (Anthropic) and GPT-4o (OpenAI). Falls back to the
rule-based engine if the API call fails.
"""

import json
import re

from loguru import logger

from analysis.fundamental import FundamentalResult
from analysis.strategy import Decision, RetirementStrategy
from analysis.technical import TechnicalResult

# Argentine ADR tickers — flag for emerging market context in the prompt
ARGENTINA_ADRS = {"YPF", "PAM", "CEPU", "LOMA", "MELI", "GLOB", "DESP", "TEO", "EDN", "GGAL", "BMA", "BBAR", "SUPV"}


class AIAnalyzer:
    def __init__(self, config):
        self.config = config

    def analyze(self, fund: FundamentalResult, tech: TechnicalResult) -> Decision:
        try:
            prompt = self._build_prompt(fund, tech)
            raw = self._call_api(prompt)
            decision = self._parse_response(raw, fund, tech)
            logger.info(f"{fund.symbol}: AI decision = {decision.action} ({self.config.provider}/{self.config.model})")
            return decision
        except Exception as exc:
            logger.warning(f"{fund.symbol}: AI analysis failed ({exc}), falling back to rule-based engine")
            return RetirementStrategy().decide(fund, tech)

    def _build_prompt(self, fund: FundamentalResult, tech: TechnicalResult) -> str:
        # Route to crypto-specific prompt when the result comes from CryptoAnalyzer
        if getattr(fund, "is_crypto", False):
            return self._build_crypto_prompt(fund, tech)

        def fmt(val, suffix="", decimals=1):
            if val is None:
                return "N/A"
            return f"{val:.{decimals}f}{suffix}"

        country_context = ""
        if fund.symbol in ARGENTINA_ADRS:
            country_context = (
                "CONTEXTO PAÍS: Argentina (mercado emergente). "
                "Considerar: controles de capital, inflación estructural, riesgo regulatorio estatal, "
                "subsidios energéticos, y que los reportes financieros están en USD pero el negocio opera en ARS. "
                "Los márgenes bajos pueden reflejar regulación, no ineficiencia operativa."
            )

        prompt = f"""Sos un analista de inversiones senior especializado en carteras de retiro a largo plazo (horizonte 10-30 años). Tu enfoque es conservador: preservación de capital primero, crecimiento de calidad segundo.

Analizá la siguiente acción y devolvé una recomendación de inversión.

EMPRESA: {fund.company_name} ({fund.symbol})
SECTOR: {fund.sector} | INDUSTRIA: {fund.industry}
PRECIO: ${fmt(fund.current_price, decimals=2)} | MARKET CAP: ${(fund.market_cap or 0)/1e9:.1f}B
{country_context}

--- ANÁLISIS FUNDAMENTAL ---
Profitability ({fund.profitability_score:.0f}/25):
  ROE={fmt(fund.roe, "%")} | ROIC={fmt(fund.roic, "%")} | Net Margin={fmt(fund.net_margin, "%")} | Gross Margin={fmt(fund.gross_margin, "%")}

Financial Health ({fund.health_score:.0f}/20):
  Deuda/Equity={fmt(fund.debt_equity, "x")} | Current Ratio={fmt(fund.current_ratio)} | Interest Coverage={fmt(fund.interest_coverage, "x")}

Valuation ({fund.valuation_score:.0f}/25):
  P/E={fmt(fund.pe_ratio, "x")} | PEG={fmt(fund.peg_ratio)} | EV/EBITDA={fmt(fund.ev_ebitda, "x")} | P/B={fmt(fund.pb_ratio, "x")}

Growth ({fund.growth_score:.0f}/20):
  Revenue CAGR 5Y={fmt(fund.revenue_cagr_5y, "%")} | EPS CAGR={fmt(fund.eps_cagr_5y, "%")} | FCF Yield={fmt(fund.fcf_yield, "%")}

Dividends ({fund.dividend_score:.0f}/10):
  Yield={fmt(fund.dividend_yield, "%")} | Payout={fmt(fund.payout_ratio, "%")}

Graham Value: ${fmt(fund.graham_value, decimals=2)} | Margen de Seguridad: {fmt(fund.margin_of_safety_pct, "%")}
Score total (rule-based): {fund.total_score:.1f}/100

Alertas detectadas: {", ".join(fund.warnings) if fund.warnings else "ninguna"}

--- ANÁLISIS TÉCNICO (barras semanales, largo plazo) ---
Señal: {tech.signal} (fuerza: {tech.signal_strength:+d}/100)
Tendencia: precio {"ENCIMA" if tech.above_sma200 else "DEBAJO"} de SMA200 | SMA200 slope 26w: {tech.sma200_slope_pct:+.1f}%
Momentum: RSI={fmt(tech.rsi_weekly)} | MACD={"alcista" if tech.macd_bullish else "bajista"} | ADX={fmt(tech.adx)}
Contexto: {tech.price_vs_52w_high_pct:+.1f}% desde 52w high | {tech.price_vs_52w_low_pct:+.1f}% desde 52w low

--- INSTRUCCIÓN ---
Teniendo en cuenta todos los datos anteriores y el contexto cualitativo del negocio y el país, emití tu recomendación.
Respondé ÚNICAMENTE con un JSON válido con esta estructura exacta:

{{
  "action": "STRONG BUY|BUY|HOLD|REDUCE|SELL",
  "confidence": "HIGH|MEDIUM|LOW",
  "rationale": ["factor positivo 1", "factor positivo 2"],
  "risks": ["riesgo 1", "riesgo 2"],
  "reasoning": "Párrafo de análisis completo en español, incluyendo contexto cualitativo del negocio, sector y país."
}}"""
        return prompt

    def _call_api(self, prompt: str) -> str:
        if self.config.provider == "claude":
            return self._call_claude(prompt)
        elif self.config.provider == "openai":
            return self._call_openai(prompt)
        elif self.config.provider == "nous":
            return self._call_nous(prompt)
        elif self.config.provider == "xai":
            return self._call_xai(prompt)
        else:
            raise ValueError(f"Unknown AI provider: {self.config.provider}")

    def _call_claude(self, prompt: str) -> str:
        import anthropic
        client = anthropic.Anthropic(api_key=self.config.api_key)
        message = client.messages.create(
            model=self.config.model,
            max_tokens=1024,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text

    def _call_openai(self, prompt: str) -> str:
        from openai import OpenAI
        client = OpenAI(api_key=self.config.api_key)
        response = client.chat.completions.create(
            model=self.config.model,
            temperature=0,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content

    def _call_nous(self, prompt: str) -> str:
        import os
        import sys

        from openai import OpenAI

        # Resolve credentials: prefer local Hermes OAuth session, fall back to explicit API key
        api_key = self.config.api_key
        base_url = "https://inference-api.nousresearch.com/v1"

        hermes_path = os.path.expanduser("~/.hermes/hermes-agent")
        if os.path.isdir(hermes_path) and hermes_path not in sys.path:
            sys.path.insert(0, hermes_path)

        try:
            from hermes_cli.auth import resolve_nous_runtime_credentials
            creds = resolve_nous_runtime_credentials()
            api_key = creds["api_key"]
            base_url = creds.get("base_url", base_url).rstrip("/")
        except Exception:
            if not api_key:
                raise RuntimeError(
                    "No Nous credentials found. Run `hermes login` or provide a NOUS_API_KEY."
                )

        client = OpenAI(api_key=api_key, base_url=base_url)
        response = client.chat.completions.create(
            model=self.config.model,
            temperature=0,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content

    def _call_xai(self, prompt: str) -> str:
        import os
        import sys

        from openai import OpenAI

        api_key = self.config.api_key
        base_url = "https://api.x.ai/v1"

        hermes_path = os.path.expanduser("~/.hermes/hermes-agent")
        if os.path.isdir(hermes_path) and hermes_path not in sys.path:
            sys.path.insert(0, hermes_path)

        try:
            from hermes_cli.auth import resolve_xai_oauth_runtime_credentials
            creds = resolve_xai_oauth_runtime_credentials()
            api_key = creds["api_key"]
            base_url = creds.get("base_url", base_url).rstrip("/")
        except Exception:
            if not api_key:
                raise RuntimeError(
                    "No xAI credentials found. Run `hermes auth add xai-oauth` or provide an XAI_API_KEY."
                )

        client = OpenAI(api_key=api_key, base_url=base_url)
        response = client.chat.completions.create(
            model=self.config.model,
            temperature=0,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content

    def _build_crypto_prompt(self, fund: FundamentalResult, tech: TechnicalResult) -> str:
        """
        Investment decision prompt for Bitcoin / crypto assets.

        Replaces the equity prompt entirely.  No financial ratios are shown —
        they don't apply.  Instead the context focuses on:
          - Technical signal (price momentum, trend)
          - Crypto moat (if AI-computed)
          - Volatility / drawdown risk for retirement portfolios
          - Halving cycle & macro context

        Output JSON schema is identical to the equity prompt so _parse_response()
        needs no changes.
        """
        def fmt(val, suffix="", decimals=1):
            if val is None:
                return "N/D"
            return f"{val:.{decimals}f}{suffix}"

        moat = fund.crypto_moat_detail
        moat_section = ""
        if moat and getattr(moat, "ai_available", False):
            moat_section = f"""
--- MOAT CRYPTO (AI) — {moat.classification} ({moat.total:.1f}/8) ---
  Efecto de red y adopción:         {moat.network_adoption}/2
  Escasez monetaria (halving):      {moat.monetary_scarcity}/2
  Seguridad y descentralización:    {moat.security_decentralization}/1.5
  Institucional y regulatorio:      {moat.institutional_regulatory}/1.5
  Resiliencia tecnológica:          {moat.tech_resilience}/1
  Razonamiento: {moat.ai_reasoning}"""

        # Extract crypto notes from fund.notes
        vol_note   = fund.notes.get("crypto_vol", "N/D")
        dd_note    = fund.notes.get("crypto_dd", "N/D")
        cagr_note  = fund.notes.get("crypto_cagr", "N/D")
        supply_note = fund.notes.get("crypto_supply", "N/D")
        halving_note = fund.notes.get("crypto_halving", "N/D")

        warnings_str = ", ".join(fund.warnings) if fund.warnings else "ninguna"

        return f"""Sos un analista senior de inversiones especializado en activos digitales y su rol en carteras de retiro a largo plazo (horizonte 10–30 años). Tu enfoque es conservador: preservación de capital primero, exposición a crecimiento de calidad en segundo lugar.

Analizá Bitcoin y emití una recomendación de inversión para un inversor en etapa de retiro o pre-retiro.

ACTIVO: {fund.company_name} ({fund.symbol})
CLASE: Criptomoneda / Reserva de Valor Digital
PRECIO: ${fmt(fund.current_price, decimals=0)} | MARKET CAP: ${(fund.market_cap or 0)/1e9:.1f}B USD

--- MÉTRICAS DE RIESGO (críticas para retiro) ---
  {vol_note}
  {dd_note}
  {cagr_note}
  {supply_note}
  {halving_note}

Alertas: {warnings_str}

--- ANÁLISIS TÉCNICO (barras semanales, largo plazo) ---
Señal: {tech.signal} (fuerza: {tech.signal_strength:+d}/100)
Tendencia: precio {"ENCIMA" if tech.above_sma200 else "DEBAJO"} de SMA200 | SMA200 slope 26w: {tech.sma200_slope_pct:+.1f}%
Momentum: RSI={fmt(tech.rsi_weekly)} | MACD={"alcista" if tech.macd_bullish else "bajista"} | ADX={fmt(tech.adx)}
Contexto: {tech.price_vs_52w_high_pct:+.1f}% desde 52w high | {tech.price_vs_52w_low_pct:+.1f}% desde 52w low
{moat_section}

--- SCORE AJUSTADO (modelo crypto) ---
Score ajustado: {fund.adjusted_score:.1f}/100  (fórmula: base + técnico − volatilidad − drawdown + moat)
Clasificación moat: {fund.moat_classification}

--- CONTEXTO PARA RETIRO CONSERVADOR ---
Bitcoin es un activo de alta volatilidad con drawdowns históricos del 70–85%. Para carteras de retiro conservadoras, el peso recomendado es del 2–5% máximo. No genera ingresos (dividendos, cupones). Su rol es de cobertura inflacionaria y diversificación, NO de ingreso recurrente. Una posición >5% en retiro representa un riesgo de secuencia desproporcionado.

--- INSTRUCCIÓN ---
Teniendo en cuenta el análisis técnico, el moat crypto, las métricas de riesgo y el perfil de un inversor conservador de retiro, emití tu recomendación.
Un score ≥ 55 puede justificar HOLD con posición pequeña (2–5%). Un score ≥ 65 justificaría BUY sólo en perfiles moderados-agresivos.

Respondé ÚNICAMENTE con un JSON válido con esta estructura exacta:
{{
  "action": "STRONG BUY|BUY|HOLD|REDUCE|SELL",
  "confidence": "HIGH|MEDIUM|LOW",
  "rationale": ["factor positivo 1", "factor positivo 2"],
  "risks": ["riesgo 1", "riesgo 2", "riesgo de secuencia para retiro"],
  "reasoning": "Párrafo completo en español: evaluá el momentum técnico, el moat crypto, el riesgo de volatilidad para el perfil de retiro, y el peso máximo recomendado en portafolio."
}}"""

    def _parse_response(self, raw: str, fund: FundamentalResult, tech: TechnicalResult) -> Decision:
        # Extract JSON from response (may have surrounding text)
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise ValueError("No JSON found in AI response")

        data = json.loads(match.group())

        action = data.get("action", "HOLD").upper()
        valid_actions = {"STRONG BUY", "BUY", "HOLD", "REDUCE", "SELL"}
        if action not in valid_actions:
            action = "HOLD"

        # For crypto, use adjusted_score (total_score is always 0)
        score = fund.adjusted_score if getattr(fund, "is_crypto", False) else fund.total_score

        return Decision(
            symbol=fund.symbol,
            action=action,
            confidence=data.get("confidence", "MEDIUM").upper(),
            fundamental_score=score,
            technical_signal=tech.signal,
            has_margin_of_safety=fund.is_value_stock(),
            rationale=data.get("rationale", []),
            risks=data.get("risks", []),
            ai_reasoning=data.get("reasoning", ""),
        )
