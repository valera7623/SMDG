"""Тесты для TelegramAlerter.

Не дёргаем настоящий Telegram API. Все HTTP-обращения подменяются через
httpx.MockTransport.
"""
from __future__ import annotations

import json
from typing import Any, Dict

import httpx
import pytest

from app.services.telegram_alerter import TelegramAlerter


def _sample_alert(
    alertname: str = "SMDGDatabaseDown",
    severity: str = "critical",
) -> Dict[str, Any]:
    return {
        "status": "firing",
        "labels": {
            "alertname": alertname,
            "severity": severity,
            "service": "smdg",
            "instance": "smdg:8000",
        },
        "annotations": {
            "summary": f"{alertname} summary",
            "description": f"{alertname} description",
            "runbook": "https://wiki.smdg/runbooks",
        },
        "startsAt": "2026-04-21T10:00:00Z",
    }


class TestNoopMode:
    """Без токена/chat_id alerter не должен ходить по сети."""

    @pytest.mark.asyncio
    async def test_send_alert_noop_returns_false(self) -> None:
        alerter = TelegramAlerter(bot_token="", chat_id="")
        assert alerter.enabled is False
        ok = await alerter.send_alert(_sample_alert())
        assert ok is False

    @pytest.mark.asyncio
    async def test_send_batch_noop(self) -> None:
        alerter = TelegramAlerter(bot_token=None, chat_id=None)
        result = await alerter.send_batch_alerts(
            [_sample_alert(), _sample_alert("SMDGRedisDown")]
        )
        assert result == 0


class TestFormatting:
    """Форматирование сообщения — проверяем содержимое."""

    def test_format_contains_severity_and_name(self) -> None:
        text, markup = TelegramAlerter._format_alert(
            _sample_alert(),
            dashboard_url="https://d",
            tracing_url="https://t",
            logs_url="https://l",
        )
        assert "SMDGDatabaseDown" in text
        assert "CRITICAL" in text
        assert "🔴" in text
        # inline_keyboard должен содержать ссылку на runbook
        assert any(
            btn.get("url") == "https://wiki.smdg/runbooks"
            for row in markup["inline_keyboard"]
            for btn in row
        )

    def test_format_truncates_long_description(self) -> None:
        huge = _sample_alert()
        huge["annotations"]["description"] = "x" * 10000
        text, _ = TelegramAlerter._format_alert(
            huge, dashboard_url="d", tracing_url="t", logs_url="l"
        )
        assert len(text) < 4096
        assert "truncated" in text

    def test_resolved_tag(self) -> None:
        resolved = _sample_alert()
        resolved["status"] = "resolved"
        text, _ = TelegramAlerter._format_alert(
            resolved, dashboard_url="d", tracing_url="t", logs_url="l"
        )
        assert "RESOLVED" in text


class TestSendAlertHttp:
    """Отправка одиночного алерта через mocked httpx."""

    @pytest.mark.asyncio
    async def test_send_alert_success(self) -> None:
        captured: Dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["json"] = json.loads(request.content.decode())
            return httpx.Response(200, json={"ok": True, "result": {}})

        alerter = TelegramAlerter(bot_token="tok", chat_id="chat")
        alerter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        ok = await alerter.send_alert(_sample_alert())
        assert ok is True
        assert captured["url"].endswith("/sendMessage")
        assert captured["json"]["chat_id"] == "chat"
        assert captured["json"]["parse_mode"] == "HTML"
        assert "SMDGDatabaseDown" in captured["json"]["text"]
        # Alertname обёрнут в <b>...</b>
        assert "<b>SMDG Alert: SMDGDatabaseDown</b>" in captured["json"]["text"]
        await alerter.close()

    @pytest.mark.asyncio
    async def test_send_alert_http_error_returns_false(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(502, text="bad gateway")

        alerter = TelegramAlerter(bot_token="tok", chat_id="chat")
        alerter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        ok = await alerter.send_alert(_sample_alert())
        assert ok is False
        await alerter.close()

    @pytest.mark.asyncio
    async def test_send_batch_uses_summary_message(self) -> None:
        sent: list[Dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            sent.append(json.loads(request.content.decode()))
            return httpx.Response(200, json={"ok": True})

        alerter = TelegramAlerter(bot_token="tok", chat_id="chat")
        alerter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        alerts = [_sample_alert(f"Alert{i}") for i in range(5)]
        delivered = await alerter.send_batch_alerts(alerts)

        assert delivered == 1
        # должно уйти ОДНО групповое сообщение, а не 5
        assert len(sent) == 1
        assert "5 alerts detected" in sent[0]["text"]
        await alerter.close()
