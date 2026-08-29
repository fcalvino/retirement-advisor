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

It also answers the question U3-7 needs answered — how much of a ticker's score
comes from the AI layer — by scoring the same universe twice, with AI off and on:

    ./venv/bin/python3 scripts/measure_score_impact.py --matrix matriz.md

**It never goes to the network.** Three guards make that true:

  * only tickers whose ``info`` *and* 10y weekly ``history`` are already cached
    are scored — everything else is skipped and counted;
  * the cache TTL is raised in-process (the entries on disk are older than the
    24h default) and ``MULTI_SOURCE.attach_in_pipeline`` is turned off, because
    the cross-source badge downloads SEC EDGAR companyfacts per ticker;
  * the AI layer runs **cache-only** (``MOAT.ai_cache_only``,
    ``TAILWINDS.ai_cache_only``): a miss returns the quantitative result instead
    of calling the provider. And the AI config is ``enrich_only``, so the
    *decision* layer — the one AI call with no cache behind it — never fires.
    Without that the leg would be neither offline nor honest, because
    ``AIAnalyzer.analyze`` swallows every failure and degrades to rule-based, so
    an unreachable API would look like "the AI changed nothing".

The TTL guard has to reach the AI caches too. ``MoatAnalyzer`` and
``TailwindAnalyzer`` each build their **own** ``DataCache`` from their config's
``ai_cache_ttl_hours``, so the module-level singleton's TTL never touched them —
and ``DataCache.get`` *deletes* the row it finds expired. Without raising those
two the first AI run would have destroyed the older half of the cached moat
entries on disk, breaking the promise in the next line.

All mutations are in-memory only: nothing on disk changes.

**What the matrix can and cannot show.** The moat and tailwind layers have a
persistent cache, so their contribution is measurable offline — and that bonus is
what U3-7 is about. The *decision* layer has no cache, so with AI on it still
produces the rule-based action. The ``ai_ran`` column says so per row rather than
letting a column of identical actions read as a finding.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


_OFFLINE_TTL_HOURS = 24 * 3650


def _make_offline() -> None:
    """Serve everything from the existing cache; disable networked side-trips."""
    import data.cache as cache_module
    from config import MOAT, MULTI_SOURCE, TAILWINDS

    cache_module.cache.ttl = timedelta(days=3650)
    MULTI_SOURCE.attach_in_pipeline = False

    # The analyzers build their own DataCache from these, so the singleton's TTL
    # above does not reach them. Raising them keeps every cached AI row fresh —
    # which also stops DataCache.get from deleting the expired ones on disk.
    MOAT.ai_cache_ttl_hours = _OFFLINE_TTL_HOURS
    TAILWINDS.ai_cache_ttl_hours = _OFFLINE_TTL_HOURS
    MOAT.ai_cache_only = True
    TAILWINDS.ai_cache_only = True


def cached_symbols() -> List[str]:
    """Tickers with both ``info`` and the 10y weekly history already cached."""
    from data.cache import cache

    info = {k.split(":", 1)[1] for k in cache.keys_with_prefix("info:")}
    hist = {k.split(":")[1] for k in cache.keys_with_prefix("history:") if k.endswith(":10y:1wk")}
    return sorted(info & hist)


# --------------------------------------------------------------------------- #
#  Measurement                                                                #
# --------------------------------------------------------------------------- #

def offline_ai_config():
    """An ``AIConfig`` that can only read the cache, never the network.

    Provider and model are read from the environment exactly as the app reads
    them, because the moat cache key embeds both: measuring with a different
    model would miss every row and report "the AI changes nothing" when the
    truth is "we looked in the wrong drawer".
    """
    from config import AI_CONFIG, AIConfig

    return AIConfig(
        provider=AI_CONFIG.provider,
        model=AI_CONFIG.model,
        api_key=AI_CONFIG.api_key,
        enabled=True,
        enrich_only=True,
    )


