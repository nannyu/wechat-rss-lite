from __future__ import annotations

import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path

from .models import Article, Credential, PollResult, Subscription


class SQLiteRepository:
    def __init__(self, path: str | Path = "wechat-rss-lite.db") -> None:
        self.path = Path(path)
        self._init()

    def add_subscription(self, subscription: Subscription) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert into subscriptions (id, title, account_id, source_url, enabled, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?)
                on conflict(id) do update set
                    title = excluded.title,
                    account_id = excluded.account_id,
                    source_url = excluded.source_url,
                    enabled = excluded.enabled,
                    updated_at = excluded.updated_at
                """,
                (
                    subscription.id,
                    subscription.title,
                    subscription.account_id or subscription.id,
                    subscription.source_url,
                    1 if subscription.enabled else 0,
                    _dt(subscription.created_at),
                    _dt(datetime.now(timezone.utc)),
                ),
            )

    def list_subscriptions(self) -> list[Subscription]:
        with self._connect() as conn:
            rows = conn.execute(
                "select id, title, source_url, created_at, updated_at from subscriptions order by title"
            ).fetchall()
        return [
            Subscription(
                id=row["id"],
                title=row["title"],
                account_id=row["account_id"] if "account_id" in row.keys() else row["id"],
                source_url=row["source_url"],
                enabled=bool(row["enabled"]) if "enabled" in row.keys() else True,
                created_at=_parse_dt(row["created_at"]),
                updated_at=_parse_dt(row["updated_at"]),
            )
            for row in rows
        ]

    def delete_subscription(self, subscription_id: str) -> None:
        with self._connect() as conn:
            conn.execute("delete from subscriptions where id = ?", (subscription_id,))

    def save_article(self, article: Article, subscription_id: str | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert into articles (
                    url, subscription_id, title, author, account_name, summary,
                    content_html, text, content_type, unavailable_reason, published_at, fetched_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    _dt(article.published_at) if article.published_at else None,
                    _dt(datetime.now(timezone.utc)),
                ),
            )

    def recent_articles(self, subscription_id: str | None = None, limit: int = 20) -> list[Article]:
        params: tuple[object, ...]
        where = ""
        if subscription_id:
            where = "where subscription_id = ?"
            params = (subscription_id, limit)
        else:
            params = (limit,)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                select url, title, author, account_name, summary, content_html, text,
                       content_type, unavailable_reason, published_at
                from articles
                {where}
                order by coalesce(published_at, fetched_at) desc
                limit ?
                """,
                params,
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
                published_at=_parse_dt(row["published_at"]) if row["published_at"] else None,
            )
            for row in rows
        ]

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
                    enabled integer not null default 1,
                    created_at text not null,
                    updated_at text not null
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

                create index if not exists idx_articles_subscription
                    on articles(subscription_id, published_at desc);
                """
            )
            _ensure_column(conn, "subscriptions", "account_id", "text not null default ''")
            _ensure_column(conn, "subscriptions", "enabled", "integer not null default 1")
            _ensure_column(conn, "articles", "content_type", "text not null default 'rich_text'")
            _ensure_column(conn, "articles", "unavailable_reason", "text not null default ''")


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
