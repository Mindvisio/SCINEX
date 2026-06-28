"""Google Scholar via SerpApi. Scholar has no official API; SerpApi scrapes it.
Key-gated (SERPAPI_API_KEY). Records are DOI-less (Scholar gives no DOI) -> dedup by title.
Metered: 1 search = 1 results page (num<=20). Frugal: one page per query, no auto-pagination.
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
_YEAR = re.compile(r"\b(19|20)\d{2}\b")


class GoogleScholarSource(BaseSource):
    BASE_URL = "https://serpapi.com/search"
    citation_stats = CITATION_STATS.get("Google Scholar", DEFAULT_CITATION_STATS)

    def __init__(self, api_key=None, contact_email=None):
        super().__init__(api_key, contact_email)
        self.api_key = api_key or os.environ.get("SERPAPI_API_KEY") or os.environ.get("SERPAPI_KEY")
        self.client = ResilientClient(service_name="Google Scholar", max_retries=2)

    @property
    def name(self) -> str:
        return "Google Scholar"

    @property
    def rate_limit_per_minute(self) -> int:
        return 60

    def _parse_summary(self, summary):
        """'A Author, B Author - Journal, Year - publisher' -> (authors, journal, year)."""
        authors, journal, year = [], None, None
        if summary:
            m = _YEAR.search(summary)
            if m:
                year = int(m.group(0))
            parts = [p.strip() for p in summary.split(" - ")]
            if parts:
                authors = [a.strip() for a in parts[0].split(",") if a.strip()][:10]
            if len(parts) >= 2:
                journal = re.sub(r",?\s*(19|20)\d{2}.*$", "", parts[1]).strip() or None
        return authors, journal, year

    def _paper(self, it: dict) -> Paper:
        pi = it.get("publication_info") or {}
        authors, journal, year = self._parse_summary(pi.get("summary"))
        if pi.get("authors"):
            authors = [a.get("name") for a in pi["authors"][:10] if a.get("name")] or authors
        pdf = None
        for res in it.get("resources") or []:
            fmt = (res.get("file_format") or "").upper()
            link = res.get("link") or ""
            if fmt == "PDF" or link.lower().endswith(".pdf"):
                pdf = link
                break
        cited = ((it.get("inline_links") or {}).get("cited_by") or {}).get("total", 0) or 0
        return Paper(
            source=self.name, doi=None,
            title=it.get("title") or "Untitled",
            authors=authors, year=year, journal=journal,
            abstract=it.get("snippet"),
            citation_count=cited,
            is_open_access=bool(pdf), pdf_url=pdf,
        )

    async def search(self, query, max_results=50, year_range=None, open_access_only=False) -> SearchResult:
        t = time.time()
        if not self.api_key:
            return SearchResult(source=self.name, error="SERPAPI_API_KEY unset", search_time_seconds=0.0)
        params = {"engine": "google_scholar", "q": query, "api_key": self.api_key,
                  "num": min(max_results, 20)}
        if year_range:
            params["as_ylo"] = year_range[0]
            params["as_yhi"] = year_range[1]
        try:
            r = await self.client.get(self.BASE_URL, params=params)
            data = r.json()
        except Exception as e:
            logger.error("Google Scholar search error: %s", e)
            return SearchResult(source=self.name, error=str(e), search_time_seconds=time.time() - t)
        if data.get("error"):
            return SearchResult(source=self.name, error=str(data["error"]), search_time_seconds=time.time() - t)
        papers = [self._paper(it) for it in data.get("organic_results", [])]
        return SearchResult(papers=papers, total_found=len(papers),
                            search_time_seconds=time.time() - t, source=self.name)

    async def get_by_doi(self, doi) -> Optional[Paper]:
        return None  # Scholar is not DOI-indexed
