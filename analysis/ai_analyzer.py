"""
AI-powered investment decision engine.

Replaces the rule-based RetirementStrategy with an LLM that receives all
fundamental + technical data as context and returns a structured decision
with free-form qualitative reasoning.

Supports Claude (Anthropic) and GPT-4o (OpenAI). Falls back to the
rule-based engine if the API call fails.
"""

import json

from loguru import logger

from analysis.fundamental import FundamentalResult
from analysis.strategy import Decision, RetirementStrategy
from analysis.technical import TechnicalResult
from analysis.utils import extract_json_object

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
            logger.warning(f"{fund.symbol}: AI analysis failed ({type(exc).__name__}: {exc}), falling back to rule-based engine")
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

    # ------------------------------------------------------------------ #
    #  Fase D: Plan-level narrative + macro risks (saved snapshot)        #
    # ------------------------------------------------------------------ #

    def generate_plan_narrative(self, snapshot, refreshed: dict | None = None) -> dict:
        """
        Explain a saved retirement plan (a ``PlanSnapshot``) in human Spanish
        and surface the 0-2 macro factors most likely to break it.

        Returns ``{"narrative": str, "macro_risks": list[dict]}``. Always returns
        a valid dict — on any failure the narrative carries a helpful message and
        ``macro_risks`` is empty, so the no-AI path of the app keeps working.

        ``refreshed`` is the optional output of
        ``data.plan_context.compute_plan_vs_reality`` (today's prices vs. save).
        """
        from analysis.prompts import plan_level_narrative_prompt

        prompt = plan_level_narrative_prompt(
            plan_name=getattr(snapshot, "name", "Mi Plan"),
            profile_name=getattr(snapshot, "profile_name", "") or "Moderado",
            personal=getattr(snapshot, "personal", None),
            metrics=getattr(snapshot, "metrics", {}) or {},
            core_holdings=getattr(snapshot, "core_holdings", []) or [],
            allocation=getattr(snapshot, "allocation", []) or [],
            sector_weights=getattr(snapshot, "sector_weights", {}) or {},
            goals=getattr(snapshot, "goals", []) or [],
            mc_summary=getattr(snapshot, "mc_summary", None),
            refreshed=refreshed,
            withdrawal_strategy=getattr(snapshot, "withdrawal_strategy", None),
        )

        try:
            raw = self._call_api(prompt, max_tokens=1800)
            text = raw.strip()
            if text.startswith("```"):
                parts = text.split("```")
                text = parts[1] if len(parts) > 1 else text
                text = text.strip()
                if text.lower().startswith("json"):
                    text = text[4:].strip()

            # Parse the JSON contract; if the model returned plain prose instead,
            # salvage the whole text as the narrative rather than failing.
            try:
                data = extract_json_object(text)
            except Exception:
                data = {}
            narrative = (data.get("narrative") or "").strip()
            macro = data.get("macro_risks") or []
            # Normalise macro entries to {factor, why, severity}, cap at 2.
            clean_macro = []
            for m in macro[:2]:
                if isinstance(m, dict) and m.get("factor"):
                    clean_macro.append({
                        "factor":   str(m.get("factor", ""))[:120],
                        "why":      str(m.get("why", ""))[:400],
                        "severity": str(m.get("severity", "media")).lower(),
                    })
            if not narrative:
                # Model returned JSON without a narrative — treat raw text as the narrative.
                narrative = text
            return {"narrative": narrative, "macro_risks": clean_macro}

        except Exception as exc:
            logger.warning(f"Plan narrative generation failed: {exc}")
            return {
                "narrative": (
                    "No se pudo generar la explicación con IA en este momento. "
                    "Revisá que AI esté habilitado en Settings con una API key válida."
                ),
                "macro_risks": [],
            }

    def generate_optimizer_advice(
        self,
        opt_result,
        goals: list | None = None,
        current_weights: dict | None = None,
    ) -> dict:
        """
        Generate Grok voice + human-manageable concentration advice for a
        full portfolio optimization result.

        Always returns a valid dict — the core_holdings key is populated
        from the deterministic profile_core_holdings on the result when the
        LLM call fails or is skipped (N too large / no AI key).

        For N > 30, only the top-15 holdings by weight are sent to the LLM.
        For N > 45, the LLM narrative is skipped entirely but the deterministic
        core (already on the result object) is still surfaced.
        """
        from analysis.prompts import portfolio_optimizer_advice_prompt

        tickers = getattr(opt_result, "tickers", []) or []
        holdings = []
        for t in tickers:
            holdings.append({
                "symbol":             getattr(t, "symbol", "?"),
                "weight_pct":         float(getattr(t, "weight_pct", 0.0) or 0.0),
                "adjusted_score":     float(getattr(t, "adjusted_score", 0.0) or 0.0),
                "moat_score":         float(getattr(t, "moat_score", 0.0) or 0.0),
                "dividend_yield_pct": float(getattr(t, "dividend_yield_pct", 0.0) or 0.0),
                "expected_return_pct":float(getattr(t, "expected_return_pct", 0.0) or 0.0),
                "volatility_pct":     float(getattr(t, "volatility_pct", 0.0) or 0.0),
                "sector":             getattr(t, "sector", ""),
                "is_ars":             bool(getattr(t, "is_ars", False)),
                "tailwind_score":          float(getattr(t, "tailwind_score", 0.0) or 0.0),
                "tailwind_classification": str(getattr(t, "tailwind_classification", "Neutral") or "Neutral"),
            })

        num_pos = len(holdings)
        sector_w = getattr(opt_result, "sector_weights", {}) or {}

        # Deterministic core — always available regardless of LLM status
        det_core = list(getattr(opt_result, "profile_core_holdings", []) or [])

        # For huge results skip the LLM entirely; deterministic core already covers the user need.
        if num_pos > 45:
            narrative = (
                f"La optimización produjo {num_pos} posiciones. "
                "Para carteras tan grandes la narrativa IA detallada no es práctica "
                "(el universo seleccionado excede el rango óptimo). "
                "Se muestra abajo la cartera núcleo calculada automáticamente por el perfil "
                f"({len(det_core)} posiciones) — sin necesidad de Grok."
            )
            return {
                "narrative":                      narrative,
                "recommended_max_human_positions": len(det_core) or 12,
                "core_holdings":                   det_core,
                "dropped_tickers":                 [],
                "human_review_tips": [
                    "Reducí el universo o aplicá un perfil más conservador para obtener menos posiciones.",
                    "La cartera núcleo de arriba ya filtra automáticamente los mejores holdings por perfil.",
                ],
                "overall_assessment": "Núcleo generado por reglas del perfil (sin LLM).",
            }

        # Truncate to top-15 for the prompt (bounds token size for 16-45 pos results)
        if num_pos > 15:
            holdings_for_prompt = sorted(holdings, key=lambda h: -h["weight_pct"])[:15]
            holdings_note = (
                f" (se muestran solo las 15 de mayor peso; "
                f"las otras {num_pos - 15} son posiciones pequeñas)"
            )
        else:
            holdings_for_prompt = holdings
            holdings_note = ""

        profile_name = getattr(opt_result, "profile_name", "Moderado")
        max_pos = 8.0
        min_pos = 8
        max_vol = 18.0
        min_div = 2.5
        max_crypto = 5.0
        reb_rat = getattr(opt_result, "rebalance_rationale", "") or ""
        warns = getattr(opt_result, "warnings", []) or []

        prompt = portfolio_optimizer_advice_prompt(
            profile_name=profile_name,
            holdings=holdings_for_prompt,
            expected_return_pct=float(getattr(opt_result, "expected_return_pct", 0.0) or 0.0),
            volatility_pct=float(getattr(opt_result, "volatility_pct", 0.0) or 0.0),
            sharpe=float(getattr(opt_result, "sharpe_ratio", 0.0) or 0.0),
            dividend_yield_pct=float(getattr(opt_result, "dividend_yield_pct", 0.0) or 0.0),
            moat_avg=float(getattr(opt_result, "moat_score_avg", 0.0) or 0.0),
            num_positions=num_pos,
            sector_weights=sector_w,
            max_position_pct=max_pos,
            min_positions=min_pos,
            max_volatility_pct=max_vol,
            min_dividend_yield_pct=min_div,
            max_crypto_pct=max_crypto,
            goal_explanation="",
            rebalance_rationale=reb_rat,
            warnings=warns,
            holdings_note=holdings_note,
        )

        try:
            raw = self._call_api(prompt, max_tokens=2500)
            text = raw.strip()
            if text.startswith("```"):
                parts = text.split("```")
                text = parts[1] if len(parts) > 1 else text
                text = text.strip()
                if text.lower().startswith("json"):
                    text = text[4:].strip()

            data = extract_json_object(text)

            data.setdefault("narrative", "")
            data.setdefault("recommended_max_human_positions", max(5, min(20, num_pos)))
            # If LLM returned empty core, fall back to deterministic
            if not data.get("core_holdings"):
                data["core_holdings"] = det_core
            data.setdefault("dropped_tickers", [])
            data.setdefault("human_review_tips", [])
            data.setdefault("overall_assessment", "")
            data.setdefault("macro_factors", [])

            try:
                n = int(data.get("recommended_max_human_positions", num_pos))
                data["recommended_max_human_positions"] = max(3, min(25, n))
            except Exception:
                data["recommended_max_human_positions"] = max(5, min(15, num_pos))

            return data

        except Exception as exc:
            logger.warning(f"Optimizer Grok advice generation failed: {exc}")
            err_str = str(exc)
            # Classify the error for a more helpful message
            if any(kw in err_str.lower() for kw in ("rate limit", "429", "quota", "too many")):
                narrative = (
                    "Grok/xAI está con rate limit en este momento. "
                    "Se muestra abajo la cartera núcleo calculada automáticamente por el perfil."
                )
            elif "incomplete json" in err_str.lower() or "unmatched" in err_str.lower():
                narrative = (
                    "La respuesta del modelo no fue JSON válido (posiblemente truncada). "
                    "Se muestra el núcleo determinístico mientras tanto."
                )
            elif "api key" in err_str.lower() or "auth" in err_str.lower():
                narrative = (
                    "API key inválida o sin permisos. "
                    "Verificá la configuración en Settings. "
                    "Se muestra el núcleo determinístico."
                )
            else:
                narrative = (
                    "No se pudo generar la narrativa IA en este momento. "
                    f"({err_str[:150]}) "
                    "Se muestra el núcleo calculado por el optimizador."
                )
            return {
                "narrative":                      narrative,
                "recommended_max_human_positions": len(det_core) or max(5, min(12, num_pos)),
                "core_holdings":                   det_core,
                "dropped_tickers":                 [],
                "human_review_tips":               [],
                "overall_assessment":              "Núcleo generado por reglas del perfil (Grok no disponible).",
            }

    def _call_api(self, prompt: str, max_tokens: int | None = None) -> str:
        if self.config.provider == "claude":
            return self._call_claude(prompt, max_tokens)
        elif self.config.provider == "openai":
            return self._call_openai(prompt, max_tokens)
        elif self.config.provider == "nous":
            return self._call_nous(prompt, max_tokens)
        elif self.config.provider == "xai":
            return self._call_xai(prompt, max_tokens)
        else:
            raise ValueError(f"Unknown AI provider: {self.config.provider}")

    def _call_claude(self, prompt: str, max_tokens: int | None = None) -> str:
        import anthropic
        client = anthropic.Anthropic(api_key=self.config.api_key)
        mt = max_tokens or 1024
        message = client.messages.create(
            model=self.config.model,
            max_tokens=mt,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text

    def _call_openai(self, prompt: str, max_tokens: int | None = None) -> str:
        from openai import OpenAI
        client = OpenAI(api_key=self.config.api_key)
        mt = max_tokens or 1024
        response = client.chat.completions.create(
            model=self.config.model,
            temperature=0,
            max_tokens=mt,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content

    def _call_nous(self, prompt: str, max_tokens: int | None = None) -> str:
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
        mt = max_tokens or 1024
        response = client.chat.completions.create(
            model=self.config.model,
            temperature=0,
            max_tokens=mt,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content

    def _call_xai(self, prompt: str, max_tokens: int | None = None) -> str:
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
        mt = max_tokens or 1024
        response = client.chat.completions.create(
            model=self.config.model,
            temperature=0,
            max_tokens=mt,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content

    def _parse_response(self, raw: str, fund: FundamentalResult, tech: TechnicalResult) -> Decision:
        try:
            data = extract_json_object(raw)
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"Could not extract JSON from AI response: {exc} — raw[:300]={raw[:300]!r}") from exc

        action = data.get("action", "HOLD").upper()
        valid_actions = {"STRONG BUY", "BUY", "HOLD", "REDUCE", "SELL"}
        if action not in valid_actions:
            action = "HOLD"

        # For crypto, use adjusted_score (total_score is always 0)
        score = fund.adjusted_score if getattr(fund, "is_crypto", False) else fund.total_score

        _alloc = None
        try:
            _alloc_raw = data.get("recommended_max_allocation_conservative")
            if _alloc_raw is not None:
                _alloc = float(_alloc_raw)
        except (TypeError, ValueError):
            pass

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
            recommended_max_allocation_pct=_alloc,
            macro_factors=data.get("macro_factors", []) or [],
        )
