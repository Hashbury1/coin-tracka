import asyncio
import itertools
import json
import os
from datetime import datetime, timezone

import asyncpg
import redis.asyncio as redis
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from scorer import score_token

structlog.configure(processors=[structlog.processors.JSONRenderer()])
log = structlog.get_logger(__name__)

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
STREAM_NAME = os.getenv("REDIS_STREAM_NAME", "raw_ticks")
CONSUMER_GROUP = "scoring_workers"
CONSUMER_NAME = "scoring_worker_1"

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://meme_admin:change_me_locally@localhost:5432/meme_tracker",
).replace("postgresql+asyncpg://", "postgresql://")

MIN_LIQUIDITY_USD = float(os.getenv("MIN_LIQUIDITY_USD", "20000"))
SCORING_INTERVAL_SECONDS = int(os.getenv("SCORING_INTERVAL_SECONDS", "30"))

# How far back to look when scoring each token. This is a rolling window
# read straight from TimescaleDB on every cycle, rather than an in-memory
# buffer - which means this worker holds zero state between cycles. Restart
# it, scale it to N replicas, kill -9 it mid-cycle: none of that loses data
# or requires coordination, because the source of truth is always the DB.
SCORING_WINDOW_MINUTES = int(os.getenv("SCORING_WINDOW_MINUTES", "60"))


async def ensure_consumer_group(redis_client: redis.Redis) -> None:
    try:
        await redis_client.xgroup_create(STREAM_NAME, CONSUMER_GROUP, id="0", mkstream=True)
    except redis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise


async def ensure_token(pool: asyncpg.Pool, tick: dict) -> None:
    await pool.execute(
        """
        INSERT INTO tokens (token_id, symbol, name, chain, source)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (token_id) DO NOTHING
        """,
        tick["token_id"], tick["symbol"], tick["name"], tick["chain"], tick["source"],
    )


async def write_tick(pool: asyncpg.Pool, tick: dict) -> None:
    await pool.execute(
        """
        INSERT INTO ticks (time, token_id, price_usd, volume_24h_usd, liquidity_usd, market_cap_usd)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT DO NOTHING
        """,
        datetime.now(timezone.utc),
        tick["token_id"],
        tick["price_usd"],
        tick.get("volume_24h_usd", 0),
        tick.get("liquidity_usd", 0),
        tick.get("market_cap_usd", 0),
    )


async def consume_loop(pool: asyncpg.Pool, redis_client: redis.Redis) -> None:
    """
    Consumes raw ticks off the Redis stream and persists them to TimescaleDB.
    This loop holds no in-memory state - it only writes. Scoring reads its
    own window straight from the DB in score_loop below, so this loop can
    crash, restart, or run as multiple replicas without any coordination.
    """
    await ensure_consumer_group(redis_client)
    log.info("scoring_worker_consuming", stream=STREAM_NAME, group=CONSUMER_GROUP)

    while True:
        try:
            entries = await redis_client.xreadgroup(
                CONSUMER_GROUP, CONSUMER_NAME, {STREAM_NAME: ">"}, count=50, block=5000
            )
        except Exception as e:  # noqa: BLE001
            log.error("redis_read_failed", error=str(e))
            await asyncio.sleep(2)
            continue

        if not entries:
            continue

        for _stream, messages in entries:
            for msg_id, fields in messages:
                try:
                    tick = json.loads(fields["data"])
                    await ensure_token(pool, tick)
                    await write_tick(pool, tick)
                    await redis_client.xack(STREAM_NAME, CONSUMER_GROUP, msg_id)
                except Exception as e:  # noqa: BLE001 - one bad message shouldn't kill the worker
                    log.error("message_processing_failed", msg_id=msg_id, error=str(e))


async def fetch_recent_ticks(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    """
    Pulls every tick within the scoring window across all tokens in a single
    query, ordered so ticks for the same token are contiguous - this lets us
    group them in Python with itertools.groupby in one pass instead of
    issuing a separate query per token.
    """
    return await pool.fetch(
        """
        SELECT token_id, time, price_usd, volume_24h_usd, liquidity_usd
        FROM ticks
        WHERE time > now() - ($1 * INTERVAL '1 minute')
        ORDER BY token_id, time ASC
        """,
        SCORING_WINDOW_MINUTES,
    )


async def score_loop(pool: asyncpg.Pool) -> None:
    """
    Periodically recomputes composite scores for every token that has
    ticks within the trailing window, reading straight from TimescaleDB
    each cycle - no in-memory state carried between iterations.
    """
    while True:
        await asyncio.sleep(SCORING_INTERVAL_SECONDS)
        now = datetime.now(timezone.utc)
        scored = 0

        try:
            rows = await fetch_recent_ticks(pool)
        except Exception as e:  # noqa: BLE001 - a slow/unreachable DB shouldn't kill the loop
            log.error("fetch_recent_ticks_failed", error=str(e))
            continue

        for token_id, group_iter in itertools.groupby(rows, key=lambda r: r["token_id"]):
            group = list(group_iter)
            if len(group) < 2:
                continue

            prices = [r["price_usd"] for r in group]
            volumes = [r["volume_24h_usd"] or 0 for r in group]
            liquidity = group[-1]["liquidity_usd"] or 0  # most recent liquidity reading

            result = score_token(prices, volumes, liquidity, MIN_LIQUIDITY_USD)

            try:
                await pool.execute(
                    """
                    INSERT INTO scores (time, token_id, volatility_score, momentum_score,
                                         liquidity_score, composite_score, window_label)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT DO NOTHING
                    """,
                    now, token_id,
                    result["volatility_score"], result["momentum_score"],
                    result["liquidity_score"], result["composite_score"],
                    "rolling",
                )
                scored += 1
            except Exception as e:  # noqa: BLE001 - one bad write shouldn't kill the cycle
                log.error("score_write_failed", token_id=token_id, error=str(e))

        log.info("scoring_cycle_complete", tokens_scored=scored, window_minutes=SCORING_WINDOW_MINUTES)


def _log_retry(retry_state):
    log.warning(
        "db_pool_connect_retry",
        attempt=retry_state.attempt_number,
        error=str(retry_state.outcome.exception()),
    )


@retry(
    stop=stop_after_attempt(10),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    before_sleep=_log_retry,
)
async def create_db_pool() -> asyncpg.Pool:
    """
    Retries pool creation with exponential backoff. This handles the common
    startup race where this container starts before TimescaleDB has finished
    initializing (running init.sql can take a few seconds), or a transient
    Docker DNS resolution hiccup for the 'timescaledb' hostname.
    """
    log.info("db_pool_connecting", database_url_host=DATABASE_URL.split("@")[-1])
    return await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)


async def main() -> None:
    pool = await create_db_pool()
    redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

    await asyncio.gather(
        consume_loop(pool, redis_client),
        score_loop(pool),
    )


if __name__ == "__main__":
    asyncio.run(main())