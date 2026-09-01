"""
Product UX helpers — pure, Streamlit-free functions for the backlog 1–15 surface.

These powers Home hub, gap-to-goal levers, annual checklist, deep plan compare,
track-record one-liner, market-drop coach predicate, AR dual-currency display,
chat missing-context copy, and decision-quality labels.

All thresholds that are product knobs live in ``config`` (CoachConfig, ArFxConfig).
No network. Fully unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

# Module-level: the copy constants below are built at import time, so they cannot
# use the lazy `from config import X as config` the functions in this file do.
# Safe in both directions — config.py imports nothing from data/.
from config import CASH_BUFFER_PCT, MOAT

# --------------------------------------------------------------------------- #
#  Canonical labels for the two models that produce a "return" (U1-1, U1-2)   #
# --------------------------------------------------------------------------- #
#  The optimizer's ``expected_return_pct`` is a proxy built from score +
#  dividend + moat (a Black-Litterman *view*), and its ``sharpe_ratio`` divides
#  that proxy by historical volatility. The Monte Carlo projects wealth from the
#  price history instead. The two do not share a return model, so every surface
#  names which one it is showing. Locked by ``tests/test_return_label_contract``.

PROXY_RETURN_LABEL = "Atractivo estimado (proxy)"
PROXY_RETURN_SHORT = "Atractivo est."
PROXY_RETURN_HELP = (
    "Proxy construido con score + dividendo, no un pronóstico. "
    "Sirve para ordenar y comparar carteras entre sí; la proyección de patrimonio "
    "la da el Monte Carlo, que parte de la historia real de precios."
)

# --------------------------------------------------------------------------- #
#  El proxy se ordena, no se cotiza (U6-1)                                    #
# --------------------------------------------------------------------------- #
#  ``OptimizationResult.expected_return_pct`` se mostraba como «7,2 % anual».
#  Medido sobre las 149 equities cacheadas con ≥5 años de historia semanal, ese
#  formato promete tres cosas que el número no tiene:
#
#    * **exactitud** — su correlación con el drift del Monte Carlo, el único
#      retorno observable que el motor calcula, es **+0,025**;
#    * **precisión** — R² de 0,116 contra el CAGR realizado, y un rango p10–p90
#      de 3,4 pp contra los 19 pp que abarca el CAGR real;
#    * **una unidad** — «% anual» invita a sumarlo, capitalizarlo o compararlo
#      contra el rendimiento de un plazo fijo, y no es ninguna de esas cosas.
#
#  Lo que la medición **sí** validó es la estructura: el score predice el CAGR
#  con la pendiente del signo correcto (p < 0,0001) y con intercepto −1,43 %, o
#  sea el cero que el motor asume. Por eso U6-1 se cierra por el lado del
#  rótulo y no del número — μ queda intacto, porque Black-Litterman lo necesita
#  en unidades de retorno y porque recalibrarlo contra diez años de historia
#  sería hornear hindsight (ver ``tests/test_proxy_ordinal_oracle.py``).
#
#  El índice es ``μ / er_absolute_cap × 100``: una transformación **estrictamente
#  monótona**, así que todo ordenamiento se conserva y ninguna decisión de
#  cartera cambia. El 100 es el cap del motor, no un redondeo elegido aparte.

PROXY_INDEX_LABEL = "Índice de atractivo (0–100)"
PROXY_INDEX_SHORT = "Atractivo"
PROXY_INDEX_HELP = (
    "Escala relativa de 0 a 100 para **ordenar y comparar** candidatos y carteras "
    "de este modelo entre sí. **No es una tasa**: no se capitaliza, no se compara "
    "contra un plazo fijo y no proyecta patrimonio — eso lo hace el Monte Carlo, "
    "que parte de la historia real de precios. Sale del score y del dividendo; "
    "100 es el techo que el motor le permite a un solo activo."
)


def proxy_attractiveness_index(
    expected_return_pct: Optional[float],
    config=None,
) -> Optional[float]:
    """``expected_return_pct`` (proxy) mapeado a un índice 0–100 (U6-1).

    Estrictamente monótona en μ, así que **el orden no cambia** — es el mismo
    ranking que usa el optimizer, descrito sin prometer una tasa anual.

    ``None`` entra y sale como ``None``: un plan sin optimización corrida no
    tiene atractivo 0, no tiene atractivo (misma regla que U3-1/U5-14).
    """
    if expected_return_pct is None:
        return None
    if config is None:
        from config import OPTIMIZER as config  # noqa: N811 — singleton default
    cap_pct = float(getattr(config, "er_absolute_cap", 0.14)) * 100.0
    if cap_pct <= 0:
        return None
    return max(0.0, min(100.0, float(expected_return_pct) / cap_pct * 100.0))

PROXY_RATIO_LABEL = "Ratio atractivo/vol"
PROXY_RATIO_HELP = (
    "No es un Sharpe: el numerador es el atractivo estimado (proxy de score) menos "
    "la tasa libre de riesgo, y el denominador es la volatilidad histórica. Sirve "
    "para comparar carteras de este modelo entre sí, no contra el Sharpe realizado "
    "de un índice."
)

MC_RETURN_LABEL = "retorno histórico"


# --------------------------------------------------------------------------- #
#  Canonical labels for the weekly moving averages (U1-3)                     #
# --------------------------------------------------------------------------- #
#  ``TechnicalAnalyzer`` reads 10 years of **weekly** bars and then takes
#  ``price.rolling(200).mean()``, so the "SMA200" of the code is 200 weeks —
#  ~3,8 years — and not the classic 200 days (~9,5 months) a reader assumes on
#  sight. The 100- and 50-bar weekly averages carry the same gap.
#
#  The window is deliberate: a ~3,8-year trend filter is the right length for a
#  5–30 year retirement horizon. U1-3 therefore fixed the **name** and left the
#  math untouched — no window, threshold or signal moved. The remaining half of
#  the finding (a short history makes the average NaN, which today reads as
#  "below trend" instead of "unknown") is U3-1 and is deliberately NOT here.
#
#  Locked by ``tests/test_trend_label_contract.py``.

TREND_MA_LABEL = "SMA de 200 semanas (~3,8 años)"
TREND_MA_SHORT = "SMA 200 sem."
TREND_MA_LABEL_EN = "200-week SMA"
TREND_MA_HELP = (
    "Promedio de las últimas 200 barras **semanales** (~3,8 años), no la SMA "
    "clásica de 200 días (~9,5 meses): el análisis técnico corre sobre 10 años "
    "de barras semanales. Es el filtro de tendencia de largo plazo del producto."
)

MID_MA_LABEL = "SMA de 100 semanas (~1,9 años)"
MID_MA_SHORT = "SMA 100 sem."

FAST_MA_LABEL = "SMA de 50 semanas (~1 año)"
FAST_MA_SHORT = "SMA 50 sem."
FAST_MA_LABEL_EN = "50-week SMA"


# --------------------------------------------------------------------------- #
#  Canonical label for the cost-of-capital hurdle of the moat (U1-4)          #
# --------------------------------------------------------------------------- #
#  ``MoatAnalyzer._wacc_proxy()`` returns ``risk_free_proxy_pct + ERP`` of the
#  sector — 4,0 % + 4,0…6,0 pp. That is a **cost of equity**: a CAPM without
#  beta, with a flat sector ERP standing in for ``β × ERP``. There is no debt in
#  it, no D/(D+E) weight and no tax shield, so it is not a WACC, and the U1-4
#  ``no_hacer`` forbids inventing a capital structure to make the old name true.
#  The fix is therefore the name: the hurdle is a **costo de equity proxy**.
#
#  ``roic_sustained`` scores the **spread** of the multi-year average ROIC over
#  that hurdle (``MOAT.roic_spread_*``), not the absolute ROIC. The absolute
#  bands only run with ``MOAT.use_roic_wacc_spread=False`` — the identifiers
#  keep "wacc" for backward compatibility, the value they hold does not.
#
#  Locked by ``tests/test_cost_of_equity_label_contract.py``: no number, band or
#  formula moved here, and the cuts named below are checked against ``MOAT``.

COST_OF_EQUITY_LABEL = "costo de equity proxy"
COST_OF_EQUITY_HELP = (
    # U5-10: la tasa venía escrita a mano acá. Era 4 % porque MOAT declaraba su
    # propia tasa libre de riesgo, 50 bp por debajo de la que usaban el backtest
    # y el optimizer. Al unificarse, una copia hardcodeada habría quedado
    # mintiendo — que es exactamente lo que este contrato de etiqueta atrapa.
    f"El umbral es la tasa libre de riesgo ({MOAT.risk_free_proxy_pct:g} %) + la prima "
    "de riesgo de acciones del sector (4–6 pp). **No es un WACC**: no pondera deuda "
    "ni escudo fiscal. Tampoco es CAPM con beta: la prima es sectorial y plana."
)

ROIC_SPREAD_LABEL = f"spread ROIC − {COST_OF_EQUITY_LABEL}"
ROIC_SPREAD_HELP = (
    f"ROIC promedio multi-año menos el {COST_OF_EQUITY_LABEL}: "
    "≥10pp=2, ≥4pp=1, ≥0pp=0.5. Un ROIC alto no suma si el sector exige tanto o "
    "más — lo que marca el moat es el exceso.\n\n"
    + COST_OF_EQUITY_HELP
)

#: The opt-out (``MOAT.use_roic_wacc_spread=False``): sector-blind bands on the
#: absolute ROIC. It compares against nothing, so it must not borrow the
#: cost-of-equity wording — that is the whole point of the two texts.
ROIC_ABSOLUTE_LABEL = "ROIC promedio (bandas absolutas)"
ROIC_ABSOLUTE_HELP = (
    "ROIC promedio multi-año contra bandas fijas: ≥20 %=2, ≥12 %=1, ≥8 %=0.5. "
    "Modo legacy: no mira el sector, así que no compara el ROIC contra ningún "
    "costo de capital."
)


#  Defensive sleeve — N9
#  ---------------------
#  The age rule (``config.recommended_bond_pct``) governs **bonds plus cash**,
#  not bonds alone. Both screens used to print the bond number next to a caption
#  calling it "la regla por edad" — which is the defensivo, bonos + efectivo, so
#  the bond line alone lands 5 pp below what the rule says: at 30
#  a conservative investor read 25 where the rule says 30. The sleeve was never
#  short — it was named after its larger half.
#
#  So the label names the sleeve and the screens show the split underneath. No
#  number moved. Locked by ``tests/test_defensive_sleeve_contract.py``.

DEFENSIVE_SLEEVE_LABEL = "Defensivo (bonos + efectivo)"
DEFENSIVE_SLEEVE_SHORT = "Defensivo"
DEFENSIVE_SLEEVE_HELP = (
    "Lo que la regla por edad y perfil pide como defensivo: bonos + efectivo. "
    f"Se muestra partido en dos: **bonos** y un **buffer de {CASH_BUFFER_PCT:g} % en "
    "efectivo** para rebalancear. Ninguna de las dos filas es la regla por "
    "separado — la regla es la suma."
)


def defensive_sleeve_caption(advice) -> str:
    """One line naming the rule and its split, for the screens that show it.

    Takes the ``AllocationAdvice`` rather than the raw numbers so the caption
    cannot disagree with the metrics beside it — the two used to be assembled
    independently on each page, which is how the bond number ended up captioned
    as the whole rule (N9).
    """
    return (
        # The sleeve is named on the same line as the rule on purpose: the sweep
        # in ``tests/test_defensive_sleeve_contract.py`` reads line by line with
        # no context window, so a qualifier three lines down would not count —
        # and a qualifier that drifts away from its claim is what went stale.
        f"📐 A los {advice.age}, la regla por edad (defensivo = bonos + efectivo) "
        f"y perfil **{advice.profile_name}** pide "
        f"**{advice.defensive_pct:.0f} % defensivo**: "
        f"se mantiene como {advice.bonds_pct:.0f} % en bonos + "
        f"{advice.cash_pct:.0f} % de efectivo, el buffer para rebalancear. "
        f"Ninguna de las dos filas es la regla por separado."
    )


#  Indexation of spending — N8
#  ---------------------------
#  The tornado lever bumps ``withdrawal_growth_rate``: how much spending (or
#  deposits) grow each year. Calling it "Inflación" promised a real-return shock
#  the Monte Carlo does not compute. For an accumulator the sign is inverted:
#  more "inflation" grows deposits and P10 rises. Identifiers (``inflation``,
#  ``inflation_hot``, ``inflation_delta_pct``) keep their names, like
#  ``above_sma200``. Locked by ``tests/test_indexation_label_contract.py``.

INDEXATION_LABEL = "Indexación del gasto"
INDEXATION_SHORT = "Indexación"
INDEXATION_HELP = (
    "Cuánto crece el gasto o el aporte cada año. **No es la inflación del plan**: "
    "no baja el retorno real. El Monte Carlo sigue siendo nominal."
)
INDEXATION_HELP_ACCUMULATION = (
    "En acumulación esta palanca hace crecer los depósitos. Subirla agranda el "
    "P10: no es que la inflación te ayude, es que el laboratorio indexa el aporte "
    "con el mismo número."
)
INDEXATION_HELP_WITHDRAWAL = (
    "En retiro esta palanca hace crecer el gasto cada año. Subirla achica el pozo. "
    "No modela inflación en el retorno."
)
INDEXATION_SCENARIO_DESCRIPTION = (
    "El gasto (o el aporte) crece más rápido cada año. No es un shock de inflación "
    "sobre el retorno real."
)


def indexation_help(*, has_contribution: bool, has_withdrawal: bool) -> str:
    """Phase-aware caption for the sensitivity lever (N8)."""
    if has_contribution and not has_withdrawal:
        return INDEXATION_HELP_ACCUMULATION
    if has_withdrawal and not has_contribution:
        return INDEXATION_HELP_WITHDRAWAL
    if has_contribution and has_withdrawal:
        return (
            INDEXATION_HELP
            + " Con aportes y retiros a la vez, el signo depende de cuál manda."
        )
    return INDEXATION_HELP


def indexation_scenario_label(delta_pct: float) -> str:
    """Scenario name: the lever, not «Inflación +Npp»."""
    sign = "+" if delta_pct >= 0 else ""
    return f"{INDEXATION_LABEL} {sign}{delta_pct:.0f}pp"


#  Dividend dimension ceiling — N7
#  -------------------------------
#  ``_score_dividends`` pays 4 (yield) + 3 (payout) + 3 (streak) = 10. A fund
#  has no ``payoutRatio`` (13/13 cached funds missing, 130/130 equities
#  present), so the payout leg is unreachable and the real ceiling is 7.
#  Showing «Dividend x/10» on a fund promised a scale the asset cannot reach.
#  The scorer is untouched: this is the denominator of the label. Locked by
#  ``tests/test_dividend_scale_label_contract.py``.

DIVIDEND_SCORE_MAX_EQUITY = 10
DIVIDEND_SCORE_MAX_FUND = 7
DIVIDEND_PAYOUT_POINTS = 3


def dividend_score_max(asset_class: str | None) -> int:
    """Label denominator for the dividend dimension (N7)."""
    if (asset_class or "").strip().lower() == "fund":
        return DIVIDEND_SCORE_MAX_FUND
    return DIVIDEND_SCORE_MAX_EQUITY


def format_dividend_score(score: float, asset_class: str | None = None) -> str:
    return f"{float(score):.0f}/{dividend_score_max(asset_class)}"


def dividend_score_help(asset_class: str | None = None) -> str:
    if dividend_score_max(asset_class) == DIVIDEND_SCORE_MAX_FUND:
        return (
            "Techo 7, no 10: un fund no reporta payoutRatio, así que los 3 puntos "
            "del payout son inalcanzables por construcción."
        )
    return "Yield (hasta 4) + payout (hasta 3) + racha (hasta 3)."


def roic_sustained_help(config=None) -> str:
    """Help for the ``roic_sustained`` dimension, for the mode actually running.

    Both texts quote thresholds, and the engine applies only one set of them:
    ``_score_roic_sustained`` scores the spread over the hurdle when
    ``MOAT.use_roic_wacc_spread`` is on and the legacy absolute bands when it is
    off. Picking the text from the flag is what keeps U1-4 from re-creating, with
    the polarity flipped, the very defect it removed — a tooltip describing a
    rule that is not running.
    """
    if config is None:
        from config import MOAT as config  # noqa: N811 — singleton default
    return ROIC_SPREAD_HELP if getattr(config, "use_roic_wacc_spread", True) else ROIC_ABSOLUTE_HELP


# --------------------------------------------------------------------------- #
#  Canonical wording for the dividend-growth streak (U1-5)                    #
# --------------------------------------------------------------------------- #
#  ``_score_dividends`` walks ``annual_dividend_totals`` — closed calendar years
#  of payments as reported by the feed (yfinance) — and pays 3 points at
#  ``streak >= 10``. The note it wrote called that company a "Dividend
#  Aristocrat", which is not a description: it is the **S&P Dividend
#  Aristocrats** index, and membership needs 25 consecutive years of increases
#  *plus* S&P 500 membership (and the index's size/liquidity screens). The engine
#  checks neither, so the badge promised a status the data cannot support.
#
#  The fix is the wording: say what was actually counted — a streak of N closed
#  years, from the feed. **No cut moved**: 10/5/2 still pay 3/2/1 points.
#
#  Locked by ``tests/test_dividend_label_contract.py``.

#: Years of increases the S&P index requires — quoted in the help so the reader
#: can see the gap between the two claims, never used as a threshold.
SP_ARISTOCRAT_YEARS = 25

DIVIDEND_STREAK_LABEL = "racha de dividendo creciente"
DIVIDEND_STREAK_HELP = (
    "Años calendario **cerrados** consecutivos en los que el dividendo total "
    "creció, contados sobre el historial de pagos del feed. **No es el índice "
    f"S&P Dividend Aristocrats**, que exige {SP_ARISTOCRAT_YEARS} años de "
    "aumentos y pertenencia al S&P 500: acá el corte que puntúa son 10 años y no "
    "se verifica ningún índice."
)


def dividend_streak_note(streak: int) -> str:
    """The note the engine attaches to a long streak — says what it counted.

    A single formatter so the number in the sentence and the number the scorer
    measured cannot drift apart, and so the wording lives with the rest of the
    canonical vocabulary instead of inside ``_score_dividends``.
    """
    return (
        f"Racha de {int(streak)} años consecutivos de dividendo creciente "
        "(años calendario cerrados del feed)"
    )


# --------------------------------------------------------------------------- #
#  Canonical wording for the guardrails withdrawal strategy (U1-6)            #
# --------------------------------------------------------------------------- #
#  ``apply_withdrawal_strategy`` implements **two** of the four Guyton-Klinger
#  decision rules: capital preservation (the withdrawal rate rises past the
#  ceiling band → cut spending) and prosperity (it falls below the floor band →
#  raise spending). Three pieces of the canonical method are not there:
#
#    * the **inflation rule** — GK freezes the inflation raise after a year with
#      a negative portfolio return; the engine applies it every year
#      (``spend *= (1 + inflation_rate)``, unconditional);
#    * the **portfolio management rule** — which sleeve funds the withdrawal;
#      the engine sells the portfolio pro rata;
#    * the **time bound on the cut** — GK suspends capital preservation in the
#      last 15 years of the plan; the engine applies it at every horizon year.
#
#  The U1-6 ``no_hacer`` forbids re-implementing canonical GK, so the fix is the
#  copy: the strategy is named "simplificado" and every surface that invokes the
#  Guyton-Klinger name carries the one-line list of what is missing.
#
#  Locked by ``tests/test_guardrails_label_contract.py``.

GUARDRAILS_LABEL = "Guardrails (simplificado)"
GUARDRAILS_LABEL_LONG = "Guardrails (Guyton-Klinger simplificado)"
#: Always rendered right after one of the labels above, which already carry the
#: word "simplificado" — so this sentence starts with the substance instead of
#: repeating the qualifier.
GUARDRAILS_OMISSIONS = (
    "Implementa 2 de las 4 reglas de Guyton-Klinger — preservación de capital "
    "(recorte) y prosperidad (aumento). No implementa la regla de "
    "inflación (GK congela el ajuste después de un año negativo; acá se aplica "
    "siempre), la regla de manejo de cartera (de qué activo sale el retiro; acá "
    "se vende a prorrata) ni el límite temporal del recorte (GK lo suspende en "
    "los últimos 15 años del plan)."
)


def guardrails_help(config=None) -> str:
    """Help for the guardrails strategy: the bands that run + what is missing.

    The bands are read from ``config.WITHDRAWAL`` rather than typed, the same way
    ``roic_sustained_help`` reads ``MOAT`` — a tooltip that quotes a number the
    engine is not using is the defect this wave exists to remove.
    """
    if config is None:
        from config import WITHDRAWAL as config  # noqa: N811 — singleton default
    return (
        f"Tasa base sobre el valor inicial. Si la tasa efectiva sube "
        f"{config.guardrail_ceiling_band * 100:.0f}% por encima → recorta el gasto "
        f"{config.guardrail_cut_pct * 100:.0f}%; si baja "
        f"{config.guardrail_floor_band * 100:.0f}% por debajo → lo sube "
        f"{config.guardrail_raise_pct * 100:.0f}%.\n\n" + GUARDRAILS_OMISSIONS
    )


# --------------------------------------------------------------------------- #
#  Canonical wording for the optimizer's drawdown estimate (U1-10)            #
# --------------------------------------------------------------------------- #
#  ``OptimizationResult.max_drawdown_estimate_pct`` is ``-volatility × 1.5``: a
#  rule of thumb, not a modelled figure. Nothing is simulated, no path is drawn
#  and this portfolio's own history is never read — the number is a linear
#  function of the annual volatility and of nothing else. The U1-10 ``no_hacer``
#  is "presentarlo como dato de modelo", so every surface says where it comes
#  from and the multiple moved to ``OptimizerConfig.max_dd_vol_multiple``.
#
#  The simulated drawdown does exist elsewhere: ``MonteCarloResult`` computes it
#  over market paths (``median_max_drawdown_pct``). The two must not be confused,
#  which is why the help points at it.
#
#  Locked by ``tests/test_drawdown_label_contract.py``.

MAX_DD_ESTIMATE_LABEL = "Max Drawdown est. (regla empírica)"
MAX_DD_ESTIMATE_SHORT = "Max DD est. (regla)"


def max_dd_estimate_help(config=None) -> str:
    """Help for the drawdown estimate, quoting the multiple actually applied."""
    if config is None:
        from config import OPTIMIZER as config  # noqa: N811 — singleton default
    return (
        f"Regla empírica, no un modelo: −{config.max_dd_vol_multiple:.1f}× la "
        "volatilidad anual de la cartera, a 1 año. No sale de simular caminos ni "
        "de la historia de esta cartera — el drawdown simulado se calcula sobre "
        "los paths del Monte Carlo, en Simulaciones."
    )


# --------------------------------------------------------------------------- #
#  Canonical wording for the Monte Carlo's annualised pot growth (U1-7)       #
# --------------------------------------------------------------------------- #
#  ``MonteCarloResult.median_cagr_pct`` is ``(terminal / initial) ** (1/n) - 1``.
#  That is a **return** only while no money crosses the boundary of the
#  portfolio. With cash flows it stops being one, in both directions:
#
#    * **contributions** land in ``terminal`` but never in ``initial``, so the
#      figure inflates far above anything the portfolio earned (measured: 6,3 %
#      published for a market that returned −0,2 % over the same 20 years);
#    * **withdrawals** leave ``terminal`` without ever leaving ``initial``, so it
#      deflates below the return (−5,0 % on that same market).
#
#  Eleven points of spread on one portfolio, driven by the payment calendar
#  alone. A third distortion rides along with withdrawals: the engine computes
#  the per-path figure as ``where(terminal > 0, terminal, nan)`` + ``nanmedian``,
#  so ruined paths are dropped and what gets published describes the survivors.
#
#  The honest number here is money-weighted (a TIR/IRR), and the U1-7 ``no_hacer``
#  is exactly "IRR completo" — so this wave names the quantity instead of
#  building it. Below the flag, the vocabulary picks itself.
#
#  ``mc_has_cash_flows`` lives here rather than on ``MonteCarloResult`` on
#  purpose: U1-7 adds nothing whatsoever to ``portfolio/monte_carlo.py``.
#
#  Locked by ``tests/test_pot_growth_label_contract.py``.

POT_GROWTH_LABEL = "Crecimiento del pozo"
POT_GROWTH_SHORT = "Crec. del pozo"
#: Only for a projection with zero cash flows, where the growth of the pot and
#: the return of the portfolio are the same number.
POT_CAGR_LABEL = "CAGR"


def mc_has_cash_flows(mc_result) -> bool:
    """True when money crossed the portfolio boundary during the projection.

    Accepts a ``MonteCarloResult``, a persisted ``mc_summary`` mapping or None,
    so the one predicate serves the live pages, the PDF and the saved bundle.

    Contributions have their own field since tier2, but a negative
    ``annual_withdrawal`` still means one — that is how ``GoalPlanner`` modelled
    ``Goal.annual_contribution`` and how older saved bundles are stored — so
    both are checked. Missing either would let a savings-only plan report "no
    cash flows", and the pot's growth would be relabelled a *return* (U1-7) on
    exactly the plan where that overstates it most.
    """
    if mc_result is None:
        return False
    if isinstance(mc_result, Mapping):
        withdrawal = mc_result.get("annual_withdrawal") or 0.0
        contribution = mc_result.get("annual_contribution") or 0.0
        strategy = mc_result.get("withdrawal_strategy_applied")
    else:
        withdrawal = getattr(mc_result, "annual_withdrawal", 0.0) or 0.0
        contribution = getattr(mc_result, "annual_contribution", 0.0) or 0.0
        strategy = getattr(mc_result, "withdrawal_strategy_applied", None)
    return bool(float(withdrawal) != 0.0 or float(contribution) != 0.0 or strategy)


def pot_growth_pct(terminal: float, initial: float, years: float) -> Optional[float]:
    """Annualised growth of the pot, in percent — the single implementation.

    Returns None where the rate is undefined: a pot that ran dry has no growth
    rate, and neither does a zero-length horizon. Callers must render that as
    "—", never as 0 %, which would read as "flat" instead of "ruined".
    """
    try:
        terminal = float(terminal)
        initial = float(initial)
        years = float(years)
    except (TypeError, ValueError):
        return None
    if terminal <= 0 or initial <= 0 or years <= 0:
        return None
    return ((terminal / initial) ** (1.0 / years) - 1.0) * 100.0


def pot_growth_delta(pct: float, has_cash_flows: bool) -> str:
    """The one-line subtitle under a projected value (``st.metric`` delta).

    When *every* simulated path ran dry the engine's ``nanmedian`` has nothing
    left to take a median of and the field is NaN. Printing "nan%/año" states a
    rate where there is none — say so instead.
    """
    try:
        pct = float(pct)
    except (TypeError, ValueError):
        pct = float("nan")
    if pct != pct or pct in (float("inf"), float("-inf")):
        return "sin tasa: todos los caminos se quedan sin dinero"
    if has_cash_flows:
        return f"{pct:.1f}%/año de {POT_GROWTH_LABEL.lower()}"
    return f"{pct:.1f}%/año ({POT_CAGR_LABEL})"


def pot_growth_column_label(has_cash_flows: bool) -> str:
    """Header for a table column holding the figure."""
    if has_cash_flows:
        return f"{POT_GROWTH_SHORT} %/año"
    return f"{POT_CAGR_LABEL} %/año"


def pot_growth_help(has_cash_flows: bool) -> str:
    """Tooltip: what the figure is, and — when it matters — what it is not."""
    if not has_cash_flows:
        return (
            "Crecimiento anual compuesto del pozo. Sin aportes ni retiros en la "
            f"proyección, coincide con el retorno de la cartera, así que acá "
            f"sí es un {POT_CAGR_LABEL}."
        )
    return (
        "Cuánto crece el pozo por año, **no es un retorno**: el capital que "
        "aportás entra en el valor final sin estar en el inicial (infla la "
        "cifra) y lo que retirás sale del final sin salir del inicial (la "
        "hunde). El número que sí sería un retorno con flujos es money-weighted "
        "(TIR), y este proyecto todavía no lo calcula.\n\n"
        "Si hay caminos que se quedan sin dinero, la cifra describe solo los "
        "que sobrevivieron."
    )


# --------------------------------------------------------------------------- #
#  Canonical wording for the backtest's return gap vs the benchmark (U1-8)    #
# --------------------------------------------------------------------------- #
#  ``BacktestResult.excess_return_pct`` and ``TickerPerformance`` are plain
#  arithmetic: ``CAGR_own − CAGR_benchmark``. Alpha is what is left of that gap
#  *after* discounting the part explained by market exposure — it needs a beta,
#  and the backtest never estimates one. A portfolio holding a 1.4-beta basket
#  in a rising market shows a positive gap with no alpha whatsoever, and the
#  ``α`` glyph the page used to print promised exactly the adjustment that was
#  missing. The U1-8 ``no_hacer`` forbids introducing beta in this pass, so the
#  fix is the name: the number is an excess return and says so.
#
#  The other half of U1-8 was not a label. The per-ticker row measured the
#  ticker over ``ticker ∩ benchmark`` and subtracted a benchmark CAGR measured
#  over ``portfolio ∩ benchmark`` — so a ticker with two years of history was
#  being scored against the benchmark's five-year rate. Both legs now come from
#  the same aligned window; see ``BacktestEngine.run``.
#
#  Locked by ``tests/test_excess_return_label_contract.py`` (copy) and
#  ``tests/test_backtesting.py`` (the window oracle).

EXCESS_RETURN_LABEL = "Exceso vs benchmark"
EXCESS_RETURN_SHORT = "Exceso vs bench"
EXCESS_RETURN_HELP = (
    "CAGR propio menos el CAGR del benchmark, medidos sobre la **misma ventana** "
    "de fechas. **No es alpha**: no se descuenta la parte del exceso que explica "
    "la exposición al mercado, porque el backtest no estima beta. Una cartera más "
    "volátil puede mostrar exceso positivo sin haber agregado nada."
)


def excess_return_column_label(benchmark: str = "") -> str:
    """Header for the per-ticker column, naming the benchmark it compares against."""
    if benchmark:
        return f"Exceso vs {benchmark} %"
    return f"{EXCESS_RETURN_SHORT} %"


# --------------------------------------------------------------------------- #
#  Canonical wording for the downside-volatility ratio (U1-9)                 #
# --------------------------------------------------------------------------- #
#  Two engines publish a number called "Sortino" and neither one is a Sortino
#  ratio. ``analysis/backtesting.py`` and ``portfolio/tracker.py`` both compute
#  the denominator as ``returns[returns < 0].std()``: the standard deviation of
#  the losing weeks **around their own mean**. The Sortino denominator is the
#  downside deviation ``√E[mín(r − MAR, 0)²]``, taken over *every* return with
#  the gains entering as zeros and the deviations measured from the MAR, not
#  from the mean of the losses.
#
#  They are not the same quantity and the difference is not a rounding
#  artefact: dropping the winning weeks shrinks the sample, and centring on the
#  mean of the losses instead of on the MAR removes the level of the losses
#  entirely. A run of uniformly bad weeks has a small spread around its own
#  mean, so the current denominator goes *down* exactly when the portfolio is
#  losing steadily — and the published ratio goes up.
#
#  The U1-9 ``no_hacer`` is "relabel + recálculo juntos": moving the formula
#  changes every ratio on two surfaces at once and belongs to its own wave
#  (oleada 5). This pass only stops the number from claiming a name it has not
#  earned — no value moves.
#
#  Locked by ``tests/test_downside_ratio_label_contract.py``.

DOWNSIDE_RATIO_LABEL = "Ratio retorno/vol bajista"
DOWNSIDE_RATIO_SHORT = "Ret./vol bajista"
DOWNSIDE_RATIO_HELP = (
    "Retorno anualizado menos la tasa libre de riesgo, dividido por el desvío de "
    "las semanas negativas. **No es el ratio de Sortino**: el denominador de "
    "Sortino es √E[mín(r − MAR, 0)²] sobre *todos* los retornos, medido contra el "
    "MAR; acá se mide el desvío de las semanas perdedoras alrededor de su propia "
    "media. Sirve para ordenar activos entre sí dentro de esta pantalla, no para "
    "compararlo contra un Sortino publicado afuera."
)


# --------------------------------------------------------------------------- #
#  Future-value primitives (used by gap-to-goal)                              #
# --------------------------------------------------------------------------- #

def _fv_lump_and_annuity(
    capital: float,
    annual_contribution: float,
    years: float,
    annual_return: float,
) -> float:
    """End value of capital compounded + end-of-year contributions (simple annuity)."""
    r = float(annual_return)
    t = max(float(years), 0.0)
    c = max(float(capital), 0.0)
    a = max(float(annual_contribution), 0.0)
    if t <= 0:
        return c
    if abs(r) < 1e-12:
        return c + a * t
    growth = (1.0 + r) ** t
    return c * growth + a * (growth - 1.0) / r


def _years_to_reach(
    capital: float,
    annual_contribution: float,
    annual_return: float,
    target: float,
    max_years: int = 80,
) -> Optional[int]:
    """Smallest whole years so FV >= target, or None if unreachable within max_years."""
    if target <= capital:
        return 0
    for y in range(1, max_years + 1):
        if _fv_lump_and_annuity(capital, annual_contribution, y, annual_return) >= target:
            return y
    return None


def _extra_annual_needed(
    capital: float,
    annual_contribution: float,
    years: float,
    annual_return: float,
    target: float,
) -> float:
    """Additional annual contribution so FV hits target (0 if already there)."""
    base = _fv_lump_and_annuity(capital, annual_contribution, years, annual_return)
    if base >= target:
        return 0.0
    r = float(annual_return)
    t = max(float(years), 0.0)
    if t <= 0:
        return max(target - capital, 0.0)
    if abs(r) < 1e-12:
        gap = target - capital - annual_contribution * t
        return max(gap / t, 0.0)
    growth = (1.0 + r) ** t
    # Solve: C*g + (A+X)*(g-1)/r >= T  →  X >= (T - C*g)*r/(g-1) - A
    needed_total_annuity = (target - capital * growth) * r / (growth - 1.0)
    return max(needed_total_annuity - annual_contribution, 0.0)


# --------------------------------------------------------------------------- #
#  1 — Home plan hub payload                                                  #
# --------------------------------------------------------------------------- #

@dataclass
class HomePlanHub:
    """What Home needs to answer “¿cómo viene tu plan?” without a live fetch."""

    has_plan: bool
    plan_name: str = ""
    prob_target_pct: Optional[float] = None
    median_terminal: Optional[float] = None
    expected_return_pct: Optional[float] = None
    drift_pct: Optional[float] = None  # weighted_delta from last refresh, if any
    data_age_days: Optional[int] = None
    unread_alerts: int = 0
    primary_action: Dict[str, str] = field(default_factory=dict)
    sample_plan_available: bool = False
    track_record_line: str = ""
    empty_reason: str = ""

    def as_dict(self) -> dict:
        return {
            "has_plan": self.has_plan,
            "plan_name": self.plan_name,
            "prob_target_pct": self.prob_target_pct,
            "median_terminal": self.median_terminal,
            "expected_return_pct": self.expected_return_pct,
            "drift_pct": self.drift_pct,
            "data_age_days": self.data_age_days,
            "unread_alerts": self.unread_alerts,
            "primary_action": dict(self.primary_action),
            "sample_plan_available": self.sample_plan_available,
            "track_record_line": self.track_record_line,
            "empty_reason": self.empty_reason,
        }


def build_home_plan_hub(
    *,
    plan_snapshot: Any = None,
    primary_action: Optional[Mapping[str, str]] = None,
    unread_alerts: int = 0,
    sample_plan_available: bool = False,
    track_record_line: str = "",
    data_age_days: Optional[int] = None,
) -> HomePlanHub:
    """Assemble Home hub fields from an optional PlanSnapshot-like object."""
    action = dict(primary_action or {})
    if plan_snapshot is None:
        return HomePlanHub(
            has_plan=False,
            primary_action=action,
            sample_plan_available=sample_plan_available,
            track_record_line=track_record_line or "",
            unread_alerts=int(unread_alerts or 0),
            empty_reason="Todavía no tenés un plan activo. Probá un plan de ejemplo o completá el camino guiado.",
        )

    mc = getattr(plan_snapshot, "mc_summary", None) or {}
    metrics = getattr(plan_snapshot, "metrics", None) or {}
    refreshed = getattr(plan_snapshot, "refreshed_metrics", None) or {}
    summary = refreshed.get("summary") if isinstance(refreshed, dict) else None
    if not isinstance(summary, dict):
        summary = {}

    drift = summary.get("weighted_delta_pct")
    if drift is not None:
        try:
            drift = float(drift)
        except (TypeError, ValueError):
            drift = None

    prob = mc.get("prob_target_pct")
    if prob is not None:
        try:
            prob = float(prob)
        except (TypeError, ValueError):
            prob = None

    median = mc.get("median_terminal")
    if median is not None:
        try:
            median = float(median)
        except (TypeError, ValueError):
            median = None

    exp_ret = metrics.get("expected_return_pct")
    if exp_ret is not None:
        try:
            exp_ret = float(exp_ret)
        except (TypeError, ValueError):
            exp_ret = None

    return HomePlanHub(
        has_plan=True,
        plan_name=str(getattr(plan_snapshot, "name", "") or ""),
        prob_target_pct=prob,
        median_terminal=median,
        expected_return_pct=exp_ret,
        drift_pct=drift,
        data_age_days=data_age_days,
        unread_alerts=int(unread_alerts or 0),
        primary_action=action,
        sample_plan_available=sample_plan_available,
        track_record_line=track_record_line or "",
    )


# --------------------------------------------------------------------------- #
#  3 — Gap-to-goal levers                                                     #
# --------------------------------------------------------------------------- #

@dataclass
class GapLever:
    kind: str           # more_savings | more_years | lower_target | higher_return
    label: str
    detail: str
    value: float        # magnitude (USD/year, years, target USD, return delta pp)
    unit: str
    cta_hint: str       # where to act in the product

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "label": self.label,
            "detail": self.detail,
            "value": self.value,
            "unit": self.unit,
            "cta_hint": self.cta_hint,
        }


def compute_gap_to_goal_levers(
    *,
    capital: float,
    annual_contribution: float,
    years: float,
    annual_return: float,
    target: float,
    prob_achieve_pct: Optional[float] = None,
    soft_threshold_pct: float = 70.0,
) -> List[dict]:
    """Concrete levers when the projection is unlikely to hit the goal.

    Uses closed-form FV (not Monte Carlo) so the UI can show *numbers* instantly.
    Returns [] when target is missing, already reachable under the simple model,
    or when probability (if provided) is already comfortable.
    """
    if target is None or float(target) <= 0:
        return []
    if prob_achieve_pct is not None and float(prob_achieve_pct) >= soft_threshold_pct:
        # Still offer levers if the simple FV is short of target (conservative floor).
        fv = _fv_lump_and_annuity(capital, annual_contribution, years, annual_return)
        if fv >= float(target):
            return []

    capital = max(float(capital), 0.0)
    annual_contribution = max(float(annual_contribution), 0.0)
    years = max(float(years), 1.0)
    annual_return = float(annual_return)
    target = float(target)

    fv = _fv_lump_and_annuity(capital, annual_contribution, years, annual_return)
    levers: List[GapLever] = []

    extra_annual = _extra_annual_needed(capital, annual_contribution, years, annual_return, target)
    if extra_annual > 0:
        monthly = extra_annual / 12.0
        levers.append(GapLever(
            kind="more_savings",
            label="Aportar más por mes",
            detail=(
                f"Sumá ~${monthly:,.0f}/mes (${extra_annual:,.0f}/año) para llegar a "
                f"${target:,.0f} en {years:.0f} años con retorno ~{annual_return*100:.1f}%."
            ),
            value=round(monthly, 2),
            unit="usd_per_month",
            cta_hint="Simulaciones → Mis Metas / perfil de ahorro · Mi Plan",
        ))

    need_years = _years_to_reach(capital, annual_contribution, annual_return, target)
    if need_years is not None and need_years > years:
        extra_y = int(need_years - years)
        levers.append(GapLever(
            kind="more_years",
            label="Extender el horizonte",
            detail=(
                f"Con el aporte actual, la meta se alcanza en ~{need_years} años "
                f"(+{extra_y} vs los {years:.0f} planificados)."
            ),
            value=float(extra_y),
            unit="years",
            cta_hint="Simulaciones → horizonte · Mi Plan",
        ))

    # Lower target to what is achievable at current path (median-style FV).
    if fv > 0 and fv < target:
        cut_pct = (1.0 - fv / target) * 100.0
        levers.append(GapLever(
            kind="lower_target",
            label="Ajustar la meta",
            detail=(
                f"Con el camino actual el valor proyectado es ~${fv:,.0f}. "
                f"Bajar la meta un ~{cut_pct:.0f}% la pone al alcance."
            ),
            value=round(fv, 0),
            unit="usd_achievable",
            cta_hint="Simulaciones → meta de capital",
        ))

    # Higher return: how many extra pp of annual return close the gap (capped search).
    if fv < target:
        for extra_pp in (0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0):
            r2 = annual_return + extra_pp / 100.0
            if _fv_lump_and_annuity(capital, annual_contribution, years, r2) >= target:
                levers.append(GapLever(
                    kind="higher_return",
                    label="Más retorno (más riesgo)",
                    detail=(
                        f"Un retorno ~{extra_pp:.1f} pp mayor al actual "
                        f"({annual_return*100:.1f}% → {(annual_return + extra_pp/100)*100:.1f}%) "
                        "alcanzaría la meta en el mismo horizonte — implica más volatilidad."
                    ),
                    value=float(extra_pp),
                    unit="return_pp",
                    cta_hint="Optimizer → perfil de riesgo · Portfolio",
                ))
                break

    return [lv.as_dict() for lv in levers]


# --------------------------------------------------------------------------- #
#  8 — Annual “qué hacer este año” checklist                                  #
# --------------------------------------------------------------------------- #

def build_annual_action_list(
    *,
    plan_snapshot: Any = None,
    monthly_savings: float = 0.0,
    has_portfolio_positions: bool = False,
    drift_pct: Optional[float] = None,
    drift_threshold_pct: float = 5.0,
    last_backup_days: Optional[int] = None,
    review_every_months: int = 6,
) -> List[dict]:
    """Actionable checklist for the next 12 months from plan + optional drift."""
    actions: List[dict] = []
    personal = {}
    if plan_snapshot is not None:
        personal = getattr(plan_snapshot, "personal", None) or {}
        name = str(getattr(plan_snapshot, "name", "") or "tu plan")
    else:
        name = "tu plan"

    annual = float(monthly_savings or 0.0) * 12.0
    if annual <= 0 and personal:
        try:
            annual = float(personal.get("annual_savings") or 0.0)
        except (TypeError, ValueError):
            annual = 0.0
        if annual <= 0:
            try:
                annual = float(personal.get("monthly_savings") or 0.0) * 12.0
            except (TypeError, ValueError):
                annual = 0.0

    if annual > 0:
        actions.append({
            "id": "contribute",
            "priority": 1,
            "title": f"Aportar ~${annual/12:,.0f}/mes a {name}",
            "detail": f"Meta de aporte anual: ${annual:,.0f} (según tu perfil/plan).",
            "when": "mensual",
            "cta_page": "12_Plan.py",
        })
    else:
        actions.append({
            "id": "define_savings",
            "priority": 1,
            "title": "Definí cuánto podés aportar este año",
            "detail": "Sin un aporte planificado la proyección es solo teórica.",
            "when": "esta semana",
            "cta_page": "9_Settings.py",
        })

    if has_portfolio_positions:
        rebalance_due = (
            drift_pct is not None and abs(float(drift_pct)) >= float(drift_threshold_pct)
        )
        actions.append({
            "id": "rebalance",
            "priority": 2 if rebalance_due else 3,
            "title": (
                "Rebalanceá hacia el plan (desvío material)"
                if rebalance_due
                else "Revisá alineación plan vs cartera"
            ),
            "detail": (
                f"Deriva ponderada ~{float(drift_pct):+.1f}% vs umbral {drift_threshold_pct:.0f}%."
                if drift_pct is not None
                else "Compará pesos objetivo del plan con tus posiciones reales."
            ),
            "when": "ahora" if rebalance_due else f"cada {review_every_months} meses",
            "cta_page": "3_Portfolio.py",
        })
    else:
        actions.append({
            "id": "fund_core",
            "priority": 2,
            "title": "Cargá o ejecutá la lista de compra del núcleo",
            "detail": "Sin posiciones reales el plan no se puede monitorear.",
            "when": "este mes",
            "cta_page": "12_Plan.py",
        })

    actions.append({
        "id": "review_plan",
        "priority": 3,
        "title": "Revisión de salud del plan",
        "detail": "Refrescá precios, registrá evolución y regenerá la narrativa si cambió el mercado.",
        "when": f"cada {review_every_months} meses",
        "cta_page": "12_Plan.py",
    })

    if last_backup_days is None or last_backup_days > 90:
        actions.append({
            "id": "backup",
            "priority": 2,
            "title": "Exportá un respaldo del plan (JSON)",
            "detail": "Los datos viven en tu máquina: un backup evita perder el trabajo.",
            "when": "esta semana" if last_backup_days is None else "pronto",
            "cta_page": "12_Plan.py",
        })

    actions.append({
        "id": "stress_check",
        "priority": 4,
        "title": "Corré un stress test o sensibilidad",
        "detail": "Confirmá que un mal año no rompe el plan de retiro.",
        "when": "1–2 veces al año",
        "cta_page": "7_Simulaciones.py",
    })

    actions.sort(key=lambda a: a["priority"])
    return actions


# --------------------------------------------------------------------------- #
#  7 — Deep plan compare                                                      #
# --------------------------------------------------------------------------- #

def _safe_float(v: Any, default: Optional[float] = None) -> Optional[float]:
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _plan_field_map(snap: Any) -> Dict[str, Any]:
    """Normalize a PlanSnapshot (or duck-type) into comparable scalar fields."""
    if snap is None:
        return {}
    mc = getattr(snap, "mc_summary", None) or {}
    metrics = getattr(snap, "metrics", None) or {}
    personal = getattr(snap, "personal", None) or {}
    drags = getattr(snap, "drags_at_save", None) or {}
    wd = getattr(snap, "withdrawal_strategy", None) or {}
    alloc = getattr(snap, "allocation", None) or []
    top = []
    if isinstance(alloc, list):
        ranked = sorted(
            [a for a in alloc if isinstance(a, dict)],
            key=lambda a: float(a.get("weight_pct") or 0),
            reverse=True,
        )
        top = [f"{a.get('symbol', '?')} {float(a.get('weight_pct') or 0):.1f}%" for a in ranked[:5]]

    return {
        "name": str(getattr(snap, "name", "") or ""),
        "profile": str(getattr(snap, "profile_name", "") or getattr(snap, "profile_key", "") or ""),
        "n_positions": int(getattr(snap, "n_positions", 0) or 0),
        "expected_return_pct": _safe_float(metrics.get("expected_return_pct")),
        "volatility_pct": _safe_float(metrics.get("volatility_pct")),
        "sharpe_ratio": _safe_float(metrics.get("sharpe_ratio")),
        "dividend_yield_pct": _safe_float(metrics.get("dividend_yield_pct")),
        "adjusted_score_avg": _safe_float(metrics.get("adjusted_score_avg")),
        "median_terminal": _safe_float(mc.get("median_terminal")),
        "p10_terminal": _safe_float(mc.get("p10_terminal")),
        "prob_target_pct": _safe_float(mc.get("prob_target_pct")),
        "horizon_years": _safe_float(personal.get("primary_horizon_years") or personal.get("horizon_years")),
        "current_capital": _safe_float(personal.get("current_capital")),
        "monthly_savings": _safe_float(personal.get("monthly_savings")),
        "drag_total_pct": _safe_float(drags.get("total_annual_drag_pct") or drags.get("annual_fee_pct")),
        "withdrawal_strategy": str(wd.get("strategy") or wd.get("name") or "") if isinstance(wd, dict) else "",
        "top_holdings": ", ".join(top) if top else "",
        "narrative_len": len(str(getattr(snap, "narrative", "") or "")),
    }


_COMPARE_LABELS = {
    "profile": "Perfil de riesgo",
    "n_positions": "Posiciones",
    "expected_return_pct": PROXY_INDEX_LABEL,
    "volatility_pct": "Volatilidad %",
    "sharpe_ratio": PROXY_RATIO_LABEL,
    "dividend_yield_pct": "Div. yield %",
    "adjusted_score_avg": "Score promedio",
    "median_terminal": "Mediana final ($)",
    "p10_terminal": "Pesimista p10 ($)",
    "prob_target_pct": "Prob. de meta %",
    "horizon_years": "Horizonte (años)",
    "current_capital": "Capital actual ($)",
    "monthly_savings": "Ahorro mensual ($)",
    "drag_total_pct": "Drags anuales %",
    "withdrawal_strategy": "Estrategia de retiro",
    "top_holdings": "Top 5 holdings",
}


def deep_compare_plans(plan_a: Any, plan_b: Any) -> dict:
    """Side-by-side assumptions + outcomes. Pure; works with PlanSnapshot or dicts."""
    a = _plan_field_map(plan_a)
    b = _plan_field_map(plan_b)
    rows: List[dict] = []
    diffs: List[str] = []

    for key, label in _COMPARE_LABELS.items():
        va, vb = a.get(key), b.get(key)
        row = {
            "field": key,
            "label": label,
            "a": va if va is not None else "—",
            "b": vb if vb is not None else "—",
            "differs": va != vb and not (va is None and vb is None),
        }
        # numeric delta when both numbers
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            row["delta"] = round(float(vb) - float(va), 4)
            if abs(row["delta"]) > 1e-9:
                diffs.append(f"{label}: {va} → {vb} (Δ {row['delta']:+g})")
        elif row["differs"]:
            diffs.append(f"{label}: «{va}» vs «{vb}»")
            row["delta"] = None
        else:
            row["delta"] = 0 if isinstance(va, (int, float)) else None
        rows.append(row)

    return {
        "name_a": a.get("name") or "Plan A",
        "name_b": b.get("name") or "Plan B",
        "rows": rows,
        "n_differences": sum(1 for r in rows if r["differs"]),
        "highlights": diffs[:12],
    }


# --------------------------------------------------------------------------- #
#  15 — Track record one-liner                                                #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
#  Promediar y capitalizar no son la misma pregunta (U7-3)                    #
# --------------------------------------------------------------------------- #
#  La página de Track Record mostraba dos agregaciones de los MISMOS datos, las
#  dos bien calculadas, y sacaba de ellas conclusiones de signo opuesto:
#
#      titular (media aritmética de excesos)  +3,21 %   -> «le ganó al mercado»
#      gráfico (capital capitalizado)         0,9134 vs 1,0307 del benchmark
#                                                       -> el modelo pierde
#
#  Con un desvío de 10,2 sobre un rango de −23,5 a +13,7, el arrastre de
#  volatilidad da vuelta la conclusión: promediar y capitalizar responden
#  preguntas distintas. Es la misma familia que `median_cagr_pct` (CONTEXT §8) y
#  se resuelve igual que U1-1/U1-2 — nombres que no se confundan.

EXCESS_MEAN_LABEL = "Exceso medio por recomendación"
EXCESS_MEAN_HELP = (
    "**Promedia** el exceso sobre el benchmark de cada recomendación, una por una, "
    "sin capitalizar. Responde «cuánto le sacó al mercado la recomendación típica». "
    "Puede dar de **signo distinto** al capital acumulado: promediar y capitalizar "
    "no son la misma operación, y con retornos dispersos el promedio puede ser "
    "positivo mientras el capital cae."
)

EQUITY_CURVE_LABEL = "Capital acumulado"
EQUITY_CURVE_HELP = (
    "**Capitaliza** las recomendaciones una tras otra, como si cada una hubiera "
    "sido una posición. Responde «en qué terminó un peso que siguió todas las "
    "señales». Puede dar de **signo distinto** al exceso medio, porque una pérdida "
    "grande pesa más al componer que al promediar."
)


def track_record_one_liner(
    summary: Optional[Mapping[str, Any]] = None,
    *,
    by_action: Optional[Mapping[str, Any]] = None,
    horizon_label: str = "12m",
    benchmark_label: str = "SPY",
) -> str:
    """Honest one-line summary for Home / Mi Plan. Empty → no history yet."""
    summary = summary or {}
    n = int(summary.get("n") or 0)
    if n <= 0:
        return "Track record: todavía no hay señales puntuadas — se va llenando con el uso."

    hit = summary.get("overall_hit_rate")
    excess = summary.get("mean_excess_pct")
    parts = [f"Track record ({n} señales, {horizon_label})"]

    # U7-3: la misma regla que el titular de la página. Un porcentaje sin su
    # banda invita a una conclusión que la muestra no sostiene: con n=11 el
    # intervalo del acierto va de 10 % a 80 %.
    if hit is not None:
        parts.append(
            "acierto direccional sin señal todavía"
            if summary.get("hit_rate_inconclusive")
            else f"acierto direccional {float(hit)*100:.0f}%"
        )
    if excess is not None:
        parts.append(
            f"exceso medio vs {benchmark_label} sin señal todavía"
            if summary.get("inconclusive")
            else f"exceso medio vs {benchmark_label} {float(excess):+.1f} pp"
        )

    # Optional BUY-focused honesty
    if by_action:
        for key in ("BUY", "STRONG BUY", "STRONG_BUY"):
            block = by_action.get(key) or by_action.get(key.replace(" ", "_"))
            if block and block.get("n"):
                hr = block.get("hit_rate")
                if hr is not None and not block.get("inconclusive"):
                    parts.append(f"{key} {float(hr)*100:.0f}% hit (n={block['n']})")
                break

    return " · ".join(parts) + "."


# --------------------------------------------------------------------------- #
#  12 — Coach: market drop + plan still OK                                    #
# --------------------------------------------------------------------------- #

def coach_should_fire_on_drop(
    *,
    portfolio_return_pct: float,
    drop_threshold_pct: float = 8.0,
    plan_prob_target_pct: Optional[float] = None,
    plan_prob_floor_pct: float = 40.0,
    already_on_cooldown: bool = False,
) -> dict:
    """Predicate for a proactive “plan sigue OK” coach after a market/portfolio drop.

    Returns ``{should_fire, severity, message, context}``. Pure — the alert engine
    owns persistence/cooldown; pass ``already_on_cooldown=True`` to suppress.
    """
    ret = float(portfolio_return_pct)
    thr = -abs(float(drop_threshold_pct))
    if already_on_cooldown or ret > thr:
        return {
            "should_fire": False,
            "severity": "info",
            "message": "",
            "context": {
                "portfolio_return_pct": ret,
                "threshold_pct": thr,
            },
        }

    plan_ok = True
    plan_note = "No hay probabilidad de meta guardada; el desvío de corto plazo no invalida un plan de largo plazo por sí solo."
    if plan_prob_target_pct is not None:
        plan_ok = float(plan_prob_target_pct) >= float(plan_prob_floor_pct)
        plan_note = (
            f"Tu plan sigue con ~{float(plan_prob_target_pct):.0f}% de probabilidad de meta "
            f"(piso de confort {plan_prob_floor_pct:.0f}%)."
            if plan_ok
            else (
                f"La cartera cayó y la prob. de meta (~{float(plan_prob_target_pct):.0f}%) "
                f"está bajo el piso {plan_prob_floor_pct:.0f}% — revisá aportes u horizonte."
            )
        )

    if plan_ok:
        msg = (
            f"📉 Caída de cartera {ret:.1f}% (umbral {thr:.0f}%). "
            f"Respirá: {plan_note} "
            "Los planes de retiro se miden en años, no en semanas. Revisá Mi Plan antes de vender por pánico."
        )
        severity = "info"
    else:
        msg = (
            f"📉 Caída de cartera {ret:.1f}% y el plan necesita atención. {plan_note}"
        )
        severity = "warning"

    return {
        "should_fire": True,
        "severity": severity,
        "message": msg,
        "context": {
            "portfolio_return_pct": ret,
            "threshold_pct": thr,
            "plan_prob_target_pct": plan_prob_target_pct,
            "plan_ok": plan_ok,
        },
    }


# --------------------------------------------------------------------------- #
#  10 — Argentina dual-currency presentation                                  #
# --------------------------------------------------------------------------- #
#
# Audit U2-5 (oleada 2 · P0 · negocio) — "Mediana 20-30y a ARS al FX spot".
#
# The Monte Carlo terminal is USD *nominal at year N*: the paths bootstrap
# nominal weekly returns and the drag layer models fees/taxes/rebalancing, never
# inflation. Multiplying that by today's USD/ARS printed a peso figure whose two
# halves live 30 years apart — the number was neither today's money nor year-30
# money, and it was the biggest number on the screen.
#
# The fix converts only a *present value*: deflate to today's USD first, then
# apply today's spot. That is an exact change of unit and needs no forecast.
#
# The rejected alternative was projecting the exchange rate to year N. It needs
# an ARS-vs-USD inflation differential that this project has from no source, so
# it would replace one invented number with a bigger one — the very defect the
# rate_source guard below exists to prevent.

#: Basis of an amount handed to :func:`ar_dual_amounts`.
AR_BASIS_TODAY = "usd_hoy"           # already in today's dollars → spot is exact
AR_BASIS_PRESENT_VALUE = "valor_presente"   # nominal future, deflated to today


def present_value_usd(
    nominal_usd: float,
    *,
    annual_inflation_pct: float,
    years: float,
) -> float:
    """Deflate a nominal future USD amount to today's purchasing power.

    The single implementation of ``nominal / (1 + i) ** n`` for the product
    surface — the Simulaciones page used to spell it inline while the ARS block
    right below it ignored it entirely.
    """
    n = max(float(years), 0.0)
    i = float(annual_inflation_pct) / 100.0
    if n <= 0 or i == 0:
        return float(nominal_usd)
    if i <= -1.0:
        raise ValueError("annual_inflation_pct must be > -100")
    # Deflation (i < 0) is handled by the same formula, which makes the present
    # value *larger* — short-circuiting on ``i < 0`` would quietly understate it.
    return float(nominal_usd) / ((1.0 + i) ** n)


def ar_dual_amounts(
    usd_amount: float,
    *,
    usd_ars_oficial: float,
    usd_ars_parallel: Optional[float] = None,
    label: str = "monto",
    horizon_years: float = 0.0,
    usd_inflation_pct: Optional[float] = None,
    rate_source: str = "explicit",
) -> dict:
    """Present a USD amount in ARS with official + optional parallel (brecha).

    Product context only — not a tax or compliance engine.
    ``usd_ars_*`` = pesos per 1 USD, i.e. **today's** rate.

    ``horizon_years`` is how far away ``usd_amount`` sits:

    * ``<= 0`` — the amount is already in today's dollars and today's spot is an
      exact unit change.
    * ``> 0`` — the amount is nominal at that horizon and ``usd_inflation_pct``
      is **required**: without it there is no honest way to reach today's money,
      and converting anyway is the U2-5 defect. A missing rate raises rather than
      guessing, so the mistake cannot be made in silence.

    ``rate_source`` comes from :class:`config.ArFxConfig`. When it is
    ``"placeholder"`` the brecha is withheld: the gap between two invented
    numbers describes nothing about the market.
    """
    oficial = float(usd_ars_oficial)
    if oficial <= 0:
        raise ValueError("usd_ars_oficial must be > 0")

    nominal = float(usd_amount)
    years = max(float(horizon_years), 0.0)
    if years > 0:
        if usd_inflation_pct is None:
            raise ValueError(
                f"{label}: a nominal amount {years:g} years out cannot be converted at "
                "today's spot — pass usd_inflation_pct so it can be deflated to "
                "today's dollars first (audit U2-5)"
            )
        usd = present_value_usd(
            nominal, annual_inflation_pct=float(usd_inflation_pct), years=years
        )
        basis = AR_BASIS_PRESENT_VALUE
    else:
        usd = nominal
        basis = AR_BASIS_TODAY

    parallel = float(usd_ars_parallel) if usd_ars_parallel is not None else None
    out = {
        "label": label,
        "usd": round(usd, 2),
        "usd_nominal": round(nominal, 2),
        "basis": basis,
        "horizon_years": years,
        "usd_inflation_pct": (
            float(usd_inflation_pct) if (years > 0 and usd_inflation_pct is not None) else None
        ),
        "ars_oficial": round(usd * oficial, 0),
        "rate_oficial": oficial,
        "ars_parallel": None,
        "rate_parallel": parallel,
        "rate_source": rate_source,
        "brecha_pct": None,
        "brecha_omitted_reason": None,
    }
    if parallel is not None and parallel > 0:
        out["ars_parallel"] = round(usd * parallel, 0)
        # N1: the brecha needs BOTH legs sourced. ``rate_source`` reports the
        # weaker one, so a market official against a placeholder parallel still
        # reads "placeholder" here — which is right: one real number minus one
        # invented one is not a market observation either.
        if rate_source == "placeholder":
            out["brecha_omitted_reason"] = (
                "al menos una de las dos no es una cotización sino un valor por "
                "defecto: su brecha no dice nada del mercado"
            )
        else:
            out["brecha_pct"] = round((parallel / oficial - 1.0) * 100.0, 1)
    return out


def format_ar_dual_line(dual: Mapping[str, Any]) -> str:
    """One human-readable line for UI captions.

    Always states the basis and the rate used: a peso figure on its own reads as
    a quote, which is exactly what these numbers are not.
    """
    is_pv = dual.get("basis") == AR_BASIS_PRESENT_VALUE
    usd_note = "en dólares de hoy" if is_pv else "USD"
    parts = [f"{usd_note} ${float(dual['usd']):,.0f}"]

    rate_of = float(dual["rate_oficial"])
    parts.append(f"ARS oficial ${float(dual['ars_oficial']):,.0f} (a ${rate_of:,.0f}/USD)")
    if dual.get("ars_parallel") is not None:
        rate_par = float(dual.get("rate_parallel") or 0.0)
        parts.append(f"ARS paralelo ${float(dual['ars_parallel']):,.0f} (a ${rate_par:,.0f}/USD)")
        if dual.get("brecha_pct") is not None:
            parts.append(f"brecha {float(dual['brecha_pct']):+.1f}%")

    line = " · ".join(parts)
    if is_pv:
        line = (
            f"{line} — pesos de hoy: se descontó la inflación "
            f"({float(dual['usd_inflation_pct']):.1f}%/año × {float(dual['horizon_years']):g} años) "
            f"antes de convertir"
        )
    if dual.get("rate_source") == "placeholder":
        line = f"⚠️ tasa de referencia (no es cotización) · {line}"
    return line


def ar_dual_context(
    usd_amount: Optional[float],
    *,
    fx_config: Any,
    label: str = "monto",
    horizon_years: Optional[float] = 0.0,
    usd_inflation_pct: Optional[float] = None,
) -> dict:
    """Page-facing wrapper: everything a UI needs to render — or to explain why not.

    Returns ``{"available", "reason", "dual", "line"}``. The expected "we cannot
    say this honestly" cases come back as ``available=False`` with a reason to
    show the user, instead of an exception the page has to swallow:

    * the feature is off, or there is no amount;
    * ``horizon_years is None`` — the basis of the amount is **unknown**, which
      is not the same as zero. Plans saved before Simulaciones ran carry no
      horizon in ``mc_summary``, and reading that as "today's money" would
      convert a nominal terminal at spot again, in silence;
    * a far-away amount with no inflation assumption to deflate it.

    ``horizon_years=0`` still means "already today's money", and
    ``usd_inflation_pct=0`` is a real assumption (the user chose 0 %/yr), not a
    missing one.
    """
    out: Dict[str, Any] = {"available": False, "reason": "", "dual": None, "line": ""}

    if not getattr(fx_config, "enabled", True):
        out["reason"] = "La vista dual USD/ARS está desactivada en la configuración."
        return out
    if not usd_amount:
        out["reason"] = "No hay un monto para convertir."
        return out

    if horizon_years is None:
        out["reason"] = (
            "Este plan no guardó el horizonte de la proyección, así que no se sabe a "
            "qué año pertenecen esos dólares. Volvé a correr la simulación y guardá "
            "el plan para poder expresarlo en pesos."
        )
        return out

    years = max(float(horizon_years), 0.0)
    if years > 0 and usd_inflation_pct is None:
        out["reason"] = (
            f"Este monto es nominal a {years:g} años y no hay supuesto de inflación "
            "guardado, así que no se puede expresar en pesos de hoy. Volvé a correr "
            "la simulación para que quede registrado."
        )
        return out

    dual = ar_dual_amounts(
        float(usd_amount),
        usd_ars_oficial=float(getattr(fx_config, "usd_ars_oficial")),
        usd_ars_parallel=(
            float(p) if (p := getattr(fx_config, "usd_ars_parallel", None)) else None
        ),
        label=label,
        horizon_years=years,
        usd_inflation_pct=usd_inflation_pct,
        rate_source=str(getattr(fx_config, "rate_source", "explicit") or "explicit"),
    )
    out["available"] = True
    out["dual"] = dual
    out["line"] = format_ar_dual_line(dual)
    return out


# --------------------------------------------------------------------------- #
#  4 / 9 — Decision transparency + second-source signal                       #
# --------------------------------------------------------------------------- #

def decision_provenance_labels(*, has_ai: bool, has_calc: bool = True) -> List[dict]:
    """Badges for decision surfaces: calculado vs interpretación IA."""
    labels = []
    if has_calc:
        labels.append({
            "kind": "calc",
            "emoji": "📊",
            "title": "Calculado",
            "detail": "Sale de una fórmula o del motor numérico — no de la IA.",
        })
    if has_ai:
        labels.append({
            "kind": "ai",
            "emoji": "🤖",
            "title": "Interpretación IA",
            "detail": "Opinión del modelo sobre los números; no reemplaza el cálculo.",
        })
    return labels


# --------------------------------------------------------------------------- #
#  Why a decision says what it says (audit item 04)                            #
# --------------------------------------------------------------------------- #


def decision_explanation(decision: Any, *, max_headline: int = 90) -> dict:
    """The "why" behind an action, shaped for a table cell plus a detail panel.

    Audit item 04. The Screener showed a score and an action side by side and let
    them contradict each other in silence — ADBE at 95.7/100 marked HOLD, with no
    hint that the technical uptrend was unconfirmed. The engine writes the
    reconciling sentence on every decision and the row builder threw it away.

    ``headline`` is the short cell text: the engine's ``decisive_reason`` when the
    action was blocked or downgraded, otherwise the first rationale line, otherwise
    a phrase derived from the action itself — never empty, because an empty cell
    reads as "no reason" rather than "reason follows from the score".
    """
    action = str(getattr(decision, "action", "") or "").upper()
    decisive = str(getattr(decision, "decisive_reason", "") or "").strip()
    rationale = [str(r).strip() for r in (getattr(decision, "rationale", None) or []) if str(r).strip()]
    risks = [str(r).strip() for r in (getattr(decision, "risks", None) or []) if str(r).strip()]

    # When nothing overrode the score, the honest answer is that the action IS the
    # score band — not a nice fact from `rationale`. Quoting one produced cells
    # like "HOLD — ROE de 30,3 % y moat Wide sustentan rentabilidad", which is the
    # same contradiction this item exists to remove, just with more words.
    score = _safe_float(getattr(decision, "fundamental_score", None))
    band = f"Score {score:.0f}/100" if score else "El score"
    headline = decisive or {
        "STRONG BUY": f"{band} en zona de compra fuerte, sin objeciones técnicas",
        "BUY": f"{band} en zona de compra, el técnico no lo contradice",
        "HOLD": f"{band}: no alcanza para comprar ni cae a zona de venta",
        "REDUCE": f"{band} en deterioro — reducir exposición",
        "SELL": f"{band} en zona de venta",
        "AVOID": "Bloqueado por una regla de seguridad",
    }.get(action, f"{band} fundamental, sin ajustes")

    truncated = headline
    if len(truncated) > max_headline:
        truncated = truncated[: max_headline - 1].rstrip() + "…"

    return {
        "headline": truncated,
        "full_headline": headline,
        "is_downgrade": bool(decisive),
        "why": rationale,
        "risks": risks,
        "confidence": str(getattr(decision, "confidence", "") or ""),
        "blocked": bool(getattr(decision, "blocked", False)),
    }


# --------------------------------------------------------------------------- #
#  Screener column presentation (audit items 08 + 18)                          #
# --------------------------------------------------------------------------- #
#
# The Screener rendered 22 columns with no `column_config` at all, which caused
# two distinct defects:
#
#   (08) The column the table is *sorted by* was not in the table. `Adj. Score`
#        was hidden and `Score Bar` — an ASCII string like "████████░░  82/100" —
#        stood in for it. Clicking that header sorts the *text*, so the ordering
#        it produces is plausible and wrong. A number column plus Streamlit's own
#        ProgressColumn gives both the bar and a header that sorts numerically.
#
#   (18) Nothing was formatted: P/E and ROE printed raw floats, Price had no
#        currency, and no column carried a tooltip explaining what it measures.
#
# These specs are plain data so the labels, units and help text are testable
# without a Streamlit session; `dashboard.shared.screener_column_config` turns
# them into `st.column_config` objects.

#: kind → "number" | "progress" | "text". `format` follows printf conventions
#: as Streamlit expects; `%%` renders a literal percent sign.
#: What the F-Score is, on every surface that shows it (U5-1).
PIOTROSKI_HELP = (
    "F-Score de Piotroski (0–9): nueve chequeos **año contra año** — ¿es esta "
    "empresa más rentable, menos endeudada y más eficiente **que el año pasado**?\n\n"
    "Mide **cambio, no nivel**: una empresa mediocre que mejoró puntúa alto y una "
    "excelente que se mantuvo igual puntúa bajo. Piotroski lo diseñó para separar "
    "ganadores de perdedores entre acciones baratas en un horizonte de **1 año**, "
    "no para juzgar si algo se puede tener veinte."
)


SCREENER_COLUMN_SPECS: Dict[str, Dict[str, Any]] = {
    "⭐":           {"kind": "text",     "help": "Está en tu watchlist. Se edita desde la barra lateral."},
    "Ticker":      {"kind": "text",     "help": "Símbolo. Tocá la fila para analizarlo."},
    "Company":     {"kind": "text",     "help": "Nombre (truncado a 25 caracteres)."},
    "Sector":      {"kind": "text",     "help": "Sector según el proveedor de datos."},
    "Fuente":      {"kind": "text",     "help": "Curado = viene del universo · ⚠️ Propio = lo agregaste vos, tratalo como experimental."},
    "Signal":      {"kind": "text",     "help": "Decisión final: combina score, señal técnica, margen de seguridad y la política de calidad de datos."},
    "Motivo":      {"kind": "text",     "help": "Por qué la señal es esa. Cuando el motor bloquea o baja la acción (por técnico, margen de seguridad o calidad de datos), acá aparece la razón. Tocá la fila para el detalle completo."},
    "Conf.":       {"kind": "text",     "help": "Confianza de la decisión: HIGH / MEDIUM / LOW. La política de calidad de datos la limita cuando faltan métricas."},
    "Percentil":   {"kind": "number",   "format": "%.0f", "help": "Posición dentro de las acciones analizadas en ESTA corrida. Cambia si cambiás el universo."},
    "Adj. Score":  {"kind": "progress", "format": "%.1f", "min": 0, "max": 100,
                    "help": "Score ajustado (base + consistencia + Piotroski + moat + viento), topeado en 100."},
    "Score bruto": {"kind": "number",   "format": "%.1f", "help": "El mismo score sin el tope de 100 — separa a los que empatan arriba. Ordená por acá."},
    "Consist./15": {"kind": "progress", "format": "%.1f", "min": 0, "max": 15,
                    "help": "Estabilidad histórica de ROE y márgenes (0–15)."},
    "Piotroski/9": {"kind": "progress", "format": "%d",   "min": 0, "max": 9,
                    "help": PIOTROSKI_HELP},
    "Moat/20":     {"kind": "progress", "format": "%.1f", "min": 0, "max": 20,
                    "help": "Ventaja competitiva: cuantitativa (0–12) + IA (0–8)."},
    "Moat":        {"kind": "text",     "help": "Clasificación del foso: Wide / Narrow / Minimal / None."},
    "Viento":      {"kind": "text",     "help": "Cola de viento estructural sector-país (dato curado, no garantía)."},
    "Technical":   {"kind": "text",     "help": "Señal técnica de precio: BULLISH / NEUTRAL / BEARISH."},
    "P/E":         {"kind": "number",   "format": "%.1f",  "help": "Precio sobre ganancias (trailing). En REITs no es el múltiplo relevante — la depreciación no es salida de caja y el score usa P/FFO; mirá el detalle en Stock Analysis."},
    "ROE %":       {"kind": "number",   "format": "%.1f %%", "help": "Retorno sobre patrimonio."},
    "Rev CAGR %":  {"kind": "number",   "format": "%.1f %%", "help": "Crecimiento anual compuesto de ingresos sobre la ventana disponible."},
    "CAGR años":   {"kind": "number",   "format": "%d a",  "help": "Años que cubre el CAGR. yfinance entrega 4 estados anuales, así que suele ser 3."},
    "Div Yield %": {"kind": "number",   "format": "%.2f %%", "help": "Dividendo anual sobre precio."},
    "MoS %":       {"kind": "number",   "format": "%.1f %%", "help": "Margen de seguridad vs el valor intrínseco de Graham."},
    "Price":       {"kind": "number",   "format": "$%.2f", "help": "Último precio de mercado conocido."},
    "Datos":       {"kind": "text",     "help": "Completitud y frescura: 🟢 OK · 🟡 Parcial · 🔴 Pobre · ⏳ cache viejo."},
    "Clase":       {"kind": "text",     "help": "Acción, fondo/ETF o cripto. Solo las acciones se puntúan."},
}


def screener_column_spec(column: str) -> Optional[Dict[str, Any]]:
    """Spec for one displayed column, or ``None`` when it has no styling."""
    spec = SCREENER_COLUMN_SPECS.get(column)
    return dict(spec) if spec else None


def universe_quality_summary(
    per_ticker: Optional[Iterable[Optional[Mapping[str, Any]]]] = None,
    *,
    config=None,
) -> dict:
    """Roll per-ticker ``data_quality`` dicts up into one honest universe verdict.

    Audit item 03. The Screener used to hand ``second_source_quality_signal`` a
    synthesized level — ``"partial" if any_custom_ticker else "good"`` — so it
    printed "calidad good" while its own warning two lines below reported 7 poor
    and 63 partial tickers in the same run. This computes the level from the rows
    that are actually on screen, so the headline and the detail can no longer
    disagree.

    Thresholds live in ``DataQualityConfig`` (``universe_poor_pct`` /
    ``universe_partial_pct``), not here.

    Returns counts plus a ``level`` usable as the ``data_quality`` argument of
    ``second_source_quality_signal``.
    """
    if config is None:
        from config import DATA_QUALITY as config  # noqa: N811 — singleton default

    n_good = n_partial = n_poor = n_stale = n_unknown = 0
    # Iterate explicitly: `per_ticker or []` raises on a pandas Series, and the
    # Screener passes one straight off the dataframe.
    for dq in ([] if per_ticker is None else per_ticker):
        if not isinstance(dq, Mapping):
            n_unknown += 1
            continue
        level = str(dq.get("level") or "")
        if dq.get("stale"):
            n_stale += 1
        if level == "good":
            n_good += 1
        elif level == "partial":
            n_partial += 1
        elif level == "poor":
            n_poor += 1
        else:
            n_unknown += 1

    n_total = n_good + n_partial + n_poor + n_unknown
    if n_total == 0:
        return {
            "level": "unknown",
            "n_total": 0,
            "n_good": 0,
            "n_partial": 0,
            "n_poor": 0,
            "n_stale": 0,
            "n_unknown": 0,
            "degraded_pct": 0.0,
            "message": "Sin datos analizados todavía.",
        }

    poor_pct = n_poor / n_total * 100.0
    degraded_pct = (n_poor + n_partial + n_unknown) / n_total * 100.0

    if poor_pct >= float(config.universe_poor_pct):
        level = "poor"
    elif degraded_pct >= float(config.universe_partial_pct):
        level = "partial"
    else:
        level = "good"

    parts = [f"🟢 {n_good} completos"]
    if n_partial:
        parts.append(f"🟡 {n_partial} parciales")
    if n_poor:
        parts.append(f"🔴 {n_poor} pobres")
    if n_unknown:
        parts.append(f"⚪ {n_unknown} sin evaluar")
    if n_stale:
        parts.append(f"⏳ {n_stale} con cache viejo")

    message = (
        f"Calidad del universo: **{level}** — {' · '.join(parts)} "
        f"sobre {n_total} tickers ({degraded_pct:.0f}% con datos incompletos)."
    )

    return {
        "level": level,
        "n_total": n_total,
        "n_good": n_good,
        "n_partial": n_partial,
        "n_poor": n_poor,
        "n_stale": n_stale,
        "n_unknown": n_unknown,
        "degraded_pct": round(degraded_pct, 1),
        "message": message,
    }


def second_source_quality_signal(
    reconciliation: Optional[Mapping[str, Any]] = None,
    *,
    data_quality: Optional[Mapping[str, Any]] = None,
) -> dict:
    """Compact signal for Screener/Optimizer/Plan decision path.

    Extends existing multi-source reconciliation + data_quality badge — does not
    invent a second price stack.
    """
    dq_level = "unknown"
    stale = False
    if data_quality:
        dq_level = str(data_quality.get("level") or "unknown")
        stale = bool(data_quality.get("stale"))

    n_conflicts = 0
    agreement = None
    sources: List[str] = []
    if reconciliation:
        n_conflicts = int(reconciliation.get("n_conflicts") or 0)
        if reconciliation.get("agreement_pct") is not None:
            agreement = float(reconciliation["agreement_pct"])
        sources = list(reconciliation.get("sources_used") or [])

    if n_conflicts > 0:
        status = "conflict"
        message = (
            f"⚠️ {n_conflicts} campo(s) en conflicto entre fuentes"
            + (f" (acuerdo {agreement:.0f}%)" if agreement is not None else "")
            + ". Revisá antes de decidir."
        )
    elif sources and len(sources) >= 2:
        status = "cross_checked"
        message = (
            f"✅ Cruzado entre {len(sources)} fuentes"
            + (f" · acuerdo {agreement:.0f}%" if agreement is not None else "")
            + f" · calidad {dq_level}"
            + (" · datos viejos" if stale else "")
        )
    elif dq_level in ("good", "partial", "poor"):
        status = "single_source"
        message = (
            f"Fuente principal · calidad {dq_level}"
            + (" · datos viejos" if stale else "")
            + ". Activá reconciliación multi-fuente para más confianza."
        )
    else:
        status = "unknown"
        message = "Sin señal de calidad todavía — corré un análisis."

    return {
        "status": status,
        "message": message,
        "dq_level": dq_level,
        "stale": stale,
        "n_conflicts": n_conflicts,
        "agreement_pct": agreement,
        "sources": sources,
    }


# --------------------------------------------------------------------------- #
#  5 — Chat suggested questions + missing context                             #
# --------------------------------------------------------------------------- #

DEFAULT_CHAT_SUGGESTIONS = (
    "¿Conviene comprar AAPL?",
    "¿Cómo viene mi plan?",
    "¿Me alcanza si me jubilo en 15 años?",
    "¿Qué riesgos tiene mi cartera?",
    "¿Qué debo hacer este año en mi plan?",
)


def chat_suggested_questions(
    *,
    has_active_plan: bool = False,
    has_portfolio: bool = False,
) -> List[str]:
    qs = list(DEFAULT_CHAT_SUGGESTIONS)
    if has_active_plan:
        qs = [
            "¿Cómo viene mi plan vs el mercado?",
            "¿Cuál es la probabilidad de alcanzar mi meta?",
            "¿Qué pasa si aporte un 20% más?",
        ] + [q for q in qs if q not in (
            "¿Cómo viene mi plan?",
            "¿Me alcanza si me jubilo en 15 años?",
        )]
    if has_portfolio:
        qs.insert(0, "¿Estoy muy concentrado en una sola acción?")
    # unique preserve order
    seen = set()
    out = []
    for q in qs:
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out[:6]


def chat_missing_context_message(
    *,
    has_active_plan: bool,
    has_goal_target: bool,
    tool_name: str = "",
) -> Optional[str]:
    """Human copy when chat would otherwise report a misleading empty/zero result."""
    if tool_name in ("plan_status", "retirement_projection") and not has_active_plan:
        return (
            "Todavía no tenés un **plan activo**. "
            "Andá a 🗺️ **Mi Plan**, cargá un plan de ejemplo o guardá el tuyo, y volvé a preguntar. "
            "No hay un 0% real: falta el plan."
        )
    if tool_name == "retirement_projection" and has_active_plan and not has_goal_target:
        return (
            "Tu plan existe, pero **no hay una meta de capital definida**, "
            "así que no se puede calcular una probabilidad de alcanzarla. "
            "Definí la meta en 🎲 **Simulaciones → Mis Metas** o en el plan — "
            "no interpretes la ausencia como 0%."
        )
    if not has_active_plan and not tool_name:
        return (
            "Tip: sin plan activo las preguntas de proyección y estado del plan "
            "no tienen base. Usá 🎁 un plan de ejemplo en Mi Plan o Inicio."
        )
    return None


# --------------------------------------------------------------------------- #
#  Empty-state helpers (backlog 2)                                            #
# --------------------------------------------------------------------------- #

def guided_empty_state(
    page: str,
    *,
    has_last_result: bool = False,
    last_result_caption: str = "",
) -> dict:
    """Copy + suggested demo for pages that used to open blank."""
    catalog = {
        "screener": {
            "title": "Aún no corriste el screener",
            "body": "Analizá el universo para ver ranking, señales y calidad de datos.",
            "demo_hint": "Tocá Actualizar análisis (o dejá que cargue con el universo actual).",
            "demo_ticker": "AAPL",
        },
        "simulaciones": {
            "title": "Todavía no hay una proyección en esta sesión",
            "body": "Necesitás una cartera del Optimizer (o un plan cargado) para simular.",
            "demo_hint": "Andá a Optimizer, o cargá un plan de ejemplo en Mi Plan y volvé.",
            "demo_ticker": "",
        },
        "comite": {
            "title": "El comité espera un ticker",
            "body": "Convocá el panel multi-agente con disenso explícito (Abogado del Diablo incluido).",
            "demo_hint": "Probá con MSFT o AAPL para ver un dictamen de ejemplo.",
            "demo_ticker": "MSFT",
        },
        "chat": {
            "title": "Empezá con una pregunta",
            "body": "El asesor elige la herramienta y responde con números reales (sin inventar).",
            "demo_hint": "Usá las preguntas sugeridas de abajo.",
            "demo_ticker": "",
        },
    }
    base = dict(catalog.get(page, {
        "title": "Nada que mostrar todavía",
        "body": "Completá el paso anterior del camino de retiro.",
        "demo_hint": "",
        "demo_ticker": "",
    }))
    base["has_last_result"] = has_last_result
    base["last_result_caption"] = last_result_caption
    return base


# --------------------------------------------------------------------------- #
#  PDF partner blurb (backlog 11) — pure text blocks                          #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
#  Graham value — the rate behind it is named (U3-4)                          #
# --------------------------------------------------------------------------- #

def graham_value_help(thresholds: Any = None) -> str:
    """Explain the Graham value, including the rate nobody was quoting.

    ``V = EPS × (8.5 + 2g) × 4.4 / Y``. The ``4.4`` is the AAA corporate yield of
    Graham's period and ``Y`` the yield today, so the ratio rebases his multiple
    onto the current cost of money. But ``Y`` here is a **frozen proxy** in
    config, not a live rate: printing "Graham Intrinsic Value" with no mention of
    it invites the reader to treat a number that moves with interest rates as if
    it did not. Fetching AAA live is out of scope (X-04); saying which number is
    being used is not.
    """
    from config import THRESHOLDS as _TH

    cfg = thresholds if thresholds is not None else _TH
    y = float(getattr(cfg, "graham_aaa_yield_pct", 4.5) or 4.5)
    g_cap = float(getattr(cfg, "graham_max_growth_pct", 15.0) or 15.0)
    return (
        "Valor intrínseco por la fórmula revisada de Graham (1974): "
        "**V = EPS × (8,5 + 2g) × 4,4 / Y**.\n\n"
        f"· **Y = {y:g} %** es un **proxy fijo** del rendimiento de bonos corporativos "
        "AAA, tomado de la configuración — no una tasa en vivo. Si las tasas de hoy "
        "difieren, este valor se mueve en sentido inverso y esta pantalla no se entera.\n\n"
        f"· **g** es el crecimiento por acción, topeado en {g_cap:g} % para la fórmula.\n\n"
        "· Con **g = 0** la fórmula sigue definida (multiplicador 8,5): una empresa "
        "estable y rentable que no crece **sí** tiene valor. Con g < 0 no se publica "
        "ninguno."
    )


# --------------------------------------------------------------------------- #
#  Why a saved plan is stale (U6-2) — one entry per engine tier               #
# --------------------------------------------------------------------------- #

ENGINE_CHANGELOG: tuple[tuple[str, str], ...] = (
    (
        "2026.08-tier0",
        "Los retiros descontaban un monto fijo en vez de capital, así que el dinero "
        "retirado seguía creciendo: el capital final y la herencia salían sobrestimados.",
    ),
    (
        "2026.08-tier1",
        "La caída máxima y el riesgo de secuencia se medían sobre el pozo después de "
        "los retiros, así que el gasto planificado se contaba como un derrumbe de mercado.",
    ),
    (
        "2026.08-tier2",
        "Los aportes entraban una vez por año en vez de una vez por mes, y un plan que "
        "arrancaba sin capital inicial descartaba todo el ahorro: proyectaba cero y 0 % "
        "de probabilidad de éxito.",
    ),
    (
        "2026.08-tier3",
        "El optimizer pagaba el foso dos veces al estimar el atractivo de cada activo, "
        "así que las empresas con foso ancho quedaban sobreponderadas respecto de lo que "
        "el propio motor dice que valen. La cartera sugerida puede cambiar.",
    ),
    (
        "2026.08-tier4",
        "La simulación nunca sorteaba la observación más reciente del historial y "
        "sub-muestreaba las anteriores, así que se apoyaba de más en la parte vieja de "
        "la ventana. Volvé a simular para usar el historial completo.",
    ),
    (
        "2026.08-tier5",
        "Dos números que el motor usa estaban escritos dos veces con valores distintos. "
        "El umbral de rentabilidad que exige el foso usaba una tasa libre de riesgo "
        "medio punto más baja que el resto del motor, y un dividendo de entre 15 % y "
        "30 % se puntuaba como bueno pero se descartaba al estimar el atractivo del "
        "activo. La cartera sugerida puede cambiar para los papeles de dividendo alto.",
    ),
    (
        "2026.08-tier6",
        "El dividendo de 8 acciones no era el suyo: en los ADRs latinoamericanos "
        "el dividendo se declara en moneda local y el precio cotiza en dólares, y "
        "el motor los dividía igual — Telecom Argentina figuraba con 94,7 % de "
        "rendimiento contra el 0,31 % real. Además, no haber podido medir un "
        "rendimiento se contaba como que la empresa no paga dividendos, y a Itaú, "
        "Telecom Argentina y Vale se les decía que no pagaban. La cartera sugerida "
        "puede cambiar para esos papeles.",
    ),
    (
        "2026.08-tier7",
        "Los retiros salían del pozo una vez al año, en diciembre, y el primer año "
        "de la jubilación transcurría entero sin que saliera un peso. Ahora el "
        "gasto se reparte en doce, que es como se gasta de verdad — la decisión de "
        "cuánto gastar sigue siendo anual. Si tu plan retira un monto fijo, el "
        "capital proyectado baja y la fecha de agotamiento se adelanta; si retira "
        "un porcentaje, el presupuesto pasa a fijarse al empezar cada año.",
    ),
    (
        "2026.08-tier8",
        "Si pedías que el dinero durara más años que el horizonte de proyección, "
        "esos años no se simulaban: la probabilidad de que el ingreso durara era "
        "la misma para 30, 45 o 60 años. Ahora se simulan de verdad. Con la "
        "configuración por defecto la probabilidad baja unos 6 puntos, y la fecha "
        "estimada de agotamiento puede caer después del horizonte. El capital "
        "proyectado no cambia.",
    ),
)


def engine_staleness_reasons(engine_version: str) -> List[str]:
    """Everything that changed AFTER the stamp a saved plan carries.

    A tier1 plan is not stale for the tier0 reason — its withdrawals were already
    correct. Telling it otherwise is a false statement shown to the user, which
    is the class of defect this project's audits exist to remove, so the copy is
    derived from the plan's own stamp instead of being written once for whichever
    tier happened to be newest when the warning was drafted.

    An unknown or empty stamp predates the changelog, so every reason applies.
    """
    versions = [version for version, _ in ENGINE_CHANGELOG]
    start = versions.index(engine_version) + 1 if engine_version in versions else 0
    return [reason for _, reason in ENGINE_CHANGELOG[start:]]


# --------------------------------------------------------------------------- #
#  Savings, in one unit, from one place (backlog U4-1)                        #
# --------------------------------------------------------------------------- #

MONTHS_PER_YEAR = 12


def contribution_inputs(
    session: Optional[Mapping[str, Any]] = None,
    *,
    prefs: Any = None,
    personal: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Resolve the user's savings to one number, in one unit, with its source.

    Returns ``{"monthly": float, "annual": float, "source": str}``.

    The profile asks for a monthly figure, the goal form asked for a yearly one,
    the PDF block wanted either, and each surface did its own ``* 12`` — so the
    same saver could be quoted different money depending on the screen they were
    looking at. The conversion lives here and nowhere else, which is what makes
    "same input, same money" checkable instead of merely intended.

    ``source`` names where the figure came from, so a surface can say whether the
    number is one the user typed here or one carried over from their profile.
    Empty when there is no savings figure at all — which is a real answer, not a
    zero to be rendered as if the user had said zero.
    """
    session = dict(session or {})
    personal = dict(personal or {})

    def _positive(value: Any) -> Optional[float]:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None

    # U4-5: un cero **tipeado** es una respuesta, no la falta de una.
    #
    # `_positive` descarta el 0, que es lo correcto para un campo de perfil sin
    # completar. Pero desde que la pestaña principal tiene su propia palanca —y
    # su rótulo dice «0 = no aporto»— un cero escrito ahí tiene que ganarle al
    # perfil: si no, el usuario pide no aportar y el motor le deposita 6.000 al
    # año igual. Es el reverso de U3-1: allá «no sé» se leía como «no»; acá «no»
    # se leía como «no sé».
    #
    # La distinción vive en la **presencia de la clave**, no en su valor, y sólo
    # aplica a los diccionarios explícitos (session/personal). Un atributo de
    # `prefs` siempre existe, así que su 0 sigue significando «sin completar».
    for fuente, datos in (("session", session), ("personal", personal)):
        for clave, divisor in (("monthly_savings", 1), ("annual_savings", MONTHS_PER_YEAR)):
            if clave in datos:
                try:
                    numero = float(datos[clave])
                except (TypeError, ValueError):
                    continue
                if numero == 0:
                    return {"monthly": 0.0, "annual": 0.0, "source": fuente}
                break

    candidates = (
        (_positive(session.get("monthly_savings")), 1, "session"),
        (_positive(session.get("annual_savings")), MONTHS_PER_YEAR, "session"),
        (_positive(personal.get("monthly_savings")), 1, "personal"),
        (_positive(personal.get("annual_savings")), MONTHS_PER_YEAR, "personal"),
        (_positive(getattr(prefs, "monthly_savings", None)), 1, "perfil"),
        (_positive(getattr(prefs, "annual_savings", None)), MONTHS_PER_YEAR, "perfil"),
    )

    for value, divisor, source in candidates:
        if value is not None:
            monthly = value / divisor
            return {
                "monthly": monthly,
                "annual": monthly * MONTHS_PER_YEAR,
                "source": source,
            }

    return {"monthly": 0.0, "annual": 0.0, "source": ""}


