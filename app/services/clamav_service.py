"""ClamAV scanning service with timeout protection."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import clamd

from app.core.config import settings
from app.core.timeout import TimeoutError, run_with_timeout
from app.core.bulkhead import BulkheadRejectedError, BulkheadTimeoutError, get_bulkhead

logger = logging.getLogger(__name__)


async def scan_file(file_path: Path) -> dict[str, Any]:
    """Scan file with ClamAV and return status payload."""

    def _scan_sync() -> dict | None:
        client = clamd.ClamdNetworkSocket(
            host=settings.CLAMAV_HOST,
            port=settings.CLAMAV_PORT,
            timeout=settings.CLAMAV_CONNECTION_TIMEOUT_SECONDS,
        )
        with open(file_path, "rb") as fh:
            return client.instream(fh)

    async def _scan_async() -> dict | None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _scan_sync)

    bulkhead = get_bulkhead("clamav")
    try:
        scan_result = await bulkhead.execute(
            run_with_timeout,
            _scan_async(),
            timeout_seconds=float(settings.CLAMAV_SCAN_TIMEOUT_SECONDS),
            error_message="ClamAV scan timeout",
            service="clamav",
            operation="scan_file",
        )
    except (TimeoutError, BulkheadTimeoutError):
        logger.warning("ClamAV scan timeout, skipping scan")
        return {"status": "skipped", "reason": "scan_timeout"}
    except BulkheadRejectedError:
        logger.warning("ClamAV bulkhead rejected request, skipping scan")
        return {"status": "skipped", "reason": "bulkhead_rejected"}

    stream_result = (scan_result or {}).get("stream") if isinstance(scan_result, dict) else None
    if stream_result and stream_result[0] == "FOUND":
        return {
            "status": "infected",
            "virus_name": stream_result[1] if len(stream_result) > 1 else "unknown",
        }
    return {"status": "clean"}

