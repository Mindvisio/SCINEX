"""Ranking weights shim for the ported aggregator (was config.settings)."""


class _Settings:
    RANKING_CITATION_MAX_SCORE = 10.0
    RANKING_CITATION_SCALE = 2.0
    RANKING_RECENCY_YEARS = 5
    RANKING_RECENCY_WEIGHT = 0.5
    RANKING_TITLE_MATCH_SCORE = 5.0
    RANKING_ABSTRACT_MATCH_SCORE = 3.0
    RANKING_OPEN_ACCESS_BONUS = 2.0


settings = _Settings()
