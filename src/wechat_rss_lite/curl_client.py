from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from .client import (
    DEFAULT_HEADERS,
    MAX_REDIRECTS,
    _has_complete_article_html,
    _invalid_content_hint,
    _is_permanent_or_actionable_response,
    _validate_wechat_article_url,
)
from .exceptions import FetchError
from .models import Article
from .page_fetcher import fetch_page
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
        credential_getter: Callable[[], Any | None] | None = None,
        token: str = "",
        cookie: str = "",
        image_proxy_base: str = "",
        tls_verify: bool = True,
    ) -> None:
        self.timeout = timeout
        self.retries = retries
        self.impersonate = impersonate
        self.headers = {**DEFAULT_HEADERS, **(headers or {})}
        self.proxy_pool = proxy_pool or ProxyPool()
        self.rate_limiter = rate_limiter
        self.credential_getter = credential_getter
        self.token = token
        self.cookie = cookie
        self.image_proxy_base = image_proxy_base
        self.tls_verify = tls_verify

    async def fetch_article(self, url: str) -> Article:
        return parse_article_html(
            await self.fetch_html(url),
            url=url,
            image_proxy_base=self.image_proxy_base,
        )

    async def fetch_html(self, url: str) -> str:
        _validate_wechat_article_url(url)
        last_error: Exception | None = None
        requested_url = self._url_with_token(url)
        extra_headers = dict(self._headers_for_request())
        extra_headers.setdefault("Referer", "https://mp.weixin.qq.com/")
        for _attempt in range(self.retries + 1):
            try:
                if self.rate_limiter:
                    await self.rate_limiter.wait()
                html = await fetch_page(
                    requested_url,
                    extra_headers=extra_headers,
                    timeout=self.timeout,
                    proxy_pool=self.proxy_pool,
                    tls_verify=self.tls_verify,
                )
                if _has_complete_article_html(html) or _is_permanent_or_actionable_response(html):
                    return html
                last_error = FetchError(_invalid_content_hint(html))
            except Exception as exc:
                last_error = exc
        raise FetchError(f"Unable to fetch {url}") from last_error

    def _headers_for_request(self) -> dict[str, str]:
        headers = dict(self.headers)
        cookie = self._credential_value("cookie") or self.cookie
        if cookie:
            headers["Cookie"] = cookie
        return headers

    def _url_with_token(self, url: str) -> str:
        token = self._credential_value("token") or self.token
        if not token:
            return url
        parsed = urlparse(url)
        query = parse_qsl(parsed.query, keep_blank_values=True)
        if any(key == "token" for key, _value in query):
            return url
        query.append(("token", token))
        return urlunparse(parsed._replace(query=urlencode(query)))

    def _credential_value(self, name: str) -> str:
        if not self.credential_getter:
            return ""
        credential = self.credential_getter()
        if not credential:
            return ""
        if getattr(credential, "is_expired", False):
            return ""
        return str(getattr(credential, name, "") or "")
