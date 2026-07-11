"""
Sector-Country Structural Tailwind Analysis (Idea 2 — "colas de viento").

Captures multi-year structural outlooks for specific sectors in specific
countries — the canonical motivating case: Argentine oil & gas benefiting from
the Vaca Muerta ramp (YPF, PAM, CEPU…) for 7-15 years, something financial
statements lag and generic macro prompts under-serve.

Architecture (mirrors the proven MoatAnalyzer pattern):

  CURATED BASE (always computed, no API cost):
    A small, human-maintained JSON file (``data/tailwinds/sector_country.json``)
    is the single source of truth. Matching precedence per ticker:
      1. explicit ticker override        (highest precision)
      2. (industry, country) match
      3. (sector, country) match         (entries without an ``industry`` field)
    No match (or missing country/sector data) → Neutral, bonus = 0 — the
    deterministic no-tailwind path is byte-identical to pre-feature behavior.

  AI QUALITATIVE (optional, cached 30 days per ticker):
    The LLM receives the curated tailwind as INPUT and only interprets/enriches
    it for the specific company (2-4 sentence reasoning + 0-2 structured
    factors). It never invents tailwinds and never changes the curated score —
    score/bonus stay deterministic and auditable.

  CLASSIFICATION (score -5 … +10, thresholds in config.TAILWINDS):
    Strong   ≥ +6   — e.g. Argentina Energy / Vaca Muerta
    Moderate ≥ +3   — real but partially priced-in (e.g. US Tech AI capex)
    Headwind ≤ −2   — structural drag (e.g. AR regulated electric distribution)
    Neutral  otherwise

  BONUS applied to FundamentalResult.adjusted_score:
    clamp(score × bonus_factor, −max_bonus, +max_bonus) → default max ±8 pts,
    intentionally smaller than the moat cap so fundamentals always dominate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from config import BASE_DIR, TAILWINDS, AIConfig, TailwindConfig

# ------------------------------------------------------------------ #
#  Data class                                                          #
# ------------------------------------------------------------------ #

@dataclass
class TailwindDetail:
    """
    Full breakdown of a (sector, country) structural tailwind for one ticker.

    Curated fields (always populated, no API cost):
      tailwind_score     -5…+10  curated structural outlook score
      classification     str     Strong | Moderate | Neutral | Headwind
      bonus              float   clamp(score × factor, ±max_bonus) — added to adjusted_score
      durability_years   int     estimated years the outlook should last
      explanation        str     curated human-readable rationale
      matched_key        str     id of the curated entry ("" = no match → Neutral)
      matched_on         str     "ticker" | "industry" | "sector" | ""
      last_reviewed      str     YYYY-MM of last human review of the entry

    AI qualitative fields (populated only when ai_available=True):
      ai_reasoning       str     LLM interpretation for this specific company
      factors            list    0-2 structured factor dicts (factor/why/impact/effect)
      ai_available       bool    True when AI enrichment succeeded (fresh or cached)
    """

    tailwind_score: float = 0.0
    classification: str = "Neutral"
    bonus: float = 0.0
    durability_years: int = 0
    explanation: str = ""
    matched_key: str = ""
    matched_on: str = ""
    last_reviewed: str = ""

    ai_reasoning: str = ""
    factors: List[Dict[str, Any]] = field(default_factory=list)
    ai_available: bool = False

    @property
    def emoji(self) -> str:
        return {
            "Strong":   "🌬️",
            "Moderate": "🍃",
            "Neutral":  "⚪",
            "Headwind": "🌪️",
        }.get(self.classification, "⚪")

    @property
    def color(self) -> str:
        return {
            "Strong":   "#00C851",
            "Moderate": "#39b54a",
            "Neutral":  "#888888",
            "Headwind": "#ff4444",
        }.get(self.classification, "#888888")

    @property
    def label_es(self) -> str:
        return {
            "Strong":   "Cola de viento fuerte",
            "Moderate": "Cola de viento moderada",
            "Neutral":  "Neutral",
            "Headwind": "Viento de frente",
        }.get(self.classification, "Neutral")


# ------------------------------------------------------------------ #
#  Pure functions (unit-testable without I/O)                          #
# ------------------------------------------------------------------ #

def classify_tailwind(score: float, config: Optional[TailwindConfig] = None) -> str:
    """Map a tailwind score (-5…+10) to a classification label."""
    cfg = config or TAILWINDS
    if score >= cfg.strong_threshold:
        return "Strong"
    if score >= cfg.moderate_threshold:
        return "Moderate"
    if score <= cfg.headwind_threshold:
        return "Headwind"
    return "Neutral"


def compute_tailwind_bonus(score: float, config: Optional[TailwindConfig] = None) -> float:
    """Capped additive bonus (can be negative for headwinds). Neutral score → 0."""
    cfg = config or TAILWINDS
    raw = score * cfg.bonus_factor
    return round(max(-cfg.max_bonus, min(cfg.max_bonus, raw)), 1)


# ------------------------------------------------------------------ #
#  Curated data loader (module-level cache, tiny file)                 #
# ------------------------------------------------------------------ #

_CURATED_CACHE: Dict[str, List[dict]] = {}


def load_curated_tailwinds(path: Optional[Path] = None) -> List[dict]:
    """Load (and memoize) the curated tailwind entries.

    Returns [] on any problem (missing file, bad JSON) — the analyzer then
    yields Neutral for everything, preserving pre-feature behavior.
    """
    p = Path(path) if path is not None else (BASE_DIR / TAILWINDS.data_file)
    key = str(p)
    if key in _CURATED_CACHE:
        return _CURATED_CACHE[key]
    entries: List[dict] = []
    try:
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            raw = data.get("entries", []) if isinstance(data, dict) else []
            entries = [e for e in raw if isinstance(e, dict)]
    except Exception as exc:
        logger.warning(f"Could not load curated tailwinds from {p}: {exc} — all Neutral")
        entries = []
    _CURATED_CACHE[key] = entries
    return entries


def invalidate_curated_cache() -> None:
    """Clear the in-memory curated-data cache (tests / after manual edits)."""
    _CURATED_CACHE.clear()


# ------------------------------------------------------------------ #
#  Analyzer                                                            #
# ------------------------------------------------------------------ #

class TailwindAnalyzer:
    """
    Evaluates the structural sector-country tailwind for a ticker.

    Usage:
        analyzer = TailwindAnalyzer()

        # Curated only (fast, no API, always available):
        tw = analyzer.analyze(symbol, sector=fund.sector,
                              country=info.get("country", ""), industry=fund.industry)

        # Optional AI qualitative enrichment (cached 30 days):
        tw = analyzer.analyze_with_ai(tw, symbol, info, ai_config)

    Conservative guarantees:
      - config.TAILWINDS.enabled=False → always Neutral / bonus 0 everywhere.
      - No curated match → Neutral / bonus 0 (identical to pre-feature numbers).
      - AI failure never corrupts the result — curated base always returned.
      - The AI layer never modifies score/classification/bonus.
    """

    def __init__(
        self,
        data_path: Optional[Path] = None,
        config: Optional[TailwindConfig] = None,
    ) -> None:
        self.cfg = config or TAILWINDS
        self.data_path = data_path  # None → config default
        self._cache = None  # lazy-init SQLite cache (avoids import cycle)

    def _get_cache(self):
        if self._cache is None:
            from data.cache import DataCache
            self._cache = DataCache(ttl_hours=self.cfg.ai_cache_ttl_hours)
        return self._cache

    # ------------------------------------------------------------------ #
    #  Curated analysis (always fast, no API)                             #
    # ------------------------------------------------------------------ #

    def analyze(
        self,
        symbol: str,
        sector: str = "",
        country: str = "",
        industry: str = "",
        info: Optional[dict] = None,
    ) -> TailwindDetail:
        """Compute the curated tailwind. Graceful for missing data (→ Neutral)."""
        detail = TailwindDetail()
        if not self.cfg.enabled:
            return detail

        if info:
            country = country or (info.get("country") or "")
            sector = sector or (info.get("sector") or "")
            industry = industry or (info.get("industry") or "")

        entry, matched_on = self._match(symbol, sector, country, industry)
        if entry is None:
            return detail  # Neutral — strict pre-feature subset

        try:
            score = float(entry.get("score", 0.0) or 0.0)
        except (TypeError, ValueError):
            score = 0.0

        detail.tailwind_score = round(score, 1)
        detail.classification = classify_tailwind(score, self.cfg)
        detail.bonus = compute_tailwind_bonus(score, self.cfg)
        try:
            detail.durability_years = int(entry.get("durability_years", 0) or 0)
        except (TypeError, ValueError):
            detail.durability_years = 0
        detail.explanation = str(entry.get("rationale", "") or "")
        detail.matched_key = str(entry.get("key", "") or "")
        detail.matched_on = matched_on
        detail.last_reviewed = str(entry.get("last_reviewed", "") or "")

        logger.debug(
            f"{symbol}: tailwind {detail.classification} "
            f"({detail.tailwind_score:+.1f}, bonus {detail.bonus:+.1f}, via {matched_on})"
        )
        return detail

    def _match(
        self, symbol: str, sector: str, country: str, industry: str
    ) -> Tuple[Optional[dict], str]:
        """Resolve the curated entry: ticker > (industry, country) > (sector, country)."""
        entries = load_curated_tailwinds(self.data_path)
        if not entries:
            return None, ""

        sym = (symbol or "").upper().strip()
        c = (country or "").strip().lower()
        s = (sector or "").strip().lower()
        i = (industry or "").strip().lower()

        # 1. Explicit ticker override (works even without country data)
        for e in entries:
            tickers = {str(t).upper().strip() for t in (e.get("tickers") or [])}
            if sym and sym in tickers:
                return e, "ticker"

        if not c:
            return None, ""

        # 2. (industry, country)
        if i:
            for e in entries:
                e_ind = str(e.get("industry", "") or "").strip().lower()
                e_cty = str(e.get("country", "") or "").strip().lower()
                if e_ind and e_ind == i and e_cty == c:
                    return e, "industry"

        # 3. (sector, country) — only entries that do NOT pin a specific industry
        if s:
            for e in entries:
                if e.get("industry"):
                    continue
                e_sec = str(e.get("sector", "") or "").strip().lower()
                e_cty = str(e.get("country", "") or "").strip().lower()
                if e_sec and e_sec == s and e_cty == c:
                    return e, "sector"

        return None, ""

    # ------------------------------------------------------------------ #
    #  Optional AI qualitative enrichment (cached, graceful failure)      #
    # ------------------------------------------------------------------ #

    def analyze_with_ai(
        self,
        base_result: TailwindDetail,
        symbol: str,
        info: dict,
        ai_config: AIConfig,
    ) -> TailwindDetail:
        """Enrich a curated TailwindDetail with LLM interpretation.

        Cached per (symbol, provider, model) for ai_cache_ttl_hours. On any
        failure the curated base is returned unchanged. Neutral tickers are
        never sent to the LLM (nothing to interpret — saves tokens).
        """
        if not self.cfg.enabled or base_result.classification == "Neutral":
            return base_result
        if not ai_config or not getattr(ai_config, "enabled", False):
            return base_result

        cache_key = f"tailwind_ai_{symbol}_{ai_config.provider}_{ai_config.model}"
        try:
            cached = self._get_cache().get(cache_key)
        except Exception:
            cached = None
        if cached:
            base_result.ai_reasoning = str(cached.get("ai_reasoning", "") or "")
            base_result.factors = cached.get("factors", []) or []
            base_result.ai_available = bool(base_result.ai_reasoning)
            return base_result

        try:
            from analysis.moat import call_ai_api  # shared provider dispatch
            from analysis.prompts import sector_country_tailwind_prompt
            from analysis.utils import extract_json_object

            prompt = sector_country_tailwind_prompt(base_result, symbol, info or {})
            raw = call_ai_api(prompt, ai_config)
            text = raw.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(ln for ln in lines if not ln.startswith("```")).strip()
            data = extract_json_object(text)

            reasoning = str(data.get("ai_reasoning", "") or data.get("reasoning", "") or "")
            factors = data.get("factors", [])
            if not isinstance(factors, list):
                factors = []
            base_result.ai_reasoning = reasoning
            base_result.factors = factors[:2]
            base_result.ai_available = bool(reasoning)

            if base_result.ai_available:
                try:
                    self._get_cache().set(cache_key, {
                        "ai_reasoning": base_result.ai_reasoning,
                        "factors":      base_result.factors,
                    })
                except Exception:
                    pass
                logger.info(f"{symbol}: tailwind AI enrichment OK ({ai_config.model})")
        except Exception as exc:
            logger.warning(f"{symbol}: tailwind AI enrichment failed — {exc}")
            # Curated base returned unchanged — graceful degradation.

        return base_result
