"""Relative ranking and the screening funnel (audit item 06).

Pure module: no network, no Streamlit, no dataframe.

Why this exists
---------------
A screener has one job — take N candidates and hand back the few worth your
attention. The Opportunity Screener was not doing it. Measured on US Quality
(78 companies, 2026-08-17):

    señal de compra:   67/78  (86 %)
    mediana del score: 74.8   ← the "Strong Buy ≥75" line sits on the median

That is not a tuning problem, it is a category problem. ``STRATEGY.strong_buy_score``
and ``buy_score`` were calibrated against the whole market, and the universe being
screened is *already* a curated quality list. Absolute thresholds applied to a
pre-filtered population must approve nearly all of it; the cut cannot cut.

The fix is not to move the thresholds — the engine's absolute verdict is still
the right thing for "is this a good company?". The fix is to add the dimension
the page was missing: **where does this name sit relative to the others in the
run**, and then to state the screening as a funnel so "67 have a buy signal"
reads as an intermediate step rather than as an answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

# --------------------------------------------------------------------------- #
#  Percentile within the analyzed universe                                    #
# --------------------------------------------------------------------------- #


def percentile_ranks(values: Sequence[float]) -> List[float]:
    """Percentile of each value within ``values``, 0–100.

    Mid-rank definition: ``(n_below + 0.5 * n_equal) / n * 100``. Ties share one
    percentile, which matters here — three tickers sit at the clamped 100 and must
    not be given three different ranks by an arbitrary tiebreak.

    Returns percentiles positionally aligned with the input.
    """
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [50.0]

    out: List[float] = []
    for v in values:
        n_below = sum(1 for other in values if other < v)
        n_equal = sum(1 for other in values if other == v)
        out.append(round((n_below + 0.5 * n_equal) / n * 100.0, 1))
    return out


def attach_percentiles(
    rows: Sequence[Mapping[str, Any]],
    *,
    score_key: str = "Adj. Score",
    out_key: str = "Percentil",
    tiebreak_key: Optional[str] = "Score bruto",
) -> List[dict]:
    """Return copies of ``rows`` with a percentile field added.

    ``tiebreak_key`` lets the uncapped score separate names the clamp merged
    (audit item 11): INTU, META and GOOGL all display 100.0 but are really
    107.9 / 104.0 / 103.0. When present it is used for the ranking so the
    percentile reflects the real ordering.
    """
    if not rows:
        return []

    def _value(row: Mapping[str, Any]) -> float:
        if tiebreak_key and row.get(tiebreak_key) is not None:
            return float(row[tiebreak_key])
        return float(row.get(score_key) or 0.0)

    ranks = percentile_ranks([_value(r) for r in rows])
    return [{**dict(row), out_key: pct} for row, pct in zip(rows, ranks)]


# --------------------------------------------------------------------------- #
#  Funnel                                                                     #
# --------------------------------------------------------------------------- #


@dataclass
class FunnelStep:
    """One narrowing step, with what it cost."""

    label: str
    kept: int
    dropped: int
    detail: str = ""


@dataclass
class ShortlistResult:
    rows: List[dict] = field(default_factory=list)
    steps: List[FunnelStep] = field(default_factory=list)
    truncated_by_cap: int = 0

    @property
    def n_analyzed(self) -> int:
        return self.steps[0].kept if self.steps else 0

    @property
    def n_selected(self) -> int:
        return len(self.rows)

    def summary(self) -> str:
        """One honest sentence for the page."""
        if not self.steps:
            return "Sin datos analizados todavía."
        if not self.rows:
            return (
                f"De {self.n_analyzed} acciones analizadas, **ninguna** pasa todos los "
                "criterios. Eso es un resultado válido — no siempre hay algo que comprar."
            )
        return (
            f"De {self.n_analyzed} acciones analizadas, **{self.n_selected}** pasan todos "
            "los criterios."
        )


def strip_badge(value: Any) -> str:
    """Text of a table badge without its leading emoji ('🏰 Wide' → 'Wide').

    Badges carry an emoji plus the value; filters need the value. Splitting on
    whitespace and dropping non-alphanumeric leading tokens keeps this working
    whether the badge is '🟩 BUY', '🟢 STRONG BUY' or a bare 'Wide'.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    parts = [p for p in text.split() if any(ch.isalnum() for ch in p)]
    return " ".join(parts)


