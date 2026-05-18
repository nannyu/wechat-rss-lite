from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .models import Credential, LoginSession


@dataclass(frozen=True)
class AccountProfile:
    id: str
    name: str
    alias: str = ""
    avatar_url: str = ""
    description: str = ""


@dataclass(frozen=True)
class ArticleSummary:
    url: str
    title: str
    account_id: str = ""
    summary: str = ""
    published_at: int | None = None


class AccountProvider(Protocol):
    """Host-project adapter for authenticated account discovery.

    The core package does not own credentials or platform-specific account search.
    Applications can implement this protocol with their own compliant data source.
    """

    async def search_accounts(self, query: str, *, limit: int = 10) -> list[AccountProfile]:
        ...

    async def list_articles(
        self,
        account_id: str,
        *,
        offset: int = 0,
        limit: int = 20,
        keyword: str = "",
    ) -> list[ArticleSummary]:
        ...

    async def account_info(self, account_id: str) -> dict:
        ...


class LoginProvider(Protocol):
    """Host-project adapter for QR-code login.

    Implementations own the platform-specific login flow. The package stores the
    resulting credential and exposes stable HTTP/admin surfaces around it.
    """

    async def create_session(self) -> LoginSession:
        ...

    async def poll_session(self, session_id: str) -> LoginSession:
        ...

    async def complete_session(self, session_id: str) -> Credential:
        ...


class EmptyAccountProvider:
    async def search_accounts(self, query: str, *, limit: int = 10) -> list[AccountProfile]:
        return []

    async def list_articles(
        self,
        account_id: str,
        *,
        offset: int = 0,
        limit: int = 20,
        keyword: str = "",
    ) -> list[ArticleSummary]:
        return []

    async def account_info(self, account_id: str) -> dict:
        return {"id": account_id, "available": False}


class ManualLoginProvider:
    """Small development provider for externally obtained credentials."""

    def __init__(self, credential: Credential | None = None) -> None:
        self.credential = credential

    async def create_session(self) -> LoginSession:
        expires_at = datetime.now().astimezone()
        return LoginSession(
            id="manual",
            qrcode_url="",
            message="Configure a custom LoginProvider for QR-code login.",
            expires_at=expires_at,
        )

    async def poll_session(self, session_id: str) -> LoginSession:
        return LoginSession(
            id=session_id,
            qrcode_url="",
            message="No QR-code provider configured.",
        )

    async def complete_session(self, session_id: str) -> Credential:
        if self.credential:
            return self.credential
        return Credential(id="manual", account_name="manual")
