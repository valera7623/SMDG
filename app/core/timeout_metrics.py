"""Prometheus metrics for timeout events."""
from prometheus_client import Counter, Histogram

timeout_total = Counter(
    "smdg_timeout_total",
    "Total number of timeout events",
    ["operation", "service"],
)

timeout_duration_seconds = Histogram(
    "smdg_timeout_duration_seconds",
    "Configured timeout duration for timed operations",
    ["operation", "service"],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300],
)

