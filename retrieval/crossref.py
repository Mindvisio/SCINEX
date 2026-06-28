"""Crossref REST API. ~155M DOIs (mostly subset of OpenAlex; cheap, solid metadata)."""
import time
import logging
import re
from typing import Optional, Tuple

from retrieval.base import BaseSource, Paper, SearchResult
from retrieval.http_client import ResilientClient
from retrieval.constants import CITATION_STATS, DEFAULT_CITATION_STATS

logger = logging.getLogger(__name__)
_TAG = re.compile(r"<[^>]+>")


class CrossrefSource(BaseSource):
    BASE_URL = "https://api.crossref.org"
    citation_stats = CITATION_STATS.get("Crossref", DEFAULT_CITATION_STATS)

    def __init__(self, api_key=None, contact_email=None):
        super().__init__(api_key, contact_email)
        self.client = ResilientClient(service_name="Crossref", max_retries=3)

    @property
    def name(self) -> str:
        return "Crossref"

    @property
    def rate_limit_per_minute(self) -> int:
        return 50

    def _paper(self, it: dict) -> Paper:
        authors = [" ".join(x for x in [a.get("given"), a.get("family")] if x)
                   for a in (it.get("author") or [])[:10]]
        authors = [a for a in authors if a]
        year = None
        dp = ((it.get("issued") or {}).get("date-parts") or [[None]])[0]
        if dp and dp[0]:
            year = dp[0]
        ab = it.get("abstract")
        if ab:
            ab = _TAG.sub("", ab).strip()
        title = it.get("title") or ["Untitled"]
        return Paper(
            source=self.name, doi=it.get("DOI"),
            title=(title[0] if title else "Untitled"),
            authors=authors, year=year,
            journal=((it.get("container-title") or [None])[0]),
            abstract=ab, citation_count=it.get("is-referenced-by-count", 0) or 0,
            is_open_access=False,
        )

    async def search(self, query, max_results=50, year_range=None, open_access_only=False) -> SearchResult:
        t = time.time()
        params = {"query": query, "rows": min(max_results, 100),
                  "select": "DOI,title,author,issued,container-title,abstract,is-referenced-by-count"}
        flt = []
        if year_range:
            flt.append(f"from-pub-date:{year_range[0]}-01-01")
            flt.append(f"until-pub-date:{year_range[1]}-12-31")
        if flt:
            params["filter"] = ",".join(flt)
        headers = {"User-Agent": f"scinex/0.1 (mailto:{self.contact_email})"}
        try:
            r = await self.client.get(f"{self.BASE_URL}/works", params=params, headers=headers)
            data = r.json()
        except Exception as e:
            logger.error("Crossref search error: %s", e)
            return SearchResult(source=self.name, error=str(e), search_time_seconds=time.time() - t)
        msg = data.get("message") or {}
        papers = [self._paper(it) for it in msg.get("items", [])]
        return SearchResult(papers=papers, total_found=msg.get("total-results", len(papers)),
                            search_time_seconds=time.time() - t, source=self.name)

    async def get_by_doi(self, doi) -> Optional[Paper]:
        headers = {"User-Agent": f"scinex/0.1 (mailto:{self.contact_email})"}
        try:
            r = await self.client.get(f"{self.BASE_URL}/works/{doi}", headers=headers)
            return self._paper((r.json() or {}).get("message") or {})
        except Exception:
            return None
