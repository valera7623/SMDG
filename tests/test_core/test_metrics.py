"""Тесты для app/core/metrics.py — SMDG алертинг метрики."""
from __future__ import annotations

import pytest
from prometheus_client import REGISTRY

from app.core import metrics


class TestMetricsRegistration:
    """Метрики регистрируются в REGISTRY ровно один раз (импорт идемпотентен)."""

    def test_all_public_names_exist(self) -> None:
        for name in metrics.__all__:
            assert hasattr(metrics, name), f"Missing public metric: {name}"

    @pytest.mark.parametrize(
        "name",
        [
            "smdg_db_up",
            "smdg_redis_up",
            "smdg_storage_up",
            "smdg_dicom_up",
            "smdg_last_audit_timestamp",
            "smdg_cleanup_queue_size",
            "smdg_webhook_retry_queue_size",
            "smdg_active_requests",
        ],
    )
    def test_gauge_in_registry(self, name: str) -> None:
        """Каждый gauge доступен через collect() REGISTRY."""
        sample_names = {
            sample.name
            for metric in REGISTRY.collect()
            for sample in metric.samples
        }
        assert name in sample_names, f"{name} not found in Prometheus registry"


class TestGaugeArithmetic:
    """Gauge поддерживает set(0) / set(1) — это база для smdg_*_up."""

    def test_db_up_toggles(self) -> None:
        metrics.smdg_db_up.set(0)
        assert self._read("smdg_db_up") == 0
        metrics.smdg_db_up.set(1)
        assert self._read("smdg_db_up") == 1

    @staticmethod
    def _read(metric_name: str) -> float:
        for metric in REGISTRY.collect():
            for sample in metric.samples:
                if sample.name == metric_name:
                    return sample.value
        raise AssertionError(f"{metric_name} not found")


class TestCounters:
    """Counter'ы корректно инкрементируются по labels."""

    def test_upload_failures_label(self) -> None:
        before = self._count("upload_failures_total", {"reason": "quota_exceeded"})
        metrics.upload_failures_total.labels(reason="quota_exceeded").inc()
        after = self._count("upload_failures_total", {"reason": "quota_exceeded"})
        assert after == before + 1

    def test_cross_tenant_access_no_labels(self) -> None:
        before = self._count("cross_tenant_access_total", {})
        metrics.cross_tenant_access_total.inc(3)
        after = self._count("cross_tenant_access_total", {})
        assert after == before + 3

    @staticmethod
    def _count(metric_name: str, labels: dict) -> float:
        full_name = f"{metric_name}_total" if not metric_name.endswith("_total") else metric_name
        # Counter exposes itself with suffix _total in samples already.
        for metric in REGISTRY.collect():
            for sample in metric.samples:
                if sample.name == metric_name and sample.labels == labels:
                    return sample.value
        return 0.0


class TestHistograms:
    """Histogram корректно наблюдает и создаёт бакеты."""

    def test_api_latency_observation(self) -> None:
        metrics.api_latency_seconds.labels(method="GET", endpoint="/api/foo").observe(0.25)
        # После observe должны появиться samples _bucket/_sum/_count
        names = {
            sample.name
            for metric in REGISTRY.collect()
            for sample in metric.samples
        }
        assert "api_latency_seconds_bucket" in names
        assert "api_latency_seconds_count" in names
        assert "api_latency_seconds_sum" in names

    def test_dicom_render_duration_buckets(self) -> None:
        # Проверяем, что наша кастомная шкала бакетов зарегистрирована.
        metrics.dicom_render_duration_seconds.observe(1.5)
        buckets: set[str] = set()
        for metric in REGISTRY.collect():
            for sample in metric.samples:
                if sample.name == "dicom_render_duration_seconds_bucket":
                    buckets.add(sample.labels.get("le", ""))
        # наличие 0.1 / 1.0 / 60 / +Inf — подтверждает конфиг бакетов
        assert "0.1" in buckets
        assert "1.0" in buckets
        assert "60.0" in buckets
        assert "+Inf" in buckets


class TestVersionInfo:
    def test_info_set(self) -> None:
        metrics.smdg_version_info.info(
            {"version": "4.0.0", "deployment_type": "saas", "git_sha": "abc123"}
        )
        found = False
        for metric in REGISTRY.collect():
            for sample in metric.samples:
                if sample.name == "smdg_version_info":
                    found = True
                    assert sample.labels["version"] == "4.0.0"
                    assert sample.labels["deployment_type"] == "saas"
        assert found, "smdg_version_info sample not exposed"
