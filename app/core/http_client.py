"""HTTP client with centralized timeout settings."""
from __future__ import annotations

import httpx

from app.core.config import settings


class TimeoutHTTPClient:
    """Shared async HTTP client configured with SMDG timeouts."""

    def __init__(self) -> None:
        self.timeout = httpx.Timeout(
            timeout=float(settings.HTTP_REQUEST_TIMEOUT_SECONDS),
            connect=float(settings.HTTP_CONNECT_TIMEOUT_SECONDS),
            read=float(settings.HTTP_READ_TIMEOUT_SECONDS),
            write=float(settings.HTTP_READ_TIMEOUT_SECONDS),
        )
        self.client = httpx.AsyncClient(timeout=self.timeout)

    async def get(self, url: str, **kwargs):
        return await self.client.get(url, **kwargs)

    async def post(self, url: str, **kwargs):
        return await self.client.post(url, **kwargs)

    async def put(self, url: str, **kwargs):
        return await self.client.put(url, **kwargs)

    async def close(self) -> None:
        await self.client.aclose()


http_client = TimeoutHTTPClient()

