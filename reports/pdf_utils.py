"""Shared PDF helpers for reportlab + matplotlib charts.

Used by both the monthly alert reporter (``alerts.reporter``) and the
investment-plan PDF (``reports.investment_plan``) so chart embedding and
page chrome stay consistent and are maintained in one place.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Callable, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import Image

# Brand colours shared by PDF generators (header/footer chrome).
_NAVY = colors.HexColor("#1B3A6B")
_WHITE = colors.white
_DGRAY = colors.HexColor("#6C757D")

_DEFAULT_FOOTER_LEFT = (
    "Este reporte es orientativo y no constituye asesoramiento financiero."
)


@dataclass(frozen=True)
class PdfBrand:
    """Colours for the shared header/footer chrome."""

    navy: object = _NAVY
    white: object = _WHITE
    dgray: object = _DGRAY


def chart_to_image(fig, width_cm: float = 16, height_cm: float = 7) -> Image:
    """Render a matplotlib figure to a reportlab ``Image`` flowable."""
    buf = io.BytesIO()
    fig.savefig(
        buf,
        format="png",
        dpi=150,
        bbox_inches="tight",
        facecolor="white",
        edgecolor="none",
    )
    buf.seek(0)
    plt.close(fig)
    return Image(buf, width=width_cm * cm, height=height_cm * cm)


def make_header_footer(
    report_date: str,
    title: str,
    *,
    right_text: Optional[str] = None,
    footer_left: str = _DEFAULT_FOOTER_LEFT,
    header_font_size: float = 11,
    header_title_y_cm: float = 1.0,
    brand: Optional[PdfBrand] = None,
) -> Callable:
    """Return a reportlab ``onPage`` callback with a navy header bar + footer.

    Parameters mirror the small differences between the alert report and the
    investment-plan PDF (title, right-side text, font size, vertical offset,
    footer copy) so callers only pass content — not geometry.
    """
    b = brand or PdfBrand()
    right = right_text if right_text is not None else report_date

    def _on_page(canvas, doc):
        canvas.saveState()
        w, h = A4
        # Header bar
        canvas.setFillColor(b.navy)
        canvas.rect(0, h - 1.5 * cm, w, 1.5 * cm, fill=1, stroke=0)
        canvas.setFont("Helvetica-Bold", header_font_size)
        canvas.setFillColor(b.white)
        canvas.drawString(1.5 * cm, h - header_title_y_cm * cm, title)
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(w - 1.5 * cm, h - header_title_y_cm * cm, right)
        # Footer line
        canvas.setStrokeColor(b.dgray)
        canvas.line(1.5 * cm, 1.2 * cm, w - 1.5 * cm, 1.2 * cm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(b.dgray)
        canvas.drawString(1.5 * cm, 0.7 * cm, footer_left)
        canvas.drawRightString(w - 1.5 * cm, 0.7 * cm, f"Pág. {doc.page}")
        canvas.restoreState()

    return _on_page
