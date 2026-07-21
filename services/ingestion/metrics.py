"""
Prometheus metrics for the ingestion worker. Exposed on a plain HTTP
server (prometheus_client.start_http_server) separate from the main
asyncio loop, since this service has no web framework of its own.
"""

from prometheus_client import Counter, Histogram, start_http_server

TICKS_FETCHED = Counter(
    "ingestion_ticks_fetched_total",
    "Number of ticks successfully fetched from an upstream source",
    ["source", "chain"],
)

TICKS_PUSHED = Counter(
    "ingestion_ticks_pushed_total",
    "Number of ticks pushed onto the Redis stream",
)

FETCH_ERRORS = Counter(
    "ingestion_fetch_errors_total",
    "Number of failed fetch attempts against an upstream source",
    ["source"],
)

TICKS_FILTERED_LOW_LIQUIDITY = Counter(
    "ingestion_ticks_filtered_low_liquidity_total",
    "Number of ticks dropped for being below the minimum liquidity floor",
    ["chain"],
)

POLL_CYCLE_DURATION = Histogram(
    "ingestion_poll_cycle_duration_seconds",
    "Time taken to complete one full poll cycle across all sources",
)


def start_metrics_server(port: int = 9101) -> None:
    start_http_server(port)