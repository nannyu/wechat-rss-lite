from __future__ import annotations

from collections.abc import Callable

from ..admin_auth import make_require_admin, make_require_rss_read
from ..config import Settings
from ..models import Subscription
from ..storage import SQLiteRepository


def build_admin_dep(settings: Settings) -> Callable[..., None]:
    from fastapi import Header, Query

    guard = make_require_admin(settings.admin_token)

    def admin_dep(
        authorization: str | None = Header(default=None),
        token: str | None = Query(default=None),
    ) -> None:
        guard(authorization=authorization, token=token)

    return admin_dep


def build_rss_dep(settings: Settings) -> Callable[..., None]:
    from fastapi import Header, Query

    guard = make_require_rss_read(settings.rss_read_token)

    def rss_dep(
        authorization: str | None = Header(default=None),
        token: str | None = Query(default=None),
    ) -> None:
        guard(authorization=authorization, token=token)

    return rss_dep


def make_find_subscription(repo: SQLiteRepository) -> Callable[[str], Subscription]:
    def find_subscription(subscription_id: str) -> Subscription:
        from fastapi import HTTPException

        subscription = next((item for item in repo.list_subscriptions() if item.id == subscription_id), None)
        if not subscription:
            raise HTTPException(status_code=404, detail="Subscription not found")
        return subscription

    return find_subscription
