"""Presentation of existing currency notes; no financial calculations.

The result stores a human-readable note, not a quote-currency field. Recognize
only the producer's explicit templates; preserve any other reason (including the
plausibility backstop) verbatim instead of guessing currencies.
"""

import re

#: Las dos patas vienen etiquetadas con monedas distintas.
_MISMATCH = {
    "fcf_yield": re.compile(
        r"FCF yield no medible: el free cash flow viene en (\S+) y el "
        r"market cap en (\S+); un yield sólo está definido si ambas patas comparten moneda\."
    ),
    "p_ffo": re.compile(
        r"P/FFO no medible: el FFO viene en (\S+) y el market cap "
        r"en (\S+); un múltiplo sólo está definido si ambas patas comparten moneda\."
    ),
}

#: UM-2: la etiqueta dice «misma moneda que la cotización» y las cifras la desmienten.
_DECLARED = {
    "fcf_yield": re.compile(
        r"FCF yield no medible: la etiqueta declara los estados en (\S+), la moneda de "
        r"cotización, pero sus cifras no lo están; un yield sólo está definido si ambas "
        r"patas comparten moneda\."
    ),
    "p_ffo": re.compile(
        r"P/FFO no medible: la etiqueta declara los estados en (\S+), la moneda de "
        r"cotización, pero sus cifras no lo están; un múltiplo sólo está definido si "
        r"ambas patas comparten moneda\."
    ),
}


def currency_metric_note(fund, metric: str) -> str:
    """Original explanation, also used unchanged as the dashboard tooltip."""
    return (getattr(fund, "notes", None) or {}).get(f"{metric}_currency", "")


def currency_metric_text(fund, metric: str, *, rationale: bool = False) -> str:
    """Suppression copy, or empty text when the metric has no currency note."""
    note = currency_metric_note(fund, metric)
    if not note:
        return ""
    match = _MISMATCH[metric].fullmatch(note)
    declared = None if match else _DECLARED[metric].fullmatch(note)
    if rationale:
        label = "FCF yield" if metric == "fcf_yield" else "P/FFO"
        if match:
            reason = f"statements in {match[1]}, quote in {match[2]}"
        elif declared:
            reason = f"statements not in the declared {declared[1]}"
        else:
            reason = note
        return f"{label} not measurable: {reason}"
    numerator = "FCF" if metric == "fcf_yield" else "FFO"
    if match:
        reason = f"{numerator} en {match[1]}, market cap en {match[2]}"
    elif declared:
        reason = f"estados fuera de la moneda declarada, {declared[1]}"
    else:
        reason = note
    return f"no medible ({reason})"
