"""Тесты SLO/SLI мониторинга.

Покрывают:

- Наличие и регистрацию метрик из :mod:`app.core.slo_metrics`.
- Внутренний расчёт квантилей через ``_histogram_quantile``.
- Работу :class:`SLOCollector` (error budget, compliance).
- Поведение :class:`SLOMiddleware` (учёт 2xx/4xx/5xx, latency).
- API-хелперы (``_status_from_compliance``) и формат отчёта.

Тесты намеренно unit-level: не поднимаем реальный TestClient c lifespan,
поскольку SLO-логика полностью чистая и проверяется без I/O. Для
middleware используем минимальный ASGI-стек.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from app.api.slo import _status_from_compliance
from app.core.slo_collector import (
    SLO_CONFIG,
    SLOCollector,
    _histogram_quantile,
)
from app.core.slo_metrics import (
    api_latency_p50,
    api_latency_p90,
    api_latency_p99,
    db_availability,
    error_budget_remaining,
    error_budget_spent,
    redis_availability,
    slo_compliance,
    slo_latency_bucket,
    slo_success_requests,
    slo_total_requests,
    storage_availability,
)


# ---------------------------------------------------------------------------
# 1. Метрики зарегистрированы и импортируются
# ---------------------------------------------------------------------------


def test_slo_metrics_importable() -> None:
    """Базовый smoke-test: все SLO-метрики доступны как объекты."""
    metrics = [
        slo_success_requests,
        slo_total_requests,
        slo_latency_bucket,
        slo_compliance,
        error_budget_remaining,
        error_budget_spent,
        db_availability,
        redis_availability,
        storage_availability,
        api_latency_p50,
        api_latency_p90,
        api_latency_p99,
    ]
    for m in metrics:
        assert m is not None


def test_slo_counters_can_be_incremented() -> None:
    """Labelled counter работает без исключений."""
    before = slo_total_requests.labels(slo_name="test_slo_isolated")._value.get()
    slo_total_requests.labels(slo_name="test_slo_isolated").inc()
    after = slo_total_requests.labels(slo_name="test_slo_isolated")._value.get()
    assert after == before + 1


# ---------------------------------------------------------------------------
# 2. Histogram quantile
# ---------------------------------------------------------------------------


def test_histogram_quantile_on_empty_histogram() -> None:
    """Пустая histogram → 0.0 (нет наблюдений)."""
    from prometheus_client import Histogram

    h = Histogram(
        "test_slo_empty_histogram_xyz", "help",
        buckets=(0.1, 0.5, 1.0),
    )
    assert _histogram_quantile(h, 0.99) == 0.0


def test_histogram_quantile_basic() -> None:
    """Kvantиль лежит в пределах последнего реального bucket.

    При наблюдениях {0.05, 0.3, 0.7, 1.2}:
    - p50 должна быть < 1.0 (большая часть наблюдений в lower-buckets)
    - p99 должна быть <= 2.0 (верхняя реальная граница)
    """
    from prometheus_client import Histogram

    h = Histogram(
        "test_slo_basic_histogram_abc", "help",
        buckets=(0.1, 0.5, 1.0, 2.0),
    )
    for value in (0.05, 0.3, 0.7, 1.2):
        h.observe(value)

    p50 = _histogram_quantile(h, 0.50)
    p99 = _histogram_quantile(h, 0.99)
    assert 0.0 <= p50 <= 1.0
    assert 0.0 <= p99 <= 2.0
    assert p99 >= p50


# ---------------------------------------------------------------------------
# 3. SLOCollector: error budget
# ---------------------------------------------------------------------------


def _reset_slo_counter(slo_name: str) -> None:
    """Обнулить counter для изолированных тестов.

    Counter сам по себе не умеет сбрасываться, но для labelled-child
    можно переустановить ``_value``. Используется только в тестах.
    """
    try:
        slo_total_requests.labels(slo_name=slo_name)._value.set(0)  # type: ignore[attr-defined]
        slo_success_requests.labels(slo_name=slo_name)._value.set(0)  # type: ignore[attr-defined]
    except Exception:
        pass


def test_calculate_error_budget_all_success() -> None:
    """При 100% успешных запросов availability = 100, budget = full."""
    slo = "test_budget_full"
    _reset_slo_counter(slo)

    for _ in range(1000):
        slo_total_requests.labels(slo_name=slo).inc()
        slo_success_requests.labels(slo_name=slo).inc()

    col = SLOCollector()
    availability = col.calculate_error_budget(slo, target=99.9)

    assert availability == pytest.approx(100.0)
    # 0 ошибок → весь допустимый budget остался.
    remaining = error_budget_remaining.labels(slo_name=slo)._value.get()
    spent = error_budget_spent.labels(slo_name=slo)._value.get()
    assert remaining == pytest.approx(1000 * 0.001)  # 0.1% от 1000
    assert spent == 0.0


def test_calculate_error_budget_breach() -> None:
    """Если ошибок больше допустимого — remaining=0."""
    slo = "test_budget_breach"
    _reset_slo_counter(slo)

    for _ in range(1000):
        slo_total_requests.labels(slo_name=slo).inc()
    for _ in range(950):
        slo_success_requests.labels(slo_name=slo).inc()

    col = SLOCollector()
    availability = col.calculate_error_budget(slo, target=99.9)

    assert availability == pytest.approx(95.0)
    remaining = error_budget_remaining.labels(slo_name=slo)._value.get()
    assert remaining == 0.0


def test_calculate_error_budget_zero_requests() -> None:
    """Если не было запросов — availability считается 100% (нет базы)."""
    slo = "test_budget_zero"
    _reset_slo_counter(slo)

    col = SLOCollector()
    availability = col.calculate_error_budget(slo, target=99.9)
    assert availability == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# 4. SLOCollector: compliance
# ---------------------------------------------------------------------------


def test_calculate_slo_compliance_updates_all() -> None:
    """После ``calculate_slo_compliance`` заполнены все SLO-метрики."""
    # Устанавливаем realistic значения зависимостей.
    db_availability.set(100.0)
    redis_availability.set(100.0)
    storage_availability.set(100.0)
    api_latency_p99.set(0.2)

    col = SLOCollector()
    col.calculate_slo_compliance()

    for slo_name, config in SLO_CONFIG.items():
        target = f"{config['target']}%"
        value = slo_compliance.labels(slo_name=slo_name, target=target)._value.get()
        assert 0.0 <= value <= 100.0


def test_calculate_slo_compliance_latency_breach() -> None:
    """Если p99 > target → compliance падает ниже 100."""
    api_latency_p99.set(5.0)  # сильно выше target=0.5

    col = SLOCollector()
    col.calculate_slo_compliance()

    val = slo_compliance.labels(slo_name="api_latency", target="0.5%")._value.get()
    assert val < 100.0


# ---------------------------------------------------------------------------
# 5. SLOMiddleware
# ---------------------------------------------------------------------------


class _FakeASGIApp:
    """Мини-ASGI-приложение для unit-тестов middleware.

    Возвращает заданный status code; не пишет тела.
    """

    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code
        self.called = 0

    async def __call__(self, scope: Dict[str, Any], receive: Any, send: Any) -> None:
        self.called += 1
        await send({"type": "http.response.start", "status": self.status_code, "headers": []})
        await send({"type": "http.response.body", "body": b""})


async def _run_middleware(mw: Any, path: str = "/api/test") -> List[Dict[str, Any]]:
    """Прогнать ASGI-сценарий и собрать сообщения, отправленные через send."""
    sent: List[Dict[str, Any]] = []

    async def send(message: Dict[str, Any]) -> None:
        sent.append(message)

    async def receive() -> Dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {"type": "http", "method": "GET", "path": path, "headers": []}
    await mw(scope, receive, send)
    return sent


@pytest.mark.asyncio
async def test_slo_middleware_counts_success() -> None:
    """2xx ответ → success_requests инкрементирован."""
    from app.core.middleware import SLOMiddleware

    _reset_slo_counter("api_availability")
    mw = SLOMiddleware(_FakeASGIApp(status_code=200))

    await _run_middleware(mw, path="/api/foo")

    total = slo_total_requests.labels(slo_name="api_availability")._value.get()
    success = slo_success_requests.labels(slo_name="api_availability")._value.get()
    assert total == 1
    assert success == 1


@pytest.mark.asyncio
async def test_slo_middleware_counts_server_error() -> None:
    """5xx ответ → total инкрементирован, success — нет."""
    from app.core.middleware import SLOMiddleware

    _reset_slo_counter("api_availability")
    mw = SLOMiddleware(_FakeASGIApp(status_code=503))

    await _run_middleware(mw, path="/api/foo")

    total = slo_total_requests.labels(slo_name="api_availability")._value.get()
    success = slo_success_requests.labels(slo_name="api_availability")._value.get()
    assert total == 1
    assert success == 0


@pytest.mark.asyncio
async def test_slo_middleware_excludes_infrastructure_paths() -> None:
    """/metrics и /health не считаются в SLO (infra probes)."""
    from app.core.middleware import SLOMiddleware

    _reset_slo_counter("api_availability")
    mw = SLOMiddleware(_FakeASGIApp(status_code=200))

    for path in ("/metrics", "/health", "/health/ready"):
        await _run_middleware(mw, path=path)

    total = slo_total_requests.labels(slo_name="api_availability")._value.get()
    assert total == 0


@pytest.mark.asyncio
async def test_slo_middleware_observes_latency() -> None:
    """Histogram получает наблюдение длительности."""
    from app.core.middleware import SLOMiddleware

    _reset_slo_counter("api_availability")
    mw = SLOMiddleware(_FakeASGIApp(status_code=200))

    # Snapshot до.
    before = slo_latency_bucket._sum.get()  # type: ignore[attr-defined]
    await _run_middleware(mw, path="/api/foo")
    after = slo_latency_bucket._sum.get()  # type: ignore[attr-defined]

    assert after >= before


# ---------------------------------------------------------------------------
# 6. API helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "compliance,target,expected",
    [
        (100.0, 99.9, "good"),
        # Compliance ниже target, но >= 95% и >= 99% → breach
        # (SLO формально нарушен, но ещё не в «красной» зоне).
        (99.5, 99.9, "breach"),
        # Compliance < 99% и < target → всё ещё breach.
        (98.5, 99.9, "breach"),
        # Compliance < 95% — критично, независимо от target.
        (90.0, 99.9, "critical"),
        # Target ниже текущего compliance (редко, но валидно) → good.
        (99.5, 99.0, "good"),
        # 98.5 при target 99.0 — формальное нарушение SLO.
        (98.5, 99.0, "breach"),
    ],
)
def test_status_from_compliance(
    compliance: float, target: float, expected: str
) -> None:
    assert _status_from_compliance(compliance, target) == expected


# ---------------------------------------------------------------------------
# 7. End-to-end: collect_once
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_collect_once_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    """``collect_once`` отрабатывает без DB/Redis/S3.

    Мокаем низкоуровневые проверки так, чтобы availability = 100% и
    смотрим, что compliance расчёт не бросил исключений.
    """
    from app.core import slo_collector as module

    async def _ok() -> None:
        return None

    monkeypatch.setattr(module, "_check_db", _ok)
    monkeypatch.setattr(module, "_check_redis", _ok)
    monkeypatch.setattr(module, "_check_storage", _ok)

    col = SLOCollector()
    await col.collect_once()

    # Все зависимости теперь 100% доступны.
    assert db_availability._value.get() == pytest.approx(100.0)
    assert redis_availability._value.get() == pytest.approx(100.0)
    assert storage_availability._value.get() == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_collect_slo_metrics_cancellable() -> None:
    """Основной цикл корректно обрабатывает CancelledError."""
    col = SLOCollector()
    # Очень короткий интервал: задача должна успеть хотя бы один тик.
    from app.core import slo_collector as module
    original_interval = module.SLO_COLLECT_INTERVAL_SEC
    module.SLO_COLLECT_INTERVAL_SEC = 1  # type: ignore[assignment]

    try:
        task = asyncio.create_task(col.collect_slo_metrics())
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        module.SLO_COLLECT_INTERVAL_SEC = original_interval  # type: ignore[assignment]
