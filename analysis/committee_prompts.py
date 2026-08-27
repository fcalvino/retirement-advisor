"""
Prompts for the multi-agent investment committee (Gran Salto — Fase 2B).

The committee replaces the single-shot AI call with a panel of specialised agents
that debate and produce a verdict with **explicit dissent**. To keep parsing and
aggregation simple and auditable, every committee agent (except the Fundamental
Analyst, which reuses the production ``equity_decision_prompt``) returns the same
strict JSON shape:

    {
      "stance": "STRONG BUY|BUY|HOLD|REDUCE|SELL",
      "confidence": "HIGH|MEDIUM|LOW",
      "key_points": ["...", "..."],
      "concerns": ["...", "..."]
    }

The Risk Manager / Devil's Advocate is the key differentiator: it is *structurally*
asked to build the bear case, which guarantees auditable dissent and fights the
single-shot LLM's complacency bias.

Conventions: prompts centralised (no hardcoding in orchestration modules); the
hard numbers are injected as context so agents anchor to data, never invent it.
"""

from __future__ import annotations

from data.product_ux import (
    DOWNSIDE_RATIO_LABEL,
    POT_CAGR_LABEL,
    POT_GROWTH_LABEL,
    PROXY_RATIO_LABEL,
    PROXY_RETURN_LABEL,
)

AGENT_JSON_SCHEMA = (
    "Respondé EXCLUSIVAMENTE con un objeto JSON válido, sin texto antes ni después, "
    "con exactamente estas claves:\n"
    '  "stance": uno de "STRONG BUY" | "BUY" | "HOLD" | "REDUCE" | "SELL"\n'
    '  "confidence": uno de "HIGH" | "MEDIUM" | "LOW"\n'
    '  "key_points": lista de 2-3 strings (tus argumentos centrales, anclados a los números)\n'
    '  "concerns": lista de 1-3 strings (lo que más te preocupa desde tu rol)\n'
    "\nIDIOMA OBLIGATORIO: Responde SIEMPRE en español. Todos los campos de texto "
    "(key_points, concerns) deben estar escritos en español correcto y natural. "
    "Nunca uses inglés en los valores de texto.\n"
)


def _num(value, suffix: str = "") -> str:
    try:
        if value is None:
            return "n/d"
        return f"{float(value):.1f}{suffix}"
    except (TypeError, ValueError):
        return "n/d"


def committee_context_block(fund, tech) -> str:
    """Compact, hard-numbers context shared by every committee agent."""
    is_crypto = bool(getattr(fund, "is_crypto", False))
    score = getattr(fund, "adjusted_score", 0.0) if is_crypto else getattr(fund, "total_score", 0.0)
    lines = [
        f"Activo: {getattr(fund, 'company_name', '') or fund.symbol} ({fund.symbol})",
        f"Sector/Industria: {getattr(fund, 'sector', 'n/d')} / {getattr(fund, 'industry', 'n/d')}",
        f"Score del motor (determinista): {_num(score)}/100"
        + ("  [cripto: adjusted_score]" if is_crypto else ""),
        f"Moat: {getattr(fund, 'moat_classification', 'n/d')}",
        f"Precio actual: {_num(getattr(fund, 'current_price', 0))}",
    ]
    if not is_crypto:
        lines += [
            f"ROE: {_num(getattr(fund, 'roe', None), '%')} | ROIC: {_num(getattr(fund, 'roic', None), '%')} | "
            f"Margen neto: {_num(getattr(fund, 'net_margin', None), '%')}",
            f"D/E: {_num(getattr(fund, 'debt_equity', None))} | P/E: {_num(getattr(fund, 'pe_ratio', None))} | "
            f"Margen de seguridad: {_num(getattr(fund, 'margin_of_safety_pct', None), '%')}",
            f"CAGR ingresos 5a: {_num(getattr(fund, 'revenue_cagr_5y', None), '%')} | "
            f"CAGR EPS 5a: {_num(getattr(fund, 'eps_cagr_5y', None), '%')}",
        ]
    lines += [
        f"Señal técnica: {getattr(tech, 'signal', 'n/d')} | RSI semanal: {_num(getattr(tech, 'rsi_weekly', None))} | "
        f"vs 52w high: {_num(getattr(tech, 'price_vs_52w_high_pct', None), '%')}",
    ]
    return "\n".join(lines)


