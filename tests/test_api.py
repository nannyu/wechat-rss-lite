from __future__ import annotations

import re
import shutil
import subprocess

import httpx
import pytest

from wechat_rss_lite.adapters import AccountProfile, ArticleSummary
from wechat_rss_lite.admin import ADMIN_HTML
from wechat_rss_lite.api import create_app
from wechat_rss_lite.config import Settings
from wechat_rss_lite.local_login import LocalQrLoginProvider
from wechat_rss_lite.models import Article, Subscription
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


class RefreshingArticleClient:
    async def fetch_article(self, url: str) -> Article:
        return Article(url=url, title="Refetched", text="Fresh content")


def test_admin_embedded_script_is_valid_javascript(tmp_path) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    match = re.search(r"<script>(?P<script>[\s\S]*)</script>", ADMIN_HTML)
    assert match is not None
    script_path = tmp_path / "admin.js"
    script_path.write_text(match.group("script"), encoding="utf-8")

    result = subprocess.run([node, "--check", str(script_path)], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr


async def test_api_exposes_admin_accounts_and_subscriptions(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "test.db")
    admin_headers = {"Authorization": "Bearer test-token"}
    app = create_app(
        settings=Settings(db_path=tmp_path / "test.db", admin_token="test-token"),
        repository=repo,
        account_provider=FakeProvider(),
        login_provider=LocalQrLoginProvider(base_url="http://test"),
        article_client=FakeArticleClient(),
    )
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin = await client.get("/admin")
        stats = await client.get("/stats", headers=admin_headers)
        rate_limit = await client.put(
            "/rate-limit",
            json={"per_minute": 12, "min_interval_seconds": 0.5},
            headers=admin_headers,
        )
        accounts = await client.get("/accounts/search", params={"query": "Demo"}, headers=admin_headers)
        image = await client.get("/image", params={"url": "http://127.0.0.1/avatar.png"})
        session = await client.post("/login/sessions", headers=admin_headers)
        confirm_page = await client.get(f"/login/confirm/{session.json()['id']}")
        confirmed = await client.post(f"/login/confirm/{session.json()['id']}")
        completed = await client.post(f"/login/sessions/{session.json()['id']}/complete", headers=admin_headers)
        health_after_demo_login = await client.get("/health")
        credential_deleted = await client.delete("/credentials/default", headers=admin_headers)
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
            headers=admin_headers,
        )
        category = await client.post(
            "/categories",
            json={"name": "Tech", "description": "Technology", "color": "green"},
            headers=admin_headers,
        )
        recategorized = await client.patch(
            "/subscriptions/acct",
            json={"category_id": category.json()["id"]},
            headers=admin_headers,
        )
        disabled = await client.patch("/subscriptions/acct", json={"enabled": False}, headers=admin_headers)
        enabled = await client.patch("/subscriptions/acct", json={"enabled": True}, headers=admin_headers)
        history = await client.post(
            "/subscriptions/acct/history",
            params={"pages": 1, "page_size": 1},
            headers=admin_headers,
        )
        articles = await client.get("/subscriptions/acct/articles", headers=admin_headers)
        history_articles = await client.get(
            "/subscriptions/acct/articles",
            params={"source": "history"},
            headers=admin_headers,
        )
        repo.save_article(
            Article(url="https://mp.weixin.qq.com/s/history-only", title="History Only", source="history"),
            subscription_id="acct",
            source="history",
        )
        downloaded_articles = await client.get("/articles", params={"limit": 10}, headers=admin_headers)
        downloaded_history = await client.get(
            "/articles",
            params={"source": "history", "limit": 10},
            headers=admin_headers,
        )
        downloaded_article = await client.get(
            "/articles/read",
            params={"url": "https://mp.weixin.qq.com/s/history-only"},
            headers=admin_headers,
        )
        account_info = await client.get("/accounts/acct/info", headers=admin_headers)
        single_feed = await client.get("/feeds/acct.rss")
        history_feed = await client.get("/feeds/acct/history.rss")
        all_feed = await client.get("/feeds/all.rss")
        category_feed = await client.get(f"/feeds/categories/{category.json()['id']}.rss")
        exported_opml = await client.get(
            "/subscriptions/export",
            params={"format": "opml"},
            headers=admin_headers,
        )
        exported_csv = await client.get(
            "/subscriptions/export",
            params={"format": "csv"},
            headers=admin_headers,
        )
        verification_created = await client.post(
            "/verifications",
            json={
                "id": "verify-1",
                "kind": "captcha",
                "target": "acct",
                "verify_url": "https://example.com/verify",
                "message": "需要验证",
            },
            headers=admin_headers,
        )
        verifications = await client.get(
            "/verifications",
            params={"status": "pending"},
            headers=admin_headers,
        )
        verification_resolved = await client.post("/verifications/verify-1/resolve", headers=admin_headers)
        blacklist_created = await client.post(
            "/blacklist",
            json={"account_id": "acct", "reason": "高频触发验证码"},
            headers=admin_headers,
        )
        blacklist = await client.get("/blacklist", headers=admin_headers)
        blacklist_removed = await client.delete("/blacklist/acct", headers=admin_headers)
        imported = await client.post(
            "/subscriptions/import",
            data={"text": "alpha, beta\ngamma"},
            headers=admin_headers,
        )
        subscriptions = await client.get("/subscriptions", headers=admin_headers)
        categories = await client.get("/categories", headers=admin_headers)

    assert admin.status_code == 200
    assert "wechat-rss-lite" in admin.text
    assert "loginDialog" in admin.text
    assert "管理令牌" in admin.text
    assert "ADMIN_API_TOKEN" in admin.text
    assert "扫码登录微信平台" in admin.text
    assert "打开确认页" in admin.text
    assert "loginConfirmUrl" in admin.text
    assert "未登录" in admin.text
    assert "未登录微信" in admin.text
    assert "验证登录" in admin.text
    assert "清除状态" in admin.text
    assert "statusCard" in admin.text
    assert "statusRaw" in admin.text
    assert "批量导入" in admin.text
    assert "bulkFile" in admin.text
    subscriptions_section = admin.text.split('<section id="sec-subscriptions"')[1].split('<section id="sec-categories"')[0]
    categories_section = admin.text.split('<section id="sec-categories"')[1].split('<section id="sec-settings"')[0]
    settings_section = admin.text.split('<section id="sec-settings"')[1].split("</section>")[0]
    assert "批量导入订阅" in subscriptions_section
    assert "bulkFile" in subscriptions_section
    assert "创建新分类" in subscriptions_section
    assert "categoryList" in subscriptions_section
    assert "批量导入订阅" not in settings_section
    assert "创建新分类" not in categories_section
    assert "categoryList" not in categories_section
    assert "accountResults" in admin.text
    assert "订阅成功" in admin.text
    assert "subscribedIds" in admin.text
    assert "验证处理" not in admin.text
    assert "subscriptionList" in admin.text
    assert "switch-btn" in admin.text
    assert "复制 RSS" in admin.text
    assert "黑名单管理" in admin.text
    assert "blacklistList" in admin.text
    assert "RSS 聚合" in admin.text
    assert "RSS 链接生成" in admin.text
    assert "按公众号" in admin.text
    assert "按分类" in admin.text
    assert "模糊查找" in admin.text
    assert "全选" in admin.text
    assert "反选" in admin.text
    assert "generatedRssLinks" in admin.text
    assert "copyGeneratedRssLinks" in admin.text
    assert "selectVisibleRssItems" in admin.text
    assert "导出 OPML" in admin.text
    assert "categoryList" in admin.text
    assert "健康检查与限频" in admin.text
    assert "ratePerMinute" in admin.text
    assert "recommendedRateLimit" in admin.text
    assert "articleList" in admin.text
    assert "文章阅读" in admin.text
    assert "downloadedArticleList" in admin.text
    assert "articleReaderFrame" in admin.text
    assert "loadDownloadedArticles" in admin.text
    assert "重新拉取全部文章" in admin.text
    assert "refreshSubscriptionArticles" in admin.text
    assert "refreshCurrentReaderArticle" in admin.text
    assert "readerHtmlUrl" in admin.text
    assert "articles/read/html" in admin.text
    assert stats.json()["rate_limit"]["per_minute"] == 6
    assert stats.json()["rate_limit"]["min_interval_seconds"] == 10.0
    assert rate_limit.json()["per_minute"] == 12
    assert rate_limit.json()["min_interval_seconds"] == 0.5
    assert session.json()["qrcode_url"].startswith("data:image/svg+xml")
    assert session.json()["confirm_url"].startswith("http://test/login/confirm/")
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
    assert "not allowed" in image.text.lower()
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
    assert downloaded_articles.json()[0]["status"] == "fetched"
    assert downloaded_history.json()[0]["source"] == "history"
    assert downloaded_article.json()["title"] == "History Only"
    assert account_info.json()["identity_name"] == "Demo Org"
    assert "<rss" in single_feed.text
    assert "History Only" not in single_feed.text
    assert "历史文章" in history_feed.text
    assert "History Only" in history_feed.text
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


