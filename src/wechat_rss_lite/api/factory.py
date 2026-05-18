from __future__ import annotations

from ..config import Settings
from ..adapters import LoginProvider, ManualLoginProvider
from ..client import WeChatArticleClient
from ..curl_client import CurlCffiArticleClient
from ..local_login import LocalQrLoginProvider
from ..proxy import ProxyPool
from ..rate_limit import AsyncRateLimiter
from ..storage import SQLiteRepository
from ..wechat_login import WeChatMpLoginProvider


def build_login_provider(settings: Settings) -> LoginProvider:
    provider = settings.login_provider.strip().lower()
    if provider == "local":
        return LocalQrLoginProvider(base_url=settings.site_url)
    if provider in {"manual", "disabled", "none"}:
        return ManualLoginProvider()
    return WeChatMpLoginProvider(timeout=settings.request_timeout_seconds)


def image_proxy_base(settings: Settings) -> str:
    return f"{settings.site_url.rstrip('/')}/image"


def build_article_client(
    settings: Settings,
    repo: SQLiteRepository,
    proxies: ProxyPool,
    limiter: AsyncRateLimiter,
) -> WeChatArticleClient | CurlCffiArticleClient:
    credential_getter = repo.get_credential
    kwargs = {
        "timeout": settings.request_timeout_seconds,
        "retries": settings.request_retries,
        "proxy_pool": proxies,
        "rate_limiter": limiter,
        "credential_getter": credential_getter,
        "image_proxy_base": image_proxy_base(settings),
        "tls_verify": settings.tls_verify,
    }
    transport = settings.article_transport
    if transport in {"auto", "curl", "curl_cffi", "tls"}:
        try:
            import curl_cffi  # noqa: F401
        except ImportError:
            if transport != "auto":
                raise RuntimeError("Install with wechat-rss-lite[tls] to use ARTICLE_TRANSPORT=curl") from None
        else:
            return CurlCffiArticleClient(impersonate="chrome120", **kwargs)
    return WeChatArticleClient(**kwargs)
