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

from config import ESTIMACION


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


def projection_scenario(snap, prefs) -> str:
    """El Escenario con que el chat re-proyecta el plan (EO-4c).

    Gana la Postura del usuario —su perfil elegido y su override de Settings—,
    como en Simulaciones (decisión del usuario, 2026-10-07). Sin perfil elegido,
    el Escenario que el plan guardó; si no guardó ninguno (anterior a EO-4c), el de
    su perfil; si tampoco, el central.
    """
    from data.product_ux import profile_planning_scenario

    postura = profile_planning_scenario(
        getattr(prefs, "chosen_profile_key", None) or None,
        getattr(prefs, "planning_scenario", None),
    )
    if postura:
        return postura
    saved = str((getattr(snap, "mc_summary", None) or {}).get("scenario") or "")
    if saved in ESTIMACION.scenarios:
        return saved
    return (profile_planning_scenario(getattr(snap, "profile_key", "") or None)
            or ESTIMACION.default_scenario)


def _plan_projection_defaults(snap, prefs) -> dict:
    """La corrida del plan activo: con qué ahorro, retiro, meta y supuestos se proyectó (AUDIT-CHAT-PROYECCION).

    Es el valor por defecto de ``retirement_projection`` cuando el modelo no pasa el argumento. Antes salía
    0, y «¿me alcanza?» proyectaba un plan sin ahorro, sin retiro y sin meta. Devuelve, para ahorro anual,
    retiro anual y meta, ``(valor, fuente)``; y los supuestos que Simulaciones pasa al motor y el plan guardó
    (``mc_summary`` y los bloques de estrategia y drags): capital, horizonte, crecimiento del retiro y del
    ahorro, estrategia de retiro con sus años de ahorro y su longevidad, y drags. Pasarlos todos es lo que
    hace que la herramienta proyecte el plan y no un híbrido: con una estrategia de retiro el motor decide
    solo qué hacer con el ahorro (``years_to_retirement``), como en la pantalla.

    El ahorro es el de la corrida guardada (``mc_summary.monthly_savings``; un 0 guardado es «no aporto» y no
    se reemplaza), después el del perfil guardado con el plan y por último el de hoy (``contribution_inputs``,
    la regla de Simulaciones y del PDF).
    """
    from data.product_ux import MONTHS_PER_YEAR, contribution_inputs

    mc = getattr(snap, "mc_summary", None) or {}
    personal = getattr(snap, "personal", None) or {}

    def _number(value):
        try:
            return None if value is None else float(value)
        except (TypeError, ValueError):
            return None

    run_monthly = _number(mc.get("monthly_savings"))
    if run_monthly is not None:
        contribution = (max(run_monthly, 0.0) * MONTHS_PER_YEAR, "plan")
    else:
        resolved = contribution_inputs(prefs=prefs, personal=personal)
        origin = {"personal": "perfil del plan", "perfil": "perfil actual"}.get(resolved["source"])
        contribution = (resolved["annual"], origin) if origin else (0.0, "sin dato")

    strategy = getattr(snap, "withdrawal_strategy", None) or None
    if strategy:
        # El motor reemplaza el retiro por la estrategia: el monto fijo no entra.
        withdrawal = (0.0, "estrategia del plan")
    else:
        saved = _number(mc.get("annual_withdrawal"))
        withdrawal = (max(saved, 0.0), "plan") if saved is not None else (0.0, "sin dato")

    target_saved = _number(mc.get("target_value"))
    target = (max(target_saved, 0.0), "plan") if target_saved is not None else (0.0, "sin dato")

    inflation = _number(mc.get("inflation_rate"))
    growth = _number(mc.get("contribution_growth_pct"))
    longevity = _number(mc.get("longevity_years")) if strategy else None
    saving_years = max(int(_number(mc.get("retirement_years")) or 0), 0) if strategy else None
    drags = getattr(snap, "drags_at_save", None) or None
    return {
        "annual_contribution": contribution,
        "annual_withdrawal": withdrawal,
        "target_value": target,
        "initial_value": _number(mc.get("initial_value")) or _number(personal.get("current_capital")) or 100_000.0,
        "horizon_years": int(_number(mc.get("horizon_years")) or _number(personal.get("primary_horizon_years")) or 20),
        "withdrawal_growth_rate": (inflation or 0.0) / 100.0,
        "contribution_growth_rate": (growth or 0.0) / 100.0,
        "withdrawal_strategy": dict(strategy) if strategy else None,
        "longevity_years": int(longevity) if longevity else None,
        "years_to_retirement": saving_years,
        "drags": dict(drags) if drags else None,
    }


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

    def _arg_float(name, default):
        try:
            v = args.get(name)
            return float(v) if v is not None else float(default)
        except (TypeError, ValueError):
            return float(default)

    try:
        from data.preferences import UserPreferences

        prefs = UserPreferences.load()
    except Exception as exc:   # sin preferencias, decide el plan
        logger.debug(f"chat_tools: sin preferencias — {exc}")
        prefs = None
    plan = _plan_projection_defaults(snap, prefs)

    initial_value = _arg_float("initial_value", plan["initial_value"])
    horizon_years = int(_arg_float("horizon_years", plan["horizon_years"]))
    sources: Dict[str, str] = {}
    not_applied: List[str] = []

    def _explicit(name):
        """La cifra que el modelo pasó (un 0 explícito cuenta), o ``None`` si omitió el argumento."""
        try:
            return None if args.get(name) is None else float(args[name])
        except (TypeError, ValueError):   # un texto no es una cifra: decide el plan
            return None

    def _arg_or_plan(name):
        value, source = plan[name]
        explicit = _explicit(name)
        if explicit is not None:
            sources[name] = "argumento"
            return explicit
        sources[name] = source
        return value

    annual_withdrawal = _arg_or_plan("annual_withdrawal")
    annual_contribution = _arg_or_plan("annual_contribution")
    target_value = _arg_or_plan("target_value")

    strategy, longevity, saving_years = plan["withdrawal_strategy"], plan["longevity_years"], plan["years_to_retirement"]
    if strategy and _explicit("annual_withdrawal") is not None:
        # «¿Y si retiro 40 000?» es otro escenario: un retiro fijo reemplaza la estrategia del plan.
        strategy, longevity, saving_years = None, None, None
        not_applied.append("la estrategia de retiro del plan no se usó: pediste un retiro fijo")

    try:
        import numpy as np

        from portfolio.monte_carlo import MonteCarloSimulator

        symbols = list(weights_pct.keys())
        w = np.array([weights_pct[s] for s in symbols], dtype=float)
        w = w / w.sum() if w.sum() > 0 else None

        from analysis.estimacion import classes_for, countries_for
        scenario = projection_scenario(snap, prefs)
        sim = MonteCarloSimulator(symbols, weights=w, asset_classes=classes_for(symbols),
                                  scenario=scenario, countries=countries_for(symbols))
        res = sim.run(
            horizon_years=horizon_years,
            n_sims=2000,
            initial_value=initial_value,
            annual_withdrawal=annual_withdrawal,
            annual_contribution=annual_contribution,
            target_value=target_value,
            # Los supuestos con que el plan corrió (los mismos que pasa Simulaciones).
            withdrawal_growth_rate=plan["withdrawal_growth_rate"],
            contribution_growth_rate=plan["contribution_growth_rate"],
            drags=plan["drags"],
            withdrawal_strategy=strategy,
            longevity_years=longevity,
            years_to_retirement=saving_years,
        )
        out = {
            "ok": True,
            "plan_name": getattr(snap, "name", ""),
            "horizon_years": horizon_years,
            "initial_value": round(initial_value, 0),
            "annual_withdrawal": round(annual_withdrawal, 0),
            "annual_contribution": round(annual_contribution, 0),
            "scenario": scenario,
            "median_terminal": round(float(res.median_terminal), 0),
            "p10_terminal": round(float(res.p10_terminal), 0),
            "p90_terminal": round(float(res.p90_terminal), 0),
            "prob_ruin_pct": round(float(res.prob_ruin_pct), 1),
            # De dónde salió cada supuesto: el modelo puede decirle al usuario «con el ahorro de tu
            # plan» o «sin dato de ahorro», y lo que el plan tiene y esta proyección no aplica.
            "assumption_sources": sources,
            "plan_not_applied": not_applied,
            "withdrawal_strategy": (strategy or {}).get("kind"),
            "drags_applied": bool(plan["drags"]),
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
                         "'¿llego si ahorro Z por mes?', que funciona incluso sin capital inicial. "
                         "Los argumentos que se omiten salen del plan activo (su ahorro, retiro y meta): "
                         "omitilos para proyectar el plan tal como está."),
            parameters={
                "horizon_years": "años de proyección (opcional)",
                "annual_withdrawal": "retiro anual en USD (opcional; omitido = el del plan)",
                "annual_contribution": "ahorro anual en USD, se deposita mensualmente (opcional; omitido = el del plan)",
                "initial_value": "capital inicial en USD (opcional)",
                "target_value": "objetivo de capital en USD (opcional; omitido = el del plan)",
            },
            run=_tool_retirement_projection,
        ),
    ]
    return {t.name: t for t in tools}


def registry_spec(registry: Dict[str, Tool]) -> str:
    return "\n".join(t.spec_line() for t in registry.values())
