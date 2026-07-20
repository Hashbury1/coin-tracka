"""Prometheus metrics for the scoring worker."""

from prometheus_client import Counter, Gauge, Histogram, start_http_server

TOKENS_SCORED = Counter(
    "scoring_tokens_scored_total",
    "Number of tokens scored across all scoring cycles",
)

SCORING_CYCLE_DURATION = Histogram(
    "scoring_cycle_duration_seconds",
    "Time taken to complete one scoring cycle (DB fetch + compute + write)",
)

TICKS_CONSUMED = Counter(
    "scoring_ticks_consumed_total",
    "Number of raw ticks consumed from the Redis stream and persisted",
)

MESSAGE_PROCESSING_ERRORS = Counter(
    "scoring_message_processing_errors_total",
    "Number of Redis stream messages that failed to process",
)

DB_CONNECT_RETRIES = Counter(
    "scoring_db_connect_retries_total",
    "Number of retry attempts made while establishing the DB connection pool",
)

LAST_SUCCESSFUL_CYCLE_TIMESTAMP = Gauge(
    "scoring_last_successful_cycle_timestamp_seconds",
    "Unix timestamp of the last scoring cycle that completed without error",
)


def start_metrics_server(port: int = 9102) -> None:
    start_http_server(port)