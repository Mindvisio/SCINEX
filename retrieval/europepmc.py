"""
Europe PMC API Source
https://europepmc.org/RestfulWebService
Coverage: ~42M biomedical articles
"""

import time
import logging
from typing import Optional, Tuple

from retrieval.base import BaseSource, Paper, SearchResult
from retrieval.http_client import ResilientClient
from retrieval.constants import CitationStats, CITATION_STATS

logger = logging.getLogger(__name__)


class EuropePMCSource(BaseSource):
    """Europe PMC data source (~42M biomedical articles)"""
    
    BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest"
    
    # Europe PMC has smaller coverage, so citations tend to be lower
    citation_stats = CITATION_STATS["Europe PMC"]
    
    def __init__(self, api_key: Optional[str] = None, contact_email: Optional[str] = None):
        super().__init__(api_key, contact_email)
        self.client = ResilientClient(
            service_name="EuropePMC",
            max_retries=3
        )
    
    @property
    def name(self) -> str:
        return "Europe PMC"
    
    @property
    def rate_limit_per_minute(self) -> int:
        return 60
    
    async def search(
        self,
        query: str,
        max_results: int = 50,
        year_range: Optional[Tuple[int, int]] = None,
        open_access_only: bool = False
    ) -> SearchResult:
        """Search Europe PMC for papers"""
        start_time = time.time()
        
        # Build search query (Lucene syntax)
        search_query = query
        
        if year_range:
            search_query += f" AND PUB_YEAR:[{year_range[0]} TO {year_range[1]}]"
        if open_access_only:
            search_query += " AND OPEN_ACCESS:y"
        
        params = {
            "query": search_query,
            "pageSize": min(max_results, 1000),
            "format": "json",
            "cursorMark": "*"
        }
        
        try:
            response = await self.client.get(
                f"{self.BASE_URL}/search",
                params=params
            )
            data = response.json()
        except Exception as e:
            logger.error(f"Europe PMC search error: {e}")
            return SearchResult(
                source=self.name,
                error=f"Error: {str(e)}",
                search_time_seconds=time.time() - start_time
            )
        
        papers = []
        result_list = (data.get("resultList") or {}).get("result", [])
        
        for result in result_list:
            # Extract authors
            authors = []
            author_list = (result.get("authorList") or {}).get("author", [])
            for author in author_list[:10]:
                full_name = (
                    author.get("fullName") or
                    f"{author.get('firstName', '')} {author.get('lastName', '')}".strip()
                )
                if full_name:
                    authors.append(full_name)
            
            # Extract year
            year = None
            if result.get("pubYear"):
                try:
                    year = int(result["pubYear"])
                except (ValueError, TypeError):
                    pass
            
            papers.append(Paper(
                source=self.name,
                doi=result.get("doi"),
                pmid=result.get("pmid"),
                pmcid=result.get("pmcid"),
                title=result.get("title") or "Untitled",
                authors=authors,
                year=year,
                journal=result.get("journalTitle"),
                abstract=result.get("abstractText"),
                citation_count=result.get("citedByCount", 0) or 0,
                is_open_access=(result.get("isOpenAccess") == "Y"),
                pdf_url=None  # Europe PMC doesn't provide direct PDF URLs in search
            ))
        
        return SearchResult(
            papers=papers,
            total_found=data.get("hitCount", len(papers)),
            search_time_seconds=time.time() - start_time,
            source=self.name
        )
    
    async def get_by_doi(self, doi: str) -> Optional[Paper]:
        """Get paper by DOI from Europe PMC"""
        try:
            response = await self.client.get(
                f"{self.BASE_URL}/search",
                params={
                    "query": f"DOI:{doi}",
                    "format": "json"
                }
            )
            data = response.json()
        except Exception as e:
            logger.debug(f"Europe PMC get_by_doi error: {e}")
            return None
        
        results = (data.get("resultList") or {}).get("result", [])
        if not results:
            return None
        
        result = results[0]
        
        # Extract authors
        authors = []
        author_list = (result.get("authorList") or {}).get("author", [])
        for author in author_list[:10]:
            full_name = (
                author.get("fullName") or
                f"{author.get('firstName', '')} {author.get('lastName', '')}".strip()
            )
            if full_name:
                authors.append(full_name)
        
        # Extract year
        year = None
        if result.get("pubYear"):
            try:
                year = int(result["pubYear"])
            except (ValueError, TypeError):
                pass
        
        return Paper(
            source=self.name,
            doi=result.get("doi"),
            pmid=result.get("pmid"),
            pmcid=result.get("pmcid"),
            title=result.get("title") or "Untitled",
            authors=authors,
            year=year,
            journal=result.get("journalTitle"),
            abstract=result.get("abstractText"),
            citation_count=result.get("citedByCount", 0) or 0,
            is_open_access=(result.get("isOpenAccess") == "Y"),
            pdf_url=None
        )