async def test_refresh_downloaded_articles_refetches_and_overwrites(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "test.db")
    repo.add_subscription(Subscription(id="acct", title="Acct"))
    repo.save_article(
        Article(url="https://mp.weixin.qq.com/s/a", title="Old", text="Old content"),
        subscription_id="acct",
    )
    app = create_app(
        settings=Settings(db_path=tmp_path / "test.db", admin_token="test-token"),
        repository=repo,
        article_client=RefreshingArticleClient(),
    )
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        single = await client.post(
            "/articles/refresh",
            params={"url": "https://mp.weixin.qq.com/s/a"},
            headers={"Authorization": "Bearer test-token"},
        )
        article = await client.get(
            "/articles/read",
            params={"url": "https://mp.weixin.qq.com/s/a"},
            headers={"Authorization": "Bearer test-token"},
        )
        batch = await client.post(
            "/subscriptions/acct/articles/refresh",
            headers={"Authorization": "Bearer test-token"},
        )

    assert single.status_code == 200
    assert single.json()["refreshed"] == 1
    assert article.json()["title"] == "Refetched"
    assert article.json()["text"] == "Fresh content"
    assert batch.json()["requested"] == 1


async def test_admin_endpoints_require_configured_token(tmp_path) -> None:
    app = create_app(settings=Settings(db_path=tmp_path / "test.db"))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        no_token = await client.put("/rate-limit", json={"per_minute": 12})

    assert no_token.status_code == 401
    assert no_token.json()["detail"] == "Admin token is not configured"


