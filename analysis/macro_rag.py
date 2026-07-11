"""
Real-time macro RAG (Gran Salto — Fase 3B).

Indexes **dated** macro facts (Fed releases, FRED series, economic news) and
retrieves the most relevant ones to inject as *fresh, time-stamped context* into
the prompts — instead of trusting the model's (possibly stale) training memory.
This turns ``macro_factors`` from an act of faith into something anchored to
verifiable, dated facts.

Deliberately dependency-light: a pure-Python TF-IDF retriever (no sklearn, no
external vector DB, no embeddings service), persisted in the shared SQLite DB.
This keeps the project synchronous and self-contained while still giving relevance
ranking. Swapping in a real embedding store later is a localized change behind
``MacroRagStore.retrieve``.

Conventions: config from ``config.MACRO_RAG``; loguru; tests use ``:memory:``.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple

from loguru import logger
from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from config import DB_PATH, MACRO_RAG


class _Base(DeclarativeBase):
    pass


class MacroDocRow(_Base):
    __tablename__ = "macro_docs"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    doc_key    = Column(String, unique=True, index=True)  # idempotent upsert key
    title      = Column(String, nullable=False)
    body       = Column(Text, nullable=False)
    source     = Column(String, default="")
    tags       = Column(String, default="")               # comma-separated
    as_of      = Column(String, default="")               # ISO date of the fact
    ingested_at = Column(DateTime, default=datetime.utcnow)


@dataclass
class MacroDoc:
    title: str
    body: str
    source: str = ""
    as_of: str = ""              # ISO date (YYYY-MM-DD) of the underlying fact
    tags: Tuple[str, ...] = ()
    doc_key: str = ""

    @property
    def text(self) -> str:
        return f"{self.title}. {self.body}"


_TOKEN_RE = re.compile(r"[a-záéíóúñü0-9]+", re.IGNORECASE)
_STOP = {
    "the", "a", "an", "of", "and", "to", "in", "on", "for", "is", "are", "el", "la",
    "los", "las", "de", "del", "y", "en", "un", "una", "por", "con", "que", "se",
}


def _tokens(text: str) -> List[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "") if t.lower() not in _STOP and len(t) > 1]


def _days_old(as_of: str, now: Optional[datetime] = None) -> Optional[int]:
    if not as_of:
        return None
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            d = datetime.strptime(as_of[: len(fmt) + 2], fmt)
            return max(0, (now - d).days)
        except ValueError:
            continue
    return None


class MacroRagStore:
    """SQLite-backed dated macro document store with TF-IDF retrieval."""

    def __init__(self, db_path: Any = None):
        path = db_path if db_path is not None else DB_PATH
        url = "sqlite:///:memory:" if path == ":memory:" else f"sqlite:///{path}"
        self._engine = create_engine(url, echo=False)
        _Base.metadata.create_all(self._engine)
        self._Session = sessionmaker(bind=self._engine)

    # ----- ingest ------------------------------------------------------ #

    def ingest(self, doc: MacroDoc) -> None:
        key = doc.doc_key or f"{doc.source}:{doc.title}:{doc.as_of}"
        with self._Session() as s:
            existing = s.query(MacroDocRow).filter(MacroDocRow.doc_key == key).first()
            if existing:
                existing.title = doc.title
                existing.body = doc.body
                existing.source = doc.source
                existing.tags = ",".join(doc.tags)
                existing.as_of = doc.as_of
                existing.ingested_at = datetime.utcnow()
            else:
                s.add(MacroDocRow(
                    doc_key=key, title=doc.title, body=doc.body, source=doc.source,
                    tags=",".join(doc.tags), as_of=doc.as_of, ingested_at=datetime.utcnow(),
                ))
            s.commit()

    def ingest_many(self, docs: List[MacroDoc]) -> int:
        for d in docs:
            self.ingest(d)
        return len(docs)

    def all_docs(self) -> List[MacroDoc]:
        with self._Session() as s:
            rows = s.query(MacroDocRow).all()
            return [
                MacroDoc(
                    title=r.title, body=r.body, source=r.source, as_of=r.as_of,
                    tags=tuple(t for t in (r.tags or "").split(",") if t), doc_key=r.doc_key,
                )
                for r in rows
            ]

    def count(self) -> int:
        with self._Session() as s:
            return s.query(MacroDocRow).count()

    def clear(self) -> None:
        with self._Session() as s:
            s.query(MacroDocRow).delete()
            s.commit()

    # ----- retrieval (TF-IDF cosine) ----------------------------------- #

    def retrieve(self, query: str, *, k: Optional[int] = None,
                 max_age_days: Optional[int] = None,
                 now: Optional[datetime] = None) -> List[Tuple[MacroDoc, float]]:
        k = k or MACRO_RAG.top_k
        max_age = MACRO_RAG.max_age_days if max_age_days is None else max_age_days
        docs = self.all_docs()
        if not docs:
            return []

        # Freshness gate: drop docs older than max_age (when dated).
        fresh = []
        for d in docs:
            age = _days_old(d.as_of, now)
            if age is None or age <= max_age:
                fresh.append(d)
        if not fresh:
            return []

        # Build IDF over the fresh corpus.
        doc_tokens = [_tokens(d.text) for d in fresh]
        df: Counter = Counter()
        for toks in doc_tokens:
            for t in set(toks):
                df[t] += 1
        n = len(fresh)
        idf = {t: math.log((n + 1) / (c + 1)) + 1.0 for t, c in df.items()}

        def vec(toks: List[str]) -> dict:
            tf = Counter(toks)
            return {t: (tf[t] / len(toks)) * idf.get(t, math.log(n + 1) + 1.0) for t in tf} if toks else {}

        q_vec = vec(_tokens(query))
        if not q_vec:
            return []

        scored: List[Tuple[MacroDoc, float]] = []
        for d, toks in zip(fresh, doc_tokens):
            d_vec = vec(toks)
            score = _cosine(q_vec, d_vec)
            if score >= MACRO_RAG.min_score:
                scored.append((d, round(score, 4)))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]

    # ----- context block ----------------------------------------------- #

    def build_context(self, query: str, *, k: Optional[int] = None,
                      now: Optional[datetime] = None) -> str:
        """Dated macro context block for prompt injection (empty string if none)."""
        if not MACRO_RAG.enabled:
            return ""
        hits = self.retrieve(query, k=k, now=now)
        if not hits:
            return ""
        lines = ["=== CONTEXTO MACRO RECIENTE (hechos fechados — usá ESTOS, no tu memoria) ==="]
        for doc, _score in hits:
            stamp = f"[{doc.as_of}]" if doc.as_of else "[s/f]"
            src = f" ({doc.source})" if doc.source else ""
            lines.append(f"- {stamp}{src} {doc.title}: {doc.body}")
        block = "\n".join(lines)
        if len(block) > MACRO_RAG.max_context_chars:
            block = block[: MACRO_RAG.max_context_chars].rsplit("\n", 1)[0] + "\n- […]"
        return block


def _cosine(a: dict, b: dict) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    num = sum(a[t] * b[t] for t in common)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return num / (na * nb)


# --------------------------------------------------------------------------- #
#  Ingest helpers                                                             #
# --------------------------------------------------------------------------- #

def example_macro_docs(as_of: Optional[str] = None) -> List[MacroDoc]:
    """A small offline seed set so the RAG works with no network/keys (demo/test).

    Dates default to *today* so the freshness gate passes; in production these are
    replaced by real FRED/Fed ingests.
    """
    today = as_of or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return [
        MacroDoc("Tasa de política de la Fed estable",
                 "La Reserva Federal mantuvo la tasa de fondos federales en el rango 4.25-4.50%, "
                 "señalando paciencia ante una inflación que baja lento.",
                 source="Fed (seed)", as_of=today, tags=("tasas", "fed", "us"), doc_key="seed:fed_funds"),
        MacroDoc("Inflación CPI en EE. UU.",
                 "El IPC interanual se ubicó en 2.9%, por encima del objetivo de 2% pero en tendencia "
                 "descendente; la inflación de servicios sigue rígida.",
                 source="FRED (seed)", as_of=today, tags=("inflacion", "cpi", "us"), doc_key="seed:cpi"),
        MacroDoc("Riesgo país y FX en Argentina",
                 "Persisten controles de cambio y brecha entre el dólar oficial y los paralelos; "
                 "la inflación argentina sigue alta y condiciona a los ADRs locales.",
                 source="seed", as_of=today, tags=("argentina", "fx", "riesgo pais", "adr"),
                 doc_key="seed:ar_fx"),
        MacroDoc("Precio del petróleo y energía",
                 "El barril de crudo se mantiene volátil por tensiones geopolíticas, afectando a "
                 "empresas de energía y costos de insumos.",
                 source="seed", as_of=today, tags=("energia", "petroleo", "commodities"),
                 doc_key="seed:oil"),
        MacroDoc("Condiciones de liquidez y tecnología",
                 "Las valuaciones del sector tecnológico siguen exigentes; tasas más altas por más "
                 "tiempo presionan los múltiplos de las acciones de crecimiento.",
                 source="seed", as_of=today, tags=("tecnologia", "valuacion", "tasas", "growth"),
                 doc_key="seed:tech_liquidity"),
    ]


def ingest_from_fred(store: MacroRagStore, series: Optional[dict] = None) -> int:
    """Best-effort ingest of latest FRED series values as dated macro docs.

    ``series`` maps ``series_id -> human title``. Requires FRED_API_KEY; returns
    the number of docs ingested (0 when no key / no network).
    """
    series = series or {
        "FEDFUNDS": "Tasa de fondos federales (FRED)",
        "CPIAUCSL": "Índice de precios al consumidor IPC (FRED)",
        "DGS10": "Rendimiento del bono del Tesoro a 10 años (FRED)",
    }
    try:
        from data.data_sources import FredSource

        fred = FredSource()
    except Exception:
        return 0

    docs: List[MacroDoc] = []
    for series_id, title in series.items():
        sv = fred.latest_series_value(series_id)
        if sv is None:
            continue
        docs.append(MacroDoc(
            title=title,
            body=f"Último valor reportado: {sv.value} (serie {series_id}).",
            source="FRED", as_of=sv.as_of or "", tags=("fred", "macro"),
            doc_key=f"fred:{series_id}:{sv.as_of}",
        ))
    if docs:
        store.ingest_many(docs)
    return len(docs)


def macro_query_for(fund) -> str:
    """Build a retrieval query from an asset's sector/country/profile."""
    parts = [
        getattr(fund, "sector", "") or "",
        getattr(fund, "industry", "") or "",
        getattr(fund, "company_name", "") or "",
    ]
    sym = (getattr(fund, "symbol", "") or "").upper()
    ar_adrs = {"YPF", "PAM", "CEPU", "LOMA", "MELI", "GLOB", "DESP", "TEO", "EDN", "GGAL", "BMA", "BBAR", "SUPV"}
    if sym in ar_adrs:
        parts.append("argentina riesgo país fx adr")
    parts.append("tasas inflación macro")
    return " ".join(p for p in parts if p)


# Module-level singleton (mirrors track_record_store / alert_store).
macro_rag_store = MacroRagStore()


def macro_context_for(fund, *, store: Optional[MacroRagStore] = None) -> str:
    """Convenience: dated macro context block relevant to ``fund`` (or "")."""
    store = store or macro_rag_store
    try:
        return store.build_context(macro_query_for(fund))
    except Exception as exc:
        logger.debug(f"macro_context_for failed — {exc}")
        return ""
