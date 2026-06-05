from __future__ import annotations

from datetime import datetime, timedelta, timezone

from wechat_rss_lite.adapters import AccountProfile, ArticleSummary
from wechat_rss_lite.client import WeChatArticleClient
from wechat_rss_lite.models import Article, Credential, Subscription
from wechat_rss_lite.parser import parse_article_html
from wechat_rss_lite.poller import RssPoller
from wechat_rss_lite.storage import SQLiteRepository


def test_parse_audio_image_only_and_unavailable_types() -> None:
    audio = """
    <html><head><meta property="og:title" content="Audio"></head>
    <body><script>window.item_show_type = '7'; var nickname = "Acct";</script></body></html>
    """
    image_only = """
    <html><head><title>Images</title></head><body>
    <div id="js_content"><img data-src="https://mmbiz.qpic.cn/a.jpg"></div>
    </body></html>
    """
    unavailable = "<html><head><title>Gone</title></head><body>该内容已被发布者删除</body></html>"
    verification = "<html><head><title>Verify</title></head><body>环境异常 完成验证后即可继续访问 去验证</body></html>"

    assert parse_article_html(audio, "https://mp.weixin.qq.com/s/a").content_type == "audio_share"
    image_article = parse_article_html(image_only, "https://mp.weixin.qq.com/s/b")
    assert image_article.content_type == "image_only"
    assert image_article.text == "[纯图片文章，共 1 张图片]"
    gone = parse_article_html(unavailable, "https://mp.weixin.qq.com/s/c")
    assert gone.content_type == "unavailable"
    assert gone.unavailable_reason == "该内容已被发布者删除"
    verify = parse_article_html(verification, "https://mp.weixin.qq.com/s/d")
    assert verify.content_type == "verification_required"
    assert "可重试" in verify.text


def test_parse_wechat_specialized_content_types() -> None:
    image_text = """
    <html><head><meta property="og:title" content="Images"></head>
    <body><script>window.item_show_type = '8';</script>
    <div id="js_content">
      <p>第一段</p>
      <img data-src="https://mmbiz.qpic.cn/a.jpg" alt="a">
      <p>第二段</p>
      <img data-original="/b.jpg">
    </div></body></html>
    """
    short_text = """
    <html><head><meta property="og:title" content="Short"></head>
    <body><script>window.item_show_type = '10'; var msg_desc = "短内容正文";</script></body></html>
    """
    audio = """
    <html><head><meta property="og:title" content="Voice"></head>
    <body><div id="js_content"><p>开场白</p></div>
      <mpvoice name="访谈音频" play_length="42"></mpvoice>
    </body></html>
    """

    image_article = parse_article_html(image_text, "https://mp.weixin.qq.com/s/img")
    assert image_article.content_type == "image_text"
    assert image_article.text == "第一段\n第二段"
    assert [img.url for img in image_article.images] == [
        "https://mmbiz.qpic.cn/a.jpg",
        "https://mp.weixin.qq.com/b.jpg",
    ]
    assert 'data-original-src="https://mmbiz.qpic.cn/a.jpg"' in image_article.content_html

    short_article = parse_article_html(short_text, "https://mp.weixin.qq.com/s/short")
    assert short_article.content_type == "short_text"
    assert short_article.text == "短内容正文"

    audio_article = parse_article_html(audio, "https://mp.weixin.qq.com/s/audio")
    assert audio_article.content_type == "audio_article"
    assert "开场白" in audio_article.text
    assert "音频：访谈音频" in audio_article.text


def test_parse_finer_unavailable_categories() -> None:
    paywalled = """
    <html><head><title>Paid</title></head><body>付费后可继续阅读</body></html>
    """
    empty_dynamic = """
    <html><head><title>Private</title></head><body>
    <script>window.item_show_type = '7';</script><div id="app"></div>
    <!-- https://mp.weixin.qq.com -->
    </body></html>
    """

    paid = parse_article_html(paywalled, "https://mp.weixin.qq.com/s/paid")
    assert paid.content_type == "unavailable"
    assert paid.unavailable_reason == "该内容需要付费后查看"

    private = parse_article_html(empty_dynamic, "https://mp.weixin.qq.com/s/private")
    assert private.content_type == "unavailable"
    assert "动态内容为空" in private.unavailable_reason


