"""Tokens y costo de cada llamada a un LLM (LLM-6).

Ninguna llamada registraba lo que gastaba: `AIAnalyzer._call_api` devolvía el
texto y tiraba la respuesta con su ``usage``. El comité hace 5–6 llamadas por
ticker y nadie sabía cuánto costaba un dictamen, que es lo que #151 necesita
medir antes de repetir 30 dictámenes en vivo.

Cada rama de `ai_analyzer` llama a `record` con la respuesta cruda **antes** de
extraer el texto: una respuesta truncada o rechazada levanta `AIUnavailable` y
se cobra igual. `record` escribe una línea ``llm_usage …`` en el log y, si hay
un `USAGE.capture()` abierto, la suma ahí — desde cualquier hilo, porque el
comité corre sus voces en un `ThreadPoolExecutor`.

Lo que el proveedor no reporta queda en ``None`` («no medido»), nunca en 0.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional, Tuple

from loguru import logger

from config import LLM_PRICES


@dataclass(frozen=True)
class UsageRecord:
    provider: str
    model: str
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    stop: Optional[str]
    cost_usd: Optional[float]


def _as_int(value: Any) -> Optional[int]:
    # bool is an int subclass; a MagicMock attribute is neither: both mean «no dato».
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def extract_usage(response: Any) -> Tuple[Optional[int], Optional[int]]:
    """(input, output) tokens de una respuesta, por duck typing.

    Anthropic: ``usage.input_tokens`` / ``usage.output_tokens``. OpenAI y
    compatibles (Groq, xAI, Nous): ``usage.prompt_tokens`` /
    ``usage.completion_tokens`` — en gpt-oss el razonamiento va dentro de
    ``completion_tokens``. Sin ``usage``, o sin el campo, ``None``.
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return None, None
    inp = _as_int(getattr(usage, "input_tokens", None))
    if inp is None:
        inp = _as_int(getattr(usage, "prompt_tokens", None))
    out = _as_int(getattr(usage, "output_tokens", None))
    if out is None:
        out = _as_int(getattr(usage, "completion_tokens", None))
    return inp, out


def cost_usd(model: str, input_tokens: Optional[int],
             output_tokens: Optional[int]) -> Optional[float]:
    """Costo en USD según `config.LLM_PRICES`; ``None`` si falta el precio o un conteo."""
    price = LLM_PRICES.get(model)
    if price is None or input_tokens is None or output_tokens is None:
        return None
    return round(
        (input_tokens * price.input_per_mtok + output_tokens * price.output_per_mtok) / 1_000_000,
        8,
    )


class UsageLedger:
    """Acumula registros mientras haya un `capture()` abierto, desde cualquier hilo."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sinks: List[List[UsageRecord]] = []

    @contextmanager
    def capture(self) -> Iterator[List[UsageRecord]]:
        sink: List[UsageRecord] = []
        with self._lock:
            self._sinks.append(sink)
        try:
            yield sink
        finally:
            with self._lock:
                self._sinks.remove(sink)

    def add(self, rec: UsageRecord) -> None:
        with self._lock:
            for sink in self._sinks:
                sink.append(rec)


USAGE = UsageLedger()


def record(provider: str, model: str, response: Any,
           stop: Optional[str] = None) -> Optional[UsageRecord]:
    """Registra una llamada. Nunca levanta: medir no puede tumbar la llamada."""
    try:
        inp, out = extract_usage(response)
        rec = UsageRecord(
            provider=str(provider), model=str(model),
            input_tokens=inp, output_tokens=out,
            stop=None if stop is None else str(stop),
            cost_usd=cost_usd(str(model), inp, out),
        )
        logger.info(
            f"llm_usage provider={rec.provider} model={rec.model} in={rec.input_tokens} "
            f"out={rec.output_tokens} stop={rec.stop} cost_usd={rec.cost_usd}"
        )
        USAGE.add(rec)
        return rec
    except Exception as exc:  # pragma: no cover — defensive by contract
        logger.debug(f"llm_usage: no se pudo registrar ({exc!r})")
        return None


def _totals(records: List[UsageRecord]) -> Dict[str, Any]:
    def _sum(key: str) -> Optional[int]:
        vals = [getattr(r, key) for r in records]
        return None if any(v is None for v in vals) else sum(vals)

    known = [r.cost_usd for r in records if r.cost_usd is not None]
    return {
        "n_calls": len(records),
        "n_calls_without_usage": sum(
            1 for r in records if r.input_tokens is None or r.output_tokens is None
        ),
        "input_tokens": _sum("input_tokens"),
        "output_tokens": _sum("output_tokens"),
        "cost_usd": round(sum(known), 6) if len(known) == len(records) else None,
        "cost_usd_known": round(sum(known), 6),
    }


def summarize(records: List[UsageRecord]) -> Dict[str, Any]:
    """Totales de una captura, para el JSON de una corrida del banco de eval.

    Un total que no se puede medir es ``None``: ``input_tokens`` si alguna
    llamada no trajo ``usage``, ``cost_usd`` si alguna no tiene precio —la suma
    parcial queda aparte como ``cost_usd_known`—. Un total que omite en
    silencio las llamadas sin dato se leería como el costo real.
    """
    groups: Dict[str, List[UsageRecord]] = {}
    for r in records:
        groups.setdefault(f"{r.provider}/{r.model}", []).append(r)
    return {**_totals(records), "by_model": {k: _totals(v) for k, v in groups.items()}}