def _is_buy(signal: Any) -> bool:
    """True only for the two buy verdicts — never for a substring accident."""
    return strip_badge(signal).upper() in {"STRONG BUY", "BUY"}


def _dq_level(row: Mapping[str, Any]) -> str:
    dq = row.get("_dq")
    if isinstance(dq, Mapping):
        return str(dq.get("level") or "")
    return ""


def build_shortlist(
    rows: Sequence[Mapping[str, Any]],
    *,
    config=None,
    signal_key: str = "Signal",
    percentile_key: str = "Percentil",
) -> ShortlistResult:
    """Narrow analyzed companies to a shortlist, recording each step.

    Composes criteria the engine already computes — data quality, the decision
    engine's action — and adds the relative one (percentile within this run).
    It deliberately invents no new financial test: the point is to *apply* what
    is already measured, in a way that actually excludes.

    ``rows`` must be equities only; funds and crypto are not fundamentally
    scorable and are handled upstream (see ``analysis/asset_class.py``).
    """
    if config is None:
        from config import SCREENER as config  # noqa: N811 — singleton default

    working = [dict(r) for r in rows]
    steps = [FunnelStep("Analizadas", kept=len(working), dropped=0)]
    if not working:
        return ShortlistResult(rows=[], steps=steps)

    if getattr(config, "shortlist_exclude_poor_data", True):
        before = len(working)
        working = [r for r in working if _dq_level(r) != "poor"]
        steps.append(FunnelStep(
            "Con datos suficientes", kept=len(working), dropped=before - len(working),
            detail="excluye 🔴 datos pobres",
        ))

    if getattr(config, "shortlist_require_buy_signal", True):
        before = len(working)
        working = [r for r in working if _is_buy(r.get(signal_key))]
        steps.append(FunnelStep(
            "Con señal de compra", kept=len(working), dropped=before - len(working),
            detail="STRONG BUY o BUY",
        ))

    threshold = float(getattr(config, "shortlist_percentile", 75.0))
    before = len(working)
    working = [r for r in working if float(r.get(percentile_key) or 0.0) >= threshold]
    # Label stays short: Streamlit truncates st.metric labels in narrow columns.
    steps.append(FunnelStep(
        f"En el top {100 - threshold:.0f}%", kept=len(working),
        dropped=before - len(working),
        detail=f"percentil ≥ {threshold:.0f} entre las {len(rows)} analizadas hoy",
    ))

    working.sort(
        key=lambda r: (
            float(r.get("Score bruto") or r.get("Adj. Score") or 0.0),
            float(r.get(percentile_key) or 0.0),
        ),
        reverse=True,
    )

    cap = int(getattr(config, "shortlist_max_names", 10))
    truncated = max(0, len(working) - cap) if cap > 0 else 0
    if truncated:
        working = working[:cap]
        steps.append(FunnelStep(
            f"Top {cap}", kept=len(working), dropped=truncated,
            detail="las mejores por score; el resto sigue en la tabla",
        ))

    return ShortlistResult(rows=working, steps=steps, truncated_by_cap=truncated)


# --------------------------------------------------------------------------- #
#  Table filters (audit item 09)                                              #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FilterCriteria:
    """What the user asked to see. Empty collection = no constraint on that axis.

    Deliberately separate from the funnel: the funnel is the page's *answer* over
    the whole run, these are a *lens* on the full table underneath it. Filtering
    the funnel too would recompute percentiles over the subset, so "top 25%" would
    silently start meaning "top 25% of Healthcare" while still being labelled as
    the universe — a new version of the exact defect audit item 03 fixed.
    """

    search: str = ""
    sectors: tuple = ()
    signals: tuple = ()
    moats: tuple = ()
    quality_levels: tuple = ()
    min_score: float = 0.0
    min_percentile: float = 0.0
    only_watchlist: bool = False

    def is_active(self) -> bool:
        return bool(
            self.search or self.sectors or self.signals or self.moats
            or self.quality_levels or self.min_score > 0 or self.min_percentile > 0
            or self.only_watchlist
        )


