from __future__ import annotations

from datetime import datetime, timezone

from .adapters import AccountProvider, EmptyAccountProvider
from .client import WeChatArticleClient
from .models import NotificationEvent, PollResult, Subscription, VerificationChallenge
from .storage import SQLiteRepository
from .webhook import WebhookNotifier


class RssPoller:
    def __init__(
        self,
        *,
        repository: SQLiteRepository,
        account_provider: AccountProvider | None = None,
        article_client: WeChatArticleClient | None = None,
        notifier: WebhookNotifier | None = None,
        verification_blacklist_threshold: int = 3,
    ) -> None:
        self.repository = repository
        self.account_provider = account_provider or EmptyAccountProvider()
        self.article_client = article_client or WeChatArticleClient()
        self.notifier = notifier or WebhookNotifier()
        self.verification_blacklist_threshold = verification_blacklist_threshold

    async def poll_subscription(self, subscription: Subscription, *, limit: int = 20) -> PollResult:
        started = datetime.now(timezone.utc)
        account_id = subscription.account_id or subscription.id
        if self.repository.is_blacklisted(account_id):
            return self._record_result(subscription.id, started, message="blacklisted")
        failed = 0
        stored = 0
        summaries = await self.account_provider.list_articles(
            account_id,
            limit=limit,
        )
        for summary in summaries:
            self.repository.mark_article_pending(
                url=summary.url,
                title=summary.title,
                subscription_id=subscription.id,
                summary=summary.summary,
                source="poll",
                published_at=_summary_time(summary.published_at),
            )
            try:
                article = await self.article_client.fetch_article(summary.url)
                self.repository.save_article(article, subscription_id=subscription.id, source="poll")
                if article.status == "verification_required":
                    await self._handle_verification(subscription, summary.url, article.unavailable_reason or article.text)
                stored += 1
            except Exception as exc:
                self.repository.mark_article_failed(url=summary.url, error=str(exc))
                failed += 1
        result = PollResult(
            subscription_id=subscription.id,
            fetched=len(summaries),
            stored=stored,
            failed=failed,
            message="ok" if failed == 0 else f"{failed} article(s) failed",
            started_at=started,
            finished_at=datetime.now(timezone.utc),
        )
        self.repository.record_poll_result(result)
        if failed:
            await self.notifier.send(
                NotificationEvent(
                    kind="poll.partial_failure",
                    message=result.message,
                    target=subscription.id,
                )
            )
        return result

    async def fetch_history(
        self,
        subscription: Subscription,
        *,
        pages: int = 5,
        page_size: int = 20,
        keyword: str = "",
    ) -> PollResult:
        started = datetime.now(timezone.utc)
        account_id = subscription.account_id or subscription.id
        if self.repository.is_blacklisted(account_id):
            return self._record_result(subscription.id, started, message="blacklisted")

        failed = 0
        stored = 0
        fetched = 0
        for page in range(pages):
            summaries = await self.account_provider.list_articles(
                account_id,
                offset=page * page_size,
                limit=page_size,
                keyword=keyword,
            )
            if not summaries:
                break
            fetched += len(summaries)
            for summary in summaries:
                self.repository.mark_article_pending(
                    url=summary.url,
                    title=summary.title,
                    subscription_id=subscription.id,
                    summary=summary.summary,
                    source="history",
                    published_at=_summary_time(summary.published_at),
                )
                try:
                    article = await self.article_client.fetch_article(summary.url)
                    self.repository.save_article(article, subscription_id=subscription.id, source="history")
                    if article.status == "verification_required":
                        await self._handle_verification(subscription, summary.url, article.unavailable_reason or article.text)
                    stored += 1
                except Exception as exc:
                    self.repository.mark_article_failed(url=summary.url, error=str(exc))
                    failed += 1

        result = self._record_result(
            subscription.id,
            started,
            fetched=fetched,
            stored=stored,
            failed=failed,
            message="history" if failed == 0 else f"history: {failed} article(s) failed",
        )
        if failed:
            await self.notifier.send(
                NotificationEvent(
                    kind="history.partial_failure",
                    message=result.message,
                    target=subscription.id,
                )
            )
        return result

    async def poll_all(self, *, limit_per_subscription: int = 20) -> list[PollResult]:
        results: list[PollResult] = []
        for subscription in self.repository.list_subscriptions():
            if subscription.enabled:
                results.append(
                    await self.poll_subscription(subscription, limit=limit_per_subscription)
                )
        return results

    def _record_result(
        self,
        subscription_id: str,
        started_at: datetime,
        *,
        fetched: int = 0,
        stored: int = 0,
        failed: int = 0,
        message: str,
    ) -> PollResult:
        result = PollResult(
            subscription_id=subscription_id,
            fetched=fetched,
            stored=stored,
            failed=failed,
            message=message,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        )
        self.repository.record_poll_result(result)
        return result

    async def _handle_verification(self, subscription: Subscription, article_url: str, message: str) -> None:
        account_id = subscription.account_id or subscription.id
        count = self.repository.increment_verification_count(
            account_id,
            reason=message or "verification_required",
            threshold=self.verification_blacklist_threshold,
        )
        self.repository.add_verification_challenge(
            VerificationChallenge(
                id=f"{account_id}:{count}",
                kind="wechat_article",
                target=account_id,
                verify_url=article_url,
                message=f"{message or '需要验证'}；累计 {count} 次。",
            )
        )
        await self.notifier.send(
            NotificationEvent(
                kind="verification.required",
                message=f"{subscription.title} 触发验证，累计 {count} 次。",
                target=account_id,
            )
        )


def _summary_time(value: int | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc)
