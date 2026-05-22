from __future__ import annotations

import sqlite3
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .models import Article, BlacklistEntry, Category, Credential, PollResult, Subscription, VerificationChallenge


def create_repository(settings: Any) -> "SQLiteRepository":
    database_url = getattr(settings, "database_url", "")
    if database_url:
        return PostgresRepository(database_url, schema=getattr(settings, "database_schema", "wechat_rss_lite"))
    return SQLiteRepository(getattr(settings, "db_path", "wechat-rss-lite.db"))


class SQLiteRepository:
    def __init__(self, path: str | Path = "wechat-rss-lite.db") -> None:
        self.path = Path(path)
        self._init()

    def add_subscription(self, subscription: Subscription) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert into subscriptions (
                    id, title, account_id, source_url, avatar_url, description,
                    category_id, enabled, created_at, updated_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(id) do update set
                    title = excluded.title,
                    account_id = excluded.account_id,
                    source_url = excluded.source_url,
                    avatar_url = coalesce(nullif(excluded.avatar_url, ''), avatar_url),
                    description = coalesce(nullif(excluded.description, ''), description),
                    category_id = excluded.category_id,
                    enabled = excluded.enabled,
                    updated_at = excluded.updated_at
                """,
                (
                    subscription.id,
                    subscription.title,
                    subscription.account_id or subscription.id,
                    subscription.source_url,
                    subscription.avatar_url,
                    subscription.description,
                    subscription.category_id,
                    1 if subscription.enabled else 0,
                    _dt(subscription.created_at),
                    _dt(datetime.now(timezone.utc)),
                ),
            )

    def list_subscriptions(self) -> list[Subscription]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select id, title, account_id, source_url, avatar_url, description, category_id,
                       enabled, created_at, updated_at
                from subscriptions
                order by title
                """
            ).fetchall()
        return [
            Subscription(
                id=row["id"],
                title=row["title"],
                account_id=row["account_id"] if "account_id" in row.keys() else row["id"],
                source_url=row["source_url"],
                avatar_url=row["avatar_url"] if "avatar_url" in row.keys() else "",
                description=row["description"] if "description" in row.keys() else "",
                category_id=row["category_id"] if "category_id" in row.keys() else None,
                enabled=bool(row["enabled"]) if "enabled" in row.keys() else True,
                created_at=_parse_dt(row["created_at"]),
                updated_at=_parse_dt(row["updated_at"]),
            )
            for row in rows
        ]

    def delete_subscription(self, subscription_id: str) -> None:
        with self._connect() as conn:
            conn.execute("delete from subscriptions where id = ?", (subscription_id,))

    def set_subscription_enabled(self, subscription_id: str, enabled: bool) -> Subscription | None:
        with self._connect() as conn:
            conn.execute(
                "update subscriptions set enabled = ?, updated_at = ? where id = ?",
                (1 if enabled else 0, _dt(datetime.now(timezone.utc)), subscription_id),
            )
        return next((item for item in self.list_subscriptions() if item.id == subscription_id), None)

    def set_subscription_category(self, subscription_id: str, category_id: int | None) -> Subscription | None:
        with self._connect() as conn:
            conn.execute(
                "update subscriptions set category_id = ?, updated_at = ? where id = ?",
                (category_id, _dt(datetime.now(timezone.utc)), subscription_id),
            )
        return next((item for item in self.list_subscriptions() if item.id == subscription_id), None)

    def subscription_article_stats(self) -> dict[str, dict[str, int]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select subscription_id,
                       count(*) as article_total,
                       sum(case when status = 'fetched' then 1 else 0 end) as article_fetched,
                       sum(case when status = 'pending' then 1 else 0 end) as article_pending,
                       sum(case when status = 'failed' then 1 else 0 end) as article_failed
                from articles
                where subscription_id is not null and subscription_id != ''
                group by subscription_id
                """
            ).fetchall()
        stats: dict[str, dict[str, int]] = {}
        for row in rows:
            subscription_id = row["subscription_id"]
            pending = int(row["article_pending"] or 0)
            failed = int(row["article_failed"] or 0)
            stats[subscription_id] = {
                "article_total": int(row["article_total"] or 0),
                "article_fetched": int(row["article_fetched"] or 0),
                "article_pending": pending,
                "article_failed": failed,
                "article_remaining": pending + failed,
            }
        return stats

    def save_article(self, article: Article, subscription_id: str | None = None, *, source: str | None = None) -> None:
        article_source = source or article.source or "poll"
        with self._connect() as conn:
            conn.execute(
                """
                insert into articles (
                    url, subscription_id, title, author, account_name, summary,
                    content_html, text, content_type, unavailable_reason, status, source, published_at, fetched_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(url) do update set
                    subscription_id = excluded.subscription_id,
                    title = excluded.title,
                    author = excluded.author,
                    account_name = excluded.account_name,
                    summary = excluded.summary,
                    content_html = excluded.content_html,
                    text = excluded.text,
                    content_type = excluded.content_type,
                    unavailable_reason = excluded.unavailable_reason,
                    status = excluded.status,
                    source = excluded.source,
                    published_at = excluded.published_at,
                    fetched_at = excluded.fetched_at
                """,
                (
                    article.url,
                    subscription_id,
                    article.title,
                    article.author,
                    article.account_name,
                    article.summary,
                    article.content_html,
                    article.text,
                    article.content_type,
                    article.unavailable_reason,
                    article.status,
                    article_source,
                    _dt(article.published_at) if article.published_at else None,
                    _dt(datetime.now(timezone.utc)),
                ),
            )

    def mark_article_pending(
        self,
        *,
        url: str,
        title: str,
        subscription_id: str,
        summary: str = "",
        source: str = "poll",
        published_at: datetime | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert into articles (
                    url, subscription_id, title, summary, content_type, status, source, published_at, fetched_at
                )
                values (?, ?, ?, ?, 'pending', 'pending', ?, ?, ?)
                on conflict(url) do update set
                    subscription_id = excluded.subscription_id,
                    title = coalesce(nullif(excluded.title, ''), title),
                    summary = coalesce(nullif(excluded.summary, ''), summary),
                    status = case
                        when articles.status in ('fetched', 'permanent_fail') then articles.status
                        else 'pending'
                    end,
                    source = excluded.source,
                    published_at = coalesce(excluded.published_at, articles.published_at),
                    fetched_at = excluded.fetched_at
                """,
                (
                    url,
                    subscription_id,
                    title,
                    summary,
                    source,
                    _dt(published_at) if published_at else None,
                    _dt(datetime.now(timezone.utc)),
                ),
            )

    def mark_article_failed(self, *, url: str, error: str = "", status: str = "failed") -> None:
        with self._connect() as conn:
            conn.execute(
                """
                update articles
                set status = ?, unavailable_reason = ?, fetched_at = ?
                where url = ?
                """,
                (status, error[:500], _dt(datetime.now(timezone.utc)), url),
            )

    def recent_articles(
        self,
        subscription_id: str | None = None,
        limit: int = 20,
        *,
        source: str | None = None,
        category_id: int | None = None,
        status: str | None = None,
    ) -> list[Article]:
        conditions: list[str] = []
        params_list: list[object] = []
        if subscription_id:
            conditions.append("a.subscription_id = ?")
            params_list.append(subscription_id)
        if source:
            conditions.append("a.source = ?")
            params_list.append(source)
        if status:
            conditions.append("a.status = ?")
            params_list.append(status)
        join = ""
        if category_id is not None:
            join = "join subscriptions s on s.id = a.subscription_id"
            conditions.append("s.category_id = ?")
            params_list.append(category_id)
        where = f"where {' and '.join(conditions)}" if conditions else ""
        params_list.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                select a.url, a.title, a.author, a.account_name, a.summary, a.content_html, a.text,
                       a.content_type, a.unavailable_reason, a.status, a.source, a.published_at
                from articles a
                {join}
                {where}
                order by coalesce(a.published_at, a.fetched_at) desc
                limit ?
                """,
                tuple(params_list),
            ).fetchall()
        return [
            Article(
                url=row["url"],
                title=row["title"],
                author=row["author"] or "",
                account_name=row["account_name"] or "",
                summary=row["summary"] or "",
                content_html=row["content_html"] or "",
                text=row["text"] or "",
                content_type=row["content_type"] or "rich_text",
                unavailable_reason=row["unavailable_reason"] or "",
                status=row["status"] if "status" in row.keys() else _status_from_content_type(row["content_type"] or "rich_text"),
                source=row["source"] if "source" in row.keys() else "poll",
                published_at=_parse_dt(row["published_at"]) if row["published_at"] else None,
            )
            for row in rows
        ]

    def get_article(self, url: str) -> Article | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                select url, title, author, account_name, summary, content_html, text,
                       content_type, unavailable_reason, status, source, published_at
                from articles
                where url = ?
                """,
                (url,),
            ).fetchone()
        if not row:
            return None
        return Article(
            url=row["url"],
            title=row["title"],
            author=row["author"] or "",
            account_name=row["account_name"] or "",
            summary=row["summary"] or "",
            content_html=row["content_html"] or "",
            text=row["text"] or "",
            content_type=row["content_type"] or "rich_text",
            unavailable_reason=row["unavailable_reason"] or "",
            status=row["status"] if "status" in row.keys() else _status_from_content_type(row["content_type"] or "rich_text"),
            source=row["source"] if "source" in row.keys() else "poll",
            published_at=_parse_dt(row["published_at"]) if row["published_at"] else None,
        )

    def article_refresh_targets(
        self,
        *,
        url: str | None = None,
        subscription_id: str | None = None,
        status: str | None = "fetched",
        limit: int | None = 50,
    ) -> list[dict[str, str]]:
        conditions: list[str] = []
        params: list[object] = []
        if url:
            conditions.append("url = ?")
            params.append(url)
        if subscription_id:
            conditions.append("subscription_id = ?")
            params.append(subscription_id)
        if status:
            conditions.append("status = ?")
            params.append(status)
        where = f"where {' and '.join(conditions)}" if conditions else ""
        limit_clause = ""
        if limit is not None and limit > 0:
            limit_clause = "limit ?"
            params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                select url, subscription_id, source
                from articles
                {where}
                order by coalesce(published_at, fetched_at) desc
                {limit_clause}
                """,
                tuple(params),
            ).fetchall()
        return [
            {
                "url": row["url"],
                "subscription_id": row["subscription_id"] or "",
                "source": row["source"] or "poll",
            }
            for row in rows
        ]

    def increment_verification_count(
        self,
        account_id: str,
        *,
        reason: str = "verification_required",
        threshold: int = 3,
    ) -> int:
        now = datetime.now(timezone.utc)
        with self._connect() as conn:
            conn.execute(
                """
                insert into verification_counts (account_id, count, last_reason, updated_at)
                values (?, 1, ?, ?)
                on conflict(account_id) do update set
                    count = count + 1,
                    last_reason = excluded.last_reason,
                    updated_at = excluded.updated_at
                """,
                (account_id, reason, _dt(now)),
            )
            row = conn.execute(
                "select count from verification_counts where account_id = ?",
                (account_id,),
            ).fetchone()
            count = int(row["count"] or 0)
            if threshold > 0 and count >= threshold:
                conn.execute(
                    """
                    insert into blacklist (account_id, reason, created_at)
                    values (?, ?, ?)
                    on conflict(account_id) do update set reason = excluded.reason
                    """,
                    (account_id, f"自动加入黑名单：连续触发验证 {count} 次", _dt(now)),
                )
        return count

    def verification_count(self, account_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "select count from verification_counts where account_id = ?",
                (account_id,),
            ).fetchone()
        return int(row["count"] or 0) if row else 0

    def create_category(self, category: Category) -> Category:
        with self._connect() as conn:
            if category.sort_order:
                sort_order = category.sort_order
            else:
                row = conn.execute("select coalesce(max(sort_order), 0) as max_order from categories").fetchone()
                sort_order = int(row["max_order"] or 0) + 1
            cursor = conn.execute(
                """
                insert into categories (name, description, color, sort_order, created_at)
                values (?, ?, ?, ?, ?)
                """,
                (
                    category.name,
                    category.description,
                    category.color,
                    sort_order,
                    _dt(category.created_at),
                ),
            )
            category_id = int(cursor.lastrowid)
        return Category(
            id=category_id,
            name=category.name,
            description=category.description,
            color=category.color,
            sort_order=sort_order,
            created_at=category.created_at,
        )

    def list_categories(self) -> list[Category]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select id, name, description, color, sort_order, created_at
                from categories
                order by sort_order, name
                """
            ).fetchall()
        return [
            Category(
                id=row["id"],
                name=row["name"],
                description=row["description"] or "",
                color=row["color"] or "blue",
                sort_order=row["sort_order"] or 0,
                created_at=_parse_dt(row["created_at"]),
            )
            for row in rows
        ]

    def update_category(self, category_id: int, *, name: str | None = None, description: str | None = None, color: str | None = None) -> Category | None:
        current = next((item for item in self.list_categories() if item.id == category_id), None)
        if not current:
            return None
        with self._connect() as conn:
            conn.execute(
                """
                update categories
                set name = ?, description = ?, color = ?
                where id = ?
                """,
                (
                    name if name is not None else current.name,
                    description if description is not None else current.description,
                    color if color is not None else current.color,
                    category_id,
                ),
            )
        return next((item for item in self.list_categories() if item.id == category_id), None)

    def delete_category(self, category_id: int) -> None:
        with self._connect() as conn:
            conn.execute("update subscriptions set category_id = null where category_id = ?", (category_id,))
            conn.execute("delete from categories where id = ?", (category_id,))

    def save_credential(self, credential: Credential) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert into credentials (id, account_name, token, cookie, extra, created_at, expires_at)
                values (?, ?, ?, ?, ?, ?, ?)
                on conflict(id) do update set
                    account_name = excluded.account_name,
                    token = excluded.token,
                    cookie = excluded.cookie,
                    extra = excluded.extra,
                    expires_at = excluded.expires_at
                """,
                (
                    credential.id,
                    credential.account_name,
                    credential.token,
                    credential.cookie,
                    json.dumps(credential.extra, ensure_ascii=False),
                    _dt(credential.created_at),
                    _dt(credential.expires_at) if credential.expires_at else None,
                ),
            )

    def get_credential(self, credential_id: str = "default") -> Credential | None:
        with self._connect() as conn:
            row = conn.execute(
                "select id, account_name, token, cookie, extra, created_at, expires_at from credentials where id = ?",
                (credential_id,),
            ).fetchone()
        if not row:
            return None
        return Credential(
            id=row["id"],
            account_name=row["account_name"] or "",
            token=row["token"] or "",
            cookie=row["cookie"] or "",
            extra=json.loads(row["extra"] or "{}"),
            created_at=_parse_dt(row["created_at"]),
            expires_at=_parse_dt(row["expires_at"]) if row["expires_at"] else None,
        )

    def delete_credential(self, credential_id: str = "default") -> None:
        with self._connect() as conn:
            conn.execute("delete from credentials where id = ?", (credential_id,))

    def record_poll_result(self, result: PollResult) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert into poll_runs (
                    subscription_id, fetched, stored, failed, message, started_at, finished_at
                )
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.subscription_id,
                    result.fetched,
                    result.stored,
                    result.failed,
                    result.message,
                    _dt(result.started_at),
                    _dt(result.finished_at),
                ),
            )

    def latest_poll_results(self, limit: int = 20) -> list[PollResult]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select subscription_id, fetched, stored, failed, message, started_at, finished_at
                from poll_runs
                order by finished_at desc
                limit ?
                """,
                (limit,),
            ).fetchall()
        return [
            PollResult(
                subscription_id=row["subscription_id"],
                fetched=row["fetched"],
                stored=row["stored"],
                failed=row["failed"],
                message=row["message"] or "",
                started_at=_parse_dt(row["started_at"]),
                finished_at=_parse_dt(row["finished_at"]),
            )
            for row in rows
        ]

    def add_verification_challenge(self, challenge: VerificationChallenge) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert into verification_challenges (
                    id, kind, target, verify_url, status, message, created_at, resolved_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(id) do update set
                    kind = excluded.kind,
                    target = excluded.target,
                    verify_url = excluded.verify_url,
                    status = excluded.status,
                    message = excluded.message,
                    resolved_at = excluded.resolved_at
                """,
                (
                    challenge.id,
                    challenge.kind,
                    challenge.target,
                    challenge.verify_url,
                    challenge.status,
                    challenge.message,
                    _dt(challenge.created_at),
                    _dt(challenge.resolved_at) if challenge.resolved_at else None,
                ),
            )

    def list_verification_challenges(self, *, status: str | None = None, limit: int = 50) -> list[VerificationChallenge]:
        where = ""
        params: tuple[object, ...]
        if status:
            where = "where status = ?"
            params = (status, limit)
        else:
            params = (limit,)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                select id, kind, target, verify_url, status, message, created_at, resolved_at
                from verification_challenges
                {where}
                order by created_at desc
                limit ?
                """,
                params,
            ).fetchall()
        return [
            VerificationChallenge(
                id=row["id"],
                kind=row["kind"],
                target=row["target"] or "",
                verify_url=row["verify_url"] or "",
                status=row["status"],
                message=row["message"] or "",
                created_at=_parse_dt(row["created_at"]),
                resolved_at=_parse_dt(row["resolved_at"]) if row["resolved_at"] else None,
            )
            for row in rows
        ]

    def resolve_verification_challenge(self, challenge_id: str) -> VerificationChallenge | None:
        resolved_at = datetime.now(timezone.utc)
        with self._connect() as conn:
            conn.execute(
                """
                update verification_challenges
                set status = 'resolved', resolved_at = ?
                where id = ?
                """,
                (_dt(resolved_at), challenge_id),
            )
        matches = [item for item in self.list_verification_challenges(limit=100) if item.id == challenge_id]
        return matches[0] if matches else None

    def add_blacklist_entry(self, entry: BlacklistEntry) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert into blacklist (account_id, reason, created_at)
                values (?, ?, ?)
                on conflict(account_id) do update set
                    reason = excluded.reason
                """,
                (entry.account_id, entry.reason, _dt(entry.created_at)),
            )

    def remove_blacklist_entry(self, account_id: str) -> None:
        with self._connect() as conn:
            conn.execute("delete from blacklist where account_id = ?", (account_id,))

    def list_blacklist(self) -> list[BlacklistEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                "select account_id, reason, created_at from blacklist order by created_at desc"
            ).fetchall()
        return [
            BlacklistEntry(
                account_id=row["account_id"],
                reason=row["reason"] or "",
                created_at=_parse_dt(row["created_at"]),
            )
            for row in rows
        ]

    def is_blacklisted(self, account_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "select 1 from blacklist where account_id = ?",
                (account_id,),
            ).fetchone()
        return row is not None

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                create table if not exists subscriptions (
                    id text primary key,
                    title text not null,
                    account_id text not null default '',
                    source_url text not null default '',
                    avatar_url text not null default '',
                    description text not null default '',
                    category_id integer,
                    enabled integer not null default 1,
                    created_at text not null,
                    updated_at text not null
                );

                create table if not exists categories (
                    id integer primary key autoincrement,
                    name text not null unique,
                    description text not null default '',
                    color text not null default 'blue',
                    sort_order integer not null default 0,
                    created_at text not null
                );

                create table if not exists articles (
                    url text primary key,
                    subscription_id text,
                    title text not null,
                    author text,
                    account_name text,
                    summary text,
                    content_html text,
                    text text,
                    content_type text not null default 'rich_text',
                    unavailable_reason text not null default '',
                    status text not null default 'fetched',
                    source text not null default 'poll',
                    published_at text,
                    fetched_at text not null
                );

                create table if not exists credentials (
                    id text primary key,
                    account_name text,
                    token text,
                    cookie text,
                    extra text not null default '{}',
                    created_at text not null,
                    expires_at text
                );

                create table if not exists poll_runs (
                    id integer primary key autoincrement,
                    subscription_id text not null,
                    fetched integer not null,
                    stored integer not null,
                    failed integer not null,
                    message text,
                    started_at text not null,
                    finished_at text not null
                );

                create table if not exists verification_challenges (
                    id text primary key,
                    kind text not null,
                    target text not null default '',
                    verify_url text not null default '',
                    status text not null default 'pending',
                    message text not null default '',
                    created_at text not null,
                    resolved_at text
                );

                create table if not exists blacklist (
                    account_id text primary key,
                    reason text not null default '',
                    created_at text not null
                );

                create table if not exists verification_counts (
                    account_id text primary key,
                    count integer not null default 0,
                    last_reason text not null default '',
                    updated_at text not null
                );

                create index if not exists idx_articles_subscription
                    on articles(subscription_id, published_at desc);
                """
            )
            _ensure_column(conn, "subscriptions", "account_id", "text not null default ''")
            _ensure_column(conn, "subscriptions", "avatar_url", "text not null default ''")
            _ensure_column(conn, "subscriptions", "description", "text not null default ''")
            _ensure_column(conn, "subscriptions", "category_id", "integer")
            _ensure_column(conn, "subscriptions", "enabled", "integer not null default 1")
            _ensure_column(conn, "articles", "content_type", "text not null default 'rich_text'")
            _ensure_column(conn, "articles", "unavailable_reason", "text not null default ''")
            _ensure_column(conn, "articles", "status", "text not null default 'fetched'")
            _ensure_column(conn, "articles", "source", "text not null default 'poll'")


