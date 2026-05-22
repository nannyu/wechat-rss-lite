from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

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

    async def poll_subscription(
        self,
        subscription: Subscription,
        *,
        limit: int = 20,
        progress_callback: Callable[[dict[str, int | str]], None] | None = None,
    ) -> PollResult:
        started = datetime.now(timezone.utc)
        account_id = subscription.account_id or subscription.id
        if self.repository.is_blacklisted(account_id):
            return self._record_result(subscription.id, started, message="blacklisted")
        failed = 0
        stored = 0
        if progress_callback:
            progress_callback(
                {
                    "processed": 0,
                    "total": limit,
                    "succeeded": 0,
                    "failed": 0,
                    "message": "正在查询最新文章",
                }
            )
        summaries = await self.account_provider.list_articles(
            account_id,
            limit=limit,
        )
        total = len(summaries)
        if progress_callback:
            progress_callback(
                {
                    "processed": 0,
                    "total": total,
                    "succeeded": 0,
                    "failed": 0,
                    "message": f"查询到 {total} 篇最新文章",
                }
            )
        for index, summary in enumerate(summaries, start=1):
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
            if progress_callback:
                progress_callback(
                    {
                        "processed": index,
                        "total": total,
                        "succeeded": stored,
                        "failed": failed,
                        "message": f"已处理 {index}/{total} 篇最新文章",
                    }
                )
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
        count: int | None = None,
        older_than_local: bool = False,
        progress_callback: Callable[[dict[str, int | str]], None] | None = None,
    ) -> PollResult:
        started = datetime.now(timezone.utc)
        account_id = subscription.account_id or subscription.id
        if self.repository.is_blacklisted(account_id):
            return self._record_result(subscription.id, started, message="blacklisted")

        failed = 0
        stored = 0
        fetched = 0
        accepted = 0
        target_count = count if count is not None else pages * page_size
        if progress_callback:
            progress_callback(
                {
                    "processed": 0,
                    "total": target_count,
                    "succeeded": 0,
                    "failed": 0,
                    "message": "准备拉取历史文章",
                }
            )
        existing_count = self.repository.subscription_article_count(subscription.id) if older_than_local else 0
        oldest_published_at = (
            self.repository.subscription_oldest_published_at(subscription.id)
            if older_than_local
            else None
        )
        start_page = 0
        skip_in_start_page = 0
        if older_than_local and existing_count:
            start_page = existing_count // page_size
            skip_in_start_page = existing_count % page_size
        max_pages = pages
        if older_than_local and count is not None:
            max_pages = max(pages, (count // page_size) + 2)

        for page in range(start_page, start_page + max_pages):
            summaries = await self.account_provider.list_articles(
                account_id,
                offset=page * page_size,
                limit=page_size,
                keyword=keyword,
            )
            if not summaries:
                break
            for index, summary in enumerate(summaries):
                if page == start_page and index < skip_in_start_page:
                    continue
                if older_than_local and not _is_older_history_summary(
                    summary,
                    oldest_published_at=oldest_published_at,
                    existing_count=existing_count,
                    absolute_index=(page * page_size) + index,
                ):
                    continue
                if accepted >= target_count:
                    break
                fetched += 1
                accepted += 1
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
                if progress_callback:
                    progress_callback(
                        {
                            "processed": accepted,
                            "total": target_count,
                            "succeeded": stored,
                            "failed": failed,
                            "message": f"已处理 {accepted}/{target_count}",
                        }
                    )
            if accepted >= target_count:
                break

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

    async def poll_all(
        self,
        *,
        limit_per_subscription: int = 20,
        progress_callback: Callable[[dict[str, int | str]], None] | None = None,
    ) -> list[PollResult]:
        results: list[PollResult] = []
        subscriptions = [subscription for subscription in self.repository.list_subscriptions() if subscription.enabled]
        total = len(subscriptions)
        if progress_callback:
            progress_callback(
                {
                    "processed": 0,
                    "total": total,
                    "succeeded": 0,
                    "failed": 0,
                    "message": f"准备轮询 {total} 个公众号",
                }
            )
        stored = 0
        failed = 0
        for index, subscription in enumerate(subscriptions, start=1):
            def relay_subscription_progress(progress: dict[str, int | str]) -> None:
                if not progress_callback:
                    return
                progress_callback(
                    {
                        "processed": index - 1,
                        "total": total,
                        "succeeded": stored + int(progress.get("succeeded", 0) or 0),
                        "failed": failed + int(progress.get("failed", 0) or 0),
                        "message": f"{subscription.title}: {progress.get('message', '后台任务运行中')}",
                    }
                )

            try:
                result = await self.poll_subscription(
                    subscription,
                    limit=limit_per_subscription,
                    progress_callback=relay_subscription_progress if progress_callback else None,
                )
                results.append(result)
                stored += result.stored
                failed += result.failed
            except Exception:
                failed += 1
                raise
            finally:
                if progress_callback:
                    progress_callback(
                        {
                            "processed": index,
                            "total": total,
                            "succeeded": stored,
                            "failed": failed,
                            "message": f"已轮询 {index}/{total} 个公众号",
                        }
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


def _is_older_history_summary(
    summary: object,
    *,
    oldest_published_at: datetime | None,
    existing_count: int,
    absolute_index: int,
) -> bool:
    summary_time = _summary_time(getattr(summary, "published_at", None))
    if oldest_published_at and summary_time:
        return summary_time < oldest_published_at
    return absolute_index >= existing_count
