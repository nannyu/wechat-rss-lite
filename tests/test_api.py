from __future__ import annotations

import httpx

from wechat_rss_lite.adapters import AccountProfile, ArticleSummary
from wechat_rss_lite.api import create_app
from wechat_rss_lite.config import Settings
from wechat_rss_lite.storage import SQLiteRepository


class FakeProvider:
    async def search_accounts(self, query: str, *, limit: int = 10) -> list[AccountProfile]:
        return [AccountProfile(id="acct", name=query)]

    async def list_articles(
        self,
        account_id: str,
        *,
        offset: int = 0,
        limit: int = 20,
        keyword: str = "",
    ) -> list[ArticleSummary]:
        return [ArticleSummary(url="https://mp.weixin.qq.com/s/a", title="A", account_id=account_id)]


async def test_api_exposes_admin_accounts_and_subscriptions(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "test.db")
    app = create_app(
        settings=Settings(db_path=tmp_path / "test.db"),
        repository=repo,
        account_provider=FakeProvider(),
    )
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin = await client.get("/admin")
        accounts = await client.get("/accounts/search", params={"query": "Demo"})
        created = await client.post(
            "/subscriptions",
            json={"id": "acct", "title": "Demo", "account_id": "acct"},
        )
        subscriptions = await client.get("/subscriptions")

    assert admin.status_code == 200
    assert "wechat-rss-lite" in admin.text
    assert accounts.json()[0]["id"] == "acct"
    assert created.json()["id"] == "acct"
    assert subscriptions.json()[0]["title"] == "Demo"