async def test_downloaded_articles_require_admin_token(tmp_path) -> None:
    app = create_app(settings=Settings(db_path=tmp_path / "test.db", admin_token="test-token"))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        denied = await client.get("/articles", params={"limit": 1})
        allowed = await client.get("/articles", params={"limit": 1}, headers={"Authorization": "Bearer test-token"})

    assert denied.status_code == 401
    assert allowed.status_code == 200


async def test_sensitive_account_endpoints_require_admin_token(tmp_path) -> None:
    app = create_app(
        settings=Settings(db_path=tmp_path / "test.db", admin_token="test-token"),
        account_provider=FakeProvider(),
    )
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        unauthenticated = await client.get("/accounts/search", params={"query": "Demo"})
        authenticated = await client.get(
            "/accounts/search",
            params={"query": "Demo"},
            headers={"Authorization": "Bearer test-token"},
        )

    assert unauthenticated.status_code == 401
    assert authenticated.status_code == 200
    assert authenticated.json()[0]["id"] == "acct"


async def test_parse_article_rejects_non_wechat_urls(tmp_path) -> None:
    app = create_app(
        settings=Settings(db_path=tmp_path / "test.db", admin_token="test-token"),
        article_client=FakeArticleClient(),
    )
    transport = httpx.ASGITransport(app=app)
    admin_headers = {"Authorization": "Bearer test-token"}

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        rejected = await client.post(
            "/articles/parse",
            json={"url": "http://127.0.0.1/admin"},
            headers=admin_headers,
        )
        accepted = await client.post(
            "/articles/parse",
            json={"url": "https://mp.weixin.qq.com/s/example"},
            headers=admin_headers,
        )

    assert rejected.status_code == 400
    assert "mp.weixin.qq.com" in rejected.json()["detail"]
    assert accepted.status_code == 200
    assert accepted.json()["title"] == "Fetched A"


async def test_rss_feed_requires_token_when_configured(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "test.db")
    repo.add_subscription(Subscription(id="acct", title="Demo"))
    app = create_app(
        settings=Settings(
            db_path=tmp_path / "test.db",
            admin_token="admin-secret",
            rss_read_token="rss-secret",
            site_url="http://test",
        ),
        repository=repo,
    )
    transport = httpx.ASGITransport(app=app)
    rss_headers = {"Authorization": "Bearer rss-secret"}

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        denied = await client.get("/feeds/acct.rss")
        allowed = await client.get("/feeds/acct.rss", headers=rss_headers)
        allowed_query = await client.get("/feeds/acct.rss", params={"token": "rss-secret"})
        listing = await client.get("/subscriptions", headers={"Authorization": "Bearer admin-secret"})

    assert denied.status_code == 401
    assert "<rss" in allowed.text
    assert "<rss" in allowed_query.text
    assert "token=rss-secret" in listing.json()[0]["feed_url"]


async def test_rss_feed_public_without_read_token(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "test.db")
    repo.add_subscription(Subscription(id="acct", title="Demo"))
    app = create_app(settings=Settings(db_path=tmp_path / "test.db", site_url="http://test"), repository=repo)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        feed = await client.get("/feeds/acct.rss")

    assert feed.status_code == 200
    assert "<rss" in feed.text
