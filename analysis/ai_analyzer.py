"""
AI-powered investment decision engine.

Replaces the rule-based RetirementStrategy with an LLM that receives all
fundamental + technical data as context and returns a structured decision
with free-form qualitative reasoning.

Supports Claude (Anthropic) and GPT-4o (OpenAI). Falls back to the
rule-based engine if the API call fails.
"""

import json
import os
import sys
from typing import Callable

from loguru import logger

from analysis.fundamental import FundamentalResult
from analysis.strategy import (
    Decision,
    RetirementStrategy,
    apply_safety_overlay,
    effective_decision_score,
)
from analysis.technical import TechnicalResult
from analysis.utils import extract_json_object
from config import (
    AI_DECISION_MAX_TOKENS,
    AI_FALLBACK,
    AI_OAUTH_PROVIDERS,
    GROQ_BASE_URL,
    GROQ_TRANSPORT,
)


class AIUnavailable(RuntimeError):
    """The AI layer could not run, with the cause already classified.

    Carries an ``AIFallbackConfig`` slug so the caller does not have to
    re-derive from a message string what the pre-flight check already knew.
    """

    def __init__(self, cause: str):
        super().__init__(cause)
        self.cause = cause


# HTTP status → cause. The SDKs (anthropic, openai) all expose `status_code`,
# so this covers both without importing either one.
_STATUS_TO_CAUSE = {
    400: AI_FALLBACK.PARAMETRO_RECHAZADO,
    401: AI_FALLBACK.KEY_INVALIDA,
    403: AI_FALLBACK.KEY_INVALIDA,
    429: AI_FALLBACK.RATE_LIMIT,
}

# Fallback when the error travels without a status code (wrapped, re-raised,
# or raised by a transport shim). Typed first, strings last — see §3 of the plan.
_EXC_NAME_TO_CAUSE = {
    "AuthenticationError":  AI_FALLBACK.KEY_INVALIDA,
    "PermissionDeniedError": AI_FALLBACK.KEY_INVALIDA,
    "BadRequestError":      AI_FALLBACK.PARAMETRO_RECHAZADO,
    "UnprocessableEntityError": AI_FALLBACK.PARAMETRO_RECHAZADO,
    "RateLimitError":       AI_FALLBACK.RATE_LIMIT,
}


def classify_ai_failure(exc: BaseException) -> str:
    """Map an exception raised by the AI layer to an ``AI_FALLBACK`` cause slug.

    Pure and testable. Order matters: the SDK's own typing is preferred over
    string matching, which is only the last resort.
    """
    if isinstance(exc, AIUnavailable):
        return exc.cause

    # 1. status_code by duck-typing (covers anthropic and openai alike)
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    try:
        status = int(status) if status is not None else None
    except (TypeError, ValueError):
        status = None
    if status is not None and status in _STATUS_TO_CAUSE:
        return _STATUS_TO_CAUSE[status]

    # 2. class name, for errors that arrive without a status code
    for klass in type(exc).__mro__:
        cause = _EXC_NAME_TO_CAUSE.get(klass.__name__)
        if cause:
            return cause

    # 3. unparseable model output
    text = str(exc).lower()
    if isinstance(exc, (json.JSONDecodeError, ValueError)):
        return AI_FALLBACK.JSON_INVALIDO
    if "incomplete json" in text or "unmatched" in text or "json" in text:
        return AI_FALLBACK.JSON_INVALIDO

    # 4. last-resort string heuristics, kept only for transports that raise
    #    plain RuntimeErrors (the Hermes credential resolver, for one).
    if any(kw in text for kw in ("rate limit", "429", "quota", "too many")):
        return AI_FALLBACK.RATE_LIMIT
    if "api key" in text or "auth" in text or "credential" in text:
        return AI_FALLBACK.KEY_INVALIDA

    return AI_FALLBACK.OTRO


