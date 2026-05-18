from wechat_rss_lite.models import Article, BlacklistEntry, Category, Subscription, VerificationChallenge
from wechat_rss_lite.storage import SQLiteRepository


def test_sqlite_repository_round_trip(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "test.db")
    repo.add_subscription(
        Subscription(
            id="account-1",
            title="Account",
            avatar_url="/image?url=https%3A%2F%2Fexample.com%2Favatar.png",
            description="Profile description",
        )
    )
    repo.save_article(
        Article(url="https://mp.weixin.qq.com/s/a", title="A", text="Body"),
        subscription_id="account-1",
    )
    repo.save_article(
        Article(url="https://mp.weixin.qq.com/s/history", title="History", text="Body", source="history"),
        subscription_id="account-1",
        source="history",
    )

    assert repo.list_subscriptions()[0].title == "Account"
    assert repo.list_subscriptions()[0].account_id == "account-1"
    assert repo.list_subscriptions()[0].avatar_url.startswith("/image?url=")
    assert repo.list_subscriptions()[0].description == "Profile description"
    assert repo.recent_articles(subscription_id="account-1", source="poll")[0].title == "A"
    assert repo.recent_articles(subscription_id="account-1", source="history")[0].title == "History"


def test_categories_and_subscription_assignment(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "test.db")
    category = repo.create_category(Category(name="Tech", description="Technology"))
    repo.add_subscription(Subscription(id="account-1", title="Account", category_id=category.id))
    repo.save_article(Article(url="https://mp.weixin.qq.com/s/a", title="A", text="Body"), subscription_id="account-1")

    assert repo.list_categories()[0].name == "Tech"
    assert repo.list_subscriptions()[0].category_id == category.id
    assert repo.recent_articles(category_id=category.id)[0].title == "A"

    updated = repo.set_subscription_category("account-1", None)
    assert updated is not None
    assert updated.category_id is None


def test_verification_challenge_round_trip(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "test.db")
    repo.add_verification_challenge(
        VerificationChallenge(
            id="verify-1",
            kind="captcha",
            target="account-1",
            verify_url="https://example.com/verify",
            message="需要验证",
        )
    )

    pending = repo.list_verification_challenges(status="pending")
    resolved = repo.resolve_verification_challenge("verify-1")

    assert pending[0].target == "account-1"
    assert resolved is not None
    assert resolved.status == "resolved"


def test_blacklist_round_trip(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "test.db")
    repo.add_blacklist_entry(BlacklistEntry(account_id="account-1", reason="高频触发验证码"))

    assert repo.is_blacklisted("account-1") is True
    assert repo.list_blacklist()[0].reason == "高频触发验证码"

    repo.remove_blacklist_entry("account-1")

    assert repo.is_blacklisted("account-1") is False


def test_article_status_lifecycle_and_verification_counter(tmp_path) -> None:
    repo = SQLiteRepository(tmp_path / "test.db")
    repo.mark_article_pending(
        url="https://mp.weixin.qq.com/s/pending",
        title="Pending",
        subscription_id="account-1",
    )

    pending = repo.recent_articles(subscription_id="account-1")[0]
    assert pending.status == "pending"
    assert pending.content_type == "pending"

    repo.save_article(
        Article(url="https://mp.weixin.qq.com/s/pending", title="Done", text="Body"),
        subscription_id="account-1",
    )

    fetched = repo.recent_articles(subscription_id="account-1")[0]
    assert fetched.status == "fetched"
    assert fetched.title == "Done"

    assert repo.increment_verification_count("account-1", threshold=2) == 1
    assert repo.is_blacklisted("account-1") is False
    assert repo.increment_verification_count("account-1", threshold=2) == 2
    assert repo.is_blacklisted("account-1") is True
