"""
Search Aggregator
Combines results from multiple sources with deduplication and ranking
"""

import asyncio
import re
import time
from typing import List, Dict, Optional, Tuple
from datetime import datetime

from retrieval.base import Paper, SearchResult
from retrieval.constants import CITATION_STATS, DEFAULT_CITATION_STATS
from retrieval._settings import settings


def normalize_title(title: Optional[str]) -> str:
    """Normalize title for deduplication"""
    if not title:
        return ""
    title = title.lower().strip()
    title = re.sub(r"\s+", " ", title)
    title = re.sub(r"[^\w\s]", "", title)
    return title


def get_normalized_citation_score(paper: Paper) -> float:
    """
    Get normalized citation score for a paper.
    
    Uses source-specific percentile statistics to ensure fair
    comparison across different databases with different coverage.
    
    Args:
        paper: Paper with source and citation_count
        
    Returns:
        Normalized score between 0.0 and 1.0
    """
    stats = CITATION_STATS.get(paper.source, DEFAULT_CITATION_STATS)
    return stats.normalize(paper.citation_count)


def calculate_relevance_score(paper: Paper, query: str) -> float:
    """
    Calculate relevance score for ranking using configurable weights.
    
    Uses normalized citation scores to ensure fair comparison
    across different sources with different coverage.
    """
    score = 0.0
    
    # Citation score (normalized across sources, then scaled)
    normalized_citations = get_normalized_citation_score(paper)
    score += normalized_citations * settings.RANKING_CITATION_MAX_SCORE
    
    # Recency bonus
    if paper.year and isinstance(paper.year, int):
        current_year = datetime.now().year
        recency_cutoff = current_year - settings.RANKING_RECENCY_YEARS
        if paper.year >= recency_cutoff:
            score += (paper.year - recency_cutoff) * settings.RANKING_RECENCY_WEIGHT
    
    # Keyword relevance
    query_lower = query.lower()
    title = (paper.title or "").lower()
    abstract = (paper.abstract or "").lower()
    
    if query_lower in title:
        score += settings.RANKING_TITLE_MATCH_SCORE
    if abstract and query_lower in abstract:
        score += settings.RANKING_ABSTRACT_MATCH_SCORE
    
    # Open access bonus
    if paper.is_open_access:
        score += settings.RANKING_OPEN_ACCESS_BONUS
    
    return score


def deduplicate_papers(papers: List[Paper]) -> List[Paper]:
    """Remove duplicates based on DOI and normalized title"""
    seen_doi = set()
    seen_title = set()
    unique_papers = []
    
    for paper in papers:
        doi = (paper.doi or "").lower().strip()
        title = normalize_title(paper.title)
        
        # Check DOI first
        if doi:
            if doi in seen_doi:
                continue
            seen_doi.add(doi)
        
        # Check title
        if title:
            if title in seen_title:
                continue
            seen_title.add(title)
        
        unique_papers.append(paper)
    
    return unique_papers


def rank_papers(papers: List[Paper], query: str) -> List[Paper]:
    """Rank papers by relevance score"""
    return sorted(
        papers,
        key=lambda x: calculate_relevance_score(x, query),
        reverse=True
    )


class SearchAggregator:
    """Aggregates search results from multiple sources"""
    
    def __init__(self, sources: List):
        """
        Initialize with list of source instances.
        
        Args:
            sources: List of BaseSource instances
        """
        self.sources = sources
    
    async def search(
        self,
        query: str,
        limit_per_source: int = 50,
        year_range: Optional[Tuple[int, int]] = None,
        open_access_only: bool = False,
        enabled_sources: Optional[Dict[str, bool]] = None,
        offset: int = 0,
        limit: int = 50
    ) -> Dict:
        """
        Search all enabled sources in parallel.
        
        Args:
            query: Search query
            limit_per_source: Max results per source
            year_range: (start_year, end_year) tuple
            open_access_only: Filter to open access only
            enabled_sources: Dict of source_name -> enabled boolean
            offset: Number of results to skip (for pagination)
            limit: Maximum results to return (for pagination)
            
        Returns:
            Dict with papers, sources_used, search_time, errors, pagination info
        """
        start_time = time.time()
        
        # Filter to enabled sources
        active_sources = self.sources
        if enabled_sources:
            active_sources = [
                s for s in self.sources 
                if enabled_sources.get(s.name, True)
            ]
        
        # Create search tasks
        tasks = [
            source.search(
                query=query,
                max_results=limit_per_source,
                year_range=year_range,
                open_access_only=open_access_only
            )
            for source in active_sources
        ]
        
        # Execute all searches in parallel
        results: List[SearchResult] = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Collect results
        all_papers = []
        sources_used = []
        errors = []
        
        for source, result in zip(active_sources, results):
            if isinstance(result, Exception):
                errors.append(f"{source.name}: {str(result)}")
            elif result.error:
                errors.append(f"{source.name}: {result.error}")
            elif result.papers:
                sources_used.append(source.name)
                all_papers.extend(result.papers)
        
        # Deduplicate and rank
        unique_papers = deduplicate_papers(all_papers)
        ranked_papers = rank_papers(unique_papers, query)
        
        # Apply pagination
        total_found = len(ranked_papers)
        paginated_papers = ranked_papers[offset:offset + limit]
        
        search_time = round(time.time() - start_time, 2)
        
        return {
            "papers": paginated_papers,
            "total_found": total_found,
            "sources_used": sources_used,
            "search_time_seconds": search_time,
            "errors": errors,
            "pagination": {
                "offset": offset,
                "limit": limit,
                "returned": len(paginated_papers),
                "has_more": offset + limit < total_found
            }
        }
    
    async def get_by_doi(self, doi: str) -> Optional[Paper]:
        """
        Get paper by DOI from any source.
        Tries each source until paper is found.
        """
        for source in self.sources:
            paper = await source.get_by_doi(doi)
            if paper:
                return paper
        return None
