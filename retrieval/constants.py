"""
Centralized constants for the application.

All magic numbers and configuration constants should be defined here
to ensure consistency and ease of maintenance.
"""

from dataclasses import dataclass
from enum import IntEnum


# ============ Time Constants ============

class Seconds(IntEnum):
    """Common time durations in seconds"""
    MINUTE = 60
    HOUR = 3600
    DAY = 86400
    WEEK = 604800


# ============ Cache TTL ============

class CacheTTL(IntEnum):
    """
    Cache Time-To-Live values in seconds.
    
    Note: TOKEN_BLACKLIST is computed dynamically in CacheService
    to stay in sync with REFRESH_TOKEN_EXPIRE_DAYS from settings.
    """
    DEFAULT = Seconds.HOUR           # 1 hour - general cache
    SEARCH_RESULTS = 1800            # 30 minutes - search results
    PAPER = Seconds.DAY              # 24 hours - individual papers


# ============ Rate Limiting ============

@dataclass(frozen=True)
class LoginRateLimitConfig:
    """Configuration for login endpoint rate limiting"""
    max_attempts: int = 5
    window_seconds: int = 60


LOGIN_RATE_LIMIT = LoginRateLimitConfig()


# ============ Circuit Breaker ============

@dataclass(frozen=True)
class CircuitBreakerConfig:
    """Default configuration for circuit breakers"""
    failure_threshold: int = 5       # Failures before opening
    recovery_timeout: float = 30.0   # Seconds before trying again
    half_open_max_calls: int = 1     # Calls allowed in half-open state


CIRCUIT_BREAKER_DEFAULTS = CircuitBreakerConfig()


# ============ Citation Normalization ============

@dataclass(frozen=True)
class CitationStats:
    """
    Percentile-based citation statistics for a data source.
    
    Used to normalize citation counts across different sources,
    since each source has different coverage and counting methodology.
    
    Attributes:
        p50: Median citation count (50th percentile)
        p90: High impact threshold (90th percentile)
        p99: Exceptional impact threshold (99th percentile)
    """
    p50: int = 5      # median
    p90: int = 50     # high impact
    p99: int = 500    # exceptional
    
    def normalize(self, count: int) -> float:
        """
        Normalize citation count to 0-1 scale based on percentiles.
        
        Distribution:
        - 0.0 - 0.5: Below median (0 to p50)
        - 0.5 - 0.9: Above median (p50 to p90)
        - 0.9 - 1.0: Exceptional (p90 to p99+)
        
        Args:
            count: Raw citation count
            
        Returns:
            Normalized score between 0.0 and 1.0
        """
        if count <= 0:
            return 0.0
        if count <= self.p50:
            return (count / self.p50) * 0.5
        if count <= self.p90:
            return 0.5 + (count - self.p50) / (self.p90 - self.p50) * 0.4
        # p90+: asymptotically approach 1.0
        return 0.9 + min(0.1, (count - self.p90) / (self.p99 - self.p90) * 0.1)


# Pre-defined citation stats for each source
# These are approximate values based on typical distributions
CITATION_STATS = {
    "OpenAlex": CitationStats(p50=5, p90=50, p99=500),
    "Europe PMC": CitationStats(p50=2, p90=20, p99=200),
    "Semantic Scholar": CitationStats(p50=3, p90=35, p99=350),
}

# Default stats for unknown sources
DEFAULT_CITATION_STATS = CitationStats()

# --- scinex: extended source stats (expanded retrieval) ---
CITATION_STATS["Crossref"] = CitationStats(p50=5, p90=50, p99=500)
CITATION_STATS["arXiv"] = CitationStats(p50=3, p90=30, p99=300)
CITATION_STATS["PubMed"] = CitationStats(p50=4, p90=40, p99=400)
CITATION_STATS["CORE"] = CitationStats(p50=2, p90=20, p99=200)
CITATION_STATS["Lens"] = CitationStats(p50=3, p90=30, p99=300)
CITATION_STATS["Google Scholar"] = CitationStats(p50=8, p90=80, p99=800)
CITATION_STATS["Google Patents"] = CitationStats(p50=3, p90=30, p99=300)
