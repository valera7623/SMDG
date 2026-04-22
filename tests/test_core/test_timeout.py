import asyncio

import pytest
from starlette.responses import Response

from app.core.middleware import TimeoutMiddleware
from app.core.timeout import TimeoutError, run_with_timeout, timeout


@pytest.mark.asyncio
async def test_run_with_timeout_success():
    async def _work():
        await asyncio.sleep(0.01)
        return "ok"

    result = await run_with_timeout(_work(), timeout_seconds=0.1)
    assert result == "ok"


@pytest.mark.asyncio
async def test_run_with_timeout_raises_timeout_error():
    async def _work():
        await asyncio.sleep(0.1)
        return "slow"

    with pytest.raises(TimeoutError):
        await run_with_timeout(_work(), timeout_seconds=0.01, error_message="timeout")


@pytest.mark.asyncio
async def test_timeout_decorator():
    @timeout(0.01, "decorator timeout")
    async def _slow():
        await asyncio.sleep(0.1)
        return "never"

    with pytest.raises(TimeoutError, match="decorator timeout"):
        await _slow()


@pytest.mark.asyncio
async def test_timeout_middleware_returns_504(monkeypatch):
    from app.core import middleware as middleware_module

    monkeypatch.setattr(
        middleware_module.settings,
        "HTTP_REQUEST_TIMEOUT_SECONDS",
        0.01,
        raising=False,
    )

    async def slow_app(scope, receive, send):
        await asyncio.sleep(0.1)
        response = Response("ok")
        await response(scope, receive, send)

    app = TimeoutMiddleware(slow_app)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [],
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    messages = []

    async def send(message):
        messages.append(message)

    await app(scope, receive, send)

    response_start = next(msg for msg in messages if msg["type"] == "http.response.start")
    assert response_start["status"] == 504

