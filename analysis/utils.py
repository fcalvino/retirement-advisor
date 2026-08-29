"""
Shared utilities across analysis modules.

AI response parsing, plus the numeric primitives that more than one scorer needs
and that must not be re-implemented per module — a formula with two copies has
two behaviours (see ``roic_pct``).
"""

from __future__ import annotations

import json
from typing import Any, Optional


def extract_json_object(raw: str) -> dict:
    """
    Robustly extract the first complete JSON object from an AI response string.

    Handles all common failure modes that arise with verbose AI responses:
    - Extra prose before the JSON (e.g., "Here is my analysis:\\n{...}")
    - Extra prose after the JSON (e.g., "{...}\\nNote: consider {country} risk")
    - Markdown code fences (```json ... ```)
    - Curly braces inside JSON string values (e.g., "returns {5-8}% annually")
    - Nested JSON objects or arrays

    The approach is a one-pass balanced-brace walk that respects string context,
    so it correctly ignores `{` and `}` inside quoted strings.

    Args:
        raw: Raw string returned by the AI provider.

    Returns:
        Parsed dict from the first complete JSON object found.

    Raises:
        ValueError: If no complete JSON object can be extracted.
        json.JSONDecodeError: If the extracted candidate is structurally invalid JSON.
    """
    text = raw.strip()

    # Strip markdown code fences if present (e.g. ```json ... ```)
    if text.startswith("```"):
        text = "\n".join(line for line in text.split("\n") if not line.startswith("```")).strip()

    # Happy path: the whole response IS the JSON object
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Balanced-brace walk: try each `{` position as a potential JSON start.
    # We iterate rather than assuming the first `{` is the JSON opening brace,
    # because prose before the JSON may also contain `{...}` fragments.
    pos = 0
    last_exc: Exception = ValueError("No JSON object found in AI response")

    while True:
        start = text.find("{", pos)
        if start == -1:
            raise last_exc

        depth = 0
        in_string = False
        escape_next = False

        for i in range(start, len(text)):
            c = text[i]

            # Handle escape sequences inside strings (e.g. \", \\)
            if escape_next:
                escape_next = False
                continue
            if c == "\\" and in_string:
                escape_next = True
                continue

            # Toggle string mode on unescaped double-quotes
            if c == '"':
                in_string = not in_string
                continue

            # Characters inside a string are inert for brace counting
            if in_string:
                continue

            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError as exc:
                        # This `{...}` block was not valid JSON; try the next `{`
                        last_exc = exc
                        pos = start + 1
                        break
        else:
            # Inner for-loop exhausted without finding a matching `}` — no more candidates
            raise ValueError("AI response contains an incomplete JSON object (unmatched braces)")


# --------------------------------------------------------------------------- #
#  ROIC — one formula, one tax rate (backlog U3-8)                            #
# --------------------------------------------------------------------------- #

def corporate_tax_rate_pct(country: Optional[str], cfg: Any = None) -> float:
    """The statutory corporate tax rate for the jurisdiction taxing the profit.

    Falls back to ``TaxConfig.default_corporate_tax_rate_pct`` — deliberately not
    the United States' rate — when the feed reports no country or one not in the
    table. An unknown jurisdiction is an assumption, and defaulting to a specific
    country's number disguises it as a fact.
    """
    from config import TAXES

    conf = cfg if cfg is not None else TAXES
    table = getattr(conf, "corporate_tax_rate_pct", None) or {}
    default = float(getattr(conf, "default_corporate_tax_rate_pct", 23.0))
    if not country:
        return default
    return float(table.get(str(country).strip(), default))


def roic_pct(
    ebit: float,
    equity: float,
    long_term_debt: float,
    tax_rate_pct: float,
) -> Optional[float]:
    """Return on invested capital, as a percentage. The single implementation.

        NOPAT = EBIT × (1 − t)
        ROIC  = NOPAT / (equity + long-term debt)

    ``fundamental`` and ``moat`` both scored a ROIC and each built it from
    scratch, spelling the same tax rate as ``0.21`` in one and ``0.79`` in the
    other (U3-8). The *window* they want genuinely differs — the latest year for
    "what does it earn now", the average for "does it last" — so that stays with
    each caller. The formula does not.

    ``None`` when the invested capital is zero or negative: there is no return on
    capital that is not there, and a negative denominator would flip the sign of
    a perfectly healthy operating profit.
    """
    invested = float(equity) + float(long_term_debt)
    if invested <= 0:
        return None
    nopat = float(ebit) * (1.0 - float(tax_rate_pct) / 100.0)
    return nopat / invested * 100.0


# --------------------------------------------------------------------------- #
#  Fiscal-period alignment (backlog U3-9 / U3-10)                             #
# --------------------------------------------------------------------------- #

def aligned_latest(
    frames_rows: "list[tuple[Any, list]]",
) -> "tuple[Optional[list], Optional[str]]":
    """Values from the newest period on which **every** requested row reported.

    Returns ``(values, period)`` in the order asked for, or ``(None, None)`` when
    no period has all of them.

    A ratio compares quantities measured over the same span; two numbers from
    different fiscal years are not one. Each side used to be fetched with its own
    ``dropna()``, so each landed on whatever year that row last reported — AAPL
    divided EBIT from 2025 by interest expense from 2023, and LLY showed 38x
    where the aligned figure is 21.8x (U3-10). Net income and D&A live in
    different statements, so FFO could drift further still (U3-9).

    It **anchors** rather than discarding. Refusing to produce a ratio whenever
    the newest columns disagree would re-break what an earlier fix repaired: the
    ``dropna()`` was added so those same two companies would not lose interest
    coverage entirely to a blank latest column. Stepping back to the newest
    shared year keeps the metric and makes it true. Only a genuine absence of
    overlap yields nothing.

    ``frames_rows`` pairs a statement with the candidate row names to try in it,
    first match winning — the same convention the callers already use. The frames
    may be different statements, which is exactly the case that drifts most.
    """
    import pandas as pd

    per_side = []
    for df, names in frames_rows:
        if df is None or getattr(df, "empty", True):
            return None, None
        reported = None
        for name in names:
            if name in df.index:
                reported = {
                    col: value
                    for col, value in df.loc[name].items()
                    if pd.notna(value)
                }
                break
        if not reported:
            return None, None
        per_side.append(reported)

    common = set(per_side[0])
    for side in per_side[1:]:
        common &= set(side)
    if not common:
        return None, None

    period = max(common, key=lambda c: str(c))
    try:
        values = [float(side[period]) for side in per_side]
    except (TypeError, ValueError):
        return None, None
    return values, str(period)
