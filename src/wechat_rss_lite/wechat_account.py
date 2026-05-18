from __future__ import annotations

import json
import time

import httpx

from .adapters import AccountProfile, ArticleSummary
from .models import Credential
from .storage import SQLiteRepository


MP_BASE_URL = "https://mp.weixin.qq.com"


class WeChatMpAccountProvider:
    def __init__(self, *, repository: SQLiteRepository, timeout: float = 15.0) -> None:
        self.repository = repository
        self.timeout = timeout

    async def search_accounts(self, query: str, *, limit: int = 10) -> list[AccountProfile]:
        credential = self._credential()
        if not credential:
            return []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{MP_BASE_URL}/cgi-bin/searchbiz",
                params={
                    "action": "search_biz",
                    "token": credential.token,
                    "lang": "zh_CN",
                    "f": "json",
                    "ajax": 1,
                    "random": time.time(),
                    "query": query,
                    "begin": 0,
                    "count": limit,
                },
                headers=_headers(credential),
            )
            response.raise_for_status()
            payload = response.json()
        if payload.get("base_resp", {}).get("ret") != 0:
            return []
        profiles: list[AccountProfile] = []
        for item in payload.get("list", []):
            fakeid = item.get("fakeid", "")
            if not fakeid:
                continue
            profiles.append(
                AccountProfile(
                    id=fakeid,
                    name=item.get("nickname", "") or fakeid,
                    alias=item.get("alias", ""),
                    avatar_url=item.get("round_head_img", ""),
                    description=str(item.get("signature", "") or item.get("service_type", "")),
                )
            )
        return profiles

    async def list_articles(
        self,
        account_id: str,
        *,
        offset: int = 0,
        limit: int = 20,
        keyword: str = "",
    ) -> list[ArticleSummary]:
        credential = self._credential()
        if not credential:
            return []
        params = {
            "sub": "search" if keyword else "list",
            "search_field": "7" if keyword else "null",
            "begin": offset,
            "count": limit,
            "query": keyword,
            "fakeid": account_id,
            "type": "101_1",
            "free_publish_type": 1,
            "sub_action": "list_ex",
            "token": credential.token,
            "lang": "zh_CN",
            "f": "json",
            "ajax": 1,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{MP_BASE_URL}/cgi-bin/appmsgpublish",
                params=params,
                headers=_headers(credential),
            )
            response.raise_for_status()
            payload = response.json()
        if payload.get("base_resp", {}).get("ret") != 0:
            return []
        publish_page = _json_object(payload.get("publish_page", {}))
        summaries: list[ArticleSummary] = []
        for item in publish_page.get("publish_list", []):
            publish_info = _json_object(item.get("publish_info", {}))
            for article in publish_info.get("appmsgex", []):
                url = article.get("link", "")
                if not url:
                    continue
                summaries.append(
                    ArticleSummary(
                        url=url,
                        title=article.get("title", "") or url,
                        account_id=account_id,
                        summary=article.get("digest", ""),
                        published_at=_timestamp(article.get("update_time") or article.get("create_time")),
                    )
                )
        return summaries

    async def account_info(self, account_id: str) -> dict:
        credential = self._credential()
        if not credential:
            return {"id": account_id, "available": False, "error": "not_logged_in"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{MP_BASE_URL}/mp/authorinfo",
                params={
                    "wxtoken": "777",
                    "biz": account_id,
                    "__biz": account_id,
                    "x5": 0,
                    "f": "json",
                },
                headers=_headers(credential),
            )
            response.raise_for_status()
            payload = response.json()
        base_resp = payload.get("base_resp", {})
        if base_resp.get("ret") != 0:
            return {
                "id": account_id,
                "available": False,
                "error": base_resp.get("err_msg", "unknown"),
                "ret": base_resp.get("ret"),
            }
        return {
            "id": account_id,
            "available": True,
            "identity_name": payload.get("identity_name", ""),
            "is_verify": payload.get("is_verify", 0),
            "original_article_count": payload.get("original_article_count", 0),
        }

    def _credential(self) -> Credential | None:
        credential = self.repository.get_credential()
        if not credential or credential.is_expired or not credential.token or not credential.cookie:
            return None
        if credential.extra.get("provider") != "wechat_mp":
            return None
        return credential


def _headers(credential: Credential) -> dict[str, str]:
    return {
        "Cookie": credential.cookie,
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
        ),
        "Referer": f"{MP_BASE_URL}/",
    }


def _json_object(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _timestamp(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed or None