# --------------------------------------------------------------------------- #
#  PDF mc_params assembly (backlog 11) — real call-path helper                #
# --------------------------------------------------------------------------- #

def enrich_pdf_mc_params(
    mc_params: Optional[Mapping[str, Any]] = None,
    *,
    prefs: Any = None,
    personal: Optional[Mapping[str, Any]] = None,
) -> dict:
    """Fill savings / capital / horizon on PDF mc_params from prefs or personal.

    Call sites historically only passed simulation widget keys (often empty).
    Without this, the shareable "Qué hacer este año" block always said
    "Definí cuánto podés aportar…" even when the user had monthly_savings set.
    """
    out: Dict[str, Any] = dict(mc_params or {})
    personal = dict(personal or {})

    def _pos(key: str) -> Optional[float]:
        v = out.get(key)
        if v is None:
            return None
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return f if f > 0 else None

    # --- monthly / annual savings ---
    monthly = _pos("monthly_savings") or _pos("monthly_contribution") or _pos("monthly_contrib")
    if monthly is None and _pos("annual_contribution") is not None:
        monthly = float(out["annual_contribution"]) / 12.0
    if monthly is None and _pos("annual_savings") is not None:
        monthly = float(out["annual_savings"]) / 12.0

    if monthly is None and personal:
        for k in ("monthly_savings", "monthly_contribution"):
            if personal.get(k) is not None:
                try:
                    m = float(personal[k])
                    if m > 0:
                        monthly = m
                        break
                except (TypeError, ValueError):
                    pass
        if monthly is None and personal.get("annual_savings") is not None:
            try:
                a = float(personal["annual_savings"])
                if a > 0:
                    monthly = a / 12.0
            except (TypeError, ValueError):
                pass

    if monthly is None and prefs is not None:
        try:
            m = float(getattr(prefs, "monthly_savings", 0) or 0)
            if m > 0:
                monthly = m
        except (TypeError, ValueError):
            pass
        if monthly is None:
            try:
                a = float(getattr(prefs, "annual_savings", 0) or 0)
                if a > 0:
                    monthly = a / 12.0
            except (TypeError, ValueError):
                pass

    if monthly is not None and monthly > 0:
        out["monthly_savings"] = float(monthly)
        if _pos("annual_savings") is None and _pos("annual_contribution") is None:
            out["annual_savings"] = float(monthly) * 12.0

    # --- capital ---
    if _pos("initial_value") is None:
        for src in (
            personal.get("current_capital"),
            getattr(prefs, "current_capital", None) if prefs is not None else None,
        ):
            if src is None:
                continue
            try:
                c = float(src)
                if c > 0:
                    out["initial_value"] = c
                    break
            except (TypeError, ValueError):
                pass

    # --- horizon ---
    if _pos("horizon_years") is None:
        for src in (
            personal.get("primary_horizon_years"),
            personal.get("horizon_years"),
            getattr(prefs, "primary_horizon_years", None) if prefs is not None else None,
        ):
            if src is None:
                continue
            try:
                h = float(src)
                if h > 0:
                    out["horizon_years"] = h
                    break
            except (TypeError, ValueError):
                pass

    return out


