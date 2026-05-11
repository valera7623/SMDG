# tests/test_core/test_webhook.py
"""
Тесты для системы webhook-уведомлений.
"""

import pytest
import json
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock, MagicMock

from app.core.webhook import (
    WebhookPayload,
    sign_payload,
)


# ==================== WebhookPayload Tests ====================

class TestWebhookPayload:
    """Тесты WebhookPayload."""

    def test_create_payload_defaults(self):
        """Создание payload с значениями по умолчанию."""
        payload = WebhookPayload(event="file.uploaded")

        assert payload.event == "file.uploaded"
        assert payload.source == "smdg"
        assert payload.data == {}
        assert "T" in payload.timestamp  # ISO format

    def test_create_payload_with_data(self):
        """Создание payload с данными."""
        payload = WebhookPayload(
            event="file.deleted",
            data={"file_id": 123, "filename": "test.pdf"},
            source="custom"
        )

        assert payload.event == "file.deleted"
        assert payload.data["file_id"] == 123
        assert payload.source == "custom"

    def test_to_dict(self):
        """to_dict возвращает словарь."""
        payload = WebhookPayload(
            event="file.uploaded",
            data={"size": 1024}
        )

        d = payload.to_dict()

        assert d["event"] == "file.uploaded"
        assert d["data"]["size"] == 1024
        assert d["source"] == "smdg"

    def test_to_json(self):
        """to_json возвращает JSON строку."""
        payload = WebhookPayload(event="test", data={"key": "value"})
        j = payload.to_json()

        parsed = json.loads(j)
        assert parsed["event"] == "test"
        assert parsed["data"]["key"] == "value"

    def test_to_json_serializes_datetime(self):
        """to_json корректно сериализует datetime."""
        payload = WebhookPayload(
            event="test",
            data={"timestamp": datetime.now(timezone.utc)}
        )
        j = payload.to_json()
        parsed = json.loads(j)
        assert "timestamp" in parsed["data"]


# ==================== sign_payload Tests ====================

class TestSignPayload:
    """Тесты HMAC подписи."""

    def test_sign_produces_hex_string(self):
        """Подпись — hex строка."""
        sig = sign_payload("test payload", "secret")
        assert len(sig) == 64  # SHA256 = 32 bytes = 64 hex chars
        assert all(c in "0123456789abcdef" for c in sig)

    def test_same_input_same_signature(self):
        """Одинаковый вход → одинаковая подпись."""
        sig1 = sign_payload("data", "key")
        sig2 = sign_payload("data", "key")
        assert sig1 == sig2

    def test_different_secret_different_signature(self):
        """Разный секрет → разная подпись."""
        sig1 = sign_payload("data", "key1")
        sig2 = sign_payload("data", "key2")
        assert sig1 != sig2

    def test_different_data_different_signature(self):
        """Разные данные → разная подпись."""
        sig1 = sign_payload("data1", "key")
        sig2 = sign_payload("data2", "key")
        assert sig1 != sig2


# ==================== WebhookEvent Enum Tests ====================

class TestWebhookEvent:
    """Тесты enum событий."""

    def test_all_events_exist(self):
        """Все события определены."""
        from app.models.webhook import WebhookEvent

        events = [e.value for e in WebhookEvent]
        assert "file.uploaded" in events
        assert "file.downloaded" in events
        assert "file.deleted" in events
        assert "link.created" in events
        assert "link.expired" in events
        assert "cleanup.completed" in events

    def test_events_are_strings(self):
        """Все события — строки."""
        from app.models.webhook import WebhookEvent

        for event in WebhookEvent:
            assert isinstance(event.value, str)


# ==================== DeliveryStatus Enum Tests ====================

class TestDeliveryStatus:
    """Тесты enum статусов доставки."""

    def test_all_statuses_exist(self):
        """Все статусы определены."""
        from app.models.webhook import DeliveryStatus

        statuses = [s.value for s in DeliveryStatus]
        assert "pending" in statuses
        assert "success" in statuses
        assert "failed" in statuses
        assert "retrying" in statuses


# ==================== WebhookDispatcher Unit Tests ====================

class TestWebhookDispatcherUnit:
    """Юнит-тесты WebhookDispatcher (без SQLAlchemy)."""

    @pytest.mark.asyncio
    async def test_dispatch_no_subscriptions(self):
        """dispatch без подписок — ничего не делает."""
        from app.core.webhook import WebhookDispatcher

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []

        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result

        dispatcher = WebhookDispatcher()

        with patch.object(dispatcher, '_send_with_retry', new_callable=AsyncMock) as mock_send:
            await dispatcher.dispatch("file.uploaded", {}, db=mock_db, tenant_id=7)
            mock_send.assert_not_called()
            stmt = mock_db.execute.call_args.args[0]
            assert "tenant_id" in str(stmt)

    def test_close_without_session(self):
        """close без активной сессии — не падает."""
        import asyncio
        from app.core.webhook import WebhookDispatcher

        dispatcher = WebhookDispatcher()
        # Не должно вызывать ошибок
        asyncio.get_event_loop().run_until_complete(dispatcher.close())


# ==================== Webhook API Schema Tests ====================

class TestWebhookApiSchemas:
    """Тесты Pydantic схем webhook API."""

    def test_subscription_create_valid(self):
        """Валидная схема создания подписки."""
        from app.api.webhooks import WebhookSubscriptionCreate

        data = WebhookSubscriptionCreate(
            url="https://93.184.216.34/webhook",
            events=["file.uploaded"],
            secret="my_secret"
        )

        assert data.url == "https://93.184.216.34/webhook"
        assert data.events == ["file.uploaded"]
        assert data.secret == "my_secret"

    def test_subscription_create_invalid_url(self):
        """Невалидный URL."""
        from app.api.webhooks import WebhookSubscriptionCreate
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            WebhookSubscriptionCreate(
                url="not-a-url",
                events=["file.uploaded"]
            )

    def test_subscription_create_invalid_event(self):
        """Невалидное событие."""
        from app.api.webhooks import WebhookSubscriptionCreate
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            WebhookSubscriptionCreate(
                url="https://93.184.216.34/webhook",
                events=["invalid.event"]
            )

    def test_subscription_create_rejects_private_url(self):
        """Production validation rejects private/internal webhook targets."""
        from app.api.webhooks import WebhookSubscriptionCreate
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            WebhookSubscriptionCreate(
                url="http://127.0.0.1:8080/webhook",
                events=["file.uploaded"],
            )

    def test_subscription_update_partial(self):
        """Частичное обновление."""
        from app.api.webhooks import WebhookSubscriptionUpdate

        data = WebhookSubscriptionUpdate(is_active=False)
        assert data.is_active is False
        assert data.url is None

    def test_response_serialization(self):
        """Сериализация response."""
        from app.api.webhooks import WebhookSubscriptionResponse

        sub = WebhookSubscriptionResponse(
            id=1,
            url="https://93.184.216.34/webhook",
            events=["file.uploaded"],
            is_active=True,
            max_retries=3,
            timeout_seconds=10,
            created_at="2026-04-10T00:00:00",
        )

        assert sub.id == 1
        assert sub.secret is None


if __name__ == "__main__":
    pytest.main([__file__])