def measure_symbol(symbol: str, ai_config=None) -> Optional[Dict[str, Any]]:
    """Score one ticker end-to-end. With ``ai_config`` the AI leg reads cache only."""
    from analysis.strategy import full_analysis

    try:
        fund, tech, decision = full_analysis(symbol, ai_config=ai_config)
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
        # U3-2 reads these: ATR and ADX are the numbers under measurement, and
        # ``adx`` in particular decides a gate (``>= 25``) that the signal above
        # only reports the aggregate of.
        "adx": tech.adx,
        "atr_pct": tech.atr_pct,
        "action": decision.action,
        "confidence": decision.confidence,
        "blocked": decision.blocked,
        # U3-7 reads these: the moat scale is the thing under measurement.
        "moat_score": round(float(fund.moat_score or 0.0), 1),
        "moat_bonus": round(float(fund.moat_bonus or 0.0), 1),
        "moat_classification": fund.moat_classification,
        # Whether the AI layer actually contributed, as opposed to having been
        # asked and having quietly failed. Without this a column of unchanged
        # scores is ambiguous between "no effect" and "never ran".
        "ai_ran": bool(getattr(fund.moat_detail, "ai_available", False)),
    }


def measure_all(symbols: List[str], ai_config=None) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for i, sym in enumerate(symbols, 1):
        row = measure_symbol(sym, ai_config=ai_config)
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
    lines.append(f"- Con la señal modificada: **{len(sig)}**")

    # The technical leg reaches ``action`` only through the BULLISH/NEUTRAL/
    # BEARISH bucket, so a change that moves ADX or ATR without flipping the
    # bucket would be invisible above. U3-2 needs it visible: the ADX gate is
    # its own decision (``technical.py`` ``adx >= 25`` pays +5) and the notes at
    # :166/:168 are read by the user.
    tech_sig = [(s, before[s].get("technical_signal"), after[s].get("technical_signal"))
                for s in common
                if before[s].get("technical_signal") != after[s].get("technical_signal")]
    lines.append(f"- Con la señal **técnica** modificada: **{len(tech_sig)}**")

    def _gate(row) -> Optional[bool]:
        v = row.get("adx")
        return bool(v >= 25) if isinstance(v, (int, float)) else None

    gate = [(s, before[s].get("adx"), after[s].get("adx"))
            for s in common
            if _gate(before[s]) is not None and _gate(after[s]) is not None
            and _gate(before[s]) != _gate(after[s])]
    lines.append(f"- Que cruzan el gate de ADX 25: **{len(gate)}**\n")

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

    if tech_sig:
        lines.append("\n## Cambios de señal técnica\n")
        for sym, old_s, new_s in tech_sig:
            b, a = before[sym].get("adx"), after[sym].get("adx")
            lines.append(f"- **{sym}**: {old_s} → {new_s} (ADX {b} → {a})")

    if gate:
        lines.append("\n## Cruces del gate de ADX 25 (+5 al score técnico)\n")
        for sym, b, a in gate:
            side = "entra" if (a or 0) >= 25 else "sale"
            lines.append(f"- **{sym}**: {b} → {a} — {side}")

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


