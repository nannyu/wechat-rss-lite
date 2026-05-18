from wechat_rss_lite.models import Article, Subscription
from wechat_rss_lite.storage import SQLiteRepository


def test_sqlite_repository_round_trip(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "test.db")
    repo.add_subscription(Subscription(id="account-1", title="Account"))
    repo.save_article(
        Article(url="https://mp.weixin.qq.com/s/a", title="A", text="Body"),
        subscription_id="account-1",
    )

    assert repo.list_subscriptions()[0].title == "Account"
    assert repo.recent_articles(subscription_id="account-1")[0].title == "A"

