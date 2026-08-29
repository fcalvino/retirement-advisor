"""
Personal-book sizing engine (Fase I) — *rule-based, puro y transparente*.

Este módulo decide, **por posición**, una acción de sizing (acumular / holdear /
trim / vender) para un **libro personal individual** y explica el porqué con total
transparencia. NO es para la cuenta de retiro: a diferencia del optimizer
conservador (``config.STRATEGY`` max 8%, ``min_positions`` 10, SLSQP), aquí la
**concentración es una ventaja competitiva estructural** del individuo:

  - Libertad de concentrar 20-30%+ en una idea de altísima convicción.
  - Sin mandatos de diversificación regulatorios ni de clientes (LPs).
  - Sin límites por emisor (~5-10% típicos en fondos).
  - Sin riesgo de redenciones que fuerzan ventas en iliquidez.
  - Sin comités de riesgo ni "career risk" por underperformance relativa.

El motor combina **cuatro ejes** (ponderación documentada en ``PERSONAL_BOOK``):
  1. Calidad estructural (adjusted_score, moat, tailwind, data_quality)  — 45%
  2. Valoración / asimetría de entrada (margin of safety, technical)      — 20%
  3. Convicción personal declarada por el usuario (HIGH/MEDIUM/LOW)       — 20%
  4. Contexto de sizing actual del libro + riesgo personal               — 15%

Diseño (idéntico al resto del proyecto):
  - Config first-class: cero números hardcodeados (todo vive en ``PERSONAL_BOOK``).
  - Path determinístico: siempre produce un resultado válido y explicable.
  - **Puro e inyectable**: ``enrich_fn`` permite tests offline (sin red ni yfinance)
    y reutilización en scripts/notebooks. Sin imports de Streamlit.

Uso standalone::

    from portfolio.personal_sizer import analyze_personal_book
    from portfolio.tracker import Portfolio
    p = Portfolio()
    analysis = analyze_personal_book(
        positions=p.get_current_values(),
        convictions={"GOOGL": "HIGH", "INTU": "MEDIUM"},
    )
    print(analysis.overall_summary)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from config import PERSONAL_BOOK, PersonalBookConfig

# --------------------------------------------------------------------------- #
#  Constantes de dominio                                                       #
# --------------------------------------------------------------------------- #

# Acciones soportadas (strings estables; sirven de claves de UI/badges/export).
ACUMULAR_AGRESIVO = "ACUMULAR_AGRESIVO"
ACUMULAR_MODERADO = "ACUMULAR_MODERADO"
AGREGAR_EN_DEBILIDAD = "AGREGAR_EN_DEBILIDAD"
HOLDEAR = "HOLDEAR"
TRIM_PARCIAL = "TRIM_PARCIAL"
VENDER_PARTE = "VENDER_PARTE"
VENDER_TODO = "VENDER_TODO"
REVISAR_URGENTE = "REVISAR_URGENTE"

# Niveles de convicción válidos (declarados por el usuario).
CONVICTION_LEVELS = ("HIGH", "MEDIUM", "LOW")

# Frase canónica de la ventaja personal (se reutiliza para garantizar que las
# tesis de concentración siempre comuniquen el edge "a diferencia de un fondo").
_FUND_CONTRAST = (
    "A diferencia de un fondo (con mandatos de diversificación, límites por emisor "
    "~5-10% y riesgo de redenciones), como libro personal podés"
)


# --------------------------------------------------------------------------- #
#  Estructuras de datos                                                        #
# --------------------------------------------------------------------------- #


@dataclass
class AnalysisView:
    """
    Vista normalizada del análisis fundamental/técnico de un ticker, desacoplada
    del pipeline real para poder inyectar mocks en tests.

    ``enrich_fn`` debe devolver un dict con estas claves (todas opcionales salvo
    que se indique lo contrario); los faltantes degradan a defaults conservadores.
    """
    symbol: str
    adjusted_score: float = 0.0
    moat_classification: str = "None"          # Wide | Narrow | Minimal | None
    tailwind_classification: str = "Neutral"   # Strong | Moderate | Neutral | Headwind
    has_margin_of_safety: bool = False
    margin_of_safety_pct: Optional[float] = None
    data_quality_level: str = "good"           # good | partial | poor
    rsi_weekly: Optional[float] = None
    above_sma200: Optional[bool] = True   # None = ventana más larga que la serie (U3-1)
    sma200_slope_pct: float = 0.0
    price_vs_52w_high_pct: float = 0.0          # ≤ 0 (qué tan lejos del máximo)
    retirement_action: str = "HOLD"            # STRONG BUY | BUY | HOLD | REDUCE | SELL

    @classmethod
    def from_enrich(cls, symbol: str, raw: Dict[str, Any]) -> "AnalysisView":
        """Construye una vista tolerante a campos faltantes."""
        return cls(
            symbol=symbol,
            adjusted_score=float(raw.get("adjusted_score", raw.get("score", 0.0)) or 0.0),
            moat_classification=str(raw.get("moat_classification", "None") or "None"),
            tailwind_classification=str(raw.get("tailwind_classification", "Neutral") or "Neutral"),
            has_margin_of_safety=bool(raw.get("has_margin_of_safety", False)),
            margin_of_safety_pct=raw.get("margin_of_safety_pct"),
            data_quality_level=str(raw.get("data_quality_level", "good") or "good"),
            rsi_weekly=raw.get("rsi_weekly"),
            # Sin coerción: ``bool(None)`` es False, así que envolver esto daría
            # vuelta el default optimista de arriba justo cuando no se sabe (U3-1).
            above_sma200=raw.get("above_sma200", True),
            sma200_slope_pct=float(raw.get("sma200_slope_pct", 0.0) or 0.0),
            price_vs_52w_high_pct=float(raw.get("price_vs_52w_high_pct", 0.0) or 0.0),
            retirement_action=str(raw.get("retirement_action", "HOLD") or "HOLD"),
        )


@dataclass
class SizingRecommendation:
    """Recomendación de sizing para una posición del libro."""
    symbol: str
    action: str
    current_weight_pct: float
    suggested_target_weight_pct: Optional[float] = None
    suggested_action_detail: str = ""
    conviction_used: str = "MEDIUM"
    justification_bullets: List[str] = field(default_factory=list)
    concentration_thesis: str = ""
    risk_notes: List[str] = field(default_factory=list)
    base_score_drivers: Dict[str, Any] = field(default_factory=dict)
    data_quality_level: str = "good"

    @property
    def action_label(self) -> str:
        return _ACTION_LABELS.get(self.action, self.action)

    @property
    def action_emoji(self) -> str:
        return _ACTION_EMOJI.get(self.action, "⚪")

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["action_label"] = self.action_label
        d["action_emoji"] = self.action_emoji
        return d


@dataclass
class PersonalBookAnalysis:
    """Resultado a nivel libro (concentración + recomendaciones + narrativa)."""
    as_of: str
    total_value: float
    num_positions: int
    max_weight_pct: float
    top3_weight_pct: float
    effective_positions: float                 # 1 / HHI (números efectivos)
    concentration_risk_note: str
    recommendations: List[SizingRecommendation]
    overall_summary: str
    suggested_book_structure: str
    concentration_justification_overall: str
    disclaimer: str = (
        "Herramienta de análisis personal, NO consejo de inversión. Las "
        "recomendaciones incorporan tu convicción declarada (subjetiva) y vos sos "
        "el único responsable de tus decisiones."
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "as_of": self.as_of,
            "total_value": self.total_value,
            "num_positions": self.num_positions,
            "max_weight_pct": self.max_weight_pct,
            "top3_weight_pct": self.top3_weight_pct,
            "effective_positions": self.effective_positions,
            "concentration_risk_note": self.concentration_risk_note,
            "overall_summary": self.overall_summary,
            "suggested_book_structure": self.suggested_book_structure,
            "concentration_justification_overall": self.concentration_justification_overall,
            "disclaimer": self.disclaimer,
            "recommendations": [r.to_dict() for r in self.recommendations],
        }


@dataclass
class BookContext:
    """Contexto agregado del libro, compartido por todas las recomendaciones."""
    total_value: float
    num_positions: int
    max_weight_pct: float
    top3_weight_pct: float
    effective_positions: float
    num_high_conviction: int


_ACTION_LABELS = {
    ACUMULAR_AGRESIVO: "Acumular (agresivo)",
    ACUMULAR_MODERADO: "Acumular (moderado)",
    AGREGAR_EN_DEBILIDAD: "Agregar en debilidad",
    HOLDEAR: "Holdear",
    TRIM_PARCIAL: "Trim parcial",
    VENDER_PARTE: "Vender parte",
    VENDER_TODO: "Vender todo",
    REVISAR_URGENTE: "Revisar urgente",
}

_ACTION_EMOJI = {
    ACUMULAR_AGRESIVO: "🟢",
    ACUMULAR_MODERADO: "🟩",
    AGREGAR_EN_DEBILIDAD: "🔵",
    HOLDEAR: "🟡",
    TRIM_PARCIAL: "🟠",
    VENDER_PARTE: "🟠",
    VENDER_TODO: "🔴",
    REVISAR_URGENTE: "🚨",
}


# --------------------------------------------------------------------------- #
#  Enrichment por defecto (usa el pipeline real; lazy import)                  #
# --------------------------------------------------------------------------- #


def _default_enrich(symbol: str, ai_config: Any = None) -> Dict[str, Any]:
    """
    Enrichment real vía ``analysis.strategy.full_analysis``. Import perezoso para
    que el módulo se pueda importar/test-ear sin red ni dependencias pesadas.
    """
    from analysis.strategy import full_analysis

    fund, tech, decision = full_analysis(symbol, ai_config=ai_config)
    dq = getattr(fund, "data_quality", None) or {}
    return {
        "adjusted_score": getattr(fund, "adjusted_score", 0.0) or getattr(fund, "total_score", 0.0),
        "moat_classification": getattr(fund, "moat_classification", "None"),
        "tailwind_classification": getattr(fund, "tailwind_classification", "Neutral"),
        "has_margin_of_safety": bool(getattr(decision, "has_margin_of_safety", False)),
        "margin_of_safety_pct": getattr(fund, "margin_of_safety_pct", None),
        "data_quality_level": (dq.get("level") if isinstance(dq, dict) else "good") or "good",
        "rsi_weekly": getattr(tech, "rsi_weekly", None),
        "above_sma200": getattr(tech, "above_sma200", True),   # sin bool(): ver U3-1
        "sma200_slope_pct": getattr(tech, "sma200_slope_pct", 0.0),
        "price_vs_52w_high_pct": getattr(tech, "price_vs_52w_high_pct", 0.0),
        "retirement_action": getattr(decision, "action", "HOLD"),
    }


# --------------------------------------------------------------------------- #
#  Helpers de concentración (puros)                                            #
# --------------------------------------------------------------------------- #


def _effective_positions(weights_pct: List[float]) -> float:
    """Número efectivo de posiciones = 1 / HHI (HHI sobre fracciones)."""
    fracs = [w / 100.0 for w in weights_pct if w > 0]
    hhi = sum(f * f for f in fracs)
    return round(1.0 / hhi, 2) if hhi > 0 else 0.0


def _estimate_drawdown_impact(weight_pct: float, shock_pct: float) -> float:
    """Impacto en el libro completo si la posición cae ``shock_pct``%."""
    return round(weight_pct * shock_pct / 100.0, 1)


def _normalize_conviction(raw: Optional[str], cfg: PersonalBookConfig) -> str:
    if raw is None:
        return cfg.default_conviction
    up = str(raw).strip().upper()
    return up if up in CONVICTION_LEVELS else cfg.default_conviction


def _is_core_concentration_candidate(view: AnalysisView, conviction: str, cfg: PersonalBookConfig) -> bool:
    """
    Un nombre es elegible para concentración "core" sólo si combina calidad
    estructural alta + moat real + viento de cola (o entrada con asimetría) +
    convicción HIGH del usuario. Esto separa "edge documentado" de "apuesta".
    """
    quality_ok = view.adjusted_score >= cfg.min_score_for_core_concentration
    moat_ok = view.moat_classification in ("Wide", "Narrow")
    tail_ok = view.tailwind_classification in ("Strong", "Moderate")
    structural_support = tail_ok or view.has_margin_of_safety
    dq_ok = view.data_quality_level != "poor"
    conviction_ok = conviction == "HIGH"
    return quality_ok and moat_ok and structural_support and dq_ok and conviction_ok


def _is_technical_weakness(view: AnalysisView) -> bool:
    """Pullback / debilidad técnica → ventana para 'agregar en debilidad'."""
    rsi_low = view.rsi_weekly is not None and view.rsi_weekly < 40
    below_trend = view.above_sma200 is False   # no saber no es estar debajo (U3-1)
    off_highs = view.price_vs_52w_high_pct <= -10.0
    return rsi_low or below_trend or off_highs


# --------------------------------------------------------------------------- #
#  Motor de decisión (núcleo)                                                  #
# --------------------------------------------------------------------------- #


def _decide_sizing(
    pos: Dict[str, Any],
    view: AnalysisView,
    conviction: str,
    ctx: BookContext,
    cfg: PersonalBookConfig,
) -> SizingRecommendation:
    """
    Decide la acción de sizing para UNA posición y construye su justificación
    completa. Determinístico y explicable: cada rama deja rastro de los drivers.
    """
    weight = float(pos.get("weight_pct", 0.0) or 0.0)
    score = view.adjusted_score
    moat = view.moat_classification
    tail = view.tailwind_classification
    drivers: Dict[str, Any] = {
        "adjusted_score": round(score, 1),
        "moat": moat,
        "tailwind": tail,
        "has_margin_of_safety": view.has_margin_of_safety,
        "conviction": conviction,
        "weight_pct": round(weight, 1),
        "data_quality": view.data_quality_level,
    }
    bullets: List[str] = []
    risks: List[str] = []
    target: Optional[float] = None
    detail = ""

    is_core = _is_core_concentration_candidate(view, conviction, cfg)
    tech_weak = _is_technical_weakness(view)

    # --- Gate duro: tesis rota o calidad colapsada --------------------------- #
    if score < cfg.sell_all_score or moat == "None":
        if weight >= cfg.high_concentration_risk_note_pct or score < cfg.sell_all_score * 0.6:
            action = VENDER_TODO
            detail = "Salir de la posición: mejor uso del capital en otra idea."
        else:
            action = VENDER_PARTE
            detail = "Reducir materialmente (50%+ de las shares); tesis deteriorada."
        bullets.append(
            f"Calidad estructural colapsada: score {score:.0f} < {cfg.sell_all_score:.0f} "
            f"o moat '{moat}'. La concentración aquí sería riesgo sin edge."
        )

    # --- Sobre-concentración extrema (hard ceiling personal) ----------------- #
    elif weight >= cfg.max_practical_concentration_single_name:
        # Por encima del techo práctico siempre se reduce; con calidad core el target
        # baja al techo de alta convicción, sin calidad el recorte es más profundo.
        if score >= cfg.min_score_for_core_concentration:
            action = TRIM_PARCIAL
            target = round(cfg.core_high_conviction_max_pct, 1)
        else:
            action = VENDER_PARTE
            target = round(cfg.trim_concentration_threshold_pct, 1)
        detail = (
            f"Bajar el tamaño hacia ~{target:.0f}% (techo práctico personal "
            f"{cfg.max_practical_concentration_single_name:.0f}%). "
            "Un solo nombre a este peso es extremo incluso para un libro personal."
        )
        bullets.append(
            f"Peso {weight:.0f}% ≥ techo práctico {cfg.max_practical_concentration_single_name:.0f}%: "
            "riesgo de ruina asimétrico, sin importar la convicción declarada."
        )

    # --- Core elegible: acumular / holdear / trim por tamaño ----------------- #
    elif is_core:
        if weight < cfg.aggressive_accumulate_weight_pct:
            action = ACUMULAR_AGRESIVO
            target = min(cfg.core_high_conviction_max_pct, 22 + (score - 75) * 0.4)
            target = round(max(target, cfg.aggressive_accumulate_weight_pct + 4), 1)
            detail = (
                f"Construir hacia ~{target:.0f}% (idealmente sumando en cualquier debilidad). "
                "Es una idea core de alta convicción con peso aún bajo."
            )
            bullets.append(
                f"Core elegible: score {score:.0f} ≥ {cfg.min_score_for_core_concentration:.0f}, "
                f"moat {moat}, convicción HIGH y peso {weight:.0f}% < "
                f"{cfg.aggressive_accumulate_weight_pct:.0f}% → ACUMULAR AGRESIVO."
            )
        elif weight < cfg.trim_concentration_threshold_pct:
            if tech_weak:
                action = AGREGAR_EN_DEBILIDAD
                target = round(min(cfg.core_high_conviction_max_pct, weight + 5), 1)
                detail = "Aprovechar el pullback para sumar algunos puntos de peso (entrada con mejor asimetría)."
            else:
                action = HOLDEAR
                detail = "Tamaño adecuado para la convicción; mantener y dejar que componga."
            bullets.append(
                f"Core de alta convicción con peso {weight:.0f}% dentro del rango sano "
                f"(< {cfg.trim_concentration_threshold_pct:.0f}%)."
            )
        else:
            action = TRIM_PARCIAL
            detail = (
                "Vender ~4-8 puntos de peso (≈15% de las shares) para re-asignar a otra idea "
                "de convicción HIGH o mantener disciplina de tamaño. NO es salida de tesis."
            )
            target = round(cfg.trim_concentration_threshold_pct - 5, 1)
            bullets.append(
                f"Tesis intacta pero peso {weight:.0f}% ≥ {cfg.trim_concentration_threshold_pct:.0f}%: "
                "re-allocación de capital dentro del libro concentrado (no diversificación por miedo)."
            )

    # --- Peso alto SIN calidad de 'core' → el tamaño no está justificado ----- #
    elif weight >= cfg.trim_concentration_threshold_pct:
        marginal = score < cfg.min_score_for_moderate_accumulate or moat in ("Minimal", "None")
        action = VENDER_PARTE if marginal else TRIM_PARCIAL
        target = round(cfg.moderate_accumulate_weight_pct, 1)
        detail = (
            f"Reducir hacia ~{target:.0f}%: el peso {weight:.0f}% excede la calidad estructural "
            "que lo respalda. Aunque declares alta convicción, los datos no sostienen un tamaño core."
            if marginal else
            f"Recortar hacia ~{target:.0f}%: peso {weight:.0f}% alto para una posición que no "
            "alcanza todos los gates de 'core' (calidad + moat + tailwind + convicción HIGH)."
        )
        bullets.append(
            f"Peso {weight:.0f}% ≥ umbral de trim {cfg.trim_concentration_threshold_pct:.0f}% sin "
            f"calificar como core (score {score:.0f}, moat {moat}, convicción {conviction}): "
            "la concentración acá es riesgo, no edge."
        )

    # --- No-core: acumular moderado / agregar en debilidad / holdear --------- #
    elif (
        conviction == "HIGH"
        and score >= cfg.min_score_for_moderate_accumulate
        and weight < cfg.moderate_accumulate_weight_pct
        and view.data_quality_level != "poor"
    ):
        if tech_weak:
            action = AGREGAR_EN_DEBILIDAD
            detail = "Sumar gradualmente sólo en debilidad adicional (RSI bajo / pullback)."
        else:
            action = ACUMULAR_MODERADO
            detail = f"Sumar hasta ~{cfg.moderate_accumulate_weight_pct:.0f}% de forma escalonada."
        target = round(cfg.moderate_accumulate_weight_pct, 1)
        bullets.append(
            f"Convicción HIGH + calidad buena (score {score:.0f}) pero sin todos los gates de 'core': "
            "acumulación moderada, no concentración extrema."
        )
        if not _is_core_concentration_candidate(view, "HIGH", cfg):
            missing = []
            if score < cfg.min_score_for_core_concentration:
                missing.append("score core")
            if moat not in ("Wide", "Narrow"):
                missing.append("moat")
            if tail not in ("Strong", "Moderate") and not view.has_margin_of_safety:
                missing.append("tailwind/asimetría")
            if missing:
                bullets.append(
                    "Marcaste HIGH, pero faltan gates objetivos (" + ", ".join(missing) +
                    "): la concentración aquí es más 'apuesta' que 'edge documentado'."
                )

    # --- Trim por sobre-tamaño con soporte débil ----------------------------- #
    elif weight > cfg.moderate_accumulate_weight_pct and (tech_weak or not view.has_margin_of_safety) and conviction != "HIGH":
        action = TRIM_PARCIAL
        detail = "Recortar algunos puntos: el tamaño excede la convicción/calidad que respalda la posición."
        target = round(cfg.moderate_accumulate_weight_pct, 1)
        bullets.append(
            f"Peso {weight:.0f}% por encima de lo que justifica una convicción {conviction} "
            "con soporte técnico/valuación débil."
        )

    # --- Default: holdear ---------------------------------------------------- #
    else:
        action = HOLDEAR
        detail = "Mantener: ni los datos ni la convicción piden cambiar el tamaño ahora."
        bullets.append(
            f"Sin gatillo de acción: score {score:.0f}, moat {moat}, convicción {conviction}, "
            f"peso {weight:.0f}%."
        )

    # --- Enriquecimiento común: tailwind, MOS, data quality ------------------ #
    if tail in ("Strong", "Moderate"):
        bullets.append(f"Viento de cola sector-país: {tail} (refuerza la tenencia).")
    elif tail == "Headwind":
        risks.append("Viento en contra estructural del sector/país: vigilá el deterioro de la tesis.")
    if view.has_margin_of_safety:
        mos = f" (~{view.margin_of_safety_pct:.0f}%)" if view.margin_of_safety_pct is not None else ""
        bullets.append(f"Margen de seguridad presente{mos}: entrada/tenencia con asimetría favorable.")
    if view.data_quality_level == "poor":
        risks.append(
            "Calidad de datos POBRE: revisá fundamentals antes de acumular. "
            "Por defecto el sistema sesga a no aumentar tamaño con datos incompletos."
        )

    # --- Riesgo de concentración (siempre que el peso sea alto) -------------- #
    if weight >= cfg.high_concentration_risk_note_pct:
        impact = _estimate_drawdown_impact(weight, cfg.drawdown_shock_pct)
        risks.append(
            f"Posición ya grande ({weight:.1f}%): un -{cfg.drawdown_shock_pct:.0f}% aquí mueve el "
            f"libro completo ≈ -{impact:.1f} puntos. Asegurate de poder tolerarlo sin vender."
        )

    # --- Impuestos en cualquier recorte / venta ------------------------------ #
    if action in (TRIM_PARCIAL, VENDER_PARTE, VENDER_TODO):
        risks.append(
            "Impuestos: calculá el impacto de ganancias de capital según tu purchase_date "
            "y régimen fiscal (largo vs corto plazo) antes de ejecutar."
        )

    # --- Tesis de concentración (siempre presente, en español) --------------- #
    concentration_thesis = _build_concentration_thesis(view, conviction, weight, action, is_core, cfg)

    return SizingRecommendation(
        symbol=view.symbol,
        action=action,
        current_weight_pct=round(weight, 1),
        suggested_target_weight_pct=target,
        suggested_action_detail=detail,
        conviction_used=conviction,
        justification_bullets=bullets,
        concentration_thesis=concentration_thesis,
        risk_notes=risks,
        base_score_drivers=drivers,
        data_quality_level=view.data_quality_level,
    )


def _build_concentration_thesis(
    view: AnalysisView,
    conviction: str,
    weight: float,
    action: str,
    is_core: bool,
    cfg: PersonalBookConfig,
) -> str:
    """
    Genera la 'tesis de concentración personal' por reglas (siempre menciona la
    ventaja del individuo vs un fondo, para mantener honestidad del edge).
    """
    if action in (VENDER_TODO, VENDER_PARTE) and view.adjusted_score < cfg.sell_all_score:
        return (
            f"{_FUND_CONTRAST} concentrar libremente — pero sólo cuando hay edge. "
            f"Acá la calidad estructural (score {view.adjusted_score:.0f}, moat "
            f"{view.moat_classification}) no respalda el tamaño: la libertad de "
            "concentración no es excusa para sostener una tesis rota."
        )
    if is_core and weight < cfg.trim_concentration_threshold_pct:
        ceiling = cfg.core_high_conviction_max_pct
        return (
            f"{_FUND_CONTRAST} ir hacia {ceiling:.0f}% en este nombre: moat "
            f"{view.moat_classification} + tailwind {view.tailwind_classification} + tu "
            "convicción HIGH son un edge real. Un fondo ya habría topado por policy "
            "(~5-10%); vos podés sostener el tamaño porque no tenés LPs que te fuercen "
            "a vender en un -30%. Esto es sizing intencional de idea de alta convicción, "
            "no diversificación perezosa."
        )
    if action == TRIM_PARCIAL:
        return (
            f"{_FUND_CONTRAST} mantener concentración, pero a {weight:.0f}% ya capturaste "
            "la mayor parte de la convicción. Recortar y re-asignar a otra idea HIGH es "
            "re-allocación dentro de un libro concentrado, no diversificación por miedo. "
            "Un fondo probablemente ya habría trimmeado por límite de emisor."
        )
    if conviction == "HIGH" and not is_core:
        return (
            f"{_FUND_CONTRAST} concentrar cuando tenés edge — pero los números no muestran "
            "todos los gates de calidad/moat/tailwind. Antes de cargar tamaño, confirmá que "
            "tu 'HIGH' viene de un edge informacional/analítico real y no de familiaridad."
        )
    return (
        f"{_FUND_CONTRAST} elegir conscientemente cuánto concentrar. A peso {weight:.0f}% y "
        f"convicción {conviction}, el tamaño actual parece razonable: mantené la disciplina y "
        "reservá la concentración extrema para tus ideas de máxima convicción y calidad."
    )


# --------------------------------------------------------------------------- #
#  Construcción del resumen de libro                                           #
# --------------------------------------------------------------------------- #


def _concentration_risk_note(ctx: BookContext, cfg: PersonalBookConfig) -> str:
    if ctx.num_positions == 0:
        return "Libro vacío: agregá posiciones para analizar el sizing."
    if ctx.max_weight_pct >= cfg.max_practical_concentration_single_name:
        return (
            f"Concentración EXTREMA: tu mayor posición pesa {ctx.max_weight_pct:.0f}%. Esto es "
            "extremo incluso para un individuo; sólo justificable con edge profundísimo + "
            "capacidad real de tolerar un drawdown grande."
        )
    if ctx.max_weight_pct >= cfg.trim_concentration_threshold_pct:
        return (
            f"Concentración ALTA: mayor posición {ctx.max_weight_pct:.0f}%, top-3 "
            f"{ctx.top3_weight_pct:.0f}%, posiciones efectivas ≈ {ctx.effective_positions:.1f}. "
            "Defendible como libro personal si cada nombre grande tiene edge documentado."
        )
    return (
        f"Concentración MODERADA: mayor posición {ctx.max_weight_pct:.0f}%, top-3 "
        f"{ctx.top3_weight_pct:.0f}%, posiciones efectivas ≈ {ctx.effective_positions:.1f}. "
        "Tenés margen para concentrar más en tus mejores ideas si aparece convicción + calidad."
    )


def _build_overall_summary(
    recs: List[SizingRecommendation],
    ctx: BookContext,
    cfg: PersonalBookConfig,
) -> str:
    if not recs:
        return (
            "Tu libro personal no tiene posiciones cargadas todavía. Agregá tickers en "
            "'Mi Portfolio' y volvé a ejecutar el análisis de sizing."
        )
    n_acum = sum(1 for r in recs if r.action in (ACUMULAR_AGRESIVO, ACUMULAR_MODERADO, AGREGAR_EN_DEBILIDAD))
    n_trim = sum(1 for r in recs if r.action in (TRIM_PARCIAL, VENDER_PARTE))
    n_sell = sum(1 for r in recs if r.action == VENDER_TODO)
    n_hold = sum(1 for r in recs if r.action == HOLDEAR)

    parts = [
        f"Libro personal de {ctx.num_positions} posiciones (valor ≈ ${ctx.total_value:,.0f}). "
        f"{_concentration_risk_note(ctx, cfg)}"
    ]
    parts.append(
        f"Acciones sugeridas: {n_acum} acumular, {n_hold} holdear, {n_trim} recortar, "
        f"{n_sell} vender. Convicciones HIGH declaradas: {ctx.num_high_conviction}/{ctx.num_positions}."
    )
    if ctx.num_high_conviction >= max(4, ctx.num_positions):
        parts.append(
            "Ojo con el sesgo de convicción inflada: marcaste HIGH en casi todo. Si todo es "
            "'alta convicción', tu libro efectivo es menos concentrado de lo que creés — revisá "
            "dónde tenés edge real vs familiaridad."
        )
    parts.append(
        "Recordá: a diferencia de un fondo con mandatos de diversificación y límites por emisor, "
        "tu ventaja estructural es la libertad de concentrar en pocas ideas de altísima convicción "
        "y la paciencia para sostenerlas — siempre que la calidad y tu edge lo justifiquen."
    )
    return " ".join(parts)


def _suggested_book_structure(cfg: PersonalBookConfig) -> str:
    return (
        f"Estructura sugerida de libro personal: 3-5 ideas 'core' de alta convicción "
        f"@ {cfg.aggressive_accumulate_weight_pct:.0f}-{cfg.core_high_conviction_max_pct:.0f}% "
        f"+ 4-6 satélites @ 4-{cfg.satellite_max_pct:.0f}% + un buffer de efectivo como dry "
        "powder para la próxima idea de alta convicción. La concentración es intencional, no inercia."
    )


def _overall_concentration_justification(cfg: PersonalBookConfig) -> str:
    """Cómo decide el sizer, dicho como decide de verdad (U5-11).

    Esta frase anunciaba «Ponderación de la lógica de sizing: calidad+moat+
    tailwind 45%, valoración+technical 20%, tu convicción 20%, contexto 15%».
    No existe tal ponderación: ``_decide_sizing`` es una cascada de gates duros
    —el primero que dispara decide— y los cuatro campos que interpolaba no los
    leía ningún gate. Los ejes son reales; el reparto en porcentajes no lo era.
    """
    return (
        f"Cómo se decide el tamaño: no es un promedio ponderado sino una cascada — "
        f"gana el primer criterio que dispara. Primero, si la tesis está rota "
        f"(score < {cfg.sell_all_score:.0f} o moat 'None') se sale, sin importar el resto. "
        f"Después, si el peso supera el techo práctico de "
        f"{cfg.max_practical_concentration_single_name:.0f}% se reduce igual, sin importar la "
        f"convicción declarada. Recién ahí se pregunta si el nombre es elegible para 'core', y "
        f"eso exige las cuatro cosas a la vez: score ≥ "
        f"{cfg.min_score_for_core_concentration:.0f}, moat Wide o Narrow, viento de cola o "
        f"margen de seguridad, y convicción HIGH tuya — con datos que no sean de calidad pobre. "
        f"Sólo entonces el peso actual elige entre acumular, holdear o recortar. "
        "Como libro personal individual (no fondo, hedge fund ni mandato institucional) tenés "
        "libertad de concentración extrema: sin límites por emisor, sin redenciones forzadas, sin "
        "comités de riesgo ni career risk. Esa libertad es tu ventaja competitiva — usala sólo "
        "donde tu edge de convicción + la calidad estructural + la duración del tailwind justifiquen "
        "tolerar la volatilidad y el capital inmovilizado."
    )


# --------------------------------------------------------------------------- #
#  API pública                                                                 #
# --------------------------------------------------------------------------- #


def analyze_personal_book(
    positions: Dict[str, Dict[str, Any]],
    convictions: Optional[Dict[str, str]] = None,
    enrich_fn: Optional[Callable[[str], Dict[str, Any]]] = None,
    config: PersonalBookConfig = PERSONAL_BOOK,
) -> PersonalBookAnalysis:
    """
    Analiza un libro personal y produce recomendaciones de sizing por ticker.

    Args:
        positions: salida de ``Portfolio.get_current_values()`` — dict por símbolo
            con al menos ``weight_pct``, ``market_value``, ``shares``, ``avg_cost``.
            Si ``weight_pct`` no viene, se calcula desde ``market_value``.
        convictions: ``{ticker: "HIGH"|"MEDIUM"|"LOW"}``; faltantes → default config.
        enrich_fn: ``(symbol) -> dict`` con análisis fundamental/técnico. Si es None
            usa el pipeline real (``full_analysis``). Inyectable para tests offline.
        config: instancia de ``PersonalBookConfig`` (default singleton ``PERSONAL_BOOK``).

    Returns:
        ``PersonalBookAnalysis`` serializable (``.to_dict()``).
    """
    convictions = {k.upper(): v for k, v in (convictions or {}).items()}
    enrich = enrich_fn or _default_enrich

    symbols = list(positions.keys())
    if not symbols:
        ctx = BookContext(0.0, 0, 0.0, 0.0, 0.0, 0)
        logger.info("personal_sizer: libro vacío")
        return PersonalBookAnalysis(
            as_of=datetime.now().isoformat(timespec="seconds"),
            total_value=0.0,
            num_positions=0,
            max_weight_pct=0.0,
            top3_weight_pct=0.0,
            effective_positions=0.0,
            concentration_risk_note=_concentration_risk_note(ctx, config),
            recommendations=[],
            overall_summary=_build_overall_summary([], ctx, config),
            suggested_book_structure=_suggested_book_structure(config),
            concentration_justification_overall=_overall_concentration_justification(config),
        )

    # --- Pesos (usar provistos o derivarlos de market_value) ----------------- #
    total_value = sum(float(p.get("market_value", 0.0) or 0.0) for p in positions.values())
    for sym, p in positions.items():
        if "weight_pct" not in p or p.get("weight_pct") is None:
            mv = float(p.get("market_value", 0.0) or 0.0)
            p["weight_pct"] = round(mv / total_value * 100, 1) if total_value > 0 else 0.0

    weights = [float(positions[s].get("weight_pct", 0.0) or 0.0) for s in symbols]
    max_weight = max(weights) if weights else 0.0
    top3 = round(sum(sorted(weights, reverse=True)[:3]), 1)
    eff = _effective_positions(weights)
    num_high = sum(
        1 for s in symbols if _normalize_conviction(convictions.get(s.upper()), config) == "HIGH"
    )
    ctx = BookContext(
        total_value=round(total_value, 2),
        num_positions=len(symbols),
        max_weight_pct=round(max_weight, 1),
        top3_weight_pct=top3,
        effective_positions=eff,
        num_high_conviction=num_high,
    )

    # --- Recomendación por posición ------------------------------------------ #
    recs: List[SizingRecommendation] = []
    for sym in symbols:
        pos = positions[sym]
        conviction = _normalize_conviction(convictions.get(sym.upper()), config)
        try:
            raw = enrich(sym)
        except Exception as exc:  # degradar gracefully ante fallos de red/datos
            logger.warning(f"personal_sizer: enrich falló para {sym}: {exc}")
            raw = {"data_quality_level": "poor"}
        view = AnalysisView.from_enrich(sym, raw)
        rec = _decide_sizing(pos, view, conviction, ctx, config)
        recs.append(rec)
        logger.info(f"personal_sizer: {sym} → {rec.action} (peso {rec.current_weight_pct}%, conv {conviction})")

    # Orden: mayor peso primero (lo más relevante para el riesgo del libro).
    recs.sort(key=lambda r: r.current_weight_pct, reverse=True)

    return PersonalBookAnalysis(
        as_of=datetime.now().isoformat(timespec="seconds"),
        total_value=ctx.total_value,
        num_positions=ctx.num_positions,
        max_weight_pct=ctx.max_weight_pct,
        top3_weight_pct=ctx.top3_weight_pct,
        effective_positions=ctx.effective_positions,
        concentration_risk_note=_concentration_risk_note(ctx, config),
        recommendations=recs,
        overall_summary=_build_overall_summary(recs, ctx, config),
        suggested_book_structure=_suggested_book_structure(config),
        concentration_justification_overall=_overall_concentration_justification(config),
    )
