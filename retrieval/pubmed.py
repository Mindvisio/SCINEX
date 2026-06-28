"""PubMed via NCBI E-utilities. ~38M biomed citations (mostly subset of OpenAlex; adds MeSH/recency).
esummary -> metadata (no abstract; abstract needs efetch, TODO). NCBI_API_KEY optional raises limits.
"""
import os
import time
import logging
from typing import Optional, Tuple

from retrieval.base import BaseSource, Paper, SearchResult
from retrieval.http_client import ResilientClient
from retrieval.constants import CITATION_STATS, DEFAULT_CITATION_STATS

logger = logging.getLogger(__name__)


class PubMedSource(BaseSource):
    BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    citation_stats = CITATION_STATS.get("PubMed", DEFAULT_CITATION_STATS)

    def __init__(self, api_key=None, contact_email=None):
        super().__init__(api_key, contact_email)
        self.api_key = api_key or os.environ.get("NCBI_API_KEY")
        self.client = ResilientClient(service_name="PubMed", max_retries=3)

    @property
    def name(self) -> str:
        return "PubMed"

    @property
    def rate_limit_per_minute(self) -> int:
        return 180 if self.api_key else 60

    def _common(self) -> dict:
        p = {"db": "pubmed", "retmode": "json", "tool": "scinex", "email": self.contact_email}
        if self.api_key:
            p["api_key"] = self.api_key
        return p

    def _paper(self, uid, rec: dict) -> Paper:
        authors = [a.get("name") for a in (rec.get("authors") or [])[:10] if a.get("name")]
        doi = None
        for aid in rec.get("articleids") or []:
            if aid.get("idtype") == "doi":
                doi = aid.get("value")
        year = None
        pd = rec.get("pubdate") or ""
        if pd[:4].isdigit():
            year = int(pd[:4])
        return Paper(source=self.name, pmid=str(uid), doi=doi,
                     title=rec.get("title") or "Untitled", authors=authors,
                     year=year, journal=rec.get("source"), abstract=None,
                     is_open_access=False)

    async def search(self, query, max_results=50, year_range=None, open_access_only=False) -> SearchResult:
        t = time.time()
        term = query
        if year_range:
            term = f"{query} AND ({year_range[0]}:{year_range[1]}[dp])"
        sp = self._common()
        sp.update({"term": term, "retmax": min(max_results, 100)})
        try:
            r = await self.client.get(f"{self.BASE_URL}/esearch.fcgi", params=sp)
            ids = (((r.json() or {}).get("esearchresult") or {}).get("idlist")) or []
            if not ids:
                return SearchResult(papers=[], total_found=0, source=self.name,
                                    search_time_seconds=time.time() - t)
            up = self._common()
            up["id"] = ",".join(ids)
            r2 = await self.client.get(f"{self.BASE_URL}/esummary.fcgi", params=up)
            res = (r2.json() or {}).get("result") or {}
        except Exception as e:
            logger.error("PubMed search error: %s", e)
            return SearchResult(source=self.name, error=str(e), search_time_seconds=time.time() - t)
        papers = [self._paper(uid, res[uid]) for uid in res.get("uids", []) if uid in res]
        return SearchResult(papers=papers, total_found=len(papers),
                            search_time_seconds=time.time() - t, source=self.name)

    async def get_by_doi(self, doi) -> Optional[Paper]:
        return None  # resolve DOI->PMID via OpenAlex/Crossref; TODO if needed
