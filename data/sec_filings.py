"""SEC EDGAR *text* retrieve for the filing evidence pack (ideas 5 + 9).

Sibling of ``SecEdgarSource`` (XBRL numbers). This module never scores.
Any failure returns an empty pack — same degrade-quietly contract as XBRL.
"""

from __future__ import annotations

import html as html_lib
import re
from datetime import date
from typing import Callable, List, Optional

from loguru import logger

from analysis.filing_evidence import (
    FilingEvidencePack,
    FilingSnippet,
    empty_pack,
    pack_from_dict,
    pack_to_dict,
)

_HttpGet = Callable[[str], Optional[str]]
_ResolveCik = Callable[[str], Optional[int]]

_ITEM_SPLIT = re.compile(r"(?im)(?=^\s*ITEM\s+\d+[A-Z]?(?:\.\d+)*)")
_ITEM_HEAD = re.compile(r"(?im)^\s*ITEM\s+(\d+[A-Z]?(?:\.\d+)*)\s*[.\-:]?\s*(.*)$")

# Item 1 / 1A → moat. Item 7 MD&A and 8-K items → catalyst.
_MOAT_ITEMS = {"1", "1A"}
_CATALYST_ITEMS = {"7"}


def _html_to_text(raw: str) -> str:
    text = re.sub(r"(?is)<script[\s\S]*?</script>", " ", raw or "")
    text = re.sub(r"(?is)<style[\s\S]*?</style>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n", text)
    text = re.sub(r"(?i)</div>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_item_section(html: str, item: str) -> str:
    """Pull the body of ``ITEM {item}`` from a 10-K/10-Q HTML document.

    Oracle: the section contains its own prose and stops before the next ITEM.
    """
    text = _html_to_text(html)
    want = item.strip().upper().lstrip("0") or item.strip().upper()
    chunks = _ITEM_SPLIT.split(text)
    for chunk in chunks:
        m = _ITEM_HEAD.match(chunk.strip())
        if not m:
            continue
        found = m.group(1).upper().lstrip("0") or m.group(1).upper()
        if found == want:
            body = chunk[m.end() :].strip()
            return body
    return ""


def _parse_filed(raw: str) -> Optional[date]:
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _default_http_get(url: str) -> Optional[str]:
    import requests

    from config import FETCH, MULTI_SOURCE

    attempts = max(1, int(FETCH.max_retries))
    headers = {"User-Agent": MULTI_SOURCE.sec_user_agent}
    timeout = float(MULTI_SOURCE.request_timeout_s)
    last_exc: Optional[Exception] = None
    for _ in range(attempts):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code != 200:
                last_exc = RuntimeError(f"HTTP {resp.status_code}")
                continue
            resp.encoding = resp.encoding or "utf-8"
            return resp.text
        except Exception as exc:  # noqa: BLE001 — degrade to empty pack
            last_exc = exc
    if last_exc:
        logger.debug(f"sec_filings: GET failed {url} — {last_exc}")
    return None


def _default_resolve_cik(symbol: str) -> Optional[int]:
    from data.data_sources import SecEdgarSource

    return SecEdgarSource()._resolve_cik(symbol)


def _recent_rows(payload: dict) -> List[dict]:
    recent = ((payload.get("filings") or {}).get("recent")) or {}
    forms = recent.get("form") or []
    n = len(forms)
    acc = recent.get("accessionNumber") or [""] * n
    filed = recent.get("filingDate") or [""] * n
    primary = recent.get("primaryDocument") or [""] * n
    rows = []
    for i in range(n):
        rows.append(
            {
                "form": str(forms[i] or ""),
                "accession": str(acc[i] if i < len(acc) else ""),
                "filed": str(filed[i] if i < len(filed) else ""),
                "primary": str(primary[i] if i < len(primary) else ""),
            }
        )
    return rows


def _first_form(rows: List[dict], prefix: str) -> Optional[dict]:
    for row in rows:
        form = (row.get("form") or "").upper()
        if form == prefix or form.startswith(prefix + "/"):
            return row
        if prefix == "10-K" and form.startswith("10-K"):
            return row
        if prefix == "10-Q" and form.startswith("10-Q"):
            return row
        if prefix == "8-K" and form.startswith("8-K"):
            return row
    return None


def _document_url(cik: int, accession: str, primary: str) -> str:
    acc = (accession or "").replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{primary}"


def _clip(text: str, max_chars: int) -> str:
    t = (text or "").strip()
    if len(t) <= max_chars:
        return t
    return t[: max(0, max_chars - 1)].rstrip() + "…"


def _kind_for_item(item: str, form: str) -> str:
    token = (item or "").upper().replace("ITEM", "").strip()
    token = token.split()[0] if token else ""
    token = token.rstrip(".")
    if form.upper().startswith("8-K"):
        return "catalyst"
    if form.upper().startswith("10-Q") and token in {"2", "7"}:
        return "catalyst"
    if token in _CATALYST_ITEMS or token.startswith("7"):
        return "catalyst"
    return "moat"


def _snippets_from_html(
    *,
    html: str,
    form: str,
    filed: Optional[date],
    accession: str,
    max_chars: int,
    items: tuple,
) -> List[FilingSnippet]:
    out: List[FilingSnippet] = []
    if form.upper().startswith("8-K"):
        text = _clip(_html_to_text(html), max_chars)
        if text:
            item_m = _ITEM_HEAD.search(_html_to_text(html))
            item = f"Item {item_m.group(1)}" if item_m else "8-K"
            out.append(
                FilingSnippet(
                    form=form,
                    filed=filed,
                    accession=accession,
                    item=item,
                    kind="catalyst",
                    text=text,
                )
            )
        return out
    for item in items:
        body = extract_item_section(html, item)
        if not body:
            continue
        kind = _kind_for_item(item, form)
        out.append(
            FilingSnippet(
                form=form,
                filed=filed,
                accession=accession,
                item=f"Item {item}",
                kind=kind,
                text=_clip(body, max_chars),
            )
        )
    return out


def retrieve_filing_pack(
    symbol: str,
    *,
    is_crypto: bool = False,
    http_get: Optional[_HttpGet] = None,
    resolve_cik: Optional[_ResolveCik] = None,
    config=None,
    use_cache: bool = True,
) -> FilingEvidencePack:
    """Return a pack. Never raises. Empty on crypto / no CIK / fetch failure."""
    from config import FILING_EVIDENCE

    cfg = config or FILING_EVIDENCE
    symbol = (symbol or "").upper()
    if is_crypto:
        return empty_pack(symbol, "crypto")
    if not getattr(cfg, "enabled", True):
        return empty_pack(symbol, "disabled")

    getter = http_get or _default_http_get
    cik_fn = resolve_cik or _default_resolve_cik

    if use_cache:
        try:
            from data.cache import DataCache

            store = DataCache(ttl_hours=int(cfg.cache_ttl_hours))
            cached = store.get(f"sec_filings:{symbol}")
            if isinstance(cached, dict):
                return pack_from_dict(cached)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"sec_filings: cache read {symbol} — {exc}")

    try:
        cik = cik_fn(symbol)
        if not cik:
            pack = empty_pack(symbol, "no_cik")
        else:
            pack = _retrieve_uncached(symbol, int(cik), getter, cfg)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"sec_filings: retrieve {symbol} — {exc}")
        pack = empty_pack(symbol, "fetch_failed")

    if use_cache:
        try:
            from data.cache import DataCache

            DataCache(ttl_hours=int(cfg.cache_ttl_hours)).set(
                f"sec_filings:{symbol}", pack_to_dict(pack)
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"sec_filings: cache write {symbol} — {exc}")
    return pack


