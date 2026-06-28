"""arXiv API (Atom XML). ~2.4M preprints; mostly in OpenAlex but fastest for newest + LaTeX/PDF."""
import time
import logging
import xml.etree.ElementTree as ET
from typing import Optional, Tuple

from retrieval.base import BaseSource, Paper, SearchResult
from retrieval.http_client import ResilientClient
from retrieval.constants import CITATION_STATS, DEFAULT_CITATION_STATS

logger = logging.getLogger(__name__)
_NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


class ArxivSource(BaseSource):
    BASE_URL = "http://export.arxiv.org/api/query"
    citation_stats = CITATION_STATS.get("arXiv", DEFAULT_CITATION_STATS)

    def __init__(self, api_key=None, contact_email=None):
        super().__init__(api_key, contact_email)
        self.client = ResilientClient(service_name="arXiv", max_retries=3)

    @property
    def name(self) -> str:
        return "arXiv"

    @property
    def rate_limit_per_minute(self) -> int:
        return 20

    def _entry(self, e) -> Paper:
        def txt(p):
            x = e.find(p, _NS)
            return x.text.strip() if x is not None and x.text else None
        aid = (txt("a:id") or "").rsplit("/", 1)[-1]
        title = (txt("a:title") or "Untitled").replace("\n", " ")
        summary = txt("a:summary")
        if summary:
            summary = summary.replace("\n", " ").strip()
        year = None
        pub = txt("a:published")
        if pub and len(pub) >= 4 and pub[:4].isdigit():
            year = int(pub[:4])
        authors = [a.findtext("a:name", default="", namespaces=_NS).strip()
                   for a in e.findall("a:author", _NS)][:10]
        authors = [a for a in authors if a]
        pdf = None
        for link in e.findall("a:link", _NS):
            if link.get("title") == "pdf" or link.get("type") == "application/pdf":
                pdf = link.get("href")
        return Paper(source=self.name, arxiv_id=aid, doi=txt("arxiv:doi"),
                     title=title, authors=authors, year=year, journal="arXiv",
                     abstract=summary, is_open_access=True,
                     pdf_url=pdf or f"https://arxiv.org/pdf/{aid}")

    async def search(self, query, max_results=50, year_range=None, open_access_only=False) -> SearchResult:
        t = time.time()
        params = {"search_query": f"all:{query}", "start": 0,
                  "max_results": min(max_results, 100), "sortBy": "relevance"}
        try:
            r = await self.client.get(self.BASE_URL, params=params)
            root = ET.fromstring(r.text)
        except Exception as e:
            logger.error("arXiv search error: %s", e)
            return SearchResult(source=self.name, error=str(e), search_time_seconds=time.time() - t)
        papers = [self._entry(e) for e in root.findall("a:entry", _NS)]
        if year_range:
            papers = [p for p in papers if p.year and year_range[0] <= p.year <= year_range[1]]
        return SearchResult(papers=papers, total_found=len(papers),
                            search_time_seconds=time.time() - t, source=self.name)

    async def get_by_doi(self, doi) -> Optional[Paper]:
        return None  # arXiv search is not DOI-indexed; use OpenAlex/Crossref for DOI lookup
