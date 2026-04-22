"""Prometheus metrics for bulkhead isolation."""
from prometheus_client import Counter, Gauge

bulkhead_active = Gauge(
    "smdg_bulkhead_active_requests",
    "Active requests in bulkhead",
    ["name"],
)

bulkhead_queued = Gauge(
    "smdg_bulkhead_queued_requests",
    "Queued requests in bulkhead",
    ["name"],
)

bulkhead_utilization = Gauge(
    "smdg_bulkhead_utilization_percent",
    "Bulkhead utilization percentage",
    ["name"],
)

bulkhead_rejected_total = Counter(
    "smdg_bulkhead_rejected_total",
    "Total rejected requests",
    ["name"],
)

bulkhead_timeout_total = Counter(
    "smdg_bulkhead_timeout_total",
    "Total timeout requests",
    ["name"],
)
