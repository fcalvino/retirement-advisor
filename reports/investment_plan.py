"""
Investment Plan PDF Generator — Fase 3: Reportes PDF Profesionales.

Genera un reporte PDF de alta calidad con el plan de inversión a largo plazo
del usuario. Diseño de banco privado: limpio, profesional y accionable.

Usage:
    from reports.investment_plan import InvestmentPlanReport, ReportOptions
    options = ReportOptions(user_name="Juan Pérez", version="completo")
    pdf_bytes = InvestmentPlanReport().generate(
        goal_plan=goal_plan,
        opt_result=opt_result,
        mc_result=mc_result,
        mc_params={"horizon_years": 20, "initial_value": 100_000, ...},
        ai_config=ai_config,
        options=options,
    )
    # pdf_bytes → pass directly to st.download_button(data=pdf_bytes)
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from typing import Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from loguru import logger
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from data.product_ux import (
    GUARDRAILS_LABEL_LONG,
    GUARDRAILS_OMISSIONS,
    POT_CAGR_LABEL,
    POT_GROWTH_LABEL,
    PROXY_INDEX_LABEL,
    PROXY_RATIO_LABEL,
    mc_has_cash_flows,
    proxy_attractiveness_index,
)
from reports.pdf_utils import chart_to_image as _chart_to_image
from reports.pdf_utils import make_header_footer


def _fmt_idx(expected_return_pct) -> str:
    """El proxy como índice 0–100 (U6-1). «—» cuando no hay optimización corrida:
    un plan sin correr no tiene atractivo 0, no tiene atractivo."""
    idx = proxy_attractiveness_index(expected_return_pct)
    return "—" if idx is None else f"{idx:.0f}"

# ------------------------------------------------------------------ #
#  Brand colours — same palette as alerts/reporter.py                  #
# ------------------------------------------------------------------ #
_NAVY  = colors.HexColor("#1B3A6B")
_TEAL  = colors.HexColor("#17A2B8")
_GREEN = colors.HexColor("#28A745")
_RED   = colors.HexColor("#DC3545")
_AMBER = colors.HexColor("#FFC107")
_LGRAY = colors.HexColor("#F5F5F5")
_DGRAY = colors.HexColor("#6C757D")
_WHITE = colors.white
_BLACK = colors.black
_LIGHT_TEAL = colors.HexColor("#E8F7FA")


# ------------------------------------------------------------------ #
#  Options dataclass                                                   #
# ------------------------------------------------------------------ #

@dataclass
class ReportOptions:
    user_name: str = ""
    version: str = "completo"          # "completo" | "breve"
    include_ai_narrative: bool = True
    include_charts: bool = True
    include_risk_section: bool = True
    include_portfolio_section: bool = True
    include_recommendations: bool = True


# ------------------------------------------------------------------ #
#  Helpers                                                             #
# ------------------------------------------------------------------ #

def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "cover_title": ParagraphStyle(
            "cover_title", fontSize=30, textColor=_NAVY,
            fontName="Helvetica-Bold", alignment=TA_CENTER, spaceAfter=6),
        "cover_sub": ParagraphStyle(
            "cover_sub", fontSize=15, textColor=_TEAL,
            fontName="Helvetica", alignment=TA_CENTER, spaceAfter=4),
        "cover_meta": ParagraphStyle(
            "cover_meta", fontSize=10, textColor=_DGRAY,
            fontName="Helvetica", alignment=TA_CENTER, spaceAfter=4),
        "h1": ParagraphStyle(
            "h1", parent=base["Heading1"],
            fontSize=18, textColor=_NAVY, spaceAfter=4,
            fontName="Helvetica-Bold"),
        "h2": ParagraphStyle(
            "h2", parent=base["Heading2"],
            fontSize=13, textColor=_NAVY, spaceBefore=12,
            spaceAfter=4, fontName="Helvetica-Bold"),
        "h3": ParagraphStyle(
            "h3", parent=base["Heading3"],
            fontSize=10, textColor=_TEAL, spaceBefore=6,
            spaceAfter=2, fontName="Helvetica-Bold"),
        "body": ParagraphStyle(
            "body", parent=base["Normal"],
            fontSize=9, leading=13, fontName="Helvetica"),
        "body_bold": ParagraphStyle(
            "body_bold", parent=base["Normal"],
            fontSize=9, leading=13, fontName="Helvetica-Bold"),
        "small": ParagraphStyle(
            "small", parent=base["Normal"],
            fontSize=7.5, textColor=_DGRAY, fontName="Helvetica"),
        "caption": ParagraphStyle(
            "caption", parent=base["Normal"],
            fontSize=8, textColor=_DGRAY, alignment=TA_CENTER,
            fontName="Helvetica-Oblique"),
        "narrative": ParagraphStyle(
            "narrative", parent=base["Normal"],
            fontSize=9.5, leading=15, fontName="Helvetica",
            leftIndent=12, rightIndent=12),
        "right": ParagraphStyle(
            "right", parent=base["Normal"],
            fontSize=9, alignment=TA_RIGHT, fontName="Helvetica"),
    }


def _make_header_footer(report_date: str, user_name: str):
    """Thin wrapper: investment-plan defaults for the shared PDF chrome."""
    return make_header_footer(
        report_date,
        "Mi Plan de Inversión a Largo Plazo",
        right_text=user_name or report_date,
        footer_left="Reporte orientativo · No constituye asesoramiento financiero.",
        header_font_size=10,
        header_title_y_cm=0.95,
    )


def _fmt(val, prefix="", suffix="", decimals=1, default="N/D") -> str:
    if val is None:
        return default
    return f"{prefix}{val:.{decimals}f}{suffix}"


def _feasibility_color(label: str) -> colors.Color:
    if "✅" in label:
        return _GREEN
    if "⚠️" in label:
        return colors.HexColor("#5CB85C")
    if "🔶" in label:
        return _AMBER
    return _RED


# ------------------------------------------------------------------ #
#  Main class                                                          #
# ------------------------------------------------------------------ #

class InvestmentPlanReport:
    """Generates a professional investment plan PDF as bytes."""

    def generate(
        self,
        goal_plan=None,          # GoalPlan | None
        opt_result=None,         # OptimizationResult | None
        mc_result=None,          # MonteCarloResult | None
        mc_params: dict = None,  # horizon, initial_value, withdrawal, target, inflation, profile
        ai_config=None,          # AIConfig | None
        options: ReportOptions = None,
    ) -> bytes:
        if options is None:
            options = ReportOptions()
        if mc_params is None:
            mc_params = {}

        report_date = datetime.now().strftime("%d/%m/%Y %H:%M")
        buf = io.BytesIO()
        st = _styles()

        doc = SimpleDocTemplate(
            buf,
            pagesize=A4,
            leftMargin=1.5 * cm,
            rightMargin=1.5 * cm,
            topMargin=2.2 * cm,
            bottomMargin=2.0 * cm,
        )

        story: list = []

        # --- 1. Portada ---
        story += self._cover(st, options, report_date, goal_plan, opt_result)
        story.append(PageBreak())

        # --- 2. Resumen Ejecutivo + Narrativa AI ---
        if options.include_ai_narrative:
            narrative = self._get_narrative(ai_config, opt_result, mc_result, mc_params)
        else:
            narrative = None
        story += self._section_executive_summary(st, goal_plan, opt_result, mc_result, mc_params, narrative, options)

        # --- 2b. Partner/advisor shareable narrative (backlog 11) ---
        story += self._section_shareable_for_partner(
            st, goal_plan, opt_result, mc_result, mc_params, options
        )

        # --- 3. Resumen de Metas ---
        if goal_plan is not None:
            story += self._section_goals(st, goal_plan, options)

        # --- 4. Portafolio Optimizado ---
        if options.include_portfolio_section and opt_result is not None:
            story += self._section_portfolio(st, opt_result, options)

        # --- 5. Análisis de Riesgo ---
        if options.version == "completo" and options.include_risk_section and mc_result is not None:
            story += self._section_risk(st, mc_result, mc_params, options)

        # --- 6. Recomendaciones ---
        if options.include_recommendations:
            story += self._section_recommendations(st, opt_result, goal_plan)

        # --- 7. Disclaimer ---
        story += self._section_disclaimer(st, mc_result)

        on_page = _make_header_footer(report_date, options.user_name)
        doc.build(story, onFirstPage=on_page, onLaterPages=on_page)

        buf.seek(0)
        return buf.getvalue()

    # ---------------------------------------------------------------- #
    #  Section: Shareable for partner/advisor (backlog 11)              #
    # ---------------------------------------------------------------- #

    def _section_shareable_for_partner(
        self, st, goal_plan, opt_result, mc_result, mc_params, options
    ) -> list:
        """Plain-language blocks for sharing with a partner or advisor."""
        from data.product_ux import (
            build_annual_action_list,
            shareable_report_narrative_blocks,
        )

        plan_name = ""
        if options and getattr(options, "user_name", ""):
            plan_name = f"Plan de {options.user_name}"
        if goal_plan is not None and getattr(goal_plan, "goals", None):
            plan_name = plan_name or "Plan con metas"
        plan_name = plan_name or "Plan de retiro"

        prob = None
        median = None
        if mc_result is not None:
            prob = getattr(mc_result, "prob_achieve_target_pct", None)
            median = getattr(mc_result, "median_terminal", None)
        horizon = None
        if mc_params:
            horizon = mc_params.get("horizon_years")
        profile = ""
        if opt_result is not None:
            profile = str(getattr(opt_result, "profile_name", "") or "")
        elif mc_params:
            profile = str(mc_params.get("profile_name") or "")

        # Prefer real savings from mc_params, then goal_plan.personal, then
        # UserPreferences on disk — so call sites that only pass sim widgets still
        # get a useful "Qué hacer este año" when the user set monthly_savings.
        from data.product_ux import enrich_pdf_mc_params

        personal_src: dict = {}
        if goal_plan is not None:
            personal_src = dict(getattr(goal_plan, "personal", None) or {})
        # Best-effort prefs load (no Streamlit) when params omit savings.
        prefs_obj = None
        try:
            from data.preferences import UserPreferences

            prefs_obj = UserPreferences.load()
        except Exception:
            prefs_obj = None

        mc_params = enrich_pdf_mc_params(
            mc_params or {}, prefs=prefs_obj, personal=personal_src
        )
        if horizon is None and mc_params.get("horizon_years") is not None:
            horizon = mc_params.get("horizon_years")

        monthly_savings = 0.0
        try:
            monthly_savings = float(mc_params.get("monthly_savings") or 0.0)
        except (TypeError, ValueError):
            monthly_savings = 0.0

        personal = {
            "primary_horizon_years": horizon,
            "monthly_savings": monthly_savings if monthly_savings > 0 else None,
            "annual_savings": (
                float(mc_params["annual_savings"])
                if mc_params.get("annual_savings") is not None
                else (monthly_savings * 12.0 if monthly_savings > 0 else None)
            ),
            "current_capital": mc_params.get("initial_value"),
        }
        # Strip Nones for a clean plan-like personal dict
        personal = {k: v for k, v in personal.items() if v is not None}

        plan_like = SimpleNamespace(
            name=plan_name,
            personal=personal,
            profile_name=profile,
            n_positions=(
                len(getattr(opt_result, "tickers", []) or [])
                if opt_result is not None
                else 0
            ),
            metrics={},
            mc_summary={
                "prob_target_pct": prob,
                "median_terminal": median,
            },
        )

        actions = build_annual_action_list(
            plan_snapshot=plan_like,
            monthly_savings=monthly_savings,
            has_portfolio_positions=bool(opt_result),
            last_backup_days=0,
        )
        blocks = shareable_report_narrative_blocks(
            plan_name=plan_name,
            prob_target_pct=float(prob) if prob is not None else None,
            median_terminal=float(median) if median is not None else None,
            horizon_years=float(horizon) if horizon is not None else None,
            profile=profile,
            annual_actions=actions,
        )
        elements = [
            Paragraph("Para compartir (pareja / asesor)", st.get("h1", st["cover_title"])),
            Spacer(1, 0.2 * cm),
            HRFlowable(width="100%", thickness=1, color=_TEAL, spaceAfter=8),
        ]
        body_style = st.get("body") or st.get("normal") or list(st.values())[0]
        h2 = st.get("h2") or body_style
        for b in blocks:
            elements.append(Paragraph(str(b.get("heading", "")), h2))
            elements.append(Paragraph(str(b.get("body", "")), body_style))
            elements.append(Spacer(1, 0.15 * cm))
        elements.append(Spacer(1, 0.3 * cm))
        return elements

    # ---------------------------------------------------------------- #
    #  Section: Cover                                                   #
    # ---------------------------------------------------------------- #

    def _cover(self, st, options, report_date, goal_plan, opt_result) -> list:
        elements = [
            Spacer(1, 1.5 * cm),
            Paragraph("Mi Plan de Inversión", st["cover_title"]),
            Paragraph("a Largo Plazo", st["cover_title"]),
            Spacer(1, 0.4 * cm),
            HRFlowable(width="80%", thickness=2, color=_TEAL, spaceAfter=10),
        ]

        if options.user_name:
            elements.append(Paragraph(options.user_name, st["cover_sub"]))
            elements.append(Spacer(1, 0.2 * cm))

        elements.append(Paragraph(
            f"Generado el {report_date}", st["cover_meta"]))
        elements.append(Paragraph(
            f"Versión: {options.version.capitalize()}", st["cover_meta"]))
        elements.append(Spacer(1, 1.0 * cm))

        # KPI summary row
        n_goals = len(goal_plan.goal_results) if goal_plan else 0
        plan_score = f"{goal_plan.plan_feasibility_score:.0f}/100" if goal_plan else "—"
        n_tickers = len(opt_result.tickers) if opt_result else 0
        exp_ret = _fmt_idx(opt_result.expected_return_pct) if opt_result else "—"

        kpi_data = [
            ["Metas planificadas", "Score del plan", "Tickers en cartera", "Atractivo (proxy)"],
            [str(n_goals), plan_score, str(n_tickers), exp_ret],
        ]
        kpi_tbl = Table(kpi_data, colWidths=[4.3 * cm] * 4)
        kpi_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0), _NAVY),
            ("TEXTCOLOR",     (0, 0), (-1, 0), _WHITE),
            ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, 0), 8),
            ("FONTNAME",      (0, 1), (-1, 1), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 1), (-1, 1), 20),
            ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS",(0, 1), (-1, 1), [_LGRAY]),
            ("GRID",          (0, 0), (-1, -1), 0.5, _DGRAY),
            ("TOPPADDING",    (0, 1), (-1, 1), 12),
            ("BOTTOMPADDING", (0, 1), (-1, 1), 12),
        ]))
        elements.append(kpi_tbl)
        elements.append(Spacer(1, 1.2 * cm))

        elements.append(Paragraph(
            "Este reporte resume tu plan de inversión: metas, portafolio optimizado, "
            "proyecciones Monte Carlo y recomendaciones accionables.",
            ParagraphStyle("cover_desc", fontSize=10, textColor=_DGRAY,
                           fontName="Helvetica", alignment=TA_CENTER,
                           leading=14),
        ))
        return elements

    # ---------------------------------------------------------------- #
    #  Section: Executive Summary + AI Narrative                        #
    # ---------------------------------------------------------------- #

    def _section_executive_summary(self, st, goal_plan, opt_result, mc_result, mc_params,
                                   narrative, options) -> list:
        elements = [
            Paragraph("Resumen Ejecutivo", st["h1"]),
            HRFlowable(width="100%", thickness=2, color=_NAVY, spaceAfter=8),
        ]

        # Quick stats table
        horizon = mc_params.get("horizon_years", "—")
        initial = mc_params.get("initial_value", 0)
        withdrawal = mc_params.get("annual_withdrawal", 0)
        inflation = mc_params.get("inflation_rate") or 3.0
        profile = mc_params.get("profile_name", "—")

        rows = [["Parámetro", "Valor"]]
        if profile and profile != "—":
            rows.append(["Perfil de riesgo", str(profile)])
        if initial:
            rows.append(["Capital inicial", f"${initial:,.0f}"])
        if horizon and horizon != "—":
            rows.append(["Horizonte", f"{horizon} años"])
        if withdrawal:
            rows.append(["Retiro anual", f"${withdrawal:,.0f}"])
        rows.append(["Inflación estimada", f"{inflation:.1f}%"])
        if opt_result:
            rows.append([PROXY_INDEX_LABEL, _fmt_idx(opt_result.expected_return_pct)])
            rows.append(["Volatilidad estimada",       f"{opt_result.volatility_pct:.1f}%"])
            rows.append([PROXY_RATIO_LABEL,            f"{opt_result.sharpe_ratio:.2f}"])
            rows.append(["Dividend yield",             f"{opt_result.dividend_yield_pct:.1f}%"])
        if mc_result:
            rows.append(["Proyección mediana (P50)", f"${mc_result.median_terminal:,.0f}"])
            rows.append(["Escenario pesimista (P10)", f"${mc_result.p10_terminal:,.0f}"])
            rows.append(["Escenario optimista (P90)", f"${mc_result.p90_terminal:,.0f}"])
            rows.append(["Probabilidad de ruina",    f"{mc_result.prob_ruin_pct:.1f}%"])

        tbl = Table(rows, colWidths=[8 * cm, 9.2 * cm])
        style_cmds = [
            ("BACKGROUND",    (0, 0), (-1, 0), _NAVY),
            ("TEXTCOLOR",     (0, 0), (-1, 0), _WHITE),
            ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 9),
            ("FONTNAME",      (0, 1), (0, -1), "Helvetica-Bold"),
            ("ALIGN",         (0, 0), (-1, -1), "LEFT"),
            ("ALIGN",         (1, 1), (1, -1), "RIGHT"),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [_WHITE, _LGRAY]),
            ("GRID",          (0, 0), (-1, -1), 0.3, _DGRAY),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ]
        tbl.setStyle(TableStyle(style_cmds))
        elements.append(tbl)
        elements.append(Spacer(1, 0.5 * cm))

        # AI Narrative
        if narrative:
            elements.append(Paragraph("Análisis IA de tu plan", st["h2"]))
            elements.append(HRFlowable(width="100%", thickness=1, color=_TEAL, spaceAfter=6))
            # Render narrative lines preserving bold markers
            for line in narrative.split("\n"):
                line = line.strip()
                if not line:
                    elements.append(Spacer(1, 0.15 * cm))
                    continue
                # Convert markdown bold **text** → reportlab <b>text</b>
                line = line.replace("**", "\x00")
                parts = line.split("\x00")
                rendered = ""
                for i, part in enumerate(parts):
                    rendered += f"<b>{part}</b>" if i % 2 == 1 else part
                elements.append(Paragraph(rendered, st["narrative"]))
            elements.append(Spacer(1, 0.3 * cm))

        return elements

    # ---------------------------------------------------------------- #
    #  Section: Goals Summary                                           #
    # ---------------------------------------------------------------- #

    def _section_goals(self, st, goal_plan, options) -> list:
        elements = [
            PageBreak(),
            Paragraph("Resumen de Metas", st["h1"]),
            HRFlowable(width="100%", thickness=2, color=_NAVY, spaceAfter=8),
        ]

        # Plan-level KPIs
        gap = goal_plan.capital_gap_today
        gap_str = f"${gap:,.0f}" if gap > 0 else "Sin déficit"
        kpi_rows = [
            ["Score del plan", "Capital requerido (hoy)", "Déficit (USD de hoy)", "Metas viables (≥65%)"],
            [
                f"{goal_plan.plan_feasibility_score:.0f}/100",
                f"${goal_plan.total_capital_needed_today:,.0f}",
                gap_str,
                f"{sum(1 for gr in goal_plan.goal_results if gr.prob_success_pct >= 65)}"
                f"/{len(goal_plan.goal_results)}",
            ],
        ]
        kpi_tbl = Table(kpi_rows, colWidths=[4.3 * cm] * 4)
        kpi_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0), _TEAL),
            ("TEXTCOLOR",     (0, 0), (-1, 0), _WHITE),
            ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, 0), 8),
            ("FONTNAME",      (0, 1), (-1, 1), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 1), (-1, 1), 15),
            ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS",(0, 1), (-1, 1), [_LIGHT_TEAL]),
            ("GRID",          (0, 0), (-1, -1), 0.5, _DGRAY),
            ("TOPPADDING",    (0, 1), (-1, 1), 10),
            ("BOTTOMPADDING", (0, 1), (-1, 1), 10),
        ]))
        elements.append(kpi_tbl)
        elements.append(Spacer(1, 0.5 * cm))

        # Per-goal table
        headers = [
            "Meta", "Tipo", "Horizonte", "Monto Objetivo",
            "Capital\nAsignado", "Prob. Éxito", "SORR\nRisk", "Estado"
        ]
        col_w = [3.8, 1.5, 1.8, 2.8, 2.5, 2.0, 1.8, 1.0]
        col_w = [w * cm for w in col_w]

        rows = [headers]
        style_cmds = [
            ("BACKGROUND",    (0, 0), (-1, 0), _NAVY),
            ("TEXTCOLOR",     (0, 0), (-1, 0), _WHITE),
            ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 8),
            ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
            ("ALIGN",         (0, 1), (0, -1), "LEFT"),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [_WHITE, _LGRAY]),
            ("GRID",          (0, 0), (-1, -1), 0.3, _DGRAY),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING",   (0, 1), (0, -1), 6),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
            ("WORDWRAP",      (0, 0), (-1, -1), True),
        ]

        from portfolio.goals import GOAL_TYPE_ICONS, GOAL_TYPE_LABELS

        for ri, gr in enumerate(goal_plan.goal_results, 1):
            g = gr.goal
            icon = GOAL_TYPE_ICONS.get(g.goal_type, "📌")
            prob = gr.prob_success_pct
            sorr = gr.sorr_risk_pct
            feas = gr.feasibility_label

            rows.append([
                f"{icon} {g.name[:22]}",
                GOAL_TYPE_LABELS.get(g.goal_type, g.goal_type)[:10],
                f"{g.horizon_years}a",
                f"${gr.goal.target_nominal:,.0f}",
                f"${gr.allocated_capital:,.0f}",
                f"{prob:.0f}%",
                f"{sorr:.0f}%",
                feas.split()[0],  # just the emoji
            ])

            # Color probability cell
            prob_color = _GREEN if prob >= 80 else (_AMBER if prob >= 60 else _RED)
            style_cmds.append(("TEXTCOLOR", (5, ri), (5, ri), prob_color))
            style_cmds.append(("FONTNAME",  (5, ri), (5, ri), "Helvetica-Bold"))

            # Color SORR cell
            sorr_color = _RED if sorr >= 30 else (_AMBER if sorr >= 15 else _GREEN)
            style_cmds.append(("TEXTCOLOR", (6, ri), (6, ri), sorr_color))

            # Color emoji feasibility cell
            feas_color = _feasibility_color(feas)
            style_cmds.append(("TEXTCOLOR", (7, ri), (7, ri), feas_color))
            style_cmds.append(("FONTNAME",  (7, ri), (7, ri), "Helvetica-Bold"))

        tbl = Table(rows, colWidths=col_w)
        tbl.setStyle(TableStyle(style_cmds))
        elements.append(tbl)

        # Warnings
        if goal_plan.warnings:
            elements.append(Spacer(1, 0.4 * cm))
            elements.append(Paragraph("Advertencias del plan:", st["h3"]))
            for w in goal_plan.warnings:
                elements.append(Paragraph(f"• {w}", st["small"]))

        return elements

    # ---------------------------------------------------------------- #
    #  Section: Portfolio Optimized                                     #
    # ---------------------------------------------------------------- #

    def _section_portfolio(self, st, opt_result, options) -> list:
        elements = [
            PageBreak(),
            Paragraph("Portafolio Optimizado", st["h1"]),
            HRFlowable(width="100%", thickness=2, color=_NAVY, spaceAfter=8),
        ]

        # Portfolio stats KPI bar
        kpi_rows = [
            ["Atractivo (proxy)", "Volatilidad", "Ratio atr./vol", "Div. Yield", "Moat Avg", "Tickers"],
            [
                _fmt_idx(opt_result.expected_return_pct),
                f"{opt_result.volatility_pct:.1f}%",
                f"{opt_result.sharpe_ratio:.2f}",
                f"{opt_result.dividend_yield_pct:.1f}%",
                f"{opt_result.moat_score_avg:.1f}",
                str(len(opt_result.tickers)),
            ],
        ]
        kpi_tbl = Table(kpi_rows, colWidths=[2.85 * cm] * 6)
        kpi_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0), _NAVY),
            ("TEXTCOLOR",     (0, 0), (-1, 0), _WHITE),
            ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, 0), 8),
            ("FONTNAME",      (0, 1), (-1, 1), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 1), (-1, 1), 13),
            ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS",(0, 1), (-1, 1), [_LGRAY]),
            ("GRID",          (0, 0), (-1, -1), 0.5, _DGRAY),
            ("TOPPADDING",    (0, 1), (-1, 1), 8),
            ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
        ]))
        elements.append(kpi_tbl)
        elements.append(Spacer(1, 0.5 * cm))

        # Donut chart
        if options.include_charts and options.version == "completo":
            try:
                elements.append(self._donut_chart(opt_result))
                elements.append(Paragraph(
                    "Distribución de asignación por ticker (excluyendo pesos < 1.5%)",
                    st["caption"]))
                elements.append(Spacer(1, 0.4 * cm))
            except Exception as e:
                logger.warning(f"Could not render donut chart: {e}")

        # Allocation table
        elements.append(Paragraph("Asignación detallada", st["h2"]))
        headers = ["Ticker", "Empresa", "Peso %", "Atract. %", "Vol %", "Div %", "Moat", "Sector"]
        col_w = [1.6, 4.0, 1.5, 2.0, 1.5, 1.3, 1.8, 3.5]
        col_w = [w * cm for w in col_w]

        rows = [headers]
        style_cmds = [
            ("BACKGROUND",    (0, 0), (-1, 0), _NAVY),
            ("TEXTCOLOR",     (0, 0), (-1, 0), _WHITE),
            ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 8),
            ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
            ("ALIGN",         (1, 1), (1, -1), "LEFT"),
            ("ALIGN",         (7, 1), (7, -1), "LEFT"),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [_WHITE, _LGRAY]),
            ("GRID",          (0, 0), (-1, -1), 0.3, _DGRAY),
            ("TOPPADDING",    (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING",   (1, 1), (1, -1), 6),
        ]

        sorted_tickers = sorted(opt_result.tickers, key=lambda t: t.weight_pct, reverse=True)
        for ri, t in enumerate(sorted_tickers, 1):
            rows.append([
                t.symbol,
                (t.symbol[:28]),
                f"{t.weight_pct:.1f}%",
                _fmt_idx(t.expected_return_pct),
                f"{t.volatility_pct:.1f}%",
                f"{t.dividend_yield_pct:.1f}%",
                getattr(t, "moat_classification", "—") or "—",
                (t.sector or "")[:18],
            ])

        tbl = Table(rows, colWidths=col_w)
        tbl.setStyle(TableStyle(style_cmds))
        elements.append(tbl)

        # Sector breakdown
        elements.append(Spacer(1, 0.5 * cm))
        elements.append(Paragraph("Distribución por sector", st["h2"]))
        sector_rows = [["Sector", "Peso %"]]
        for sec, w in sorted(opt_result.sector_weights.items(), key=lambda x: x[1], reverse=True):
            sector_rows.append([sec, f"{w:.1f}%"])
        sec_tbl = Table(sector_rows, colWidths=[12 * cm, 5.2 * cm])
        sec_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0), _TEAL),
            ("TEXTCOLOR",     (0, 0), (-1, 0), _WHITE),
            ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 8.5),
            ("ALIGN",         (1, 0), (1, -1), "RIGHT"),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [_WHITE, _LGRAY]),
            ("GRID",          (0, 0), (-1, -1), 0.3, _DGRAY),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("RIGHTPADDING",  (1, 0), (1, -1), 8),
        ]))
        elements.append(sec_tbl)

        return elements

    # ---------------------------------------------------------------- #
    #  Section: Risk Analysis                                           #
    # ---------------------------------------------------------------- #

    def _section_risk(self, st, mc_result, mc_params, options) -> list:
        elements = [
            PageBreak(),
            Paragraph("Análisis de Riesgo", st["h1"]),
            HRFlowable(width="100%", thickness=2, color=_NAVY, spaceAfter=8),
        ]

        # Risk metrics table
        # U1-7: con aportes o retiros la tasa anualizada del pozo no es un
        # retorno — el flujo mueve el terminal sin mover el inicial. El PDF es
        # un export, así que el rótulo y la interpretación salen del vocabulario
        # canónico en vez de prometer "rendimiento compuesto" en los dos casos.
        _pdf_flows = mc_has_cash_flows(mc_result)
        _pdf_growth = POT_GROWTH_LABEL if _pdf_flows else POT_CAGR_LABEL
        _pdf_growth_note = (
            "Mezcla retorno y flujos: no es un retorno"
            if _pdf_flows else
            "Rendimiento anual compuesto típico"
        )
        risk_rows = [["Métrica de riesgo", "Valor", "Interpretación"]]
        risk_data = [
            ("Prob. de ruina (terminal ≤ $0)",
             f"{mc_result.prob_ruin_pct:.1f}%",
             "< 5% es aceptable para retiro"),
            (f"{_pdf_growth} mediano",
             f"{mc_result.median_cagr_pct:.1f}%",
             _pdf_growth_note),
            (f"{_pdf_growth} pesimista (P10)",
             f"{mc_result.p10_cagr_pct:.1f}%",
             "En el 10% de peores escenarios"),
            ("Max Drawdown mediano",
             f"{mc_result.median_max_drawdown_pct:.0f}%",
             "Caída pico-a-valle típica del mercado (no incluye retiros)"),
            ("Riesgo SORR (caída >30% en primeros 5 años)",
             f"{mc_result.sorr_early_drawdown_pct:.0f}%",
             "< 20% es manejable con glide path"),
            ("Paths con caída ≥ 50%",
             f"{mc_result.pct_paths_severe_drawdown:.0f}%",
             "Probabilidad de pérdida severa"),
            ("Mínimo P10 intra-horizonte",
             f"${mc_result.p10_intra_min:,.0f}",
             "Valor mínimo típico del 10% peor"),
        ]
        for label, val, interp in risk_data:
            risk_rows.append([label, val, interp])

        risk_tbl = Table(risk_rows, colWidths=[7.5 * cm, 2.5 * cm, 7.2 * cm])
        risk_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0), _NAVY),
            ("TEXTCOLOR",     (0, 0), (-1, 0), _WHITE),
            ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 8.5),
            ("FONTNAME",      (0, 1), (0, -1), "Helvetica"),
            ("FONTNAME",      (1, 1), (1, -1), "Helvetica-Bold"),
            ("TEXTCOLOR",     (2, 1), (2, -1), _DGRAY),
            ("ALIGN",         (1, 0), (1, -1), "CENTER"),
            ("ALIGN",         (0, 0), (0, -1), "LEFT"),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [_WHITE, _LGRAY]),
            ("GRID",          (0, 0), (-1, -1), 0.3, _DGRAY),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ]))
        elements.append(risk_tbl)
        elements.append(Spacer(1, 0.5 * cm))

        # Fan chart
        if options.include_charts:
            try:
                elements.append(Paragraph("Fan Chart — Proyección Monte Carlo", st["h2"]))
                elements.append(self._fan_chart(mc_result, mc_params))
                elements.append(Paragraph(
                    "Proyección de valor de cartera según percentiles de simulación (10.000 paths)",
                    st["caption"]))
                elements.append(Spacer(1, 0.4 * cm))
            except Exception as e:
                logger.warning(f"Could not render fan chart: {e}")

        # Fase H.1/H.4 — retirement-income (decumulation) block. Rendered only
        # when the simulation used an explicit withdrawal strategy, so plans in
        # pure accumulation keep the report byte-identical to before.
        _wd = getattr(mc_result, "withdrawal_strategy_applied", None)
        if _wd:
            kind = _wd.get("kind", "")
            _desc = {
                "fixed_real": f"Retiro fijo real de ${_wd.get('annual_amount', 0):,.0f}/año (ajustado por inflación, estilo regla del 4%).",
                "constant_pct": f"Retiro de {float(_wd.get('pct', 0)) * 100:.1f}% del valor actual cada año (ingreso variable, no se agota del todo).",
                "guardrails": (f"{GUARDRAILS_LABEL_LONG} con tasa base "
                               f"{float(_wd.get('pct', 0)) * 100:.1f}%: recorta el gasto en caídas "
                               f"y lo sube en mercados buenos. {GUARDRAILS_OMISSIONS}"),
            }.get(kind, f"Estrategia: {kind}.")

            elements.append(Spacer(1, 0.3 * cm))
            elements.append(Paragraph("Estrategia de retiro (decumulación)", st["h2"]))
            elements.append(HRFlowable(width="100%", thickness=1, color=_TEAL, spaceAfter=6))
            elements.append(Paragraph(_desc, st["small"]))
            elements.append(Spacer(1, 0.2 * cm))

            _ly = getattr(mc_result, "longevity_years", 0) or mc_params.get("horizon_years", "—")
            _dep = float(getattr(mc_result, "expected_depletion_year", 0) or 0)
            _dep_txt = f"~año {_dep:.0f}" if _dep > 0 else "no se agota en el horizonte"
            dec_rows = [
                ["Métrica de retiro", "Valor", "Interpretación"],
                [f"Prob. de que el ingreso dure {_ly} años",
                 f"{getattr(mc_result, 'prob_sustain_real_pct', 0):.0f}%",
                 "≥ 85% es robusto para retiro"],
                ["Herencia mediana",
                 f"${getattr(mc_result, 'median_legacy', 0):,.0f}",
                 "Valor final mediano"],
                ["Si se agota, año típico",
                 _dep_txt,
                 "Entre los paths que sí se agotan"],
            ]
            dec_tbl = Table(dec_rows, colWidths=[7.5 * cm, 2.5 * cm, 7.2 * cm])
            dec_tbl.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, 0), _TEAL),
                ("TEXTCOLOR",     (0, 0), (-1, 0), _WHITE),
                ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE",      (0, 0), (-1, -1), 8.5),
                ("FONTNAME",      (1, 1), (1, -1), "Helvetica-Bold"),
                ("TEXTCOLOR",     (2, 1), (2, -1), _DGRAY),
                ("ALIGN",         (1, 0), (1, -1), "CENTER"),
                ("ROWBACKGROUNDS",(0, 1), (-1, -1), [_WHITE, _LGRAY]),
                ("GRID",          (0, 0), (-1, -1), 0.3, _DGRAY),
                ("TOPPADDING",    (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ]))
            elements.append(dec_tbl)
            elements.append(Spacer(1, 0.3 * cm))

        return elements

    # ---------------------------------------------------------------- #
    #  Section: Recommendations                                         #
    # ---------------------------------------------------------------- #

    def _section_recommendations(self, st, opt_result, goal_plan) -> list:
        elements = [
            Spacer(1, 0.3 * cm),
            Paragraph("Recomendaciones Accionables", st["h1"]),
            HRFlowable(width="100%", thickness=2, color=_NAVY, spaceAfter=8),
        ]

        # From optimizer rebalance suggestions
        if opt_result and opt_result.rebalance_suggestions:
            elements.append(Paragraph("Rebalanceo sugerido", st["h2"]))
            elements.append(HRFlowable(width="100%", thickness=1, color=_TEAL, spaceAfter=6))
            elements.append(Paragraph(
                f"Frecuencia recomendada: <b>{opt_result.rebalance_frequency}</b>. "
                f"{opt_result.rebalance_rationale}",
                st["body"],
            ))
            elements.append(Spacer(1, 0.3 * cm))
            headers = ["Ticker", "Peso actual %", "Peso objetivo %", "Acción"]
            col_w = [2.5, 3.5, 3.5, 7.7]
            col_w = [w * cm for w in col_w]
            rows = [headers]
            for s in opt_result.rebalance_suggestions[:10]:
                rows.append([
                    s.symbol,
                    f"{s.current_pct:.1f}%",
                    f"{s.target_pct:.1f}%",
                    s.action[:60],
                ])
            rb_tbl = Table(rows, colWidths=col_w)
            rb_tbl.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, 0), _TEAL),
                ("TEXTCOLOR",     (0, 0), (-1, 0), _WHITE),
                ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE",      (0, 0), (-1, -1), 8),
                ("ALIGN",         (0, 0), (-1, -1), "LEFT"),
                ("ROWBACKGROUNDS",(0, 1), (-1, -1), [_WHITE, _LGRAY]),
                ("GRID",          (0, 0), (-1, -1), 0.3, _DGRAY),
                ("TOPPADDING",    (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ]))
            elements.append(rb_tbl)
            elements.append(Spacer(1, 0.4 * cm))

        # Próximos pasos generales
        elements.append(Paragraph("Próximos pasos", st["h2"]))
        elements.append(HRFlowable(width="100%", thickness=1, color=_GREEN, spaceAfter=6))

        next_steps = []
        if goal_plan:
            at_risk = [gr for gr in goal_plan.goal_results if gr.prob_success_pct < 65]
            if at_risk:
                names = ", ".join(gr.goal.name for gr in at_risk[:3])
                next_steps.append(
                    f"Revisar metas con baja probabilidad de éxito: <b>{names}</b>. "
                    "Considerá aumentar el capital asignado o extender el horizonte."
                )
            high_sorr = [gr for gr in goal_plan.goal_results if gr.sorr_risk_pct >= 30]
            if high_sorr:
                next_steps.append(
                    "Implementar <b>Glide Path</b> en metas con alto riesgo SORR: "
                    "reducir exposición a renta variable en los 3 años previos a cada meta."
                )

        next_steps += [
            "Revisar la asignación del portafolio <b>al menos una vez por año</b> o ante cambios significativos de mercado.",
            "Mantener un <b>fondo de emergencia</b> de 6-12 meses de gastos fuera del portafolio de inversión.",
            "Documentar las contribuciones anuales planeadas y ajustarlas por inflación cada año.",
        ]

        for step in next_steps:
            elements.append(Paragraph(f"• {step}", st["body"]))
            elements.append(Spacer(1, 0.15 * cm))

        return elements

    # ---------------------------------------------------------------- #
    #  Section: Disclaimer                                              #
    # ---------------------------------------------------------------- #

    def _section_disclaimer(self, st, mc_result=None) -> list:
        # Item 1 — explicit, hard-to-miss statement of modeling assumptions.
        _drag_total = float(getattr(mc_result, "total_annual_drag_pct", 0.0) or 0.0) if mc_result is not None else 0.0
        if _drag_total > 0:
            assumptions = (
                f"<b>SUPUESTOS APLICADOS:</b> Las proyecciones incluyen una capa de "
                f"<i>drags económicos</i> de aproximadamente {_drag_total:.2f}% anual "
                f"(fees, impuesto a dividendos, costo de rebalanceo y/o buffer AR) sobre "
                f"el crecimiento, además de los ajustes conservadores del motor (+10% "
                f"volatilidad, −20% retorno histórico). Los datos provienen de historia de "
                f"precios pura (yfinance). No se modelan tax lots ni inflación estocástica."
            )
        else:
            assumptions = (
                "<b>SUPUESTOS APLICADOS:</b> Salvo indicación contraria, las proyecciones "
                "asumen <b>0% de fees, 0% de impuestos sobre dividendos y 0% de costo de "
                "rebalanceo</b>, y no modelan fricciones locales argentinas (cepo, brecha, "
                "diferencial de inflación). Parten de historia de precios pura (yfinance) con "
                "ajustes conservadores (+10% volatilidad, −20% retorno histórico). Los números "
                "reales tras costos serán menores."
            )
        return [
            Spacer(1, 0.5 * cm),
            HRFlowable(width="100%", thickness=0.5, color=_DGRAY),
            Spacer(1, 0.2 * cm),
            Paragraph(assumptions, st["small"]),
            Spacer(1, 0.2 * cm),
            Paragraph(
                "<b>AVISO LEGAL:</b> Este reporte es generado automáticamente con fines "
                "informativos y educativos únicamente. No constituye asesoramiento financiero, "
                "recomendación de inversión, ni oferta de compra o venta de valores. "
                "Rendimientos pasados no garantizan resultados futuros. Las proyecciones "
                "Monte Carlo son simulaciones estadísticas, no predicciones. "
                "Consultá siempre con un asesor financiero autorizado antes de tomar "
                "decisiones de inversión. Retirement Advisor no asume responsabilidad "
                "por decisiones tomadas en base a este reporte.",
                st["small"],
            ),
        ]

    # ---------------------------------------------------------------- #
    #  Charts                                                           #
    # ---------------------------------------------------------------- #

    def _donut_chart(self, opt_result):
        threshold = 1.5
        labels, sizes = [], []
        for t in opt_result.tickers:
            if t.weight_pct >= threshold:
                labels.append(t.symbol)
                sizes.append(t.weight_pct)

        other = sum(t.weight_pct for t in opt_result.tickers if t.weight_pct < threshold)
        if other > 0:
            labels.append("Otros")
            sizes.append(other)

        if not sizes:
            sizes = [100]
            labels = ["Sin datos"]

        cmap = plt.colormaps.get_cmap("tab20")
        clrs = [cmap(i / len(sizes)) for i in range(len(sizes))]

        fig, ax = plt.subplots(figsize=(9, 5))
        wedges, texts, autotexts = ax.pie(
            sizes, labels=None, autopct=lambda p: f"{p:.1f}%" if p >= 3 else "",
            startangle=90, colors=clrs, pctdistance=0.75,
            wedgeprops={"width": 0.55, "edgecolor": "white", "linewidth": 1.5},
        )
        for at in autotexts:
            at.set_fontsize(7)
            at.set_color("white")
            at.set_fontweight("bold")

        ax.legend(
            wedges, [f"{l} {s:.1f}%" for l, s in zip(labels, sizes)],
            loc="center left", bbox_to_anchor=(1, 0, 0.5, 1),
            fontsize=7.5, frameon=False,
        )
        ax.set_title("Asignación del portafolio", fontsize=11, fontweight="bold",
                     color="#1B3A6B", pad=12)
        fig.tight_layout()
        return _chart_to_image(fig, width_cm=16, height_cm=7)

    def _fan_chart(self, mc_result, mc_params):
        horizon = mc_params.get("horizon_years", len(mc_result.fan_paths.get(50, {})))
        years = list(range(0, horizon + 1))
        initial = mc_params.get("initial_value", 0)

        # fan_paths: {percentile: {year: value}}
        fp = mc_result.fan_paths

        fig, ax = plt.subplots(figsize=(12, 5))

        # Shaded bands
        bands = [(5, 95, "#1B3A6B", 0.10), (10, 90, "#17A2B8", 0.14), (25, 75, "#28A745", 0.20)]
        labels_added = set()
        for lo, hi, color, alpha in bands:
            if lo in fp and hi in fp:
                lo_vals = [fp[lo].get(y, 0) for y in range(1, horizon + 1)]
                hi_vals = [fp[hi].get(y, 0) for y in range(1, horizon + 1)]
                band_label = f"P{lo}–P{hi}" if (lo, hi) not in labels_added else None
                ax.fill_between(range(1, horizon + 1), lo_vals, hi_vals,
                                alpha=alpha, color=color, label=band_label)
                labels_added.add((lo, hi))

        # Median line
        if 50 in fp:
            med_vals = [initial] + [fp[50].get(y, 0) for y in range(1, horizon + 1)]
            ax.plot(years, med_vals, color="#1B3A6B", linewidth=2.5,
                    label="Mediana (P50)", zorder=5)

        # P10 line
        if 10 in fp:
            p10_vals = [initial] + [fp[10].get(y, 0) for y in range(1, horizon + 1)]
            ax.plot(years, p10_vals, color="#DC3545", linewidth=1.5,
                    linestyle="--", label="Pesimista (P10)", zorder=4)

        # Initial value line
        if initial > 0:
            ax.axhline(initial, color="#6C757D", linewidth=1, linestyle=":",
                       label=f"Capital inicial ${initial:,.0f}", alpha=0.7)

        ax.yaxis.set_major_formatter(mticker.FuncFormatter(
            lambda v, _: f"${v/1e6:.1f}M" if v >= 1e6 else f"${v/1e3:.0f}K"))
        ax.set_xlabel("Años", fontsize=9)
        ax.set_ylabel("Valor del portafolio", fontsize=9)
        ax.set_title("Proyección Monte Carlo — Fan Chart", fontsize=11,
                     fontweight="bold", color="#1B3A6B")
        ax.legend(fontsize=8, loc="upper left")
        ax.grid(axis="y", alpha=0.3, linestyle="--")
        ax.set_xlim(0, horizon)
        fig.tight_layout()
        return _chart_to_image(fig, width_cm=16, height_cm=6)

    # ---------------------------------------------------------------- #
    #  AI Narrative                                                     #
    # ---------------------------------------------------------------- #

    def _get_narrative(self, ai_config, opt_result, mc_result, mc_params) -> Optional[str]:
        if ai_config is None or not getattr(ai_config, "enabled", False):
            return None
        if opt_result is None or mc_result is None:
            return None

        try:
            from analysis.ai_analyzer import AIAnalyzer
            analyzer = AIAnalyzer(ai_config)
            context = {
                "profile_name":    mc_params.get("profile_name", "Moderado"),
                "tickers":         [t.symbol for t in opt_result.tickers],
                "weights":         [t.weight_pct / 100 for t in opt_result.tickers],
                "expected_return": opt_result.expected_return_pct,
                "volatility":      opt_result.volatility_pct,
                "sharpe":          opt_result.sharpe_ratio,
                "dividend_yield":  opt_result.dividend_yield_pct,
                "horizon_years":   mc_params.get("horizon_years", 15),
                "initial_value":   mc_params.get("initial_value", 100_000),
                "annual_withdrawal": mc_params.get("annual_withdrawal", 0),
                "inflation_rate":  mc_params.get("inflation_rate") or 3.0,
                "median_terminal": mc_result.median_terminal,
                "p10_terminal":    mc_result.p10_terminal,
                "p90_terminal":    mc_result.p90_terminal,
                "prob_ruin":       mc_result.prob_ruin_pct,
                "prob_target":     mc_result.prob_achieve_target_pct,
                "target_value":    mc_params.get("target_value", 0),
            }
            return analyzer.generate_long_term_narrative(context)
        except Exception as e:
            logger.warning(f"AI narrative for PDF failed: {e}")
            return None
