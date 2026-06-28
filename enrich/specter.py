"""SPECTER2 paper embeddings via Semantic Scholar API (the 'cheat' — no local model).

S2 is an open API (no RU proxy needed). Optional S2 API key raises rate limits.
Batch endpoint takes up to 500 ids. Returns vectors (768-d) or None on miss.
"""
from __future__ import annotations
import os
from typing import Optional

import httpx

from config import S2_BASE

_FIELDS = "embedding.specter_v2"


def _headers() -> dict:
    k = os.environ.get("S2_API_KEY") or os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
    return {"x-api-key": k} if k else {}


def _sid(doi_or_id: str) -> str:
    """Build an S2 paper id. Accepts raw DOI, prefixed id, or S2 id."""
    s = doi_or_id.strip()
    if s.lower().startswith(("doi:", "arxiv:", "pmid:", "corpusid:", "mag:")):
        return s
    if "/" in s and not s.startswith("http"):
        return f"DOI:{s}"
    return s


def get_specter2(doi_or_id: str, *, timeout: float = 30.0) -> Optional[list]:
    url = f"{S2_BASE}/paper/{_sid(doi_or_id)}"
    try:
        r = httpx.get(url, params={"fields": _FIELDS}, headers=_headers(), timeout=timeout)
        r.raise_for_status()
        emb = (r.json() or {}).get("embedding") or {}
        return emb.get("vector")
    except Exception:
        return None


def get_specter2_batch(ids: list, *, timeout: float = 60.0) -> dict:
    """Map input id -> vector (or None). Uses the S2 batch endpoint (<=500 ids)."""
    out = {i: None for i in ids}
    if not ids:
        return out
    try:
        r = httpx.post(
            f"{S2_BASE}/paper/batch",
            params={"fields": _FIELDS},
            json={"ids": [_sid(i) for i in ids]},
            headers=_headers(),
            timeout=timeout,
        )
        r.raise_for_status()
        for inp, item in zip(ids, r.json() or []):
            if item:
                out[inp] = (item.get("embedding") or {}).get("vector")
    except Exception:
        pass
    return out
