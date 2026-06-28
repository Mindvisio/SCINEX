from abc import ABC, abstractmethod
from typing import List, Optional, Tuple
from pydantic import BaseModel, Field
from datetime import datetime

from retrieval.constants import CitationStats, CITATION_STATS, DEFAULT_CITATION_STATS


class Paper(BaseModel):
    """Paper metadata model"""
    source: str = Field(..., description="Source database name")
    doi: Optional[str] = None
    title: str
    authors: List[str] = Field(default_factory=list)
    year: Optional[int] = None
    journal: Optional[str] = None
    abstract: Optional[str] = None
    citation_count: int = 0
    is_open_access: bool = False
    pdf_url: Optional[str] = None
    
    # Source-specific IDs
    openalex_id: Optional[str] = None
    pmid: Optional[str] = None
    pmcid: Optional[str] = None
    arxiv_id: Optional[str] = None
    semantic_scholar_id: Optional[str] = None
    
    class Config:
        from_attributes = True


class SearchResult(BaseModel):
    """Search result container"""
    papers: List[Paper] = Field(default_factory=list)
    total_found: int = 0
    search_time_seconds: float = 0.0
    source: str = ""
    error: Optional[str] = None


class BaseSource(ABC):
    """Abstract base class for all data sources"""
    
    # Override in subclasses with source-specific citation statistics
    # This enables fair comparison of citations across different databases
    citation_stats: CitationStats = DEFAULT_CITATION_STATS
    
    def __init__(self, api_key: Optional[str] = None, contact_email: Optional[str] = None):
        self.api_key = api_key
        self.contact_email = contact_email or "demo@example.com"
    
    def normalize_citations(self, count: int) -> float:
        """
        Normalize citation count to 0-1 scale.
        
        Uses source-specific percentile statistics to ensure fair
        comparison across different databases with different coverage.
        
        Args:
            count: Raw citation count from this source
            
        Returns:
            Normalized score between 0.0 and 1.0
        """
        return self.citation_stats.normalize(count)
    
    @abstractmethod
    async def search(
        self, 
        query: str, 
        max_results: int = 50,
        year_range: Optional[Tuple[int, int]] = None,
        open_access_only: bool = False
    ) -> SearchResult:
        """Search for papers"""
        pass
    
    @abstractmethod
    async def get_by_doi(self, doi: str) -> Optional[Paper]:
        """Get paper by DOI"""
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Source name"""
        pass
    
    @property
    def rate_limit_per_minute(self) -> int:
        """Rate limit per minute"""
        return 60
