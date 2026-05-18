from __future__ import annotations

import base64
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx

from .models import Credential, LoginSession, LoginStatus


MP_BASE_URL = "https://mp.weixin.qq.com"
QR_ENDPOINT = f"{MP_BASE_URL}/cgi-bin/scanloginqrcode"
BIZ_LOGIN_ENDPOINT = f"{MP_BASE_URL}/cgi-bin/bizlogin"


@dataclass
class _WeChatLoginState:
    client: httpx.AsyncClient
    session: LoginSession


class WeChatMpLoginProvider:
    """QR login provider for WeChat Official Account Platform.

    The flow mirrors the browser login sequence at a protocol level:
    start a biz-login session, fetch the QR image, poll scan status, then
    exchange the confirmed session for cookies and a token.
    """

    def __init__(
        self,
        *,
        timeout: float = 15.0,
        session_ttl: timedelta = timedelta(minutes=10),
    ) -> None:
        self.timeout = timeout
        self.session_ttl = session_ttl
        self._states: dict[str, _WeChatLoginState] = {}

    async def create_session(self) -> LoginSession:
        session_id = secrets.token_urlsafe(18)
        client = httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=False,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
                ),
                "Referer": f"{MP_BASE_URL}/",
            },
        )
        expires_at = datetime.now(timezone.utc) + self.session_ttl
        await client.post(
            BIZ_LOGIN_ENDPOINT,
            params={"action": "startlogin"},
            data={
                "userlang": "zh_CN",
                "redirect_url": "",
                "login_type": 3,
                "sessionid": session_id,
                "token": "",
                "lang": "zh_CN",
                "f": "json",
                "ajax": 1,
            },
        )
        qr = await client.get(
            QR_ENDPOINT,
            params={"action": "getqrcode", "random": int(time.time() * 1000)},
        )
        qr.raise_for_status()
        media_type = _image_media_type(qr.headers.get("content-type", ""), qr.content)
        if not media_type:
            await client.aclose()
            raise RuntimeError("WeChat did not return a QR-code image. Retry creating the login session.")

        session = LoginSession(
            id=session_id,
            qrcode_url=f"data:{media_type};base64,{base64.b64encode(qr.content).decode('ascii')}",
            status=LoginStatus.PENDING,
            message="请使用微信扫描此二维码，并在手机端确认登录公众平台。",
            expires_at=expires_at,
        )
        self._states[session_id] = _WeChatLoginState(client=client, session=session)
        return session

    async def poll_session(self, session_id: str) -> LoginSession:
        state = self._states.get(session_id)
        if not state:
            return LoginSession(
                id=session_id,
                qrcode_url="",
                status=LoginStatus.FAILED,
                message="登录会话不存在，请重新创建。",
            )
        if state.session.expires_at and state.session.expires_at <= datetime.now(timezone.utc):
            state.session = _replace_session(state.session, status=LoginStatus.EXPIRED, message="登录二维码已过期。")
            return state.session

        response = await state.client.get(
            QR_ENDPOINT,
            params={"action": "ask", "token": "", "lang": "zh_CN", "f": "json", "ajax": 1},
        )
        response.raise_for_status()
        data = response.json()
        scan_status = int(data.get("status", 0) or 0)
        if scan_status == 1:
            state.session = _replace_session(
                state.session,
                status=LoginStatus.CONFIRMED,
                message="手机端已确认登录，请点击完成登录保存凭证。",
            )
        elif scan_status in {4, 6}:
            state.session = _replace_session(
                state.session,
                status=LoginStatus.SCANNED,
                message="已扫码，请在手机端确认登录。",
            )
        elif scan_status in {2, 3}:
            state.session = _replace_session(
                state.session,
                status=LoginStatus.EXPIRED,
                message="登录二维码已过期，请刷新二维码。",
            )
        return state.session

    async def complete_session(self, session_id: str) -> Credential:
        state = self._states.get(session_id)
        if not state:
            raise ValueError("Login session does not exist")
        session = await self.poll_session(session_id)
        if session.status != LoginStatus.CONFIRMED:
            raise ValueError("Login session is not confirmed yet")

        response = await state.client.post(
            BIZ_LOGIN_ENDPOINT,
            params={"action": "login"},
            data={
                "userlang": "zh_CN",
                "redirect_url": "",
                "cookie_forbidden": 0,
                "cookie_cleaned": 0,
                "plugin_used": 0,
                "login_type": 3,
                "token": "",
                "lang": "zh_CN",
                "f": "json",
                "ajax": 1,
            },
        )
        response.raise_for_status()
        data = response.json()
        ret = data.get("base_resp", {}).get("ret", 0)
        if ret != 0:
            message = data.get("base_resp", {}).get("err_msg", "WeChat login failed")
            raise ValueError(message)

        token = _extract_token(data.get("redirect_url", ""))
        if not token:
            raise ValueError("WeChat login did not return a token")
        cookie = "; ".join(f"{cookie.name}={cookie.value}" for cookie in state.client.cookies.jar)
        account_name = "wechat-mp"
        validation = await validate_wechat_credential(
            Credential(id="default", account_name=account_name, token=token, cookie=cookie),
            client=state.client,
        )
        if validation.get("account_name"):
            account_name = str(validation["account_name"])
        await state.client.aclose()
        self._states.pop(session_id, None)
        return Credential(
            id="default",
            account_name=account_name,
            token=token,
            cookie=cookie,
            extra={
                "provider": "wechat_mp",
                "username": str(validation.get("username", "")),
            },
            expires_at=datetime.now(timezone.utc) + timedelta(days=3),
        )


