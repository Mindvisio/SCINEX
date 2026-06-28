"""API embeddings (OpenAI text-embedding-3) via the LLM proxy. NOT self-hosted.

Reuses LLM_PROXY + key loading from lib.llm_clients (OpenAI geoblocks sci-node's RU IP -> proxy).
"""
from __future__ import annotations
from lib.llm_clients import LLM_PROXY, _key, LLMError

EMBED_MODEL = "text-embedding-3-large"   # 3072-dim; swap to -small (1536) to cut cost
_client = None


def _client_get():
    global _client
    if _client is None:
        from openai import OpenAI
        import httpx
        key = _key("OPENAI_API_KEY")
        if not key:
            raise LLMError("OPENAI_API_KEY missing")
        kw = {"api_key": key}
        if LLM_PROXY:
            kw["http_client"] = httpx.Client(proxy=LLM_PROXY, timeout=httpx.Timeout(120.0))
        _client = OpenAI(**kw)
    return _client


def embed(texts: list[str], model: str = EMBED_MODEL, batch: int = 128) -> list[list[float]]:
    """Embed a list of texts -> list of vectors. Batched; trims very long inputs."""
    if not texts:
        return []
    cli = _client_get()
    out: list[list[float]] = []
    for i in range(0, len(texts), batch):
        chunk = [(t or " ").replace("\n", " ")[:8000] for t in texts[i:i + batch]]
        resp = cli.embeddings.create(model=model, input=chunk)
        out.extend([d.embedding for d in resp.data])
    return out
