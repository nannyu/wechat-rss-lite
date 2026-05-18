from __future__ import annotations

import asyncio
from collections.abc import Mapping

import httpx

from .exceptions import FetchError
from .models import Article
from .parser import parse_article_html
from .proxy import ProxyPool
from .rate_limit import AsyncRateLimiter

DEFAULT_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
    "user-agent": "Mozilla/5.0 (compatible; wechat-rss-lite/0.1; +https://example.invalid)",
}


class WeChatArticleClient:
    def __init__(
        self,
        *,
        timeout: float = 15.0,
        retries: int = 2,
        headers: Mapping[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
        proxy_pool: ProxyPool | None = None,
        rate_limiter: AsyncRateLimiter | None = None,
    ) -> None:
        self.retries = retries
        self.headers = {**DEFAULT_HEADERS, **(headers or {})}
        self.timeout = timeout
        self.proxy_pool = proxy_pool or ProxyPool()
        self.rate_limiter = rate_limiter
        self._owned_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
            headers=self.headers,
        )

    async def __aenter__(self) -> "WeChatArticleClient":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owned_client:
            await self._client.aclose()

    async def fetch_article(self, url: str) -> Article:
        html = await self.fetch_html(url)
        return parse_article_html(html, url=url)

    async def fetch_html(self, url: str) -> str:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                if self.rate_limiter:
                    await self.rate_limiter.wait()
                response = await self._get(url)
                response.raise_for_status()
                return response.text
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                last_error = exc
                if attempt < self.retries:
                    await asyncio.sleep(0.2 * (attempt + 1))
        raise FetchError(f"Unable to fetch {url}") from last_error

    async def _get(self, url: str) -> httpx.Response:
        proxy = self.proxy_pool.next().httpx_proxy
        if not proxy or not self._owned_client:
            return await self._client.get(url)
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout),
            follow_redirects=True,
            headers=self.headers,
            proxy=proxy,
        ) as client:
            return await client.get(url)
