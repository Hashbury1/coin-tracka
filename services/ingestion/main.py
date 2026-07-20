import asyncio
import json
import time

import redis.asyncio as redis
import structlog
from aiohttp import ClientSession

from config import settings
from metrics import (
    FETCH_ERRORS,
    POLL_CYCLE_DURATION,
    TICKS_FETCHED,
    TICKS_FILTERED_LOW_LIQUIDITY,
    TICKS_PUSHED,
    start_metrics_server,
)
from sources import coingecko, dexscreener

structlog.configure(processors=[structlog.processors.JSONRenderer()])
log = structlog.get_logger(__name__)


async def push_ticks(redis_client: redis.Redis, ticks: list[dict]) -> None:
    """Push normalized ticks onto the Redis stream for the scoring worker to consume."""
    if not ticks:
        return

    pipe = redis_client.pipeline()
    for tick in ticks:
        tick["ingested_at"] = time.time()
        pipe.xadd(settings.stream_name, {"data": json.dumps(tick)})
    await pipe.execute()
    TICKS_PUSHED.inc(len(ticks))
    log.info("pushed_ticks", count=len(ticks), stream=settings.stream_name)


async def poll_once(session: ClientSession, redis_client: redis.Redis) -> None:
    all_ticks: list[dict] = []

    # CoinGecko: established meme coins
    try:
        cg_ticks = await coingecko.fetch_meme_category(session, settings.coingecko_api_key)
        TICKS_FETCHED.labels(source="coingecko", chain="multi").inc(len(cg_ticks))
        all_ticks += cg_ticks
    except Exception as e:  # noqa: BLE001 - a single source failing shouldn't kill the loop
        FETCH_ERRORS.labels(source="coingecko").inc()
        log.error("coingecko_fetch_failed", error=str(e))

    # DEXScreener: on-chain / freshly launched tokens, per tracked chain
    for chain in settings.tracked_chains:
        chain = chain.strip()
        if not chain:
            continue
        try:
            pairs = await dexscreener.fetch_trending_pairs(
                session, settings.dexscreener_base_url, chain
            )
            TICKS_FETCHED.labels(source="dexscreener", chain=chain).inc(len(pairs))

            # Filter out low-liquidity tokens early — rug-pull / bad-data risk mitigation
            before = len(pairs)
            pairs = [p for p in pairs if p["liquidity_usd"] >= settings.min_liquidity_usd]
            TICKS_FILTERED_LOW_LIQUIDITY.labels(chain=chain).inc(before - len(pairs))

            all_ticks += pairs
        except Exception as e:  # noqa: BLE001
            FETCH_ERRORS.labels(source="dexscreener").inc()
            log.error("dexscreener_fetch_failed", chain=chain, error=str(e))

    await push_ticks(redis_client, all_ticks)


async def main() -> None:
    redis_client = redis.Redis(
        host=settings.redis_host, port=settings.redis_port, decode_responses=True
    )

    start_metrics_server(9101)
    log.info(
        "ingestion_worker_starting",
        poll_interval=settings.poll_interval_seconds,
        chains=settings.tracked_chains,
        metrics_port=9101,
    )

    async with ClientSession() as session:
        while True:
            start = time.monotonic()
            try:
                with POLL_CYCLE_DURATION.time():
                    await poll_once(session, redis_client)
            except Exception as e:  # noqa: BLE001 - keep the loop alive no matter what
                log.error("poll_cycle_failed", error=str(e))

            elapsed = time.monotonic() - start
            sleep_for = max(0, settings.poll_interval_seconds - elapsed)
            await asyncio.sleep(sleep_for)


if __name__ == "__main__":
    asyncio.run(main())