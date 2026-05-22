from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import segno

from .models import Credential, LoginSession, LoginStatus


class LocalQrLoginProvider:
    """Default QR login provider for self-hosted admin access.

    This is a real QR-code flow owned by this application: scanning the code opens
    a local confirmation page, and confirming it marks the session as ready.
    Platform-specific providers can replace this class when integrating with a
    third-party identity system.
    """

    def __init__(
        self,
        *,
        base_url: str,
        repository: Any | None = None,
        session_ttl: timedelta = timedelta(minutes=10),
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.repository = repository
        self.session_ttl = session_ttl
        self._sessions: dict[str, LoginSession] = {}

    async def create_session(self) -> LoginSession:
        session_id = secrets.token_urlsafe(18)
        expires_at = datetime.now(timezone.utc) + self.session_ttl
        confirm_url = f"{self.base_url}/login/confirm/{session_id}"
        session = LoginSession(
            id=session_id,
            qrcode_url=segno.make(confirm_url).svg_data_uri(scale=6),
            status=LoginStatus.PENDING,
            message="请扫码打开确认页。",
            confirm_url=confirm_url,
            expires_at=expires_at,
        )
        self._save_session(session)
        return session

    async def poll_session(self, session_id: str) -> LoginSession:
        session = self._get_session(session_id)
        if _expired(session):
            session = _replace_session(session, status=LoginStatus.EXPIRED, message="登录二维码已过期。")
            self._save_session(session)
        return session

    async def confirm_session(self, session_id: str) -> LoginSession:
        session = await self.poll_session(session_id)
        if session.status == LoginStatus.EXPIRED:
            return session
        session = _replace_session(session, status=LoginStatus.CONFIRMED, message="扫码确认完成，可以返回后台完成登录。")
        self._save_session(session)
        return session

    async def complete_session(self, session_id: str) -> Credential:
        session = await self.poll_session(session_id)
        if session.status != LoginStatus.CONFIRMED:
            raise ValueError("Login session is not confirmed yet")
        return Credential(
            id="default",
            account_name="local-admin",
            token=secrets.token_urlsafe(24),
            extra={"provider": "local_qr", "session_id": session_id},
            expires_at=datetime.now(timezone.utc) + timedelta(days=4),
        )

    def _get_session(self, session_id: str) -> LoginSession:
        session = self.repository.get_login_session(session_id) if self.repository else None
        session = session or self._sessions.get(session_id)
        if not session:
            return LoginSession(
                id=session_id,
                qrcode_url="",
                status=LoginStatus.FAILED,
                message="登录会话不存在。",
            )
        return session

    def _save_session(self, session: LoginSession) -> None:
        if self.repository:
            self.repository.save_login_session(session)
        self._sessions[session.id] = session


def _expired(session: LoginSession) -> bool:
    return bool(session.expires_at and session.expires_at <= datetime.now(timezone.utc))


def _replace_session(session: LoginSession, *, status: LoginStatus, message: str) -> LoginSession:
    return LoginSession(
        id=session.id,
        qrcode_url=session.qrcode_url,
        status=status,
        message=message,
        confirm_url=session.confirm_url,
        created_at=session.created_at,
        expires_at=session.expires_at,
    )