def test_storage_credentials_and_poll_runs(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "test.db")
    credential = Credential(
        id="default",
        account_name="Acct",
        token="token",
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    repo.save_credential(credential)

    assert repo.get_credential().account_name == "Acct"
    assert repo.get_credential().is_expired is False


def test_article_client_uses_saved_wechat_credentials() -> None:
    credential = Credential(id="default", token="token-1", cookie="wxuin=abc")
    client = WeChatArticleClient(credential_getter=lambda: credential)

    try:
        url = client._url_with_token("https://mp.weixin.qq.com/s/a?__biz=biz")
        headers = client._headers_for_request()
    finally:
        # No request was made, but close the owned httpx client cleanly in async tests.
        import asyncio

        asyncio.run(client.aclose())

    assert "token=token-1" in url
    assert headers["Cookie"] == "wxuin=abc"


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


class FakeArticleClient:
    async def fetch_article(self, url: str) -> Article:
        return Article(url=url, title="A")


class VerificationArticleClient:
    async def fetch_article(self, url: str) -> Article:
        return Article(
            url=url,
            title="Verify",
            text="访问触发验证，稍后或人工处理后可重试。",
            content_type="verification_required",
            status="verification_required",
        )


class HistoryProvider:
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
        if offset >= 2:
            return []
        return [
            ArticleSummary(
                url=f"https://mp.weixin.qq.com/s/history-{offset}",
                title=f"History {offset}",
                account_id=account_id,
            )
        ]


class DatedHistoryProvider:
    def __init__(self) -> None:
        self.base = datetime(2026, 1, 10, tzinfo=timezone.utc)

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
        items = [
            ArticleSummary(
                url=f"https://mp.weixin.qq.com/s/dated-{index}",
                title=f"Dated {index}",
                account_id=account_id,
                published_at=int((self.base - timedelta(days=index)).timestamp()),
            )
            for index in range(6)
        ]
        return items[offset:offset + limit]


class OffsetTrackingHistoryProvider:
    def __init__(self) -> None:
        self.offsets: list[int] = []

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
        self.offsets.append(offset)
        return [
            ArticleSummary(
                url=f"https://mp.weixin.qq.com/s/offset-{index}",
                title=f"Offset {index}",
                account_id=account_id,
            )
            for index in range(offset, offset + limit)
        ]


async def test_poller_fetches_and_stores_articles(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "test.db")
    subscription = Subscription(id="acct", title="Account", account_id="acct")
    repo.add_subscription(subscription)
    poller = RssPoller(
        repository=repo,
        account_provider=FakeProvider(),
        article_client=FakeArticleClient(),
    )

    result = await poller.poll_subscription(subscription)

    assert result.fetched == 1
    assert result.stored == 1
    assert repo.recent_articles(subscription_id="acct")[0].title == "A"
    assert repo.latest_poll_results()[0].subscription_id == "acct"


async def test_poller_fetches_history_pages_into_local_database(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "test.db")
    subscription = Subscription(id="acct", title="Account", account_id="acct")
    repo.add_subscription(subscription)
    poller = RssPoller(
        repository=repo,
        account_provider=HistoryProvider(),
        article_client=FakeArticleClient(),
    )

    result = await poller.fetch_history(subscription, pages=3, page_size=1)

    assert result.message == "history"
    assert result.fetched == 2
    assert result.stored == 2
    assert len(repo.recent_articles(subscription_id="acct")) == 2


async def test_history_fetch_continues_before_oldest_local_article(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "test.db")
    subscription = Subscription(id="acct", title="Account", account_id="acct")
    repo.add_subscription(subscription)
    repo.save_article(
        Article(
            url="https://mp.weixin.qq.com/s/dated-2",
            title="Existing",
            published_at=datetime(2026, 1, 8, tzinfo=timezone.utc),
        ),
        subscription_id="acct",
    )
    poller = RssPoller(
        repository=repo,
        account_provider=DatedHistoryProvider(),
        article_client=FakeArticleClient(),
    )

    result = await poller.fetch_history(
        subscription,
        page_size=2,
        count=2,
        older_than_local=True,
    )
    urls = {article.url for article in repo.recent_articles(subscription_id="acct", limit=10)}

    assert result.fetched == 2
    assert "https://mp.weixin.qq.com/s/dated-3" in urls
    assert "https://mp.weixin.qq.com/s/dated-4" in urls
    assert repo.subscription_oldest_published_at("acct") == datetime(2026, 1, 6, tzinfo=timezone.utc)


async def test_history_fetch_uses_existing_count_when_local_dates_are_missing(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "test.db")
    subscription = Subscription(id="acct", title="Account", account_id="acct")
    repo.add_subscription(subscription)
    for index in range(3):
        repo.save_article(
            Article(url=f"https://mp.weixin.qq.com/s/existing-{index}", title=f"Existing {index}"),
            subscription_id="acct",
        )
    provider = OffsetTrackingHistoryProvider()
    poller = RssPoller(
        repository=repo,
        account_provider=provider,
        article_client=FakeArticleClient(),
    )

    result = await poller.fetch_history(
        subscription,
        page_size=1,
        count=1,
        older_than_local=True,
    )

    assert result.fetched == 1
    assert provider.offsets == [3]


async def test_poller_skips_blacklisted_subscription(tmp_path) -> None:
    from wechat_rss_lite.models import BlacklistEntry

    repo = SQLiteRepository(tmp_path / "test.db")
    subscription = Subscription(id="acct", title="Account", account_id="acct")
    repo.add_subscription(subscription)
    repo.add_blacklist_entry(BlacklistEntry(account_id="acct", reason="captcha"))
    poller = RssPoller(
        repository=repo,
        account_provider=FakeProvider(),
        article_client=FakeArticleClient(),
    )

    result = await poller.poll_subscription(subscription)

    assert result.message == "blacklisted"
    assert result.fetched == 0
    assert repo.recent_articles(subscription_id="acct") == []


async def test_poller_records_verification_and_auto_blacklists(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "test.db")
    subscription = Subscription(id="acct", title="Account", account_id="acct")
    repo.add_subscription(subscription)
    poller = RssPoller(
        repository=repo,
        account_provider=FakeProvider(),
        article_client=VerificationArticleClient(),
        verification_blacklist_threshold=1,
    )

    result = await poller.poll_subscription(subscription)

    assert result.stored == 1
    assert repo.recent_articles(subscription_id="acct")[0].status == "verification_required"
    assert repo.verification_count("acct") == 1
    assert repo.is_blacklisted("acct") is True
    assert repo.list_verification_challenges(status="pending")[0].target == "acct"