def _role_prompt(role_title: str, role_instructions: str, fund, tech) -> str:
    return (
        f"Sos el **{role_title}** en un comité de inversión para un inversor de RETIRO "
        f"con filosofía conservadora (preservación de capital primero).\n\n"
        f"=== DATOS DUROS (anclá tus argumentos a estos números, no inventes otros) ===\n"
        f"{committee_context_block(fund, tech)}\n\n"
        f"=== TU ROL ===\n{role_instructions}\n\n"
        f"=== FORMATO DE SALIDA ===\n{AGENT_JSON_SCHEMA}"
    )


def macro_strategist_prompt(fund, tech, macro_context: str = "") -> str:
    instructions = (
        "Evaluá el contexto macro relevante para ESTE activo: tasas de interés, ciclo "
        "económico, riesgo país (especialmente si es un ADR emergente/argentino), liquidez y "
        "régimen de inflación. Conectá cada factor macro a los números concretos del activo "
        "(valuación, sector, deuda). Tu stance refleja cómo el macro inclina la decisión, no "
        "la calidad del negocio en sí."
    )
    if macro_context:
        # Fase 3B: dated facts injected — the agent must use these, not its memory.
        instructions += (
            "\n\nUsá EXCLUSIVAMENTE estos hechos macro fechados como tu fuente de actualidad "
            "(no inventes datos macro ni uses tu memoria de entrenamiento):\n" + macro_context
        )
    return _role_prompt("Estratega Macro", instructions, fund, tech)


def devils_advocate_prompt(fund, tech) -> str:
    """The structural red-team. Its mandate is to build the strongest bear case."""
    return _role_prompt(
        "Risk Manager y Abogado del Diablo",
        "Tu mandato es CONSTRUIR EL BEAR CASE más fuerte y honesto posible: buscá "
        "activamente por qué NO comprar o por qué reducir. Cuestioná la tesis optimista, "
        "señalá fragilidades (apalancamiento, valuación exigente, dependencia cíclica, "
        "deterioro de márgenes, riesgo de moat). Aunque el activo parezca bueno, tu trabajo "
        "es el contrapunto: tu stance debe inclinarse a la cautela y tus concerns son el "
        "núcleo del disenso del comité. No seas complaciente.",
        fund, tech,
    )


def portfolio_manager_prompt(fund, tech) -> str:
    return _role_prompt(
        "Portfolio Manager",
        "Concilá las visiones (fundamental, macro y el bear case del abogado del diablo) y "
        "decidí el dimensionamiento práctico para una cartera de retiro conservadora "
        "(máximo prudente por nombre ~8-15%). Tu stance es la decisión de cartera, no un "
        "análisis aislado: pesá el upside contra el riesgo de capital. Si el bear case es "
        "serio, reflejalo en una postura y un tamaño más cautos.",
        fund, tech,
    )


def behavioral_coach_prompt(fund, tech) -> str:
    return _role_prompt(
        "Behavioral Coach",
        "Traducí la situación a lenguaje humano y anclá al plan de largo plazo del inversor. "
        "Tu foco es el comportamiento: evitar el pánico en caídas y la euforia en subas. Tu "
        "stance debe favorecer la consistencia con un plan de retiro (sesgo a HOLD salvo señal "
        "clara) y tus concerns apuntan a las trampas conductuales de este caso concreto.",
        fund, tech,
    )


