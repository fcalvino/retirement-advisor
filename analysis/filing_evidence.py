"""Evidence pack of SEC filing snippets for AI moat/catalysts (ideas 5 + 9).

Pure: no Streamlit, no network. Retrieve lives in ``data/sec_filings.py``.
SEC/FMP still do not score — this pack is only injected into prompts and the
post-parse catalyst policy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, List, Optional, Sequence, Tuple

EMPTY_CATALYSTS_BODY = "ninguno citado."
NO_SOURCE_NOTE = "Catalizadores vaciados: no hay filing citable"

_CATALYST_SECTION = re.compile(
    r"(Catalizadores:\s*)(.*?)(?=(Asignación:|$))",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class FilingSnippet:
    form: str
    filed: Optional[date]
    accession: str
    item: str
    kind: str  # "moat" | "catalyst"
    text: str


@dataclass
class FilingEvidencePack:
    symbol: str
    snippets: List[FilingSnippet] = field(default_factory=list)
    empty_reason: str = ""

    @property
    def has_catalyst_source(self) -> bool:
        return any(s.kind == "catalyst" and (s.text or "").strip() for s in self.snippets)

    @property
    def fingerprint(self) -> str:
        if not self.snippets:
            return f"empty:{self.empty_reason or 'none'}"
        acc = sorted({s.accession for s in self.snippets if s.accession})
        return ",".join(acc) if acc else "snippets"

    def prompt_block(self) -> str:
        if not self.snippets:
            reason = self.empty_reason or "sin filing"
            return (
                "--- EVIDENCE PACK DE FILINGS ---\n"
                f"NO HAY FILING CITABLE ({reason}). "
                "El campo JSON catalysts DEBE ser []. No inventes eventos, "
                "catalizadores a 12–18 meses ni frases de un 10-K. "
                "confidence no puede superar LOW.\n"
            )
        lines = [
            "--- EVIDENCE PACK DE FILINGS "
            "(única fuente cualitativa de moat y catalizadores; prohibido usar memoria) ---"
        ]
        for sn in self.snippets:
            filed = sn.filed.isoformat() if sn.filed else "fecha-desconocida"
            excerpt = (sn.text or "").strip()
            lines.append(
                f"[{sn.kind}] {sn.form} {sn.item} filed {filed} accession {sn.accession}:\n{excerpt}"
            )
        lines.append(
            "Cada claim de catalysts debe citar form+item+filed o accession de este pack. "
            "La sección Catalizadores del reasoning solo parafrasea esa lista."
        )
        return "\n".join(lines) + "\n"


def empty_pack(symbol: str, reason: str) -> FilingEvidencePack:
    return FilingEvidencePack(symbol=symbol, snippets=[], empty_reason=reason)


def replace_catalysts_section(reasoning: str, replacement: str) -> str:
    """Swap the Catalizadores body; append the section if it is missing."""
    body = (replacement or "").strip() or EMPTY_CATALYSTS_BODY
    text = reasoning or ""
    if _CATALYST_SECTION.search(text):
        return _CATALYST_SECTION.sub(lambda m: f"{m.group(1)}{body} ", text, count=1)
    if not text.strip():
        return f"Catalizadores: {body}"
    return f"{text.rstrip()}\nCatalizadores: {body}"


def citation_matches_pack(citation: str, pack: FilingEvidencePack) -> bool:
    blob = (citation or "").strip().lower()
    if not blob:
        return False
    for sn in pack.snippets:
        tokens = [sn.form, sn.item, sn.accession]
        if sn.filed is not None:
            tokens.append(sn.filed.isoformat())
            tokens.append(f"{sn.filed.year}")
        for tok in tokens:
            t = str(tok or "").strip().lower()
            if t and t in blob:
                return True
    return False


def filter_cited_catalysts(catalysts: Sequence[dict], pack: FilingEvidencePack) -> List[dict]:
    kept: List[dict] = []
    for raw in catalysts or []:
        if not isinstance(raw, dict):
            continue
        claim = str(raw.get("claim") or "").strip()
        citation = str(raw.get("citation") or "").strip()
        if not claim and not citation:
            continue
        if citation_matches_pack(citation, pack) or citation_matches_pack(claim, pack):
            kept.append({"claim": claim[:400], "citation": citation[:240]})
    return kept


def filing_panel_state(
    *,
    ai_on: bool,
    pack: Optional[FilingEvidencePack],
    catalysts: Optional[Iterable[dict]],
) -> dict:
    """Pure UI state for Stock Analysis — no Streamlit."""
    if not ai_on:
        return {
            "show_expander": False,
            "show_empty_caption": False,
            "snippets": (),
            "empty_caption": "",
        }
    snippets: Tuple[FilingSnippet, ...] = tuple(getattr(pack, "snippets", None) or ())
    cats = [c for c in (catalysts or []) if isinstance(c, dict)]
    empty = len(cats) == 0
    return {
        "show_expander": bool(snippets),
        "show_empty_caption": empty,
        "snippets": snippets,
        "empty_caption": "Sin catalizadores citados" if empty else "",
    }


def pack_to_dict(pack: FilingEvidencePack) -> dict:
    return {
        "symbol": pack.symbol,
        "empty_reason": pack.empty_reason,
        "snippets": [
            {
                "form": s.form,
                "filed": s.filed.isoformat() if s.filed else None,
                "accession": s.accession,
                "item": s.item,
                "kind": s.kind,
                "text": s.text,
            }
            for s in pack.snippets
        ],
    }


def pack_from_dict(data: dict) -> FilingEvidencePack:
    snippets = []
    for raw in data.get("snippets") or []:
        filed = raw.get("filed")
        filed_d = None
        if filed:
            try:
                filed_d = date.fromisoformat(str(filed)[:10])
            except ValueError:
                filed_d = None
        snippets.append(
            FilingSnippet(
                form=str(raw.get("form") or ""),
                filed=filed_d,
                accession=str(raw.get("accession") or ""),
                item=str(raw.get("item") or ""),
                kind=str(raw.get("kind") or "moat"),
                text=str(raw.get("text") or ""),
            )
        )
    return FilingEvidencePack(
        symbol=str(data.get("symbol") or ""),
        snippets=snippets,
        empty_reason=str(data.get("empty_reason") or ""),
    )