def assemble_plan_pdf_mc_params(
    *,
    session: Optional[Mapping[str, Any]] = None,
    prefs: Any = None,
    profile_name: str = "",
    personal: Optional[Mapping[str, Any]] = None,
) -> dict:
    """Real Plan-page PDF param assembly (mirrors dashboard/pages/12_Plan path).

    ``session`` is a mapping of Streamlit session_state-like keys from Simulaciones.
    ``prefs`` is UserPreferences (or duck-type). Pure — no Streamlit import.
    """
    session = dict(session or {})
    base = {
        "horizon_years": session.get("horizon_years"),
        "initial_value": session.get("initial_value"),
        "inflation_rate": session.get("inflation_rate"),
        "target_value": session.get("target_value"),
        "annual_withdrawal": session.get("annual_withdrawal"),
        "profile_name": profile_name or session.get("profile_name") or "",
        "monthly_savings": session.get("monthly_savings"),
        "annual_contribution": (
            session.get("annual_contribution")
            or session.get("annual_savings")
            or session.get("new_goal_contribution")
        ),
        "annual_savings": session.get("annual_savings"),
    }
    return enrich_pdf_mc_params(base, prefs=prefs, personal=personal)


def plan_load_session_updates(
    plan_snapshot: Any,
    *,
    horizon_years: int,
    profile_key: str = "",
) -> Dict[str, Any]:
    """session_state keys to seed when loading a saved plan ("what-if" hand-off).

    Mirrors ``dashboard/pages/12_Plan.py::_render_load_plan``. Returns **only**
    the keys that carry a real value from the plan: a key the plan cannot answer
    is left out so the user's current widget value survives.

    That omission rule is the whole point. The page used to set
    ``target_value`` unconditionally, so loading a plan saved without a Monte
    Carlo run (``mc_summary is None`` — a supported path) reset the retirement
    goal to $0, while ``inflation_rate`` right next to it was correctly guarded.
    Concentrating the decision here removes the "one guard yes, the neighbour
    no" class of bug.

    ``horizon_years`` comes in already snapped to the Simulaciones selectbox
    options (``dashboard.shared._snap_sim_horizon``, which imports Streamlit).
    """
    mc = getattr(plan_snapshot, "mc_summary", None) or {}
    personal = getattr(plan_snapshot, "personal", None) or {}

    capital = int(
        _safe_float(personal.get("current_capital"), 0.0)
        or _safe_float(mc.get("initial_value"), 0.0)
        or 100_000
    )

    updates: Dict[str, Any] = {
        "optimizer_total_capital": capital,
        "horizon_years": int(horizon_years),
        "initial_value": min(max(capital, 1_000), 10_000_000),
    }

    if profile_key:
        updates["_preset_profile_key"] = profile_key

    target = _safe_float(mc.get("target_value"), 0.0) or 0.0
    if target > 0:
        updates["target_value"] = int(target)

    inflation = mc.get("inflation_rate")
    if inflation is not None:
        _inf = _safe_float(inflation)
        if _inf is not None:
            updates["inflation_rate"] = _inf

    goals = getattr(plan_snapshot, "goals", None) or []
    if goals:
        updates["goals_list"] = list(goals)

    return updates


