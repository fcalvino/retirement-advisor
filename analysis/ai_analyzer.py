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
        """Delegate to the centralized prompt library."""
        if getattr(fund, "is_crypto", False):
            from analysis.prompts import crypto_decision_prompt
            return crypto_decision_prompt(fund, tech)
        from analysis.prompts import equity_decision_prompt
        return equity_decision_prompt(fund, tech)

    # ------------------------------------------------------------------ #
    #  Phase 0: Long-term plan narrative (portfolio-level explanation)    #
    # ------------------------------------------------------------------ #

    def generate_long_term_narrative(self, context: dict) -> str:
        """
        Generate a human-readable, conservative narrative for a long-term
        investment plan using the current optimizer + Monte Carlo results.
        `context` must contain the keys expected by long_term_plan_narrative_prompt.
        """
        from analysis.prompts import long_term_plan_narrative_prompt

        prompt = long_term_plan_narrative_prompt(
            profile_name=context.get("profile_name", "Moderado"),
            tickers=context.get("tickers", []),
            weights=context.get("weights", []),
            expected_return=context.get("expected_return", 0.0),
            volatility=context.get("volatility", 0.0),
            sharpe=context.get("sharpe", 0.0),
            dividend_yield=context.get("dividend_yield", 0.0),
            horizon_years=context.get("horizon_years", 15),
            initial_value=context.get("initial_value", 100_000),
            annual_withdrawal=context.get("annual_withdrawal", 0),
            inflation_rate=context.get("inflation_rate", 3.0),
            median_terminal=context.get("median_terminal", 0),
            p10_terminal=context.get("p10_terminal", 0),
            p90_terminal=context.get("p90_terminal", 0),
            prob_ruin=context.get("prob_ruin", 0),
            prob_target=context.get("prob_target", 0),
            target_value=context.get("target_value", 0),
        )

        try:
            raw = self._call_api(prompt)
            # Clean up common LLM artifacts
            text = raw.strip()
            if text.startswith("```"):
                text = text.split("```")[1].strip()
            return text
        except Exception as exc:
            logger.warning(f"Long-term narrative generation failed: {exc}")
            return (
                "No se pudo generar la explicación con IA en este momento. "
                "Revisá que AI esté habilitado en Settings con una API key válida."
            )

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