def _image_media_type(content_type: str, body: bytes) -> str:
    if body.startswith(b"\x89PNG"):
        return "image/png"
    if body.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if "image/png" in content_type:
        return "image/png"
    if "image/jpeg" in content_type or "image/jpg" in content_type:
        return "image/jpeg"
    return ""


def _extract_token(redirect_url: str) -> str:
    if not redirect_url:
        return ""
    parsed = urlparse(f"{MP_BASE_URL}{redirect_url}" if redirect_url.startswith("/") else redirect_url)
    return parse_qs(parsed.query).get("token", [""])[0]


async def validate_wechat_credential(
    credential: Credential,
    *,
    timeout: float = 15.0,
    client: httpx.AsyncClient | None = None,
) -> dict[str, object]:
    if not credential.token or not credential.cookie:
        return {"valid": False, "reason": "missing_token_or_cookie"}
    close_client = client is None
    client = client or httpx.AsyncClient(timeout=timeout, follow_redirects=False)
    try:
        response = await client.get(
            f"{MP_BASE_URL}/cgi-bin/home",
            params={"t": "home/index", "lang": "zh_CN", "token": credential.token},
            headers={
                "Cookie": credential.cookie,
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
                ),
                "Referer": f"{MP_BASE_URL}/",
            },
        )
        text = response.text if "text/html" in response.headers.get("content-type", "") else ""
        location = response.headers.get("location", "")
        account_name = _match_js_string(text, "nick_name")
        username = _match_js_string(text, "user_name")
        login_redirect = "login" in location.lower()
        login_page = "扫码登录" in text or ("登录" in text and not account_name)
        valid = response.status_code == 200 and not login_redirect and not login_page and bool(account_name or username)
        return {
            "valid": valid,
            "status_code": response.status_code,
            "account_name": account_name,
            "username": username,
            "reason": "ok" if valid else "wechat_rejected_or_unrecognized",
        }
    finally:
        if close_client:
            await client.aclose()


def _match_js_string(text: str, key: str) -> str:
    import re

    match = re.search(rf'{re.escape(key)}\s*:\s*"([^"]*)"', text)
    return match.group(1) if match else ""


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