def resolve_optimizer_profile(profile_name: str | None = None):
    """Map OptimizationResult.profile_name (or key) → ProfileConfig (P1 D13).

    Pure helper so optimizer-advice prompts use real profile constraints
    instead of hard-coded moderate/conservative defaults.
    """
    from config import CONSERVATIVE_PROFILE, OPTIMIZER_PROFILES

    raw = (profile_name or "").strip().lower()
    if not raw:
        return CONSERVATIVE_PROFILE

    for key, cfg in OPTIMIZER_PROFILES.items():
        if key == raw or cfg.name.lower() == raw:
            return cfg

    # Fuzzy Spanish/English fragments
    if "agres" in raw or "aggress" in raw:
        return OPTIMIZER_PROFILES.get("aggressive", CONSERVATIVE_PROFILE)
    if "moder" in raw:
        return OPTIMIZER_PROFILES.get("moderate", CONSERVATIVE_PROFILE)
    if "conserv" in raw:
        return OPTIMIZER_PROFILES.get("conservative", CONSERVATIVE_PROFILE)

    return CONSERVATIVE_PROFILE


def _strip_code_fence(text: str) -> str:
    """Remove ```[json] fences from LLM output. Safe when fence has no content."""
    text = text.strip()
    if not text.startswith("```"):
        return text
    parts = text.split("```")
    inner = parts[1] if len(parts) > 1 else text
    inner = inner.strip()
    if inner.lower().startswith("json"):
        inner = inner[4:].strip()
    return inner


_CLAUDE_STOP_REASON_TO_CAUSE = {
    "max_tokens": AI_FALLBACK.RESPUESTA_TRUNCADA,
    "refusal":    AI_FALLBACK.RECHAZO_MODELO,
}


def _claude_message_text(message) -> str:
    """Texto de una respuesta de Anthropic, o `AIUnavailable` con la causa.

    Pura y testeable: recibe el objeto de respuesta, no el cliente. Chequea
    `stop_reason` **antes** de leer el contenido y toma el primer bloque de tipo
    `text` — con thinking adaptativo el primer bloque no es el texto.
    """
    stop_reason = getattr(message, "stop_reason", None)
    cause = _CLAUDE_STOP_REASON_TO_CAUSE.get(stop_reason or "")
    if cause:
        raise AIUnavailable(cause)

    for block in getattr(message, "content", None) or []:
        if getattr(block, "type", None) == "text":
            return block.text

    # 200 sin bloque de texto: raro, pero es un final propio. Llamarlo «JSON
    # inválido» mandaría al usuario a mirar el prompt por un problema que no
    # está ahí.
    raise AIUnavailable(AI_FALLBACK.RESPUESTA_VACIA)


_OPENAI_FINISH_REASON_TO_CAUSE = {
    "length":     AI_FALLBACK.RESPUESTA_TRUNCADA,
    "max_tokens": AI_FALLBACK.RESPUESTA_TRUNCADA,
    "content_filter": AI_FALLBACK.RECHAZO_MODELO,
}


def _openai_message_text(choice) -> str:
    """Texto de un choice OpenAI-compatible, o `AIUnavailable` con la causa.

    ``finish_reason=length`` y ``content`` vacío se disfrazaban de
    ``json_invalido`` (gpt-oss gasta el techo en ``message.reasoning``).
    """
    finish = getattr(choice, "finish_reason", None)
    cause = _OPENAI_FINISH_REASON_TO_CAUSE.get(finish or "")
    if cause:
        raise AIUnavailable(cause)
    content = getattr(getattr(choice, "message", None), "content", None)
    if content is None or not str(content).strip():
        raise AIUnavailable(AI_FALLBACK.RESPUESTA_VACIA)
    return content


