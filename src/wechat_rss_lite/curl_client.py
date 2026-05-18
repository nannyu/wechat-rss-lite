from __future__ import annotations

from collections.abc import Mapping

from .exceptions import FetchError
from .models import Article
from .parser import parse_article_html
from .proxy import ProxyPool
from .rate_limit import AsyncRateLimiter


class CurlCffiArticleClient:
    """Optional browser-compatible TLS transport.

    Install `wechat-rss-lite[tls]` to use this client. Keeping it separate from
    the default httpx client makes the dependency and policy choice explicit.
    """

    def __init__(
        self,
        *,
        timeout: float = 15.0,
        retries: int = 2,
        impersonate: str = "chrome",
        headers: Mapping[str, str] | None = None,
        proxy_pool: ProxyPool | None = None,
        rate_limiter: AsyncRateLimiter | None = None,
    ) -> None:
        self.timeout = timeout
        self.retries = retries
        self.impersonate = impersonate
        self.headers = dict(headers or {})
        self.proxy_pool = proxy_pool or ProxyPool()
        self.rate_limiter = rate_limiter

    async def fetch_article(self, url: str) -> Article:
        return parse_article_html(await self.fetch_html(url), url=url)

    async def fetch_html(self, url: str) -> str:
        try:
            from curl_cffi.requests import AsyncSession
        except ImportError as exc:
            raise RuntimeError("Install with wechat-rss-lite[tls] to use CurlCffiArticleClient") from exc

        last_error: Exception | None = None
        for _attempt in range(self.retries + 1):
            try:
                if self.rate_limiter:
                    await self.rate_limiter.wait()
                proxy = self.proxy_pool.next().httpx_proxy
                proxies = {"http": proxy, "https": proxy} if proxy else None
                async with AsyncSession(impersonate=self.impersonate) as session:
                    response = await session.get(
                        url,
                        timeout=self.timeout,
                        headers=self.headers,
                        proxies=proxies,
                    )
                    response.raise_for_status()
                    return response.text
            except Exception as exc:
                last_error = exc
        raise FetchError(f"Unable to fetch {url}") from last_error

