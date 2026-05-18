from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .adapters import LoginProvider, ManualLoginProvider
from .models import Credential, LoginSession, NotificationEvent
from .storage import SQLiteRepository
from .webhook import WebhookNotifier


class AuthManager:
    def __init__(
        self,
        *,
        repository: SQLiteRepository,
        login_provider: LoginProvider | None = None,
        notifier: WebhookNotifier | None = None,
        warning_before: timedelta = timedelta(hours=24),
    ) -> None:
        self.repository = repository
        self.login_provider = login_provider or ManualLoginProvider()
        self.notifier = notifier or WebhookNotifier()
        self.warning_before = warning_before

    async def create_login_session(self) -> LoginSession:
        return await self.login_provider.create_session()

    async def poll_login_session(self, session_id: str) -> LoginSession:
        return await self.login_provider.poll_session(session_id)

    async def complete_login_session(self, session_id: str, *, credential_id: str = "default") -> Credential:
        credential = await self.login_provider.complete_session(session_id)
        if credential.id != credential_id:
            credential = Credential(
                id=credential_id,
                account_name=credential.account_name,
                token=credential.token,
                cookie=credential.cookie,
                extra=credential.extra,
                created_at=credential.created_at,
                expires_at=credential.expires_at,
            )
        self.repository.save_credential(credential)
        return credential

    async def check_expiry(self, credential_id: str = "default") -> NotificationEvent | None:
        credential = self.repository.get_credential(credential_id)
        if not credential or not credential.expires_at:
            return None
        now = datetime.now(timezone.utc)
        if credential.expires_at <= now:
            event = NotificationEvent(kind="credential.expired", message="Credential has expired.")
        elif credential.expires_at - now <= self.warning_before:
            event = NotificationEvent(kind="credential.expiring", message="Credential will expire soon.")
        else:
            return None
        await self.notifier.send(event)
        return event

