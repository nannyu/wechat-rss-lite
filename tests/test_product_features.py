from __future__ import annotations

from datetime import datetime, timedelta, timezone

from wechat_rss_lite.adapters import AccountProfile, ArticleSummary
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

    assert parse_article_html(audio, "https://mp.weixin.qq.com/s/a").content_type == "audio_share"
    image_article = parse_article_html(image_only, "https://mp.weixin.qq.com/s/b")
    assert image_article.content_type == "image_only"
    assert image_article.text == "[纯图片文章，共 1 张图片]"
    gone = parse_article_html(unavailable, "https://mp.weixin.qq.com/s/c")
    assert gone.content_type == "unavailable"
    assert gone.unavailable_reason == "该内容已被发布者删除"


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

