from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


@dataclass(frozen=True)
class Image:
    url: str
    alt: str = ""


@dataclass(frozen=True)
class Article:
    url: str
    title: str
    author: str = ""
    account_name: str = ""
    summary: str = ""
    content_html: str = ""
    text: str = ""
    content_type: str = "rich_text"
    unavailable_reason: str = ""
    published_at: datetime | None = None
    images: tuple[Image, ...] = field(default_factory=tuple)

    @property
    def published_or_now(self) -> datetime:
        return self.published_at or datetime.now(timezone.utc)


@dataclass(frozen=True)
class Subscription:
    id: str
    title: str
    account_id: str = ""
    source_url: str = ""
    enabled: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class LoginStatus(str, Enum):
    PENDING = "pending"
    SCANNED = "scanned"
    CONFIRMED = "confirmed"
    EXPIRED = "expired"
    FAILED = "failed"


@dataclass(frozen=True)
class LoginSession:
    id: str
    qrcode_url: str
    status: LoginStatus = LoginStatus.PENDING
    message: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None


@dataclass(frozen=True)
class Credential:
    id: str
    account_name: str = ""
    token: str = ""
    cookie: str = ""
    extra: dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None

    @property
    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at <= datetime.now(timezone.utc)


@dataclass(frozen=True)
class PollResult:
    subscription_id: str
    fetched: int
    stored: int
    failed: int
    message: str = ""
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class NotificationEvent:
    kind: str
    message: str
    target: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
