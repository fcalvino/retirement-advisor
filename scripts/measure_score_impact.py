#!/usr/bin/env python3
"""Offline score-impact harness — re-scores the cached universe, no network.

Why this exists: the 2026-08-22 data-inventory audit found four defects that
change scores across the board (missing metrics paying points, a quarterly YoY
figure used as a CAGR and as Graham's `g`, the leverage guard skipped exactly on
negative-equity companies, and a dividend streak that the in-progress calendar
year always truncates). Fixing them moves numbers, and thresholds like
``STRATEGY.strong_buy_score`` were calibrated on the old distribution. A fix
whose effect nobody measured is a fix nobody can argue about, so:

    ./venv/bin/python3 scripts/measure_score_impact.py --baseline before.json
    # ... apply a fix ...
    ./venv/bin/python3 scripts/measure_score_impact.py --compare before.json

**It never goes to the network.** Two guards make that true:

  * only tickers whose ``info`` *and* 10y weekly ``history`` are already cached
    are scored — everything else is skipped and counted;
  * the cache TTL is raised in-process (the entries on disk are older than the
    24h default) and ``MULTI_SOURCE.attach_in_pipeline`` is turned off, because
    the cross-source badge downloads SEC EDGAR companyfacts per ticker.

Both mutations are in-memory only: nothing on disk changes.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _make_offline() -> None:
    """Serve everything from the existing cache; disable networked side-trips."""
    import data.cache as cache_module
    from config import MULTI_SOURCE

    cache_module.cache.ttl = timedelta(days=3650)
    MULTI_SOURCE.attach_in_pipeline = False


def cached_symbols() -> List[str]:
    """Tickers with both ``info`` and the 10y weekly history already cached."""
    from data.cache import cache

    info = {k.split(":", 1)[1] for k in cache.keys_with_prefix("info:")}
    hist = {k.split(":")[1] for k in cache.keys_with_prefix("history:") if k.endswith(":10y:1wk")}
    return sorted(info & hist)


# --------------------------------------------------------------------------- #
#  Measurement                                                                #
# --------------------------------------------------------------------------- #

def measure_symbol(symbol: str) -> Optional[Dict[str, Any]]:
    """Score one ticker end-to-end (rule-based path — no AI, no network)."""
    from analysis.strategy import full_analysis

    try:
        fund, tech, decision = full_analysis(symbol, ai_config=None)
    except Exception as exc:  # pragma: no cover - defensive, reported not raised
        print(f"  ! {symbol}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None

    dq = fund.data_quality or {}
    return {
        "symbol": symbol,
        "sector": fund.sector,
        "asset_class": fund.asset_class,
        "total_score": round(fund.total_score, 1),
        "adjusted_score": round(fund.adjusted_score, 1),
        "raw_adjusted_score": round(fund.raw_adjusted_score, 1),
        "profitability": round(fund.profitability_score, 1),
        "health": round(fund.health_score, 1),
        "valuation": round(fund.valuation_score, 1),
        "growth": round(fund.growth_score, 1),
        "dividend": round(fund.dividend_score, 1),
        "graham_value": fund.graham_value,
        "margin_of_safety_pct": fund.margin_of_safety_pct,
        "is_value_stock": fund.is_value_stock(),
        "eps_cagr": fund.eps_cagr_5y,
        "eps_cagr_years": fund.eps_cagr_years,
        "revenue_cagr": fund.revenue_cagr_5y,
        "dividend_yield": fund.dividend_yield,
        "debt_equity": fund.debt_equity,
        "data_quality": dq.get("level"),
        "technical_signal": tech.signal,
        "action": decision.action,
        "confidence": decision.confidence,
        "blocked": decision.blocked,
    }


def measure_all(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for i, sym in enumerate(symbols, 1):
        row = measure_symbol(sym)
        if row is not None:
            out[sym] = row
        print(f"\r  {i}/{len(symbols)} {sym:<10}", end="", file=sys.stderr, flush=True)
    print(file=sys.stderr)
    return out


# --------------------------------------------------------------------------- #
#  Reporting                                                                  #
# --------------------------------------------------------------------------- #

_SCORE_FIELDS = ("total_score", "adjusted_score", "profitability", "health",
                 "valuation", "growth", "dividend")


def _delta(new: Any, old: Any) -> Optional[float]:
    if isinstance(new, (int, float)) and isinstance(old, (int, float)):
        return round(float(new) - float(old), 1)
    return None


def render_comparison(before: Dict[str, Any], after: Dict[str, Any]) -> str:
    common = sorted(set(before) & set(after))
    lines: List[str] = []

    moved = []
    for sym in common:
        b, a = before[sym], after[sym]
        d = _delta(a["adjusted_score"], b["adjusted_score"])
        if d:
            moved.append((abs(d), d, sym, b, a))
    moved.sort(reverse=True)

    lines.append(f"# Impacto sobre {len(common)} tickers cacheados\n")
    lines.append(f"- Con score modificado: **{len(moved)}**")

    sig = [(s, before[s]["action"], after[s]["action"])
           for s in common if before[s]["action"] != after[s]["action"]]
    lines.append(f"- Con la señal modificada: **{len(sig)}**\n")

    if moved:
        lines.append("## Deltas por ticker\n")
        lines.append("| Ticker | Adj. antes | Adj. después | Δ | Dimensiones movidas | Señal |")
        lines.append("|---|---:|---:|---:|---|---|")
        for _, d, sym, b, a in moved:
            dims = ", ".join(
                f"{f}{_delta(a[f], b[f]):+g}"
                for f in _SCORE_FIELDS
                if f not in ("total_score", "adjusted_score") and _delta(a[f], b[f])
            ) or "—"
            action = (f"{b['action']} → **{a['action']}**"
                      if b["action"] != a["action"] else a["action"])
            lines.append(
                f"| {sym} | {b['adjusted_score']} | {a['adjusted_score']} | {d:+g} | {dims} | {action} |"
            )

    if sig:
        lines.append("\n## Cambios de señal\n")
        for sym, old, new in sig:
            lines.append(f"- **{sym}**: {old} → {new}")

    gained = [s for s in common if not before[s]["is_value_stock"] and after[s]["is_value_stock"]]
    lost = [s for s in common if before[s]["is_value_stock"] and not after[s]["is_value_stock"]]
    if gained or lost:
        lines.append("\n## Margen de seguridad (`is_value_stock`, habilita STRONG BUY)\n")
        lines.append(f"- Lo pierden: {len(lost)} — {', '.join(lost[:20]) or '—'}")
        lines.append(f"- Lo ganan: {len(gained)} — {', '.join(gained[:20]) or '—'}")

    only_before = sorted(set(before) - set(after))
    only_after = sorted(set(after) - set(before))
    if only_before or only_after:
        lines.append(
            f"\n> Fuera de la comparación: {len(only_before)} solo en el baseline, "
            f"{len(only_after)} solo ahora."
        )

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline", metavar="PATH",
                        help="escribir la medición actual como baseline JSON")
    parser.add_argument("--compare", metavar="PATH",
                        help="comparar la medición actual contra un baseline JSON")
    parser.add_argument("--out", metavar="PATH",
                        help="guardar el reporte markdown de --compare")
    parser.add_argument("--limit", type=int, default=0,
                        help="medir solo los primeros N tickers (debug)")
    args = parser.parse_args()

    if not args.baseline and not args.compare:
        parser.error("elegí --baseline o --compare")

    _make_offline()
    symbols = cached_symbols()
    if args.limit:
        symbols = symbols[: args.limit]
    print(f"Midiendo {len(symbols)} tickers desde la caché (sin red)…", file=sys.stderr)

    current = measure_all(symbols)

    if args.baseline:
        Path(args.baseline).write_text(json.dumps(current, indent=1, sort_keys=True))
        print(f"Baseline escrito: {args.baseline} ({len(current)} tickers)")

    if args.compare:
        before = json.loads(Path(args.compare).read_text())
        report = render_comparison(before, current)
        if args.out:
            Path(args.out).write_text(report)
            print(f"Reporte escrito: {args.out}")
        else:
            print(report)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
