from prometheus_client import Counter, Gauge, Histogram

dlq_messages_total = Gauge(
    "smdg_dlq_messages_total",
    "Total messages in Dead Letter Queue",
    ["queue_name", "status"],
)

dlq_retries_total = Counter(
    "smdg_dlq_retries_total",
    "Total retry attempts",
    ["queue_name", "success"],
)

dlq_processing_time = Histogram(
    "smdg_dlq_processing_seconds",
    "Time to process DLQ messages",
    ["queue_name"],
)
