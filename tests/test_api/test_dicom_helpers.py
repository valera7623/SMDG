"""Unit tests for small helpers in ``app.api.dicom`` (no HTTP stack)."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_enqueue_dicom_dlq_calls_send():
    with patch("app.api.dicom.dlq.send_to_dlq", new_callable=AsyncMock) as send:
        from app.api.dicom import _enqueue_dicom_dlq

        err = ValueError("boom")
        await _enqueue_dicom_dlq(
            operation="read_meta",
            file_id=9,
            encrypted_path="/enc/x.age",
            error=err,
            extra={"k": "v"},
        )
        send.assert_awaited_once()
        call_kw = send.call_args.kwargs
        assert call_kw["queue_name"] == "dicom"
        assert call_kw["error"] is err
        assert call_kw["payload"]["file_id"] == 9
        assert call_kw["metadata"]["source"] == "dicom_api"


@pytest.mark.asyncio
async def test_enqueue_dicom_dlq_swallows_send_error():
    with patch("app.api.dicom.dlq.send_to_dlq", new_callable=AsyncMock) as send:
        send.side_effect = RuntimeError("dlq down")
        from app.api.dicom import _enqueue_dicom_dlq

        await _enqueue_dicom_dlq(
            operation="x",
            file_id=None,
            encrypted_path=None,
            error=Exception("inner"),
        )


@pytest.mark.asyncio
async def test_get_dicom_metadata_cache_returns_none_on_error():
    with patch("redis.asyncio.Redis.from_url", side_effect=OSError("unreachable")):
        from app.api.dicom import _get_dicom_metadata_cache

        assert await _get_dicom_metadata_cache(1) is None