class AIAnalyzer:
    def __init__(self, config):
        self.config = config

    # ------------------------------------------------------------------ #
    #  Failure plumbing — one classification, one log line, one message   #
    # ------------------------------------------------------------------ #

    def _preflight(self) -> None:
        """Raise ``AIUnavailable(SIN_API_KEY)`` before spending a round-trip.

        A missing key is a configuration state, not an exception — classifying it
        after the fact would make it indistinguishable from a 401. `xai`/`nous`
        are skipped: they authenticate through Hermes OAuth, so an empty
        ``api_key`` is their normal, working state (same criterion as
        ``config_validator._hermes_oauth_available``).
        """
        provider = (getattr(self.config, "provider", "") or "").lower()
        if provider in AI_OAUTH_PROVIDERS:
            return
        if not getattr(self.config, "api_key", ""):
            raise AIUnavailable(AI_FALLBACK.SIN_API_KEY)

    def _classify_and_log(self, exc: BaseException, context: str) -> str:
        """Classify `exc`, emit the single warning for it, return the cause slug."""
        cause = classify_ai_failure(exc)
        logger.warning(
            f"{context}: AI fallback — causa={cause} proveedor={self.config.provider} "
            f"({type(exc).__name__}: {exc})"
        )
        return cause

    def _fallback_message(self, cause: str) -> str:
        """User-facing sentence for `cause`, naming the configured provider only."""
        return AI_FALLBACK.message(cause, getattr(self.config, "provider", ""))

    def analyze(self, fund: FundamentalResult, tech: TechnicalResult) -> Decision:
        try:
            self._preflight()
            prompt = self._build_prompt(fund, tech)
            raw = self._call_api(prompt, max_tokens=AI_DECISION_MAX_TOKENS)
            decision = self._parse_response(raw, fund, tech)
            # P0 D1: never let LLM bypass hard safety blocks
            decision = apply_safety_overlay(decision, fund, tech)
            decision.ai_used = True
            decision.ai_provider = self.config.provider
            decision.ai_model = self.config.model
            logger.info(f"{fund.symbol}: AI decision = {decision.action} ({self.config.provider}/{self.config.model})")
            return decision
        except Exception as exc:
            cause = self._classify_and_log(exc, fund.symbol)
            decision = RetirementStrategy().decide(fund, tech)
            # The action is byte-identical to the rule-based engine's; the only
            # thing that changes is that the UI now knows *why* it is showing it.
            decision.ai_fallback_reason = cause
            # ai_used stays False: this verdict came from the rule-based engine, not the LLM.
            # It *is* the engine's verdict, so it doubles as the overlay's floor reference
            # instead of making it recompute decide() (SIGNAL-6).
            return apply_safety_overlay(decision, fund, tech, rule_decision=decision)

    def _build_prompt(self, fund: FundamentalResult, tech: TechnicalResult) -> str:
        """Delegate to the centralized prompt library."""
        if getattr(fund, "is_crypto", False):
            from analysis.prompts import crypto_decision_prompt
            return crypto_decision_prompt(fund, tech)
        from analysis.prompts import equity_decision_prompt
        # #130 paso 4: the macro section is anchored to the dated RAG facts.
        try:
            from analysis.macro_rag import macro_context_for

            macro_ctx = macro_context_for(fund)
        except Exception:
            macro_ctx = ""
        return equity_decision_prompt(fund, tech, macro_ctx)

    # ------------------------------------------------------------------ #
    #  Phase 0: Long-term plan narrative (portfolio-level explanation)    #
    # ------------------------------------------------------------------ #

    def generate_long_term_narrative(self, context: dict) -> dict:
        """
        Generate a human-readable, conservative narrative for a long-term
        investment plan using the current optimizer + Monte Carlo results.
        `context` must contain the keys expected by long_term_plan_narrative_prompt.

        Returns ``{"narrative": str, "ai_fallback_reason": str}``. The reason is
        ``""`` when the LLM produced the narrative and an ``AI_FALLBACK`` cause
        slug when the text is the rule-based explanation instead — aligned with
        ``generate_plan_narrative`` so every surface reads the same key.
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
            self._preflight()
            raw = self._call_api(prompt)
            return {"narrative": _strip_code_fence(raw), "ai_fallback_reason": ""}
        except Exception as exc:
            cause = self._classify_and_log(exc, "long-term narrative")
            return {
                "narrative": self._fallback_message(cause),
                "ai_fallback_reason": cause,
            }

    # ------------------------------------------------------------------ #
    #  Fase D: Plan-level narrative + macro risks (saved snapshot)        #
    # ------------------------------------------------------------------ #

    def generate_plan_narrative(self, snapshot, refreshed: dict | None = None) -> dict:
        """
        Explain a saved retirement plan (a ``PlanSnapshot``) in human Spanish
        and surface the 0-2 macro factors most likely to break it.

        Returns ``{"narrative": str, "macro_risks": list[dict], "ai_fallback_reason": str}``.
        ``ai_fallback_reason`` is ``""`` when the LLM answered. Always returns
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
            self._preflight()
            raw = self._call_api(prompt, max_tokens=1800)
            text = _strip_code_fence(raw)

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
            return {
                "narrative": narrative,
                "macro_risks": clean_macro,
                "ai_fallback_reason": "",
            }

        except Exception as exc:
            cause = self._classify_and_log(exc, "plan narrative")
            return {
                "narrative": self._fallback_message(cause),
                "macro_risks": [],
                "ai_fallback_reason": cause,
            }

    def generate_optimizer_advice(
        self,
        opt_result,
        goals: list | None = None,
        current_weights: dict | None = None,
    ) -> dict:
        """
        Generate the AI narrative + human-manageable concentration advice for a
        full portfolio optimization result.

        Always returns a valid dict, including ``ai_fallback_reason`` (``""``
        when the LLM answered) — the core_holdings key is populated
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
                f"({len(det_core)} posiciones) — sin necesidad de IA."
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
                # Deliberate skip, not a failure: there is no cause to report.
                "ai_fallback_reason": "",
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
        # P1 audit D13: real profile constraints (not hard-coded 8/8/18/2.5/5)
        pcfg = resolve_optimizer_profile(profile_name)
        max_pos = float(pcfg.max_position_pct)
        min_pos = int(pcfg.min_positions)
        max_vol = float(pcfg.max_volatility_pct)
        min_div = float(pcfg.min_dividend_yield_pct)
        max_crypto = float(pcfg.max_crypto_pct)
        reb_rat = getattr(opt_result, "rebalance_rationale", "") or ""
        warns = getattr(opt_result, "warnings", []) or []

        prompt = portfolio_optimizer_advice_prompt(
            profile_name=profile_name or pcfg.name,
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
            self._preflight()
            raw = self._call_api(prompt, max_tokens=2500)
            text = _strip_code_fence(raw)
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

            data["ai_fallback_reason"] = ""
            return data

        except Exception as exc:
            cause = self._classify_and_log(exc, "optimizer advice")
            return {
                "narrative":                      self._fallback_message(cause),
                "recommended_max_human_positions": len(det_core) or max(5, min(12, num_pos)),
                "core_holdings":                   det_core,
                "dropped_tickers":                 [],
                "human_review_tips":               [],
                "overall_assessment": (
                    f"Núcleo generado por reglas del perfil ({AI_FALLBACK.label(cause)})."
                ),
                "ai_fallback_reason":              cause,
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
        elif self.config.provider == "groq":
            return self._call_groq(prompt, max_tokens)
        else:
            raise ValueError(f"Unknown AI provider: {self.config.provider}")

    def _call_claude(self, prompt: str, max_tokens: int | None = None) -> str:
        """Anthropic branch. Divergente de los OpenAI-compatible **a propósito**.

        Tres cosas que este branch no puede compartir con los otros, ninguna de
        las cuales toca el prompt (PR 1, H2 del plan multimodelo):

        1. **Sin parámetros de sampling.** `temperature`/`top_p`/`top_k` fueron
           removidos de la API y devuelven 400 en todo lo posterior a 4.6. El
           branch mandaba `temperature=0` incondicionalmente, así que cualquier
           modelo actual del selector fallaba con 400 → fallback silencioso →
           «la IA no anda» sin causa visible. Los branches OpenAI-compatible
           siguen mandándolo porque ahí sigue siendo válido: es una divergencia
           de **transporte**, no de prompt, y por eso ningún prompt cambia.
        2. **`stop_reason` antes que el contenido.** Un corte por techo de
           tokens o un rechazo de seguridad devuelven HTTP 200 con contenido
           parcial o vacío; leerlo sin mirar `stop_reason` los convertía en un
           «JSON inválido» que culpaba al modelo del error equivocado.
        3. **El primer bloque de tipo `text`, no `content[0]`.** Con thinking
           adaptativo —encendido por defecto en los modelos actuales— el primer
           bloque es un `thinking` block y `content[0].text` era un
           `AttributeError` que el `except Exception` de arriba se tragaba.
        """
        import anthropic

        from config import CLAUDE_TRANSPORT

        client = anthropic.Anthropic(api_key=self.config.api_key)
        message = client.messages.create(
            model=self.config.model,
            max_tokens=CLAUDE_TRANSPORT.resolve_max_tokens(max_tokens),
            messages=[{"role": "user", "content": prompt}],
        )
        return _claude_message_text(message)

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

    def _call_openai_compatible(
        self,
        base_url: str,
        credential_resolver: Callable,
        prompt: str,
        max_tokens: int | None = None,
        extra_create_kwargs: dict | None = None,
    ) -> str:
        """Call any OpenAI-compatible inference endpoint with optional Hermes credential resolution."""
        from openai import OpenAI

        api_key = self.config.api_key

        hermes_path = os.path.expanduser("~/.hermes/hermes-agent")
        if os.path.isdir(hermes_path) and hermes_path not in sys.path:
            sys.path.insert(0, hermes_path)

        try:
            creds = credential_resolver()
            api_key = creds["api_key"]
            base_url = creds.get("base_url", base_url).rstrip("/")
        except Exception:
            if not api_key:
                raise RuntimeError(
                    f"No credentials found for {base_url}. "
                    "Run `hermes login` or provide an API key in Settings."
                )

        client = OpenAI(api_key=api_key, base_url=base_url)
        mt = max_tokens or 1024
        create_kwargs: dict = {
            "model": self.config.model,
            "temperature": 0,
            "max_tokens": mt,
            "messages": [{"role": "user", "content": prompt}],
        }
        extra = extra_create_kwargs or {}
        if extra:
            create_kwargs["extra_body"] = extra
        response = client.chat.completions.create(**create_kwargs)
        return _openai_message_text(response.choices[0])

    def _call_nous(self, prompt: str, max_tokens: int | None = None) -> str:
        def _resolver():
            from hermes_cli.auth import resolve_nous_runtime_credentials
            return resolve_nous_runtime_credentials()
        return self._call_openai_compatible(
            "https://inference-api.nousresearch.com/v1", _resolver, prompt, max_tokens,
        )

    def _call_xai(self, prompt: str, max_tokens: int | None = None) -> str:
        def _resolver():
            from hermes_cli.auth import resolve_xai_oauth_runtime_credentials
            return resolve_xai_oauth_runtime_credentials()
        return self._call_openai_compatible(
            "https://api.x.ai/v1", _resolver, prompt, max_tokens,
        )

    def _call_groq(self, prompt: str, max_tokens: int | None = None) -> str:
        # Static API key (GROQ_API_KEY / AI_API_KEY). Hermes is not a Groq
        # auth path: the resolver is expected to fail so `_call_openai_compatible`
        # falls through to `self.config.api_key`, same as a missing Hermes login.
        def _resolver():
            raise RuntimeError("groq uses a static API key, not Hermes OAuth")
        return self._call_openai_compatible(
            GROQ_BASE_URL,
            _resolver,
            prompt,
            max_tokens if max_tokens is not None else GROQ_TRANSPORT.default_max_tokens,
            extra_create_kwargs=GROQ_TRANSPORT.extra_create_kwargs(self.config.model),
        )

    def _parse_response(self, raw: str, fund: FundamentalResult, tech: TechnicalResult) -> Decision:
        try:
            data = extract_json_object(raw)
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"Could not extract JSON from AI response: {exc} — raw[:300]={raw[:300]!r}") from exc

        action = data.get("action", "HOLD").upper()
        valid_actions = {"STRONG BUY", "BUY", "HOLD", "REDUCE", "SELL"}
        if action not in valid_actions:
            action = "HOLD"

        # P0 D2: same effective score as rule-based engine / optimizer
        score = effective_decision_score(fund)

        _alloc = None
        try:
            _alloc_raw = data.get("recommended_max_allocation_conservative")
            if _alloc_raw is not None:
                _alloc = max(0.0, min(15.0, float(_alloc_raw)))
        except (TypeError, ValueError):
            pass

        conf = str(data.get("confidence", "MEDIUM") or "MEDIUM").upper()
        if conf not in {"HIGH", "MEDIUM", "LOW"}:
            conf = "MEDIUM"

        return Decision(
            symbol=fund.symbol,
            action=action,
            ai_confidence=conf,   # LLM's own label — explanation only, never the operative confidence
            fundamental_score=score,
            technical_signal=tech.signal,
            has_margin_of_safety=fund.is_value_stock(),
            rationale=data.get("rationale", []) or [],
            risks=data.get("risks", []) or [],
            ai_reasoning=data.get("reasoning", "") or "",
            recommended_max_allocation_pct=_alloc,
            macro_factors=data.get("macro_factors", []) or [],
        )
