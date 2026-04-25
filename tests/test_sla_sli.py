"""API /api/sli и публичная /status (при моке Redis в conftest)."""
from __future__ import annotations


def test_sli_root(client) -> None:
    r = client.get("/api/sli")
    assert r.status_code == 200
    assert r.json().get("service") == "SMDG"


def test_sli_status_json(client) -> None:
    r = client.get("/api/sli/status")
    assert r.status_code == 200
    data = r.json()
    for key in (
        "current_status",
        "api_availability",
        "error_budget_remaining",
        "latency_p95",
        "active_incidents",
    ):
        assert key in data


def test_status_page_html(client) -> None:
    r = client.get("/status")
    assert r.status_code == 200
    assert b"service status" in r.content.lower() or b"SMDG" in r.content
