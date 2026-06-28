"""
Semantic Scholar API Source
https://api.semanticscholar.org/api-docs/graph
Coverage: ~220M papers (CS, biomedical focus)
"""

import os
import time
import logging
from typing import Optional, Tuple

from httpx import HTTPStatusError

from retrieval.base import BaseSource, Paper, SearchResult
from retrieval.http_client import ResilientClient
from retrieval.constants import CitationStats, CITATION_STATS

logger = logging.getLogger(__name__)


class SemanticScholarSource(BaseSource):
    """Semantic Scholar data source (~220M papers)"""
    
    BASE_URL = "https://api.semanticscholar.org/graph/v1"
    
    # Semantic Scholar focuses on CS and biomedical, with moderate coverage
    citation_stats = CITATION_STATS["Semantic Scholar"]
    
    def __init__(self, api_key: Optional[str] = None, contact_email: Optional[str] = None):
        super().__init__(api_key, contact_email)
        self.api_key = self.api_key or os.environ.get("S2_API_KEY") or os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
        self.client = ResilientClient(
            service_name="SemanticScholar",
            max_retries=3,
            use_proxy=True,  # S2 geoblocks RU IP -> route via proxy
        )
    
    @property
    def name(self) -> str:
        return "Semantic Scholar"
    
    @property
    def rate_limit_per_minute(self) -> int:
        # 100 per 5 min without key = ~20/min
        # With API key: 100/min
        return 100 if self.api_key else 20
    
    async def search(
        self,
        query: str,
        max_results: int = 50,
        year_range: Optional[Tuple[int, int]] = None,
        open_access_only: bool = False
    ) -> SearchResult:
        """Search Semantic Scholar for papers"""
        start_time = time.time()
        
        headers = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        
        params = {
            "query": query,
            "limit": min(max_results, 100),
            "fields": "paperId,externalIds,title,authors,year,venue,abstract,citationCount,isOpenAccess,openAccessPdf"
        }
        
        if year_range:
            params["year"] = f"{year_range[0]}-{year_range[1]}"
        
        if open_access_only:
            params["openAccessPdf"] = ""
        
        try:
            response = await self.client.get(
                f"{self.BASE_URL}/paper/search",
                params=params,
                headers=headers
            )
            data = response.json()
        except HTTPStatusError as e:
            if e.response.status_code == 429:
                logger.warning("Semantic Scholar rate limit exceeded")
                return SearchResult(
                    source=self.name,
                    error="Rate limit exceeded. Consider using an API key.",
                    search_time_seconds=time.time() - start_time
                )
            logger.error(f"Semantic Scholar HTTP error: {e}")
            return SearchResult(
                source=self.name,
                error=f"HTTP error: {str(e)}",
                search_time_seconds=time.time() - start_time
            )
        except Exception as e:
            logger.error(f"Semantic Scholar search error: {e}")
            return SearchResult(
                source=self.name,
                error=f"Error: {str(e)}",
                search_time_seconds=time.time() - start_time
            )
        
        papers = []
        for item in data.get("data", []):
            external_ids = item.get("externalIds") or {}
            
            # Extract authors (limit to 10)
            authors = [
                author.get("name")
                for author in (item.get("authors") or [])[:10]
                if author.get("name")
            ]
            
            # PDF URL
            pdf_info = item.get("openAccessPdf") or {}
            pdf_url = pdf_info.get("url")
            
            papers.append(Paper(
                source=self.name,
                semantic_scholar_id=item.get("paperId"),
                doi=external_ids.get("DOI"),
                pmid=external_ids.get("PubMed"),
                arxiv_id=external_ids.get("ArXiv"),
                title=item.get("title") or "Untitled",
                authors=authors,
                year=item.get("year"),
                journal=item.get("venue"),
                abstract=item.get("abstract"),
                citation_count=item.get("citationCount", 0) or 0,
                is_open_access=item.get("isOpenAccess", False),
                pdf_url=pdf_url
            ))
        
        return SearchResult(
            papers=papers,
            total_found=data.get("total", len(papers)),
            search_time_seconds=time.time() - start_time,
            source=self.name
        )
    
    async def get_by_doi(self, doi: str) -> Optional[Paper]:
        """Get paper by DOI from Semantic Scholar"""
        headers = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        
        try:
            response = await self.client.get(
                f"{self.BASE_URL}/paper/DOI:{doi}",
                params={
                    "fields": "paperId,externalIds,title,authors,year,venue,abstract,citationCount,isOpenAccess,openAccessPdf"
                },
                headers=headers
            )
            item = response.json()
        except Exception as e:
            logger.debug(f"Semantic Scholar get_by_doi error: {e}")
            return None
        
        external_ids = item.get("externalIds") or {}
        
        # Extract authors
        authors = [
            author.get("name")
            for author in (item.get("authors") or [])[:10]
            if author.get("name")
        ]
        
        # PDF URL
        pdf_info = item.get("openAccessPdf") or {}
        pdf_url = pdf_info.get("url")
        
        return Paper(
            source=self.name,
            semantic_scholar_id=item.get("paperId"),
            doi=external_ids.get("DOI"),
            pmid=external_ids.get("PubMed"),
            arxiv_id=external_ids.get("ArXiv"),
            title=item.get("title") or "Untitled",
            authors=authors,
            year=item.get("year"),
            journal=item.get("venue"),
            abstract=item.get("abstract"),
            citation_count=item.get("citationCount", 0) or 0,
            is_open_access=item.get("isOpenAccess", False),
            pdf_url=pdf_url
        )
