# retrieval (L0) — PORT, do not rewrite

Carry the working connectors from the old project:
  /root/scientific-search/backend/sources/{base,openalex,europepmc,semantic_scholar,aggregator}.py

Bring/inline when porting:
  - core.constants.CITATION_STATS (citation normalization percentiles)
  - config.settings.RANKING_* (relevance weights)

Interface: BaseSource.search(query, ...) -> SearchResult(papers: list[Paper]);
SearchAggregator.search(...) = parallel fan-out + DOI/title dedup + ranking.
