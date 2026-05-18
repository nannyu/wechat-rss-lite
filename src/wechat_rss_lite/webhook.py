from __future__ import annotations

from dataclasses import asdict

import httpx

from .models import NotificationEvent


class WebhookNotifier:
    def __init__(self, url: str = "", *, timeout: float = 5.0) -> None:
        self.url = url
        self.timeout = timeout

    async def send(self, event: NotificationEvent) -> bool:
        if not self.url:
            return False
        payload = {
            **asdict(event),
            "created_at": event.created_at.isoformat(),
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(self.url, json=payload)
            response.raise_for_status()
        return True