class PostgresRepository(SQLiteRepository):
    def __init__(self, database_url: str, *, schema: str = "wechat_rss_lite") -> None:
        self.database_url = database_url
        self.schema = _safe_identifier(schema)
        self._init()

    @contextmanager
    def _connect(self) -> Iterator["_PostgresConnection"]:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("Install psycopg to use Postgres storage") from exc

        conn = psycopg.connect(self.database_url, row_factory=dict_row, autocommit=False)
        wrapper = _PostgresConnection(conn, self.schema)
        try:
            conn.execute(f'create schema if not exists "{self.schema}"')
            wrapper.execute(f'set local search_path to "{self.schema}"')
            yield wrapper
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def create_category(self, category: Category) -> Category:
        with self._connect() as conn:
            if category.sort_order:
                sort_order = category.sort_order
            else:
                row = conn.execute("select coalesce(max(sort_order), 0) as max_order from categories").fetchone()
                sort_order = int(row["max_order"] or 0)
                sort_order += 1
            row = conn.execute(
                """
                insert into categories (name, description, color, sort_order, created_at)
                values (?, ?, ?, ?, ?)
                returning id
                """,
                (
                    category.name,
                    category.description,
                    category.color,
                    sort_order,
                    _dt(category.created_at),
                ),
            ).fetchone()
            category_id = int(row["id"])
        return Category(
            id=category_id,
            name=category.name,
            description=category.description,
            color=category.color,
            sort_order=sort_order,
            created_at=category.created_at,
        )

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                create table if not exists subscriptions (
                    id text primary key,
                    title text not null,
                    account_id text not null default '',
                    source_url text not null default '',
                    avatar_url text not null default '',
                    description text not null default '',
                    category_id bigint,
                    enabled integer not null default 1,
                    created_at text not null,
                    updated_at text not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists categories (
                    id bigint generated by default as identity primary key,
                    name text not null unique,
                    description text not null default '',
                    color text not null default 'blue',
                    sort_order integer not null default 0,
                    created_at text not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists articles (
                    url text primary key,
                    subscription_id text,
                    title text not null,
                    author text,
                    account_name text,
                    summary text,
                    content_html text,
                    text text,
                    content_type text not null default 'rich_text',
                    unavailable_reason text not null default '',
                    status text not null default 'fetched',
                    source text not null default 'poll',
                    published_at text,
                    fetched_at text not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists credentials (
                    id text primary key,
                    account_name text,
                    token text,
                    cookie text,
                    extra text not null default '{}',
                    created_at text not null,
                    expires_at text
                )
                """
            )
            conn.execute(
                """
                create table if not exists poll_runs (
                    id bigint generated by default as identity primary key,
                    subscription_id text not null,
                    fetched integer not null,
                    stored integer not null,
                    failed integer not null,
                    message text,
                    started_at text not null,
                    finished_at text not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists verification_challenges (
                    id text primary key,
                    kind text not null,
                    target text not null default '',
                    verify_url text not null default '',
                    status text not null default 'pending',
                    message text not null default '',
                    created_at text not null,
                    resolved_at text
                )
                """
            )
            conn.execute(
                """
                create table if not exists blacklist (
                    account_id text primary key,
                    reason text not null default '',
                    created_at text not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists verification_counts (
                    account_id text primary key,
                    count integer not null default 0,
                    last_reason text not null default '',
                    updated_at text not null
                )
                """
            )
            conn.execute(
                """
                create index if not exists idx_wechat_rss_articles_subscription
                    on articles(subscription_id, published_at desc)
                """
            )


class _PostgresConnection:
    def __init__(self, conn: Any, schema: str) -> None:
        self._conn = conn
        self.schema = schema

    def execute(self, query: str, params: tuple[object, ...] | list[object] = ()) -> Any:
        return self._conn.execute(_pg_query(query), params)

    def executescript(self, _script: str) -> None:
        raise NotImplementedError("PostgresRepository does not use sqlite executescript")


def _pg_query(query: str) -> str:
    return query.replace("?", "%s")


def _safe_identifier(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char == "_" else "_" for char in value.strip())
    if not cleaned:
        return "wechat_rss_lite"
    if cleaned[0].isdigit():
        cleaned = f"_{cleaned}"
    return cleaned


def _dt(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"pragma table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"alter table {table} add column {column} {definition}")


def _status_from_content_type(content_type: str) -> str:
    if content_type == "verification_required":
        return "verification_required"
    if content_type == "unavailable":
        return "permanent_fail"
    if content_type == "pending":
        return "pending"
    return "fetched"
