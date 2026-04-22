"""Тесты для Alertmanager webhook endpoint.

Проверяем:
* прием корректного payload возвращает 200 и count/delivered;
* пустой список — тоже 200 без падений;
* shared secret работает, когда включён (envvar задан);
* Telegram alerter вызывается через мок (не дёргаем настоящий Telegram).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def fake_alert_payload() -> dict:
    return {
        "receiver": "default",
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "SMDGDatabaseDown",
                    "severity": "critical",
                    "service": "smdg",
                    "instance": "smdg:8000",
                },
                "annotations": {
                    "summary": "PostgreSQL недоступен",
                    "description": "SELECT 1 не проходит",
                    "runbook": "https://wiki.smdg/runbooks/database-down",
                },
                "startsAt": "2026-04-21T10:00:00Z",
            }
        ],
        "groupKey": "{}:{alertname=\"SMDGDatabaseDown\"}",
    }


class TestAlertWebhook:
    def test_webhook_accepts_payload(self, client, fake_alert_payload):
        with patch(
            "app.api.alert_webhook.get_telegram_alerter"
        ) as mock_get:
            mock_alerter = AsyncMock()
            mock_alerter.send_batch_alerts = AsyncMock(return_value=1)
            mock_get.return_value = mock_alerter

            resp = client.post("/api/alerts/webhook", json=fake_alert_payload)

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "received"
        assert body["count"] == 1
        assert body["delivered"] == 1
        mock_alerter.send_batch_alerts.assert_awaited_once()

    def test_webhook_empty_alerts(self, client):
        with patch("app.api.alert_webhook.get_telegram_alerter") as mock_get:
            mock_alerter = AsyncMock()
            mock_get.return_value = mock_alerter
            resp = client.post(
                "/api/alerts/webhook",
                json={"receiver": "default", "alerts": []},
            )
        assert resp.status_code == 200
        assert resp.json()["count"] == 0
        # send_batch_alerts не должен дергаться для пустого списка
        mock_alerter.send_batch_alerts.assert_not_awaited()

    def test_webhook_invalid_json(self, client):
        resp = client.post(
            "/api/alerts/webhook",
            data="not a json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    def test_webhook_secret_required(self, client, fake_alert_payload, monkeypatch):
        monkeypatch.setenv("SMDG_ALERT_WEBHOOK_SECRET", "topsecret")
        # Без заголовка — 401
        resp = client.post("/api/alerts/webhook", json=fake_alert_payload)
        assert resp.status_code == 401

    def test_webhook_secret_match(self, client, fake_alert_payload, monkeypatch):
        monkeypatch.setenv("SMDG_ALERT_WEBHOOK_SECRET", "topsecret")
        with patch("app.api.alert_webhook.get_telegram_alerter") as mock_get:
            mock_alerter = AsyncMock()
            mock_alerter.send_batch_alerts = AsyncMock(return_value=1)
            mock_get.return_value = mock_alerter
            resp = client.post(
                "/api/alerts/webhook",
                json=fake_alert_payload,
                headers={"X-Alert-Secret": "topsecret"},
            )
        assert resp.status_code == 200

    def test_webhook_health_endpoint(self, client):
        resp = client.get("/api/alerts/webhook/health")
        assert resp.status_code == 200
        body = resp.json()
        assert "telegram_enabled" in body
        assert "shared_secret_required" in body
