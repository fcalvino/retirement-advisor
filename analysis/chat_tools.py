"""
Tool registry for the conversational agent (Gran Salto — Fase 4).

The chat orchestrator never invents numbers: it routes a question to one of these
*deterministic* tools, runs the real engine function, and only then narrates over
the returned data. Each tool wraps an existing engine capability (exactly the
"library of tools" the codebase already is) behind a uniform, JSON-serializable
interface so the LLM can pick and call it.

Tools degrade gracefully: missing context (no active plan, bad ticker, no network)
returns ``{"ok": False, "error": ...}`` instead of raising, so the chat can explain
the limitation instead of crashing.

Conventions: no Streamlit here (pure, reusable, testable); loguru.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from loguru import logger


@dataclass
class Tool:
    name: str
    description: str
    parameters: Dict[str, str]                 # arg_name -> human description (for the router prompt)
    run: Callable[[dict], dict]                # args dict -> result dict
    required: List[str] = field(default_factory=list)

    def spec_line(self) -> str:
        params = ", ".join(
            f"{k}{'*' if k in self.required else ''}: {v}" for k, v in self.parameters.items()
        ) or "(sin parámetros)"
        return f"- {self.name}: {self.description}  Parámetros: {params}"


# --------------------------------------------------------------------------- #
#  Shared helpers                                                             #
# --------------------------------------------------------------------------- #

def _price_lookup(symbol: str) -> Optional[float]:
    try:
        from data.fetcher import get_info

        info = get_info(symbol) or {}
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        return float(price) if price else None
    except Exception:
        return None


def _active_plan():
    """Most-recently-updated saved plan, or None."""
    try:
        from data.plan_store import PlanStore

        plans = PlanStore().list()
        if not plans:
            return None
        return sorted(plans, key=lambda p: getattr(p, "updated_at", "") or getattr(p, "created_at", ""))[-1]
    except Exception as exc:
        logger.debug(f"chat_tools: no active plan — {exc}")
        return None


# --------------------------------------------------------------------------- #
#  Tool implementations                                                       #
# --------------------------------------------------------------------------- #

def _tool_analyze_ticker(args: dict) -> dict:
    symbol = str(args.get("symbol", "")).strip().upper()
    if not symbol:
        return {"ok": False, "error": "Falta el ticker a analizar."}
    try:
        from analysis.strategy import full_analysis

        fund, tech, decision = full_analysis(symbol)
        return {
            "ok": True,
            "symbol": symbol,
            "company": getattr(fund, "company_name", "") or symbol,
            "action": decision.action,
            "confidence": decision.confidence,
            "fundamental_score": round(float(decision.fundamental_score), 1),
            "technical_signal": getattr(tech, "signal", ""),
            "current_price": round(float(getattr(fund, "current_price", 0.0) or 0.0), 2),
            "pe_ratio": getattr(fund, "pe_ratio", None),
            "roe": getattr(fund, "roe", None),
            "debt_equity": getattr(fund, "debt_equity", None),
            "moat": getattr(fund, "moat_classification", ""),
            "rationale": list(getattr(decision, "rationale", []))[:3],
            "risks": list(getattr(decision, "risks", []))[:3],
        }
    except Exception as exc:
        logger.warning(f"analyze_ticker[{symbol}] failed — {exc}")
        return {"ok": False, "error": f"No pude analizar {symbol}: {exc}"}


def _tool_plan_status(args: dict) -> dict:
    snap = _active_plan()
    if snap is None:
        return {"ok": False, "error": "No hay ningún plan guardado. Creá uno en 'Mi Plan' primero."}
    try:
        from data.plan_context import compute_plan_vs_reality

        result = compute_plan_vs_reality(snap, _price_lookup)
        summary = result.get("summary", {})
        return {
            "ok": True,
            "plan_name": getattr(snap, "name", ""),
            "weighted_delta_pct": round(float(summary.get("weighted_delta_pct", 0.0)), 2),
            "n_priced": summary.get("n_priced"),
            "n_total": summary.get("n_total"),
            "gainers": summary.get("gainers"),
            "losers": summary.get("losers"),
            "avg_score_then": summary.get("avg_score_then"),
        }
    except Exception as exc:
        logger.warning(f"plan_status failed — {exc}")
        return {"ok": False, "error": f"No pude evaluar el plan: {exc}"}


def _tool_retirement_projection(args: dict) -> dict:
    snap = _active_plan()
    if snap is None:
        return {"ok": False, "error": "No hay plan guardado para proyectar. Creá uno en 'Mi Plan'."}
    weights_pct = {}
    try:
        weights_pct = snap.target_weights() or {}
    except Exception:
        weights_pct = {}
    if not weights_pct:
        return {"ok": False, "error": "El plan no tiene una asignación con la que proyectar."}

    personal = getattr(snap, "personal", None) or {}

    def _arg_float(name, default):
        try:
            v = args.get(name)
            return float(v) if v is not None else float(default)
        except (TypeError, ValueError):
            return float(default)

    initial_value = _arg_float("initial_value", personal.get("current_capital", 100_000))
    horizon_years = int(_arg_float("horizon_years", personal.get("primary_horizon_years", 20)))
    annual_withdrawal = _arg_float("annual_withdrawal", 0.0)
    annual_contribution = _arg_float("annual_contribution", 0.0)
    target_value = _arg_float("target_value", 0.0)

    try:
        import numpy as np

        from portfolio.monte_carlo import MonteCarloSimulator

        symbols = list(weights_pct.keys())
        w = np.array([weights_pct[s] for s in symbols], dtype=float)
        w = w / w.sum() if w.sum() > 0 else None

        sim = MonteCarloSimulator(symbols, weights=w)
        res = sim.run(
            horizon_years=horizon_years,
            n_sims=2000,
            initial_value=initial_value,
            annual_withdrawal=annual_withdrawal,
            annual_contribution=annual_contribution,
            target_value=target_value,
        )
        out = {
            "ok": True,
            "plan_name": getattr(snap, "name", ""),
            "horizon_years": horizon_years,
            "initial_value": round(initial_value, 0),
            "annual_withdrawal": round(annual_withdrawal, 0),
            "annual_contribution": round(annual_contribution, 0),
            "median_terminal": round(float(res.median_terminal), 0),
            "p10_terminal": round(float(res.p10_terminal), 0),
            "p90_terminal": round(float(res.p90_terminal), 0),
            "prob_ruin_pct": round(float(res.prob_ruin_pct), 1),
        }
        # Only report goal probability when a real target was provided.
        # target_value <= 0 means "no goal set", in which case the engine
        # leaves prob_achieve_target_pct at its 0.0 default — reporting that
        # as a real "0%" would be misleading.
        if target_value > 0:
            out["target_value"] = round(target_value, 0)
            out["prob_achieve_target_pct"] = round(float(res.prob_achieve_target_pct), 1)
        else:
            # No goal set: OMIT the probability field entirely (do not emit 0.0
            # nor null) so the model cannot report a misleading "0%". Surface an
            # explicit instruction instead.
            out["prob_achieve_target_pct_available"] = False
            out["target_note"] = (
                "No hay meta de capital definida, así que NO se puede calcular una "
                "probabilidad de alcanzarla. No reportes 0%. Indicá al usuario que "
                "cargue una meta en 'Mi Plan' (o en 'Simulaciones → Mis Metas') para estimarla."
            )
        return out
    except Exception as exc:
        logger.warning(f"retirement_projection failed — {exc}")
        return {"ok": False, "error": f"No pude correr la proyección: {exc}"}


# --------------------------------------------------------------------------- #
#  Registry                                                                   #
# --------------------------------------------------------------------------- #

def build_default_registry() -> Dict[str, Tool]:
    tools = [
        Tool(
            name="analyze_ticker",
            description="Analiza una acción/cripto: decisión (BUY/HOLD/SELL), score, métricas y riesgos.",
            parameters={"symbol": "ticker a analizar, ej. AAPL"},
            required=["symbol"],
            run=_tool_analyze_ticker,
        ),
        Tool(
            name="plan_status",
            description="Estado del plan de retiro guardado vs el mercado de hoy (drift, ganadores/perdedores).",
            parameters={},
            run=_tool_plan_status,
        ),
        Tool(
            name="retirement_projection",
            description=("Proyección Monte Carlo del plan: probabilidad de éxito y rangos de capital final. "
                         "Útil para '¿me alcanza si me jubilo en X años / retiro Y por año?' y para "
                         "'¿llego si ahorro Z por mes?', que funciona incluso sin capital inicial."),
            parameters={
                "horizon_years": "años de proyección (opcional)",
                "annual_withdrawal": "retiro anual en USD (opcional)",
                "annual_contribution": "ahorro anual en USD, se deposita mensualmente (opcional)",
                "initial_value": "capital inicial en USD (opcional)",
                "target_value": "objetivo de capital en USD (opcional)",
            },
            run=_tool_retirement_projection,
        ),
    ]
    return {t.name: t for t in tools}


def registry_spec(registry: Dict[str, Tool]) -> str:
    return "\n".join(t.spec_line() for t in registry.values())
