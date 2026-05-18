from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..adapters import AccountProvider, LoginProvider
from ..auth import AuthManager
from ..client import WeChatArticleClient
from ..config import Settings
from ..curl_client import CurlCffiArticleClient
from ..image_proxy import ImageProxy
from ..poller import RssPoller
from ..proxy import ProxyPool
from ..rate_limit import AsyncRateLimiter
from ..storage import SQLiteRepository
from ..webhook import WebhookNotifier


@dataclass(slots=True)
class ApiContext:
    settings: Settings
    repo: SQLiteRepository
    proxies: ProxyPool
    limiter: AsyncRateLimiter
    notifier: WebhookNotifier
    article_client: WeChatArticleClient | CurlCffiArticleClient
    accounts: AccountProvider
    login_provider: LoginProvider
    auth: AuthManager
    poller: RssPoller
    images: ImageProxy
    image_proxy_base: str
    api_image_proxy_base: str = "/image"
