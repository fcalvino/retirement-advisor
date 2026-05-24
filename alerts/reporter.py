"""
PDF Report Generator — monthly/quarterly retirement advisor report.

Uses reportlab SimpleDocTemplate (Platypus) for layout and matplotlib
for embedded charts. No system dependencies required.

Usage:
    from alerts.reporter import ReportGenerator
    path = ReportGenerator().generate(scored_tickers, portfolio_positions)
    # → "reports/retirement_report_2026-05.pdf"
"""

from __future__ import annotations

import io
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd
from loguru import logger

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from config import REPORT

# ------------------------------------------------------------------ #
#  Brand colours                                                       #
# ------------------------------------------------------------------ #
_NAVY   = colors.HexColor("#1B3A6B")
_TEAL   = colors.HexColor("#17A2B8")
_GREEN  = colors.HexColor("#28A745")
_RED    = colors.HexColor("#DC3545")
_AMBER  = colors.HexColor("#FFC107")
_LGRAY  = colors.HexColor("#F5F5F5")
_DGRAY  = colors.HexColor("#6C757D")
_WHITE  = colors.white
_BLACK  = colors.black


def _styles():
    base = getSampleStyleSheet()
    styles = {
        "h1": ParagraphStyle("h1", parent=base["Heading1"],
                              fontSize=22, textColor=_NAVY, spaceAfter=6,
                              fontName="Helvetica-Bold"),
        "h2": ParagraphStyle("h2", parent=base["Heading2"],
                              fontSize=14, textColor=_NAVY, spaceBefore=14,
                              spaceAfter=4, fontName="Helvetica-Bold"),
        "h3": ParagraphStyle("h3", parent=base["Heading3"],
                              fontSize=11, textColor=_TEAL, spaceBefore=8,
                              spaceAfter=2, fontName="Helvetica-Bold"),
        "body": ParagraphStyle("body", parent=base["Normal"],
                               fontSize=9, leading=13, fontName="Helvetica"),
        "small": ParagraphStyle("small", parent=base["Normal"],
                                fontSize=7.5, textColor=_DGRAY,
                                fontName="Helvetica"),
        "caption": ParagraphStyle("caption", parent=base["Normal"],
                                  fontSize=8, textColor=_DGRAY, alignment=TA_CENTER,
                                  fontName="Helvetica-Oblique"),
        "right": ParagraphStyle("right", parent=base["Normal"],
                                fontSize=9, alignment=TA_RIGHT, fontName="Helvetica"),
    }
    return styles


def _chart_to_image(fig, width_cm: float = 16, height_cm: float = 7) -> Image:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor="white", edgecolor="none")
    buf.seek(0)
    plt.close(fig)
    return Image(buf, width=width_cm * cm, height=height_cm * cm)


def _score_color(score: float) -> colors.Color:
    if score >= 75:
        return _GREEN
    if score >= 55:
        return _AMBER
    return _RED


def _signal_color(signal: str) -> colors.Color:
    s = signal.upper()
    if "STRONG_BUY" in s or "STRONG BUY" in s:
        return _GREEN
    if "BUY" in s:
        return colors.HexColor("#5CB85C")
    if "HOLD" in s:
        return _AMBER
    return _RED


# ------------------------------------------------------------------ #
#  Header / Footer callbacks                                           #
# ------------------------------------------------------------------ #

