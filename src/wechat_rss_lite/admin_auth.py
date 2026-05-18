from __future__ import annotations

from collections.abc import Callable
from typing import Any


def make_require_admin(admin_token: str) -> Callable[..., None]:
    """FastAPI dependency: accept Bearer header or ?token= for iframe-friendly auth."""
    return _make_token_guard(admin_token, missing_detail="Admin token is not configured", invalid_detail="Admin token required")


def make_require_rss_read(rss_read_token: str) -> Callable[..., None]:
    """Optional RSS feed guard. When token is unset, feeds stay public (local dev)."""
    return _make_token_guard(
        rss_read_token,
        missing_detail="RSS read token is not configured",
        invalid_detail="RSS read token required",
        optional_when_unconfigured=True,
    )


def _make_token_guard(
    expected_token: str,
    *,
    missing_detail: str,
    invalid_detail: str,
    optional_when_unconfigured: bool = False,
) -> Callable[..., None]:
    def guard(authorization: str | None = None, token: str | None = None) -> None:
        from fastapi import HTTPException

        if not expected_token:
            if optional_when_unconfigured:
                return
            raise HTTPException(status_code=401, detail=missing_detail)
        provided = _extract_admin_token(authorization, token)
        if provided and provided == expected_token:
            return
        raise HTTPException(status_code=401, detail=invalid_detail)

    return guard


def _extract_admin_token(authorization: str | None, token: str | None) -> str | None:
    if token and token.strip():
        return token.strip()
    if not authorization:
        return None
    value = authorization.strip()
    if value.lower().startswith("bearer "):
        return value[7:].strip() or None
    return value or None


def dependency_kwargs(require_admin: Callable[..., None]) -> dict[str, Any]:
    try:
        from fastapi import Depends, Header, Query
    except ImportError as exc:
        raise RuntimeError("Install with wechat-rss-lite[api]") from exc

    def _guard(
        authorization: str | None = Header(default=None),
        token: str | None = Query(default=None),
    ) -> None:
        require_admin(authorization=authorization, token=token)

    return {"dependencies": [Depends(_guard)]}
