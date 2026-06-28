"""Google Patents via SerpApi (engine=google_patents). Patents = coverage outside AnswerThis's
corpus (chem/IP scouting). Same SERPAPI_API_KEY as Google Scholar; replaces the Lens.org route.
Patents have no DOI -> dedup by title. num must be 10..100; 1 search per page.
"""
import os
import time
import logging
import re
from typing import Optional, Tuple

from retrieval.base import BaseSource, Paper, SearchResult
from retrieval.http_client import ResilientClient
from retrieval.constants import CITATION_STATS, DEFAULT_CITATION_STATS

logger = logging.getLogger(__name__)
_YEAR = re.compile(r"(\d{4})")


class GooglePatentsSource(BaseSource):
    BASE_URL = "https://serpapi.com/search"
    citation_stats = CITATION_STATS.get("Google Patents", DEFAULT_CITATION_STATS)

    def __init__(self, api_key=None, contact_email=None):
        super().__init__(api_key, contact_email)
        self.api_key = api_key or os.environ.get("SERPAPI_API_KEY") or os.environ.get("SERPAPI_KEY")
        self.client = ResilientClient(service_name="Google Patents", max_retries=2)

    @property
    def name(self) -> str:
        return "Google Patents"

    @property
    def rate_limit_per_minute(self) -> int:
        return 60

    def _year(self, *dates):
        for d in dates:
            if d:
                m = _YEAR.match(str(d))
                if m:
                    return int(m.group(1))
        return None

    def _paper(self, it: dict) -> Paper:
        inv = it.get("inventor") or ""
        authors = [a.strip() for a in inv.split(",") if a.strip()][:10]
        assignee = it.get("assignee")
        year = self._year(it.get("publication_date"), it.get("grant_date"),
                          it.get("filing_date"), it.get("priority_date"))
        pubnum = (it.get("publication_number") or "").strip()
        label = f"Patent {pubnum}".strip()
        journal = " \u00b7 ".join(x for x in [label, assignee] if x and x != "Patent")
        return Paper(
            source=self.name, doi=None,
            title=it.get("title") or "Untitled",
            authors=authors, year=year, journal=journal or "Patent",
            abstract=it.get("snippet"),
            citation_count=0,
            is_open_access=True, pdf_url=it.get("pdf"),
        )

    async def search(self, query, max_results=50, year_range=None, open_access_only=False) -> SearchResult:
        t = time.time()
        if not self.api_key:
            return SearchResult(source=self.name, error="SERPAPI_API_KEY unset", search_time_seconds=0.0)
        params = {"engine": "google_patents", "q": query, "api_key": self.api_key,
                  "num": max(10, min(max_results, 100))}
        # TODO: year_range via before/after = publication:YYYYMMDD (format-sensitive).
        try:
            r = await self.client.get(self.BASE_URL, params=params)
            data = r.json()
        except Exception as e:
            logger.error("Google Patents search error: %s", e)
            return SearchResult(source=self.name, error=str(e), search_time_seconds=time.time() - t)
        if data.get("error"):
            return SearchResult(source=self.name, error=str(data["error"]), search_time_seconds=time.time() - t)
        papers = [self._paper(it) for it in data.get("organic_results", [])]
        return SearchResult(papers=papers, total_found=len(papers),
                            search_time_seconds=time.time() - t, source=self.name)

    async def get_by_doi(self, doi) -> Optional[Paper]:
        return None  # patents have no DOI
