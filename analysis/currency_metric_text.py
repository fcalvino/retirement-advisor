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


#: UM-1: el múltiplo del feed no cierra con P/E × ROE y los estados vienen en otra
#: moneda, así que no se puede reconstruir sin tipo de cambio.
_UNIT = {
    "pb_ratio": re.compile(
        r"P/B no medible: el del feed \((\S+)\) no cierra con P/E × ROE \((\S+)\) y los "
        r"estados vienen en otra moneda que la cotización; un múltiplo sólo está definido "
        r"si ambas patas comparten unidad\."
    ),
    "ev_ebitda": re.compile(
        r"EV/EBITDA no medible: el del feed \((\S+)\) no cierra con el reconstruido desde "
        r"P/E × ROE \((\S+)\) y los estados vienen en otra moneda que la cotización; un "
        r"múltiplo sólo está definido si ambas patas comparten unidad\."
    ),
}

_LABEL = {"fcf_yield": "FCF yield", "p_ffo": "P/FFO", "pb_ratio": "P/B", "ev_ebitda": "EV/EBITDA"}
_NUMERATOR = {"fcf_yield": "FCF", "p_ffo": "FFO"}


def currency_metric_note(fund, metric: str) -> str:
    """Original explanation, also used unchanged as the dashboard tooltip."""
    return (getattr(fund, "notes", None) or {}).get(f"{metric}_currency", "")


def currency_metric_text(fund, metric: str, *, rationale: bool = False) -> str:
    """Suppression copy, or empty text when the metric has no currency note."""
    note = currency_metric_note(fund, metric)
    if not note:
        return ""
    match = _MISMATCH[metric].fullmatch(note) if metric in _MISMATCH else None
    declared = (
        _DECLARED[metric].fullmatch(note) if not match and metric in _DECLARED else None
    )
    unit = _UNIT[metric].fullmatch(note) if metric in _UNIT else None
    if rationale:
        if match:
            reason = f"statements in {match[1]}, quote in {match[2]}"
        elif declared:
            reason = f"statements not in the declared {declared[1]}"
        elif unit:
            reason = "feed ratio inconsistent with P/E × ROE, statements in another currency"
        else:
            reason = note
        return f"{_LABEL[metric]} not measurable: {reason}"
    if match:
        reason = f"{_NUMERATOR[metric]} en {match[1]}, market cap en {match[2]}"
    elif declared:
        reason = f"estados fuera de la moneda declarada, {declared[1]}"
    elif unit:
        reason = "el del feed no cierra con P/E × ROE y los estados vienen en otra moneda"
    else:
        reason = note
    return f"no medible ({reason})"
