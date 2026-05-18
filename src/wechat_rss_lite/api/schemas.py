from __future__ import annotations

from typing import Any

try:
    from pydantic import BaseModel, HttpUrl
except ImportError as exc:
    raise RuntimeError("Install with wechat-rss-lite[api] to use the FastAPI app") from exc


class ParseRequest(BaseModel):
    url: HttpUrl


class RssRequest(BaseModel):
    title: str
    link: HttpUrl
    description: str = ""
    articles: list[dict[str, Any]]


class SubscriptionRequest(BaseModel):
    id: str
    title: str
    account_id: str = ""
    source_url: str = ""
    avatar_url: str = ""
    description: str = ""
    category_id: int | None = None
    enabled: bool = True


class SubscriptionUpdateRequest(BaseModel):
    enabled: bool | None = None
    category_id: int | None = None


class CategoryRequest(BaseModel):
    name: str
    description: str = ""
    color: str = "blue"


class CredentialRequest(BaseModel):
    id: str = "default"
    account_name: str = ""
    token: str = ""
    cookie: str = ""
    extra: dict[str, str] = {}
    expires_at: str | None = None


class VerificationRequest(BaseModel):
    id: str
    kind: str = "manual"
    target: str = ""
    verify_url: str = ""
    message: str = ""


class BlacklistRequest(BaseModel):
    account_id: str
    reason: str = ""


class RateLimitRequest(BaseModel):
    per_minute: int | None = None
    min_interval_seconds: float | None = None