def _retrieve_uncached(symbol: str, cik: int, getter: _HttpGet, cfg) -> FilingEvidencePack:
    import json

    sub_url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
    raw = getter(sub_url)
    if not raw:
        return empty_pack(symbol, "fetch_failed")
    try:
        payload = json.loads(raw)
    except ValueError:
        return empty_pack(symbol, "fetch_failed")

    rows = _recent_rows(payload)
    if not rows:
        return empty_pack(symbol, "no_filings")

    max_chars = int(cfg.max_snippet_chars)
    max_snips = int(cfg.max_snippets)
    snippets: List[FilingSnippet] = []

    for prefix, items in (("10-K", ("1", "1A", "7")), ("10-Q", ("2", "1A", "7"))):
        row = _first_form(rows, prefix)
        if not row or not row.get("primary"):
            continue
        url = _document_url(cik, row["accession"], row["primary"])
        html = getter(url)
        if not html:
            continue
        snippets.extend(
            _snippets_from_html(
                html=html,
                form=row["form"] or prefix,
                filed=_parse_filed(row.get("filed") or ""),
                accession=row.get("accession") or "",
                max_chars=max_chars,
                items=items,
            )
        )
        if len(snippets) >= max_snips:
            break

    if getattr(cfg, "include_8k", True):
        taken = 0
        max_8k = int(getattr(cfg, "max_8k", 3))
        for row in rows:
            if taken >= max_8k or len(snippets) >= max_snips:
                break
            form = (row.get("form") or "").upper()
            if not form.startswith("8-K") or not row.get("primary"):
                continue
            url = _document_url(cik, row["accession"], row["primary"])
            html = getter(url)
            if not html:
                continue
            snippets.extend(
                _snippets_from_html(
                    html=html,
                    form=row["form"] or "8-K",
                    filed=_parse_filed(row.get("filed") or ""),
                    accession=row.get("accession") or "",
                    max_chars=max_chars,
                    items=(),
                )
            )
            taken += 1

    snippets = snippets[:max_snips]
    if not snippets:
        return empty_pack(symbol, "no_filings")
    return FilingEvidencePack(symbol=symbol, snippets=snippets, empty_reason="")
