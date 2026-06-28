"""
OpenAlex API Source
https://docs.openalex.org/
Coverage: ~260M works across all disciplines
"""

import time
import logging
from typing import Optional, Tuple, List

from retrieval.base import BaseSource, Paper, SearchResult
from retrieval.http_client import ResilientClient
from retrieval.constants import CitationStats, CITATION_STATS

logger = logging.getLogger(__name__)


class OpenAlexSource(BaseSource):
    """OpenAlex data source (~260M works)"""
    
    BASE_URL = "https://api.openalex.org"
    
    # OpenAlex has the broadest coverage, so citations tend to be higher
    citation_stats = CITATION_STATS["OpenAlex"]
    
    def __init__(self, api_key: Optional[str] = None, contact_email: Optional[str] = None):
        super().__init__(api_key, contact_email)
        self.client = ResilientClient(
            service_name="OpenAlex",
            max_retries=3
        )
    
    @property
    def name(self) -> str:
        return "OpenAlex"
    
    @property
    def rate_limit_per_minute(self) -> int:
        return 100  # Polite usage with email
    
    def _reconstruct_abstract(self, inverted_index: dict) -> Optional[str]:
        """Reconstruct abstract from inverted index format"""
        if not inverted_index:
            return None
        
        positions = {}
        for word, pos_list in inverted_index.items():
            for pos in pos_list:
                positions[pos] = word
        
        if not positions:
            return None
            
        return " ".join(positions[i] for i in sorted(positions.keys()))
    
    async def search(
        self,
        query: str,
        max_results: int = 50,
        year_range: Optional[Tuple[int, int]] = None,
        open_access_only: bool = False
    ) -> SearchResult:
        """Search OpenAlex for papers"""
        start_time = time.time()
        
        params = {
            "search": query,
            "per_page": min(max_results, 200),
            "page": 1
        }
        
        # Build filters
        filters = []
        if year_range:
            filters.append(f"publication_year:{year_range[0]}-{year_range[1]}")
        if open_access_only:
            filters.append("is_oa:true")
        if filters:
            params["filter"] = ",".join(filters)
        
        headers = {
            "User-Agent": f"ScientificSearch/1.0 (mailto:{self.contact_email})"
        }
        
        try:
            response = await self.client.get(
                f"{self.BASE_URL}/works",
                params=params,
                headers=headers
            )
            data = response.json()
        except Exception as e:
            logger.error(f"OpenAlex search error: {e}")
            return SearchResult(
                source=self.name,
                error=f"Error: {str(e)}",
                search_time_seconds=time.time() - start_time
            )
        
        papers = []
        for work in data.get("results", []):
            # Extract DOI
            doi = (work.get("doi") or "").replace("https://doi.org/", "") or None
            
            # Extract authors (limit to 10)
            authors = [
                authorship["author"]["display_name"]
                for authorship in work.get("authorships", [])[:10]
                if authorship.get("author")
            ]
            
            # Reconstruct abstract
            abstract = self._reconstruct_abstract(work.get("abstract_inverted_index"))
            
            # Open access info
            oa_info = work.get("open_access") or {}
            pdf_url = oa_info.get("oa_url") if oa_info.get("is_oa") else None
            
            # Extract journal
            primary_location = work.get("primary_location") or {}
            source_info = primary_location.get("source") or {}
            journal = source_info.get("display_name")
            
            papers.append(Paper(
                source=self.name,
                openalex_id=(work.get("id") or "").replace("https://openalex.org/", ""),
                doi=doi,
                title=work.get("title") or "Untitled",
                authors=authors,
                year=work.get("publication_year"),
                journal=journal,
                abstract=abstract,
                citation_count=work.get("cited_by_count", 0),
                is_open_access=bool(oa_info.get("is_oa")),
                pdf_url=pdf_url
            ))
        
        return SearchResult(
            papers=papers,
            total_found=data.get("meta", {}).get("count", len(papers)),
            search_time_seconds=time.time() - start_time,
            source=self.name
        )
    
    async def get_by_doi(self, doi: str) -> Optional[Paper]:
        """Get paper by DOI from OpenAlex"""
        headers = {
            "User-Agent": f"ScientificSearch/1.0 (mailto:{self.contact_email})"
        }
        
        try:
            response = await self.client.get(
                f"{self.BASE_URL}/works/doi:{doi}",
                headers=headers
            )
            work = response.json()
        except Exception as e:
            logger.debug(f"OpenAlex get_by_doi error: {e}")
            return None
        
        # Extract authors
        authors = [
            authorship["author"]["display_name"]
            for authorship in work.get("authorships", [])[:10]
            if authorship.get("author")
        ]
        
        # Reconstruct abstract
        abstract = self._reconstruct_abstract(work.get("abstract_inverted_index"))
        
        # Open access info
        oa_info = work.get("open_access") or {}
        pdf_url = oa_info.get("oa_url") if oa_info.get("is_oa") else None
        
        # Extract journal
        primary_location = work.get("primary_location") or {}
        source_info = primary_location.get("source") or {}
        journal = source_info.get("display_name")
        
        return Paper(
            source=self.name,
            openalex_id=(work.get("id") or "").replace("https://openalex.org/", ""),
            doi=doi,
            title=work.get("title") or "Untitled",
            authors=authors,
            year=work.get("publication_year"),
            journal=journal,
            abstract=abstract,
            citation_count=work.get("cited_by_count", 0),
            is_open_access=bool(oa_info.get("is_oa")),
            pdf_url=pdf_url
        )
