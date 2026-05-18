from __future__ import annotations

import httpx

from wechat_rss_lite.adapters import AccountProfile, ArticleSummary
from wechat_rss_lite.api import create_app
from wechat_rss_lite.config import Settings
from wechat_rss_lite.local_login import LocalQrLoginProvider
from wechat_rss_lite.models import Article
from wechat_rss_lite.storage import SQLiteRepository


class FakeProvider:
    async def search_accounts(self, query: str, *, limit: int = 10) -> list[AccountProfile]:
        return [
            AccountProfile(
                id="acct",
                name=query,
                avatar_url="https://example.com/avatar.png",
                description="Profile description",
            )
        ]

    async def list_articles(
        self,
        account_id: str,
        *,
        offset: int = 0,
        limit: int = 20,
        keyword: str = "",
    ) -> list[ArticleSummary]:
        return [ArticleSummary(url="https://mp.weixin.qq.com/s/a", title="A", account_id=account_id)]

    async def account_info(self, account_id: str) -> dict:
        return {"id": account_id, "available": True, "identity_name": "Demo Org"}


class FakeArticleClient:
    async def fetch_article(self, url: str) -> Article:
        return Article(url=url, title="Fetched A")


async def test_api_exposes_admin_accounts_and_subscriptions(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "test.db")
    app = create_app(
        settings=Settings(db_path=tmp_path / "test.db"),
        repository=repo,
        account_provider=FakeProvider(),
        login_provider=LocalQrLoginProvider(base_url="http://test"),
        article_client=FakeArticleClient(),
    )
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin = await client.get("/admin")
        stats = await client.get("/stats")
        rate_limit = await client.put(
            "/rate-limit",
            json={"per_minute": 12, "min_interval_seconds": 0.5},
        )
        accounts = await client.get("/accounts/search", params={"query": "Demo"})
        image = await client.get("/image", params={"url": "https://example.com/avatar.png"})
        session = await client.post("/login/sessions")
        confirm_page = await client.get(f"/login/confirm/{session.json()['id']}")
        confirmed = await client.post(f"/login/confirm/{session.json()['id']}")
        completed = await client.post(f"/login/sessions/{session.json()['id']}/complete")
        health_after_demo_login = await client.get("/health")
        credential_deleted = await client.delete("/credentials/default")
        health_after_delete = await client.get("/health")
        created = await client.post(
            "/subscriptions",
            json={
                "id": "acct",
                "title": "Demo",
                "account_id": "acct",
                "avatar_url": "/image?url=https%3A%2F%2Fexample.com%2Favatar.png",
                "description": "Profile description",
            },
        )
        category = await client.post(
            "/categories",
            json={"name": "Tech", "description": "Technology", "color": "green"},
        )
        recategorized = await client.patch(
            "/subscriptions/acct",
            json={"category_id": category.json()["id"]},
        )
        disabled = await client.patch("/subscriptions/acct", json={"enabled": False})
        enabled = await client.patch("/subscriptions/acct", json={"enabled": True})
        history = await client.post("/subscriptions/acct/history", params={"pages": 1, "page_size": 1})
        articles = await client.get("/subscriptions/acct/articles")
        history_articles = await client.get("/subscriptions/acct/articles", params={"source": "history"})
        account_info = await client.get("/accounts/acct/info")
        single_feed = await client.get("/feeds/acct.rss")
        history_feed = await client.get("/feeds/acct/history.rss")
        all_feed = await client.get("/feeds/all.rss")
        category_feed = await client.get(f"/feeds/categories/{category.json()['id']}.rss")
        exported_opml = await client.get("/subscriptions/export", params={"format": "opml"})
        exported_csv = await client.get("/subscriptions/export", params={"format": "csv"})
        verification_created = await client.post(
            "/verifications",
            json={
                "id": "verify-1",
                "kind": "captcha",
                "target": "acct",
                "verify_url": "https://example.com/verify",
                "message": "需要验证",
            },
        )
        verifications = await client.get("/verifications", params={"status": "pending"})
        verification_resolved = await client.post("/verifications/verify-1/resolve")
        blacklist_created = await client.post(
            "/blacklist",
            json={"account_id": "acct", "reason": "高频触发验证码"},
        )
        blacklist = await client.get("/blacklist")
        blacklist_removed = await client.delete("/blacklist/acct")
        imported = await client.post(
            "/subscriptions/import",
            data={"text": "alpha, beta\ngamma"},
        )
        subscriptions = await client.get("/subscriptions")
        categories = await client.get("/categories")

    assert admin.status_code == 200
    assert "wechat-rss-lite" in admin.text
    assert "loginDialog" in admin.text
    assert "登录二维码" in admin.text
    assert "scanloginqrcode?action=getqrcode" in admin.text
    assert "查看登录会话" in admin.text
    assert "点击扫码登录创建会话后扫码确认" not in admin.text
    assert "未登录" in admin.text
    assert "未登录微信" in admin.text
    assert "验证登录" in admin.text
    assert "清除登录状态" in admin.text
    assert "statusCard" in admin.text
    assert "statusRaw" in admin.text
    assert "批量导入" in admin.text
    assert "bulkFile" in admin.text
    assert "accountResults" in admin.text
    assert "result-avatar" in admin.text
    assert "result-desc" in admin.text
    assert "加入订阅" in admin.text
    assert "订阅成功" in admin.text
    assert "subscribedIds" in admin.text
    assert "验证处理" not in admin.text
    assert "subscriptionList" in admin.text
    assert "switch-button" in admin.text
    assert "toggleSubscription" in admin.text
    assert "复制 RSS" in admin.text
    assert "黑名单管理" in admin.text
    assert "blacklistList" in admin.text
    assert "RSS 与分类" in admin.text
    assert "导出 OPML" in admin.text
    assert "categoryList" in admin.text
    assert "健康检查与限频" in admin.text
    assert "ratePerMinute" in admin.text
    assert "应用推荐值" in admin.text
    assert "每分钟最多 6 次" in admin.text
    assert "获取历史" in admin.text
    assert "historyPages" in admin.text
    assert "articleList" in admin.text
    assert stats.json()["rate_limit"]["per_minute"] == 6
    assert stats.json()["rate_limit"]["min_interval_seconds"] == 10.0
    assert rate_limit.json()["per_minute"] == 12
    assert rate_limit.json()["min_interval_seconds"] == 0.5
    assert session.json()["qrcode_url"].startswith("data:image/svg+xml")
    assert "确认登录" in confirm_page.text
    assert "扫码确认完成" in confirmed.text
    assert completed.json()["configured"] is False
    assert completed.json()["demo"] is True
    assert health_after_demo_login.json()["credential"]["stored"] is True
    assert health_after_demo_login.json()["credential"]["wechat_configured"] is False
    assert credential_deleted.json()["deleted"] is True
    assert health_after_delete.json()["credential"]["stored"] is False
    assert accounts.json()[0]["id"] == "acct"
    assert accounts.json()[0]["avatar_url"].startswith("/image?url=")
    assert accounts.json()[0]["raw_avatar_url"] == "https://example.com/avatar.png"
    assert image.status_code == 400
    assert created.json()["id"] == "acct"
    assert created.json()["avatar_url"].startswith("/image?url=")
    assert created.json()["description"] == "Profile description"
    assert created.json()["feed_url"].endswith("/feeds/acct.rss")
    assert category.json()["name"] == "Tech"
    assert recategorized.json()["category_id"] == category.json()["id"]
    assert disabled.json()["enabled"] is False
    assert enabled.json()["enabled"] is True
    assert history.json()["message"] == "history"
    assert articles.json()[0]["title"] == "Fetched A"
    assert history_articles.json()[0]["source"] == "history"
    assert account_info.json()["identity_name"] == "Demo Org"
    assert "<rss" in single_feed.text
    assert "历史文章" in history_feed.text
    assert "<rss" in all_feed.text
    assert "<rss" in category_feed.text
    assert "<opml" in exported_opml.text
    assert "RSS URL" in exported_csv.text
    assert verification_created.json()["status"] == "pending"
    assert verifications.json()[0]["id"] == "verify-1"
    assert verification_resolved.json()["status"] == "resolved"
    assert blacklist_created.json()["account_id"] == "acct"
    assert blacklist.json()[0]["reason"] == "高频触发验证码"
    assert blacklist_removed.json()["deleted"] is True
    assert imported.json()["imported"] == 3
    assert categories.json()[0]["subscription_count"] >= 1
    assert {item["id"] for item in subscriptions.json()} >= {"acct", "alpha", "beta", "gamma"}