# --------------------------------------------------------------------------- #
#  Portfolio-level committee (evalúa el PLAN completo, no un ticker)           #
# --------------------------------------------------------------------------- #
#  Reuses the same JSON schema and the same stance vocabulary as the per-ticker
#  committee, so the deterministic aggregation works unchanged. Here ``stance``
#  expresses the HEALTH/ALIGNMENT of the whole plan (not a buy/sell on an asset):

_PORTFOLIO_STANCE_GUIDE = (
    "=== QUÉ SIGNIFICA TU STANCE (es sobre la SALUD de la CARTERA, no compra/venta de un activo) ===\n"
    '  "STRONG BUY" = la cartera es muy sólida, no tocar nada.\n'
    '  "BUY"        = cartera sólida, a lo sumo retoques menores.\n'
    '  "HOLD"       = mantener pero con ajustes (rebalanceo, diversificación).\n'
    '  "REDUCE"     = la cartera necesita ajustes importantes.\n'
    '  "SELL"       = la cartera necesita reestructurarse.\n'
)


def _fmt_pct(value, suffix: str = "%") -> str:
    return _num(value, suffix)


def portfolio_committee_context_block(ctx: dict) -> str:
    """Compact, hard-numbers context about the whole portfolio.

    Every value here is already computed elsewhere (tracker metrics, stress test,
    concentration, alignment vs the active plan, optionally optimizer/Monte Carlo,
    tailwinds, macro RAG). Sections render only when their data is present, so the
    same block serves both the real holdings and a proposed plan. Agents must
    anchor to these numbers and never invent others.
    """
    g = ctx.get
    lines = [
        f"Cartera: {g('plan_name', 'tu portfolio actual')}"
        + (f" · Perfil: {g('profile_name')}" if g("profile_name") else "")
        + f" · {g('n_positions', 'n/d')} posiciones"
        + (f" · Valor: ${_num(g('total_value'))} USD" if g("total_value") else ""),
    ]
    if g("horizon_years") or g("target_value"):
        lines.append(
            f"Horizonte: {g('horizon_years', 'n/d')} años · Meta: ${_num(g('target_value'))} USD"
        )

    # Realized risk/return (from the actual holdings' equity curve).
    rz = ctx.get("realized") or {}
    if rz:
        lines += [
            "",
            "--- Riesgo/retorno REALIZADO (histórico de tus tenencias) ---",
            f"Retorno anualizado: {_fmt_pct(rz.get('annualized_return_pct'))} · "
            f"P&L total: {_fmt_pct(rz.get('total_pnl_pct'))}",
            f"Sharpe: {_num(rz.get('sharpe_ratio'))} · "
            f"{DOWNSIDE_RATIO_LABEL} (no es Sortino): "
            f"{_num(rz.get('downside_vol_ratio'))} · "
            f"Beta vs SPY: {_num(rz.get('beta'))} · Max drawdown: {_fmt_pct(rz.get('max_drawdown_pct'))}",
        ]

    # Forward projection (only when present — e.g. a proposed/optimized plan).
    if g("expected_return_pct") is not None or g("prob_target_pct") is not None:
        # U1-7: la tasa anualizada del Monte Carlo solo es un retorno si no hubo
        # flujos. Con aportes o retiros el modelo tiene que leer "crecimiento del
        # pozo" — si lee "CAGR" razona sobre un retorno que nadie calculó.
        # Un ctx sin el flag es *desconocido*, no "sin flujos": ahí manda la
        # etiqueta prudente, porque el default barato es el que miente.
        _mc_flows = bool(ctx.get("mc_has_cash_flows", True))
        _growth_label = POT_GROWTH_LABEL if _mc_flows else POT_CAGR_LABEL
        _growth_caveat = (
            " — crecimiento del pozo con aportes/retiros incluidos, NO un "
            "retorno de la cartera (el retorno money-weighted no se calcula)."
            if _mc_flows else ""
        )
        lines += [
            "",
            "--- Riesgo/retorno del MODELO (proyección de un plan propuesto) ---",
            f"{PROXY_RETURN_LABEL}: {_fmt_pct(g('expected_return_pct'))} anual — proxy de "
            "score + dividendo + moat, no un pronóstico de retorno.",
            f"Volatilidad: {_fmt_pct(g('volatility_pct'))} · {PROXY_RATIO_LABEL}: "
            f"{_num(g('sharpe_ratio'))} — (atractivo − tasa libre de riesgo) / volatilidad "
            "histórica, no es un Sharpe.",
            f"Probabilidad de alcanzar la meta: {_fmt_pct(g('prob_target_pct'))} · "
            f"Pesimista (p10): ${_num(g('p10_terminal'))} · {_growth_label} mediano: "
            f"{_fmt_pct(g('median_cagr_pct'))}{_growth_caveat}",
        ]

    sw = ctx.get("sector_weights") or {}
    if sw:
        top_sw = sorted(sw.items(), key=lambda kv: kv[1], reverse=True)[:5]
        lines.append("")
        lines.append("Sectores (peso %): " + ", ".join(f"{k} {v:.0f}%" for k, v in top_sw))

    th = ctx.get("top_holdings") or []
    if th:
        lines.append(
            "Mayores posiciones: "
            + ", ".join(f"{h.get('symbol','?')} {h.get('weight_pct',0):.0f}%" for h in th[:6])
        )

    lines += [
        "",
        "--- Concentración ---",
        f"Posición máxima: {_fmt_pct(g('max_weight_pct'))} · "
        f"Top-3: {_fmt_pct(g('top3_weight_pct'))} · "
        f"Posiciones efectivas: {_num(g('effective_positions'))}",
    ]

    wc = ctx.get("worst_crisis") or {}
    if wc:
        lines += [
            "",
            "--- Resistencia a crisis (Stress Test) ---",
            f"Peor escenario ({wc.get('name','n/d')}): caída {_fmt_pct(wc.get('drawdown_pct'))} "
            f"(vs SPY {_fmt_pct(wc.get('vs_spy_pct'))} relativo)",
        ]
        others = ctx.get("stress_scenarios") or []
        if others:
            lines.append(
                "Otros: " + ", ".join(
                    f"{s.get('name','?')} {s.get('drawdown_pct',0):.0f}%" for s in others[:3]
                )
            )

    # Alignment vs the active plan ("deriva inteligente").
    al = ctx.get("alignment") or {}
    if al:
        lines += [
            "",
            "--- Alineación con tu plan activo ---",
            f"Plan: {al.get('plan_name','n/d')} · Deriva total: {_fmt_pct(al.get('drift_pct'))}",
        ]
        trades = al.get("trades") or []
        if trades:
            lines.append(
                "Trades sugeridos: " + "; ".join(
                    f"{t.get('action','?')} {t.get('symbol','?')} (drift {t.get('drift_pct',0):+.0f}%)"
                    for t in trades[:5]
                )
            )

    tw = ctx.get("tailwinds") or []
    if tw:
        lines += [
            "",
            "--- Vientos sector-país (curados) ---",
            ", ".join(
                f"{t.get('symbol','?')}: {t.get('classification','?')} ({t.get('score',0):+.0f})"
                for t in tw[:6]
            ),
        ]

    goals = ctx.get("goals") or []
    if goals:
        lines += [
            "",
            "--- Metas ---",
            "; ".join(
                f"{gg.get('name','meta')}: ${_num(gg.get('target_amount_today'))} en "
                f"{gg.get('horizon_years','n/d')}a" for gg in goals[:4]
            ),
        ]

    macro = ctx.get("macro_context") or ""
    if macro:
        lines += ["", "--- Contexto macro fechado (usalo, no inventes) ---", macro.strip()]

    return "\n".join(lines)


