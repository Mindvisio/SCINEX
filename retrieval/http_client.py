"""Minimal async HTTP client with retries + optional egress proxy — ResilientClient shim.

Some sources (e.g. Semantic Scholar) geoblock the RU egress IP (HTTP 403). Those are
constructed with use_proxy=True and routed through the proxy at HTTPS_PROXY / LLM_PROXY.
Sources that work direct from RU stay direct (proxy can itself cause 403 on some hosts).
"""
from __future__ import annotations
import asyncio
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


def proxy_url() -> Optional[str]:
    """Egress proxy from env (same var the rest of the stack uses)."""
    return (os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
            or os.environ.get("LLM_PROXY"))


class ResilientClient:
    def __init__(self, service_name: str = "", max_retries: int = 3,
                 timeout: float = 30.0, use_proxy: bool = False, **_):
        self.service_name = service_name
        self.max_retries = max_retries
        self.timeout = timeout
        self.use_proxy = use_proxy

    def _client(self) -> httpx.AsyncClient:
        kw = {"timeout": self.timeout, "follow_redirects": True}
        if self.use_proxy:
            px = proxy_url()
            if px:
                kw["proxy"] = px
            else:
                logger.warning("%s: use_proxy set but no HTTPS_PROXY/LLM_PROXY in env",
                               self.service_name)
        return httpx.AsyncClient(**kw)

    async def get(self, url, params=None, headers=None) -> httpx.Response:
        return await self._req("GET", url, params=params, headers=headers)

    async def post(self, url, params=None, headers=None, json=None) -> httpx.Response:
        return await self._req("POST", url, params=params, headers=headers, json=json)

    async def _req(self, method, url, **kw) -> httpx.Response:
        last = None
        for attempt in range(self.max_retries):
            try:
                async with self._client() as c:
                    r = await c.request(method, url, **kw)
                r.raise_for_status()
                return r
            except Exception as e:
                last = e
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(0.5 * (attempt + 1))
        logger.debug("%s %s failed after %d tries: %s", method, url, self.max_retries, last)
        raise last
