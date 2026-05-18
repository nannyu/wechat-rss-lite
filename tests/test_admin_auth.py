from __future__ import annotations

import pytest

from wechat_rss_lite.admin_auth import make_require_admin


def test_make_require_admin_accepts_bearer_header() -> None:
    guard = make_require_admin("secret")
    guard(authorization="Bearer secret", token=None)


def test_make_require_admin_accepts_query_token() -> None:
    guard = make_require_admin("secret")
    guard(authorization=None, token="secret")


def test_make_require_admin_rejects_missing_token() -> None:
    guard = make_require_admin("secret")
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        guard(authorization=None, token=None)
    assert exc.value.status_code == 401
