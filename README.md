# wechat-rss-lite

Lightweight AGPL-3.0-only toolkit for integrating WeChat public article parsing and RSS generation into other Python projects.

The package is designed as **library first, API optional**:

- Parse public WeChat article URLs into structured data.
- Generate RSS 2.0 from normalized article objects.
- Store subscriptions and cached articles in a small SQLite repository.
- Expose an optional FastAPI app for projects that want HTTP endpoints.
- Avoid bundling account-specific crawling logic into the core. Authenticated discovery can be provided through a small adapter interface.
- Provide product scaffolding for QR login providers, credential expiry notifications, account search/list adapters, RSS polling, image proxying, proxy rotation, request limiting, webhooks, and an admin page.
- Run long polling, history imports, subscription imports, and article refreshes as persistent background jobs with queryable progress.

## Install

```bash
pip install -e ".[api,dev]"
```

## Library Usage

```python
import asyncio
from wechat_rss_lite import WeChatArticleClient, render_rss

async def main():
    async with WeChatArticleClient() as client:
        article = await client.fetch_article("https://mp.weixin.qq.com/s/example")
        xml = render_rss(
            title="My Feed",
            link="https://example.com/rss.xml",
            description="Selected WeChat articles",
            articles=[article],
        )
        print(xml)

asyncio.run(main())
```

## Optional API

Copy `.env.example` to `.env` and set `ADMIN_API_TOKEN` before using the admin UI.

```bash
uvicorn wechat_rss_lite.api:create_app --factory --host 127.0.0.1 --port 8080
```

### Security notes

- Bind to `127.0.0.1` unless you intentionally expose the service on your LAN.
- Set `ADMIN_API_TOKEN` in `.env`. Admin APIs accept `Authorization: Bearer <token>` or `?token=` (used by the article reader iframe).
- Optionally set `RSS_READ_TOKEN` to require the same auth on `/feeds/*.rss`. When unset, feeds stay public (convenient for local dev). Subscription export and Admin “复制 RSS” URLs include `?token=` automatically when configured.
- The image proxy (`/image`) stays public so RSS HTML and avatars can load in external readers.
- Bulk article refresh is capped by `REFRESH_BATCH_LIMIT` (default `50`) to avoid hour-long HTTP requests.
- Background jobs are stored in the repository so the admin UI can keep showing progress after a browser refresh.

Endpoints:

- `POST /articles/parse`
- `POST /rss/render`
- `GET /health`
- `POST /login/sessions`
- `GET /accounts/search`
- `GET /accounts/{account_id}/articles`
- `POST /subscriptions`
- `POST /subscriptions/import`
- `POST /subscriptions/{subscription_id}/history?background=true`
- `POST /subscriptions/{subscription_id}/poll?background=true`
- `POST /subscriptions/{subscription_id}/articles/refresh?background=true`
- `POST /articles/refresh?background=true`
- `POST /poll?background=true`
- `GET /jobs`
- `GET /jobs/{job_id}`
- `GET /feeds/{subscription_id}.rss`
- `GET /image?url=...`
- `GET /admin`

History fetching can be called with `older_than_local=true` and a `count` value to continue backward from the oldest locally stored article. Latest polling and article refresh both emit progress updates to the background job record.

## Optional Browser-Compatible TLS Transport

The default client uses `httpx` to keep the package small. If an authorized deployment needs a browser-compatible TLS stack, install the optional transport explicitly:

```bash
pip install "wechat-rss-lite[tls]"
```

```python
from wechat_rss_lite import CurlCffiArticleClient

client = CurlCffiArticleClient(impersonate="chrome")
```

## Design

The core is intentionally small:

- `parser.py` extracts article metadata and content from HTML.
- `client.py` performs bounded HTTP fetches with timeouts and retries.
- `rss.py` renders standards-compliant RSS without a template engine.
- `storage.py` provides a SQLite repository for embedding projects.
- `service.py` composes the pieces for application use.

For authenticated account search, article list pagination, or tenant-specific credentials, implement `AccountProvider` in your host project. This keeps credentials, rate limits, and platform-policy decisions outside the reusable package.

```python
from wechat_rss_lite import AccountProvider, AccountProfile, ArticleSummary

class MyAccountProvider(AccountProvider):
    async def search_accounts(self, query: str, *, limit: int = 10) -> list[AccountProfile]:
        ...

    async def list_articles(
        self,
        account_id: str,
        *,
        offset: int = 0,
        limit: int = 20,
        keyword: str = "",
    ) -> list[ArticleSummary]:
        ...
```

## License

AGPL-3.0-only. See `LICENSE` and `NOTICE`.
