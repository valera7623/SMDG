# app/core/sla_tracker.py
"""
Агрегация SLI/SLA-friendly данных для /api/sli и status page.

1) Читает in-process gauge'и из :mod:`app.core.slo_metrics` (обновляются
   ``slo_collector``) — работает без Prometheus.
2) Опционально дополняет данные из ``PROMETHEUS_URL`` (PromQL instant query).
"""
from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090").rstrip("/")
SLO_NAME_API = "api_availability"

# «Инциденты» из файла (опционально): JSON list of { title, description, status, started_at, ... }
_INCIDENTS_PATH = os.getenv("SMDG_STATUS_INCIDENTS_PATH", "")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gauge_unlabeled_value(getter) -> float:
    try:
        return float(getter._value.get())  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return 0.0


def _labeled_gauge_value(g, **labels: str) -> float:
    try:
        return float(g.labels(**labels)._value.get())  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return 0.0


def _error_budget_percent() -> float:
    """Процент **оставшегося** error budget (api_availability), 0..100."""
    from app.core.slo_metrics import error_budget_remaining, error_budget_spent

    r = _labeled_gauge_value(error_budget_remaining, slo_name=SLO_NAME_API)
    s = _labeled_gauge_value(error_budget_spent, slo_name=SLO_NAME_API)
    t = r + s
    if t <= 0:
        return 100.0
    return max(0.0, min(100.0, 100.0 * r / t))


def _slo_request_total() -> float:
    """Сколько HTTP-запросов учтено SLO (api_availability). 0 = ещё не было трафика."""
    from app.core.slo_metrics import slo_total_requests

    return _labeled_gauge_value(slo_total_requests, slo_name=SLO_NAME_API)


def _in_process_api_availability() -> float:
    from app.core.slo_metrics import api_availability

    return _gauge_unlabeled_value(api_availability)


def _in_process_latency_ms_p95_proxy() -> float:
    """
    p90 из in-process SLO-histogram, как ориентир (настоящий p95 — из Prom/Grafana).
    """
    from app.core.slo_metrics import api_latency_p90

    sec = _gauge_unlabeled_value(api_latency_p90)
    return round(sec * 1000.0, 2)


def _promql_instant_vector(query: str) -> Optional[float]:
    if not PROMETHEUS_URL:
        return None
    try:
        url = f"{PROMETHEUS_URL}/api/v1/query?" + urllib.parse.urlencode({"query": query})
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
            body = json.loads(resp.read().decode("utf-8"))
        r = body.get("data", {}).get("result", [])
        if not r:
            return None
        v = r[0].get("value", [None, None])
        return float(v[1])
    except Exception as exc:  # noqa: BLE001
        logger.debug("Prometheus query failed: %s: %s", query, exc)
        return None


def _load_incidents() -> List[Dict[str, Any]]:
    if not _INCIDENTS_PATH or not os.path.isfile(_INCIDENTS_PATH):
        return []
    try:
        with open(_INCIDENTS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to read incidents from %s: %s", _INCIDENTS_PATH, exc)
    return []


class SLATracker:
    """
    Снимок для status page; при наличии Prometheus — усредняет 30d availability.
    """

    @staticmethod
    def _api_availability_resolved_5m() -> Optional[float]:
        """5m/rolling availability: сначала Prom recording, иначе in-process SLO-гauges."""
        v = _promql_instant_vector("smdg:api_availability:5m")
        if v is not None:
            return round(v, 3)
        in_app = _in_process_api_availability()
        if _slo_request_total() <= 0 and in_app <= 0:
            return None
        return round(in_app, 3)

    def get_current_status(self) -> str:
        av = self._api_availability_resolved_5m()
        if av is None:
            return "unknown"
        if av >= 99.9:
            return "ok"
        if av >= 99.0:
            return "warning"
        return "error"

    def get_uptime_30d(self) -> Optional[float]:
        v = _promql_instant_vector("smdg:api_availability:30d")
        if v is not None:
            return round(v, 3)
        in_app = _in_process_api_availability()
        if _slo_request_total() <= 0 and in_app <= 0:
            return None
        return round(in_app, 3)

    def get_api_availability(self) -> Optional[float]:
        return self._api_availability_resolved_5m()

    def get_error_budget(self) -> float:
        return round(_error_budget_percent(), 2)

    def get_latency_p95(self) -> float:
        p = _promql_instant_vector("smdg:api_latency_p95:5m")
        if p is not None:
            return round(p * 1000.0, 2)
        return _in_process_latency_ms_p95_proxy()

    def get_active_incidents(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for row in _load_incidents():
            if str(row.get("status", "")).lower() in ("", "open", "investigating"):
                out.append(row)
        return out

    def get_incident_history(self, days: int = 30) -> List[Dict[str, Any]]:
        # days зарезервирован для будущей фильтрации
        _ = days
        hist: List[Dict[str, Any]] = []
        for row in _load_incidents():
            if str(row.get("status", "")).lower() in ("resolved", "closed"):
                hist.append(row)
        return hist

    def generate_report(self) -> Dict[str, Any]:
        return {
            "timestamp": _now_iso(),
            "summary": {
                "current_status": self.get_current_status(),
                "api_availability_percent": self.get_api_availability(),
                "uptime_30d_percent": self.get_uptime_30d(),
                "error_budget_remaining_percent": self.get_error_budget(),
                "latency_p95_ms": self.get_latency_p95(),
            },
            "sources": {
                "prometheus": PROMETHEUS_URL,
                "latency_p95_note": "Prometheus: smdg:api_latency_p95:5m; иначе p90*1000 in-process",
            },
        }


sla_tracker = SLATracker()
