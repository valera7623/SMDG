# app/services/cdn_service.py
"""CDN management: CloudFront invalidation, Cloudflare cache purge."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class CDNService:
    """Операции с edge CDN (инвалидация / сведения о дистрибутиве)."""

    def __init__(self, config: dict) -> None:
        self.provider = (config.get("provider") or "cloudfront").lower()
        self.enabled: bool = bool(config.get("enabled", False))
        self._client: Any = None

        if not self.enabled:
            return
        if self.provider == "cloudfront":
            self._init_cloudfront(config)
        elif self.provider == "cloudflare":
            self._init_cloudflare(config)
        else:
            logger.warning("CDN provider %s: инвалидация не настроена", self.provider)
            self.enabled = False

    def _init_cloudfront(self, config: dict) -> None:
        self.distribution_id: Optional[str] = config.get("distribution_id") or None
        self.domain: Optional[str] = config.get("domain")
        if not self.distribution_id:
            self.enabled = False
            return
        try:
            import boto3
        except ImportError:  # pragma: no cover
            logger.error("boto3 не установлен: pip install boto3")
            self.enabled = False
            return
        self._client = boto3.client("cloudfront")

    def _init_cloudflare(self, config: dict) -> None:
        self.zone_id: Optional[str] = config.get("zone_id")
        self.api_token: str = (config.get("api_token") or "").strip()
        self.domain: Optional[str] = (config.get("domain") or "").rstrip("/")
        if not self.zone_id or not self.api_token:
            self.enabled = False
            return
        self._base = "https://api.cloudflare.com/client/v4"
        self._headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _format_paths(paths: List[str]) -> List[str]:
        out: List[str] = []
        for p in paths:
            s = p if p.startswith("/") else f"/{p}"
            out.append(s)
        return out

    def _sync_invalidate_cloudfront(self, items: List[str]) -> dict:
        assert self._client is not None
        resp = self._client.create_invalidation(
            DistributionId=self.distribution_id,
            InvalidationBatch={
                "Paths": {
                    "Quantity": len(items),
                    "Items": items,
                },
                "CallerReference": f"smdg-invalidation-{datetime.now(timezone.utc).timestamp()}",
            },
        )
        return {
            "status": "success",
            "invalidation_id": resp["Invalidation"]["Id"],
            "paths": items,
        }

    def _sync_invalidate_cloudflare(self, items: List[str]) -> dict:
        base = self.domain or ""
        urls: List[str] = []
        for p in items:
            path = p if p.startswith("/") else f"/{p}"
            if base:
                if base.startswith("http://") or base.startswith("https://"):
                    urls.append(f"{base}{path}")
                else:
                    urls.append(f"https://{base}{path}")
            else:
                urls.append(path)
        r = requests.post(
            f"{self._base}/zones/{self.zone_id}/purge_cache",
            headers=self._headers,
            json={"files": urls},
            timeout=60,
        )
        if r.status_code == 200:
            return {"status": "success", "paths": urls}
        return {"status": "error", "message": r.text}

    def _sync_get_cloudfront_stats(self) -> dict:
        assert self._client is not None
        resp = self._client.get_distribution(Id=self.distribution_id)
        dist = resp["Distribution"]
        return {
            "status": "success",
            "domain": self.domain,
            "distribution_id": self.distribution_id,
            "status": dist.get("Status"),
            "enabled": dist.get("DistributionConfig", {}).get("Enabled"),
        }

    def _sync_get_cloudflare_stats(self) -> dict:
        r = requests.get(
            f"{self._base}/zones/{self.zone_id}",
            headers=self._headers,
            timeout=30,
        )
        if r.status_code == 200:
            data = r.json().get("result", {})
            return {
                "status": "success",
                "domain": self.domain or data.get("name"),
            }
        return {"status": "error", "message": r.text}

    async def invalidate_files(self, paths: List[str]) -> Dict[str, Any]:
        if not self.enabled:
            return {"status": "disabled", "paths": paths}
        items = self._format_paths(paths)
        try:
            if self.provider == "cloudfront" and self._client is not None:
                return await asyncio.to_thread(self._sync_invalidate_cloudfront, items)
            if self.provider == "cloudflare":
                return await asyncio.to_thread(self._sync_invalidate_cloudflare, items)
        except Exception as e:  # noqa: BLE001
            logger.exception("CDN invalidation failed: %s", e)
            return {"status": "error", "message": str(e)}
        return {"status": "error", "message": "Unknown provider or client"}

    async def get_cache_stats(self) -> dict:
        if not self.enabled:
            return {"status": "disabled"}
        try:
            if self.provider == "cloudfront" and self._client is not None:
                return await asyncio.to_thread(self._sync_get_cloudfront_stats)
            if self.provider == "cloudflare":
                return await asyncio.to_thread(self._sync_get_cloudflare_stats)
        except Exception as e:  # noqa: BLE001
            return {"status": "error", "message": str(e)}
        return {"status": "error", "message": "Unknown provider"}


cdn_service: Optional[CDNService] = None


def init_cdn_service(config: dict) -> Optional[CDNService]:
    global cdn_service
    cdn_service = CDNService(config)
    if not cdn_service.enabled:
        return None
    return cdn_service