def _portfolio_role_prompt(role_title: str, role_instructions: str, ctx: dict) -> str:
    return (
        f"Sos el **{role_title}** en un comité que evalúa el PORTFOLIO ACTUAL (las posiciones "
        f"REALES que el inversor tiene hoy) de un inversor de retiro con filosofía conservadora "
        f"(preservación de capital primero). No analizás un activo suelto: evaluás la cartera "
        f"como un todo, tal como está hoy.\n\n"
        f"=== DATOS DUROS DE LA CARTERA (anclá tus argumentos a estos números, no inventes otros) ===\n"
        f"{portfolio_committee_context_block(ctx)}\n\n"
        f"{_PORTFOLIO_STANCE_GUIDE}\n"
        f"=== TU ROL ===\n{role_instructions}\n\n"
        f"=== FORMATO DE SALIDA ===\n{AGENT_JSON_SCHEMA}"
    )


def plan_strategist_prompt(ctx: dict) -> str:
    return _portfolio_role_prompt(
        "Estratega del Plan",
        "Evaluá si el PORTFOLIO ACTUAL está ALINEADO con el plan y la meta del inversor. Si hay "
        "un plan activo, mirá la deriva (drift) respecto a los pesos objetivo y los trades "
        "sugeridos. Si no hay plan activo, juzgá si la cartera luce coherente para un objetivo de "
        "retiro de largo plazo (calidad, diversificación, sentido estratégico). Tu stance refleja "
        "qué tan en línea está la cartera con el rumbo deseado; tus concerns marcan los desvíos.",
        ctx,
    )