def render_matrix(off: Dict[str, Any], on: Dict[str, Any]) -> str:
    """The AI on/off matrix U3-7 needs before it can pick a moat threshold.

    Reports the ceiling the quantitative scale actually reaches, which is the
    heart of U3-7: ``wide_threshold`` is 14 on a 0–20 scale whose quant-only
    tramo tops out at 12, so Wide Moat is unreachable without the AI layer.
    """
    common = sorted(set(off) & set(on))
    ran = [s for s in common if on[s]["ai_ran"]]

    lines: List[str] = [f"# Matriz IA on/off — {len(common)} tickers cacheados\n"]
    lines.append(f"- Con la capa IA efectivamente aplicada: **{len(ran)}/{len(common)}**")
    if len(ran) < len(common):
        lines.append(
            f"- Sin entrada en caché (la IA no corrió, la fila queda quant-only): "
            f"**{len(common) - len(ran)}**"
        )

    def _ceiling(rows, key: str) -> float:
        vals = [rows[s][key] for s in common if isinstance(rows[s].get(key), (int, float))]
        return max(vals) if vals else 0.0

    lines.append(
        f"\n## Techo alcanzado por la escala\n\n"
        f"| | moat_score máx | bonus máx | adjusted_score máx |\n|---|---:|---:|---:|\n"
        f"| IA apagada | {_ceiling(off, 'moat_score')} | {_ceiling(off, 'moat_bonus')} "
        f"| {_ceiling(off, 'adjusted_score')} |\n"
        f"| IA prendida | {_ceiling(on, 'moat_score')} | {_ceiling(on, 'moat_bonus')} "
        f"| {_ceiling(on, 'adjusted_score')} |"
    )

    from config import MOAT
    lines.append(
        f"\n`MOAT.wide_threshold` = **{MOAT.wide_threshold}**. Cualquier techo por debajo "
        f"de ese número significa que la etiqueta es inalcanzable en ese modo."
    )

    moved = []
    for sym in common:
        d = _delta(on[sym]["adjusted_score"], off[sym]["adjusted_score"])
        if d:
            moved.append((abs(d), d, sym))
    moved.sort(reverse=True)

    lines.append(f"\n## Tickers cuyo score mueve la IA: **{len(moved)}**\n")
    if moved:
        lines.append("| Ticker | Adj. sin IA | Adj. con IA | Δ | Moat sin IA | Moat con IA | Señal |")
        lines.append("|---|---:|---:|---:|---|---|---|")
        for _, d, sym in moved:
            a, b = off[sym], on[sym]
            action = (f"{a['action']} → **{b['action']}**"
                      if a["action"] != b["action"] else a["action"])
            lines.append(
                f"| {sym} | {a['adjusted_score']} | {b['adjusted_score']} | {d:+g} "
                f"| {a['moat_classification']} ({a['moat_score']}) "
                f"| {b['moat_classification']} ({b['moat_score']}) | {action} |"
            )

    flips = [s for s in common if off[s]["action"] != on[s]["action"]]
    lines.append(
        f"\n## Señales que se dan vuelta: **{len(flips)}**\n\n"
        "> La capa de decisión no tiene caché, así que en modo offline corre "
        "rule-based en las dos patas. Un cambio de señal acá viene del bonus de "
        "moat moviendo el `adjusted_score` por encima de un umbral, no de que el "
        "LLM haya opinado distinto."
    )
    for sym in flips:
        lines.append(f"- **{sym}**: {off[sym]['action']} → {on[sym]['action']}")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline", metavar="PATH",
                        help="escribir la medición actual como baseline JSON")
    parser.add_argument("--compare", metavar="PATH",
                        help="comparar la medición actual contra un baseline JSON")
    parser.add_argument("--out", metavar="PATH",
                        help="guardar el reporte markdown de --compare")
    parser.add_argument("--matrix", metavar="PATH", nargs="?", const="-",
                        help="medir el universo con IA apagada y prendida (U0-2); "
                             "sin PATH imprime a stdout")
    parser.add_argument("--limit", type=int, default=0,
                        help="medir solo los primeros N tickers (debug)")
    args = parser.parse_args()

    if not args.baseline and not args.compare and not args.matrix:
        parser.error("elegí --baseline, --compare o --matrix")

    _make_offline()
    symbols = cached_symbols()
    if args.limit:
        symbols = symbols[: args.limit]
    print(f"Midiendo {len(symbols)} tickers desde la caché (sin red)…", file=sys.stderr)

    if args.matrix:
        print("  pata 1/2: IA apagada…", file=sys.stderr)
        off = measure_all(symbols)
        print("  pata 2/2: IA prendida (solo caché)…", file=sys.stderr)
        on = measure_all(symbols, ai_config=offline_ai_config())
        report = render_matrix(off, on)
        if args.matrix != "-":
            Path(args.matrix).write_text(report)
            print(f"Matriz escrita: {args.matrix}")
        else:
            print(report)
        if not (args.baseline or args.compare):
            return 0

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
