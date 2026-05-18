from __future__ import annotations

from wechat_rss_lite.models import Article, Subscription
from wechat_rss_lite.storage import SQLiteRepository


def test_article_refresh_targets_respects_limit(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "test.db")
    repo.add_subscription(Subscription(id="acct", title="Acct"))
    for index in range(5):
        repo.save_article(
            Article(url=f"https://mp.weixin.qq.com/s/{index}", title=f"A{index}"),
            subscription_id="acct",
        )
    targets = repo.article_refresh_targets(subscription_id="acct", status="fetched", limit=2)
    assert len(targets) == 2