def apply_filters(
    rows: Sequence[Mapping[str, Any]],
    criteria: FilterCriteria,
    *,
    watchlist: Sequence[str] = (),
) -> List[dict]:
    """Narrow ``rows`` to what the criteria allow, preserving order.

    Pure: ``watchlist`` is injected rather than read from preferences, so the
    behaviour is testable without a Streamlit session.
    """
    watched = {str(s).upper().strip() for s in watchlist}
    needle = criteria.search.strip().lower()
    want_signals = {str(s).upper() for s in criteria.signals}
    want_moats = {str(m) for m in criteria.moats}
    want_quality = {str(q) for q in criteria.quality_levels}
    want_sectors = set(criteria.sectors)

    out: List[dict] = []
    for row in rows:
        if needle:
            haystack = f"{row.get('Ticker', '')} {row.get('Company', '')}".lower()
            if needle not in haystack:
                continue
        if want_sectors and row.get("Sector") not in want_sectors:
            continue
        if want_signals and strip_badge(row.get("Signal")).upper() not in want_signals:
            continue
        if want_moats and strip_badge(row.get("Moat")) not in want_moats:
            continue
        if want_quality and _dq_level(row) not in want_quality:
            continue
        if criteria.min_score > 0 and float(row.get("Adj. Score") or 0.0) < criteria.min_score:
            continue
        if criteria.min_percentile > 0 and float(row.get("Percentil") or 0.0) < criteria.min_percentile:
            continue
        if criteria.only_watchlist and str(row.get("Ticker", "")).upper() not in watched:
            continue
        out.append(dict(row))
    return out


def filter_preset(name: str, *, config=None) -> FilterCriteria:
    """Build criteria from a named preset in ``ScreenerConfig.filter_presets``."""
    if config is None:
        from config import SCREENER as config  # noqa: N811

    spec: Dict[str, Any] = dict(config.filter_presets.get(name, {}))
    return FilterCriteria(**spec)


#: The axes a preset can name values on, with the label the page shows for each.
#: Only the collection axes are here: a search string, a percentile floor and a
#: checkbox cannot be silently dropped, because they are not chosen from options.
_GAP_AXES: Sequence[tuple] = (
    ("sectors", "Sector"),
    ("signals", "Se\u00f1al"),
    ("moats", "Foso"),
    ("quality_levels", "Calidad de datos"),
)


def preset_gap(
    requested: FilterCriteria, available: FilterCriteria
) -> Dict[str, tuple]:
    """Values a preset asked for that this run cannot offer, keyed by axis label.

    Streamlit *drops* multiselect values that are not in ``options`` rather than
    raising, so a preset naming a signal no ticker in the run carries — "Lo que
    descart\u00e9" over a universe that is 86 % buys — applies nothing at all, and
    the table shows every row while the preset box still reads "Lo que descart\u00e9".
    A filter that silently does the opposite of what its name says is worse than
    one that refuses.

    ``available`` is what the **run** can offer (the option lists), not the
    current widgets (U7-1). Comparing against widgets made a manual uncheck
    look like "ese filtro no se aplicó", which is false: the user applied a
    custom slice. Empty dict = every value the preset named exists in this run.
    """
    gaps: Dict[str, tuple] = {}
    for field_name, label in _GAP_AXES:
        wanted = tuple(getattr(requested, field_name, ()) or ())
        if not wanted:
            continue
        got = {str(v).upper() for v in (getattr(available, field_name, ()) or ())}
        dropped = tuple(v for v in wanted if str(v).upper() not in got)
        if dropped:
            gaps[label] = dropped
    return gaps