def _make_header_footer(report_date: str, title: str):
    def _on_page(canvas, doc):
        canvas.saveState()
        w, h = A4
        # Header bar
        canvas.setFillColor(_NAVY)
        canvas.rect(0, h - 1.5 * cm, w, 1.5 * cm, fill=1, stroke=0)
        canvas.setFont("Helvetica-Bold", 11)
        canvas.setFillColor(_WHITE)
        canvas.drawString(1.5 * cm, h - 1.0 * cm, title)
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(w - 1.5 * cm, h - 1.0 * cm, report_date)
        # Footer line
        canvas.setStrokeColor(_DGRAY)
        canvas.line(1.5 * cm, 1.2 * cm, w - 1.5 * cm, 1.2 * cm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(_DGRAY)
        canvas.drawString(1.5 * cm, 0.7 * cm,
                          "Este reporte es orientativo y no constituye asesoramiento financiero.")
        canvas.drawRightString(w - 1.5 * cm, 0.7 * cm, f"Pág. {doc.page}")
        canvas.restoreState()
    return _on_page


# ------------------------------------------------------------------ #
#  ReportGenerator                                                     #
# ------------------------------------------------------------------ #

class ReportGenerator:
    """Generates a professional PDF retirement report."""

    def __init__(self) -> None:
        out_dir = Path(REPORT.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        self.out_dir = out_dir

    def generate(
        self,
        scored_tickers: List[dict],
        portfolio_positions: Optional[List[dict]] = None,
        period: str = "",
    ) -> str:
        """
        Build the PDF and return its file path.

        scored_tickers: list of dicts with symbol, adjusted_score, signal,
                        moat_classification, dividend_yield, sector, company_name
        portfolio_positions: list of dicts with symbol, quantity, avg_price,
                             current_price (optional, from Portfolio page)
        period: label like "Mayo 2026" — defaults to current month
        """
        if not period:
            period = datetime.now().strftime("%B %Y").capitalize()

        report_date = datetime.now().strftime("%d/%m/%Y %H:%M")
        filename    = self.out_dir / f"retirement_report_{datetime.now().strftime('%Y-%m')}.pdf"
        title       = f"Retirement Advisor — Reporte {period}"

        st = _styles()
        doc = SimpleDocTemplate(
            str(filename),
            pagesize=A4,
            leftMargin=1.5 * cm,
            rightMargin=1.5 * cm,
            topMargin=2.2 * cm,
            bottomMargin=2.0 * cm,
        )

        story = []
        story += self._cover(st, title, period, report_date, scored_tickers)
        story.append(PageBreak())
        story += self._section_score_leaderboard(st, scored_tickers)
        story += self._section_opportunities(st, scored_tickers)
        story += self._section_risk_alerts(st, scored_tickers)
        if portfolio_positions:
            story += self._section_portfolio(st, portfolio_positions, scored_tickers)
        story += self._section_full_table(st, scored_tickers)
        story += self._section_disclaimer(st)

        on_page = _make_header_footer(report_date, title)
        doc.build(story, onFirstPage=on_page, onLaterPages=on_page)

        logger.info(f"Report generated: {filename}")
        return str(filename)

    # ------------------------------------------------------------------ #
    #  Sections                                                            #
    # ------------------------------------------------------------------ #

    def _cover(self, st, title, period, report_date, tickers):
        top_signals   = [t for t in tickers if "BUY" in t.get("signal", "").upper()]
        sell_signals  = [t for t in tickers if "SELL" in t.get("signal", "").upper()]
        avg_score     = (sum(t.get("adjusted_score", 0) for t in tickers) / len(tickers)
                         if tickers else 0)

        elements = [
            Spacer(1, 1.0 * cm),
            Paragraph(f"📊 Retirement Advisor", ParagraphStyle(
                "cover_title", fontSize=28, textColor=_NAVY,
                fontName="Helvetica-Bold", alignment=TA_CENTER, spaceAfter=4)),
            Paragraph(f"Reporte Periódico — {period}", ParagraphStyle(
                "cover_sub", fontSize=16, textColor=_TEAL,
                fontName="Helvetica", alignment=TA_CENTER, spaceAfter=20)),
            HRFlowable(width="100%", thickness=2, color=_NAVY, spaceAfter=16),
            Spacer(1, 0.5 * cm),
        ]

        # KPI row
        kpi_data = [
            ["Tickers analizados", "Señales BUY/STRONG", "Señales SELL", "Score promedio"],
            [str(len(tickers)), str(len(top_signals)), str(len(sell_signals)),
             f"{avg_score:.1f}/100"],
        ]
        kpi_table = Table(kpi_data, colWidths=[4.3 * cm] * 4)
        kpi_table.setStyle(TableStyle([
            ("BACKGROUND",  (0, 0), (-1, 0), _NAVY),
            ("TEXTCOLOR",   (0, 0), (-1, 0), _WHITE),
            ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",    (0, 0), (-1, 0), 9),
            ("FONTNAME",    (0, 1), (-1, 1), "Helvetica-Bold"),
            ("FONTSIZE",    (0, 1), (-1, 1), 18),
            ("ALIGN",       (0, 0), (-1, -1), "CENTER"),
            ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, 1), [_LGRAY]),
            ("GRID",        (0, 0), (-1, -1), 0.5, _DGRAY),
            ("TOPPADDING",  (0, 1), (-1, 1), 10),
            ("BOTTOMPADDING", (0, 1), (-1, 1), 10),
        ]))
        elements.append(kpi_table)
        elements.append(Spacer(1, 0.8 * cm))

        # Score distribution chart
        if tickers and REPORT.include_charts:
            elements.append(self._score_dist_chart(tickers))
            elements.append(Paragraph(
                "Distribución de Score Ajustado — universo completo",
                st["caption"]))
            elements.append(Spacer(1, 0.3 * cm))

        elements.append(Paragraph(
            f"Generado el {report_date} · Datos: yfinance · Todos los valores en USD",
            st["small"]))
        return elements

    def _section_score_leaderboard(self, st, tickers):
        sorted_t = sorted(tickers, key=lambda t: t.get("adjusted_score", 0), reverse=True)
        top = sorted_t[:REPORT.top_n_opportunities]

        elements = [
            Paragraph("Top oportunidades — Score Ajustado", st["h2"]),
            HRFlowable(width="100%", thickness=1, color=_TEAL, spaceAfter=8),
        ]

        headers = ["#", "Ticker", "Empresa", "Score", "Señal", "Div %", "Moat", "Sector"]
        col_w   = [0.6, 1.4, 4.0, 1.2, 1.8, 1.1, 1.8, 3.0]
        col_w   = [w * cm for w in col_w]

        rows = [headers]
        style_cmds = [
            ("BACKGROUND",  (0, 0), (-1, 0), _NAVY),
            ("TEXTCOLOR",   (0, 0), (-1, 0), _WHITE),
            ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",    (0, 0), (-1, -1), 8),
            ("ALIGN",       (0, 0), (-1, -1), "CENTER"),
            ("ALIGN",       (2, 1), (2, -1), "LEFT"),
            ("ALIGN",       (7, 1), (7, -1), "LEFT"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [_WHITE, _LGRAY]),
            ("GRID",        (0, 0), (-1, -1), 0.3, _DGRAY),
            ("TOPPADDING",  (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]

        for i, t in enumerate(top, 1):
            score  = t.get("adjusted_score", 0)
            signal = t.get("signal", "—")
            div    = t.get("dividend_yield", 0) or 0
            moat   = t.get("moat_classification", "None")
            row_idx = i
            rows.append([
                str(i),
                t.get("symbol", ""),
                (t.get("company_name", "") or "")[:30],
                f"{score:.1f}",
                signal,
                f"{div:.2f}%",
                moat,
                (t.get("sector", "") or "")[:20],
            ])
            # Color the score cell
            style_cmds.append(("TEXTCOLOR", (3, row_idx), (3, row_idx), _score_color(score)))
            style_cmds.append(("FONTNAME",  (3, row_idx), (3, row_idx), "Helvetica-Bold"))
            style_cmds.append(("TEXTCOLOR", (4, row_idx), (4, row_idx), _signal_color(signal)))
            style_cmds.append(("FONTNAME",  (4, row_idx), (4, row_idx), "Helvetica-Bold"))

        tbl = Table(rows, colWidths=col_w)
        tbl.setStyle(TableStyle(style_cmds))
        elements.append(tbl)
        elements.append(Spacer(1, 0.4 * cm))
        return elements

    def _section_opportunities(self, st, tickers):
        buys = [t for t in tickers if "BUY" in t.get("signal", "").upper()]
        if not buys:
            return []

        elements = [
            Paragraph("Señales de compra activas", st["h2"]),
            HRFlowable(width="100%", thickness=1, color=_GREEN, spaceAfter=6),
        ]
        for t in sorted(buys, key=lambda x: x.get("adjusted_score", 0), reverse=True):
            signal = t.get("signal", "BUY")
            emoji  = "🟢" if "STRONG" in signal.upper() else "🔵"
            div    = t.get("dividend_yield", 0) or 0
            elements.append(Paragraph(
                f"{emoji} <b>{t.get('symbol')}</b> — {t.get('company_name', '')[:40]} · "
                f"Score: <b>{t.get('adjusted_score', 0):.1f}</b> · "
                f"Señal: <b>{signal}</b> · Div: {div:.2f}% · "
                f"Moat: {t.get('moat_classification', 'None')}",
                st["body"],
            ))
        elements.append(Spacer(1, 0.3 * cm))
        return elements

    def _section_risk_alerts(self, st, tickers):
        sells = [t for t in tickers if "SELL" in t.get("signal", "").upper()]
        if not sells:
            return []

        elements = [
            Paragraph("Señales de riesgo — SELL", st["h2"]),
            HRFlowable(width="100%", thickness=1, color=_RED, spaceAfter=6),
        ]
        for t in sells:
            elements.append(Paragraph(
                f"🔴 <b>{t.get('symbol')}</b> — {t.get('company_name', '')[:40]} · "
                f"Score: <b>{t.get('adjusted_score', 0):.1f}</b> · "
                f"Moat: {t.get('moat_classification', 'None')}",
                st["body"],
            ))
        elements.append(Spacer(1, 0.3 * cm))
        return elements

    def _section_portfolio(self, st, positions, scored_map_list):
        scored_map = {t["symbol"]: t for t in scored_map_list}
        elements = [
            Paragraph("Portafolio actual", st["h2"]),
            HRFlowable(width="100%", thickness=1, color=_TEAL, spaceAfter=8),
        ]
        headers = ["Ticker", "Cantidad", "P. Promedio", "P. Actual", "P&L %", "Señal"]
        col_w   = [1.5, 1.5, 2.0, 2.0, 1.5, 2.0]
        col_w   = [w * cm for w in col_w]
        rows = [headers]
        for pos in positions:
            sym   = pos.get("symbol", "")
            qty   = pos.get("quantity", 0)
            avg   = pos.get("avg_price", 0)
            cur   = pos.get("current_price", 0)
            pnl   = ((cur - avg) / avg * 100) if avg else 0
            sig   = scored_map.get(sym, {}).get("signal", "—")
            rows.append([sym, str(qty), f"${avg:.2f}", f"${cur:.2f}",
                         f"{pnl:+.1f}%", sig])
        tbl = Table(rows, colWidths=col_w)
        tbl.setStyle(TableStyle([
            ("BACKGROUND",  (0, 0), (-1, 0), _NAVY),
            ("TEXTCOLOR",   (0, 0), (-1, 0), _WHITE),
            ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",    (0, 0), (-1, -1), 8),
            ("ALIGN",       (0, 0), (-1, -1), "CENTER"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [_WHITE, _LGRAY]),
            ("GRID",        (0, 0), (-1, -1), 0.3, _DGRAY),
        ]))
        elements.append(tbl)
        elements.append(Spacer(1, 0.4 * cm))
        return elements

    def _section_full_table(self, st, tickers):
        elements = [
            PageBreak(),
            Paragraph("Universo completo — todos los tickers", st["h2"]),
            HRFlowable(width="100%", thickness=1, color=_TEAL, spaceAfter=8),
        ]
        headers = ["Ticker", "Empresa", "Score", "Base", "Moat bonus", "Señal",
                   "Div %", "Moat", "Sector"]
        col_w   = [1.3, 3.8, 1.0, 1.0, 1.2, 1.5, 1.0, 1.5, 2.7]
        col_w   = [w * cm for w in col_w]

        rows = [headers]
        style_cmds = [
            ("BACKGROUND",  (0, 0), (-1, 0), _NAVY),
            ("TEXTCOLOR",   (0, 0), (-1, 0), _WHITE),
            ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",    (0, 0), (-1, -1), 7),
            ("ALIGN",       (0, 0), (-1, -1), "CENTER"),
            ("ALIGN",       (1, 1), (1, -1), "LEFT"),
            ("ALIGN",       (8, 1), (8, -1), "LEFT"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [_WHITE, _LGRAY]),
            ("GRID",        (0, 0), (-1, -1), 0.2, _DGRAY),
            ("TOPPADDING",  (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]
        sorted_t = sorted(tickers, key=lambda t: t.get("adjusted_score", 0), reverse=True)
        for ri, t in enumerate(sorted_t, 1):
            score      = t.get("adjusted_score", 0)
            base       = t.get("total_score", t.get("fundamental_score", 0))
            moat_bonus = t.get("moat_bonus", 0)
            signal     = t.get("signal", "—")
            div        = t.get("dividend_yield", 0) or 0
            rows.append([
                t.get("symbol", ""),
                (t.get("company_name", "") or "")[:28],
                f"{score:.0f}",
                f"{base:.0f}",
                f"+{moat_bonus:.1f}" if moat_bonus else "—",
                signal,
                f"{div:.2f}%",
                t.get("moat_classification", "None"),
                (t.get("sector", "") or "")[:20],
            ])
            style_cmds.append(("TEXTCOLOR", (2, ri), (2, ri), _score_color(score)))
            style_cmds.append(("FONTNAME",  (2, ri), (2, ri), "Helvetica-Bold"))
            style_cmds.append(("TEXTCOLOR", (5, ri), (5, ri), _signal_color(signal)))

        tbl = Table(rows, colWidths=col_w)
        tbl.setStyle(TableStyle(style_cmds))
        elements.append(tbl)
        return elements

    def _section_disclaimer(self, st):
        return [
            Spacer(1, 0.5 * cm),
            HRFlowable(width="100%", thickness=0.5, color=_DGRAY),
            Spacer(1, 0.2 * cm),
            Paragraph(
                "⚠️ <b>Aviso legal:</b> Este reporte es generado automáticamente con fines "
                "informativos y educativos. No constituye asesoramiento financiero, "
                "recomendación de inversión, ni oferta de compra/venta de valores. "
                "Consultá siempre con un asesor financiero autorizado antes de tomar "
                "decisiones de inversión. Rendimientos pasados no garantizan resultados futuros.",
                st["small"],
            ),
        ]

    # ------------------------------------------------------------------ #
    #  Charts                                                              #
    # ------------------------------------------------------------------ #

    def _score_dist_chart(self, tickers) -> Image:
        scores = [t.get("adjusted_score", 0) for t in tickers if t.get("adjusted_score")]
        fig, ax = plt.subplots(figsize=(10, 3.5))
        ax.hist(scores, bins=20, color="#1B3A6B", alpha=0.8, edgecolor="white", linewidth=0.5)
        ax.axvline(75, color="#28A745", linestyle="--", linewidth=1.5, label="Strong Buy ≥75")
        ax.axvline(60, color="#17A2B8", linestyle="--", linewidth=1.5, label="Buy ≥60")
        ax.axvline(45, color="#FFC107", linestyle="--", linewidth=1.5, label="Hold ≥45")
        ax.set_xlabel("Score Ajustado", fontsize=9)
        ax.set_ylabel("Nº de tickers", fontsize=9)
        ax.set_title("Distribución de scores — universo completo", fontsize=10)
        ax.legend(fontsize=8)
        ax.grid(axis="y", alpha=0.3)
        fig.tight_layout()
        return _chart_to_image(fig, width_cm=15, height_cm=5)