def risk_manager_portfolio_prompt(ctx: dict) -> str:
    return _portfolio_role_prompt(
        "Gestor de Riesgo",
        "Evaluá el RIESGO de la cartera tal como está hoy: concentración (posición máxima, top-3, "
        "posiciones efectivas), riesgo REALIZADO (Sharpe, ratio retorno/vol bajista, beta vs "
        "SPY, max drawdown histórico) y caída esperada en una crisis (stress test). El ratio "
        "retorno/vol bajista no es un Sortino — no lo compares contra un Sortino publicado. "
        "Penalizá la concentración "
        "excesiva, un beta alto y la fragilidad ante crisis. Tu stance refleja qué tan resistente "
        "es la cartera a un mal escenario; tus concerns son los riesgos concretos.",
        ctx,
    )


def macro_strategist_portfolio_prompt(ctx: dict) -> str:
    return _portfolio_role_prompt(
        "Estratega Macro",
        "Evaluá cómo el contexto macro (tasas, ciclo, inflación, riesgo país —en especial para "
        "exposición a ADRs argentinos/emergentes—) y los vientos sector-país inciden sobre ESTA "
        "cartera real. Conectá cada factor macro a los pesos sectoriales y posiciones concretas. "
        "Usá EXCLUSIVAMENTE los hechos macro fechados provistos, no tu memoria. Tu stance refleja "
        "si el viento macro sopla a favor o en contra de la cartera tal como está.",
        ctx,
    )


def devils_advocate_portfolio_prompt(ctx: dict) -> str:
    """Portfolio-level red-team: builds the strongest bear case against the actual holdings."""
    return _portfolio_role_prompt(
        "Abogado del Diablo",
        "Tu mandato es CONSTRUIR EL BEAR CASE más fuerte y honesto contra ESTA CARTERA tal como "
        "está hoy: buscá activamente por qué podría hacerle daño al inversor. Cuestioná la "
        "dependencia de pocas posiciones o de un país/sector, un beta o drawdown históricos altos, "
        "la fragilidad ante una crisis como 2008, y la deriva respecto del plan. Aunque la cartera "
        "parezca buena, tu trabajo es el contrapunto: tu stance debe inclinarse a la cautela y tus "
        "concerns son el núcleo del disenso del comité. No seas complaciente.",
        ctx,
    )
