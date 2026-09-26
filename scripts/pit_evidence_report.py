#!/usr/bin/env python3
"""
PIT-2 — the evidence the point-in-time backtest produced, as a markdown report.

Reads every ``synthetic_recommendation`` row (``synthetic_backtest_store``) and
writes what ``analysis/synthetic_evidence.summarize`` makes of it: per F-Score
group (the engine's cuts), the mean excess over one year with its 95 % band,
the share that beat the benchmark, the outcome statuses, and the strong − weak
comparison per cutoff. Read-only: it never writes to the database.

It does not recommend a recalibration — that is U5-1b, a human decision.

Run from project root (after point_in_time_backtest.py and score_synthetic_outcomes.py):
    ./venv/bin/python3 scripts/pit_evidence_report.py --out docs/PIT2_EVIDENCIA_2026-09.md
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_sys_root = Path(__file__).resolve().parent.parent
if str(_sys_root) not in sys.path:
    sys.path.insert(0, str(_sys_root))
from bootstrap import ensure_project_root  # noqa: E402

ensure_project_root()

from analysis.synthetic_evidence import GROUPS, summarize  # noqa: E402
from config import PIOTROSKI, SYNTHETIC_BACKTEST, TRACK_RECORD  # noqa: E402
from data.clock import utc_now  # noqa: E402

SURVIVORSHIP_WARNING = (
    "**Sesgo de supervivencia.** Los tickers salen de universos curados hoy y el mapa "
    "ticker→CIK de la SEC es el vigente: una empresa que quebró o fue absorbida antes de hoy "
    "casi nunca está en la muestra. Los deslistados que sí entran quedan marcados "
    "(`delisted_before_horizon`) y sin outcome. Sólo filers de la SEC (10-K): los listados "
    "locales, ADRs 20-F, ETFs y cripto de los universos no tienen fila."
)


def _fmt(value: Optional[float], suffix: str = "") -> str:
    return "—" if value is None else f"{value:+.2f}{suffix}"


def _band(mean: Optional[float], band: Optional[float]) -> str:
    if mean is None:
        return "—"
    return f"{mean:+.2f} % ± {band:.2f}" if band is not None else f"{mean:+.2f} % (n<2, sin banda)"


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:
        return "desconocido"


def render_markdown(summary: Dict[str, Any], *, generated_at: str, sha: str,
                    universes: List[str], cutoffs: List[str]) -> str:
    """Pure: the summary and its provenance in, the markdown out."""
    groups = summary["groups"]
    cmp_ = summary["strong_minus_weak"]
    lines = [
        "# PIT-2 — Evidencia point-in-time del Piotroski (1 año)",
        "",
        f"> Generado {generated_at} desde `{sha}` con `scripts/pit_evidence_report.py`. "
        "Auditoría histórica: no se actualiza, se regenera.",
        "",
        f"- **Universos:** {', '.join(universes)}",
        f"- **Cortes con filas:** {len(cutoffs)}"
        + (f" ({cutoffs[0]} → {cutoffs[-1]})" if cutoffs else ""),
        f"- **Filas:** {summary['n_rows']}",
        f"- **Horizonte:** {SYNTHETIC_BACKTEST.horizon_days} días calendario; exceso contra "
        f"`{TRACK_RECORD.benchmark}` (cierre ajustado, retorno total)",
        f"- **Grupos (cortes del motor):** fuerte ≥ {PIOTROSKI.strong_threshold} "
        f"(+{PIOTROSKI.bonus_strong:.0f} pts), aceptable ≥ {PIOTROSKI.good_threshold} "
        f"(+{PIOTROSKI.bonus_good:.0f}), débil < {PIOTROSKI.good_threshold}",
        "",
        SURVIVORSHIP_WARNING,
        "",
        "## Por grupo",
        "",
        "| Grupo | Filas | Con exceso | Exceso medio ± banda 95 % | % que le ganó al benchmark |",
        "|---|---:|---:|---|---:|",
    ]
    for g in GROUPS:
        row = groups[g]
        pct = "—" if row["pct_positive"] is None else f"{row['pct_positive']:.1f} %"
        lines.append(f"| {g} | {row['n']} | {row['n_excess']} | {_band(row['mean'], row['band'])} | {pct} |")
    lines += [
        "",
        "Las filas de un mismo corte comparten el mercado de ese año: estas bandas, "
        "calculadas por fila, son **más angostas de lo que la muestra justifica**. "
        "La comparación que cuenta es la de abajo.",
        "",
        "## Fuerte − débil, por corte",
        "",
        f"Unidad: el corte (media del grupo fuerte − media del débil en cada fecha). "
        f"Cortes con los dos grupos: **{cmp_['n_cutoffs']}**. "
        f"Diferencia media: **{_band(cmp_['mean'], cmp_['band'])}**.",
        "",
        "Cortes a menos de un horizonte de distancia comparten parte del mismo año de "
        "mercado (con la grilla por defecto, cada 6 meses sobre 1 año, medio año): tampoco son "
        "del todo independientes, así que esta banda también es algo optimista. Un veredicto "
        "«inconcluso» con esta banda lo sería con más razón con la honesta.",
        "",
        f"**Veredicto: {summary['verdict']}.**",
        "",
    ]
    if cmp_["cutoffs"]:
        lines += ["| Corte | Fuerte − débil |", "|---|---:|"]
        lines += [f"| {c} | {_fmt(d, ' pp')} |" for c, d in zip(cmp_["cutoffs"], cmp_["diffs"])]
        lines.append("")
    lines += ["## Estado de los outcomes", "", "| Estado | Filas |", "|---|---:|"]
    lines += [f"| `{k}` | {v} |" for k, v in sorted(summary["status_counts"].items())]
    lines += [
        "",
        "## Qué no dice este reporte",
        "",
        "- No recalibra nada: mover `PiotroskiConfig.strong_threshold`/`bonus_strong` es U5-1b, "
        "una decisión humana con esta tabla sobre la mesa.",
        "- La mitad «moat» de U5-1b queda fuera: reconstruir el tramo IA del pasado con un modelo "
        "que ya sabe qué pasó después es hindsight bias.",
        "",
    ]
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", help="Markdown file to write (default: stdout)")
    p.add_argument(
        "--universes",
        default=",".join(SYNTHETIC_BACKTEST.pit2_universes),
        help="Universes the rows came from, for the header only",
    )
    args = p.parse_args(argv)

    from analysis.synthetic_backtest import synthetic_backtest_store

    rows = synthetic_backtest_store.get_all()
    text = render_markdown(
        summarize(rows),
        generated_at=utc_now().strftime("%Y-%m-%d %H:%M UTC"),
        sha=_git_sha(),
        universes=[u.strip() for u in args.universes.split(",") if u.strip()],
        cutoffs=sorted({r.as_of for r in rows}),
    )
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