def shareable_report_narrative_blocks(
    *,
    plan_name: str,
    prob_target_pct: Optional[float],
    median_terminal: Optional[float],
    horizon_years: Optional[float],
    profile: str = "",
    annual_actions: Optional[Sequence[Mapping[str, Any]]] = None,
) -> List[dict]:
    """Narrative sections oriented to partner/advisor (not a technical dump)."""
    blocks = [
        {
            "heading": "Para quién es este documento",
            "body": (
                f"Resumen del plan de retiro «{plan_name or 'sin nombre'}» "
                "pensado para compartir con tu pareja o un asesor. "
                "Es educativo: no constituye asesoramiento financiero regulado."
            ),
        },
        {
            "heading": "En una mirada",
            "body": (
                f"Perfil: {profile or '—'}. "
                + (f"Horizonte ~{horizon_years:.0f} años. " if horizon_years else "")
                + (f"Probabilidad de meta ~{prob_target_pct:.0f}%. " if prob_target_pct is not None else "Sin probabilidad de meta cargada. ")
                + (f"Resultado mediano proyectado ~${median_terminal:,.0f}." if median_terminal else "")
            ),
        },
        {
            "heading": "Qué hacer este año",
            "body": (
                " · ".join(
                    f"{a.get('title', '')}" for a in (annual_actions or [])[:5]
                )
                or "Definí aportes, revisá alineación y respaldá el plan."
            ),
        },
        {
            "heading": "Cómo leer los números",
            "body": (
                "Las proyecciones usan un sesgo conservador a propósito (más volatilidad, "
                "menor retorno histórico). Cuando veas «realista vs conservador», planificá "
                "con el conservador. Los sellos 📊 son cálculos; 🤖 es interpretación de IA."
            ),
        },
    ]
    return blocks
