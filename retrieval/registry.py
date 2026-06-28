"""Source registry. Build the aggregator from the full source set.

Deduplicated coverage > AnswerThis (OpenAlex u S2 u PubMed u arXiv): we hold their backbone
+ Europe PMC + CORE (unique OA) + Google Patents via SerpApi. See COVERAGE.md.
"""
from __future__ import annotations
import os

from retrieval.base import BaseSource
from retrieval.aggregate import SearchAggregator
from retrieval.openalex import OpenAlexSource
from retrieval.semantic_scholar import SemanticScholarSource
from retrieval.europepmc import EuropePMCSource
from retrieval.crossref import CrossrefSource
from retrieval.arxiv import ArxivSource
from retrieval.pubmed import PubMedSource
from retrieval.core import CoreSource
from retrieval.google_patents import GooglePatentsSource
from retrieval.google_scholar import GoogleScholarSource

# name -> (class, key_env or None). key_env=None => always ready (keyless).
REGISTRY = {
    "OpenAlex":         (OpenAlexSource, None),
    "Semantic Scholar": (SemanticScholarSource, None),   # key optional (raises limits)
    "Europe PMC":       (EuropePMCSource, None),
    "Crossref":         (CrossrefSource, None),
    "arXiv":            (ArxivSource, None),
    "PubMed":           (PubMedSource, None),             # key optional
    "CORE":             (CoreSource, "CORE_API_KEY"),
    "Google Patents":             (GooglePatentsSource, "SERPAPI_API_KEY"),
    "Google Scholar":   (GoogleScholarSource, "SERPAPI_API_KEY"),
}

DEFAULT_CONTACT = os.environ.get("CONTACT_EMAIL", "demo@example.com")


def build_sources(contact_email: str = DEFAULT_CONTACT) -> list:
    """Instantiate every source. Keyed sources without a key self-report an error result
    (the aggregator collects it into `errors` and skips them) — no special-casing here.
    """
    out = []
    for _name, (cls, key_env) in REGISTRY.items():
        key = os.environ.get(key_env) if key_env else None
        out.append(cls(api_key=key, contact_email=contact_email))
    return out


def build_aggregator(contact_email: str = DEFAULT_CONTACT) -> SearchAggregator:
    return SearchAggregator(build_sources(contact_email))


def source_status() -> dict:
    """name -> 'ready' | 'needs <ENV>'  (for UI / diagnostics)."""
    return {name: ("ready" if (key_env is None or os.environ.get(key_env)) else f"needs {key_env}")
            for name, (cls, key_env) in REGISTRY.items()}
