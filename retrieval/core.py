"""CORE v3 API. ~290M+ OA records from repositories/theses — the big UNIQUE open-access add.
Requires CORE_API_KEY (free at core.ac.uk/services/api). Without it -> empty + error.
"""
import os
import time
import logging
from typing import Optional, Tuple

from retrieval.base import BaseSource, Paper, SearchResult
from retrieval.http_client import ResilientClient
from retrieval.constants import CITATION_STATS, DEFAULT_CITATION_STATS

logger = logging.getLogger(__name__)


class CoreSource(BaseSource):
    BASE_URL = "https://api.core.ac.uk/v3"
    citation_stats = CITATION_STATS.get("CORE", DEFAULT_CITATION_STATS)

    def __init__(self, api_key=None, contact_email=None):
        super().__init__(api_key, contact_email)
        self.api_key = api_key or os.environ.get("CORE_API_KEY")
        self.client = ResilientClient(service_name="CORE", max_retries=3)

    @property
    def name(self) -> str:
        return "CORE"

    @property
    def rate_limit_per_minute(self) -> int:
        return 10

    def _paper(self, w: dict) -> Paper:
        authors = [a.get("name") for a in (w.get("authors") or [])[:10] if a.get("name")]
        return Paper(source=self.name, doi=w.get("doi"),
                     title=w.get("title") or "Untitled", authors=authors,
                     year=w.get("yearPublished"), journal=w.get("publisher"),
                     abstract=w.get("abstract"),
                     citation_count=w.get("citationCount", 0) or 0,
                     is_open_access=True, pdf_url=w.get("downloadUrl"))

    async def search(self, query, max_results=50, year_range=None, open_access_only=False) -> SearchResult:
        t = time.time()
        if not self.api_key:
            return SearchResult(source=self.name, error="CORE_API_KEY unset", search_time_seconds=0.0)
        q = query
        if year_range:
            q = f"{query} AND yearPublished>={year_range[0]} AND yearPublished<={year_range[1]}"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        body = {"q": q, "limit": min(max_results, 100), "offset": 0}
        try:
            r = await self.client.post(f"{self.BASE_URL}/search/works", headers=headers, json=body)
            data = r.json()
        except Exception as e:
            logger.error("CORE search error: %s", e)
            return SearchResult(source=self.name, error=str(e), search_time_seconds=time.time() - t)
        papers = [self._paper(w) for w in data.get("results", [])]
        return SearchResult(papers=papers, total_found=data.get("totalHits", len(papers)),
                            search_time_seconds=time.time() - t, source=self.name)

    async def get_by_doi(self, doi) -> Optional[Paper]:
        if not self.api_key:
            return None
        headers = {"Authorization": f"Bearer {self.api_key}"}
        body = {"q": f'doi:"{doi}"', "limit": 1, "offset": 0}
        try:
            r = await self.client.post(f"{self.BASE_URL}/search/works", headers=headers, json=body)
            res = (r.json() or {}).get("results") or []
            return self._paper(res[0]) if res else None
        except Exception:
            return None
