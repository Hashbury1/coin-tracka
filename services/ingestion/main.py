import asyncio
import json
import time

import redis.asyncio as redis
import structlog
from aiohttp import ClientSession
from config import settings
from metrics import (
    ENRICHMENT_ERRORS,
    ENRICHMENT_HITS,
    FETCH_ERRORS,
    POLL_CYCLE_DURATION,
    TICKS_FETCHED,
    TICKS_FILTERED_LOW_LIQUIDITY,
    TICKS_PUSHED,
    start_metrics_server,
)
from sources import birdeye, coingecko, dexscreener, moralis, twitter

structlog.configure(processors=[structlog.processors.JSONRenderer()])
log = structlog.get_logger(__name__)


async def enrich_tick(session: ClientSession, tick: dict) -> dict:
    # Best-effort enrichment with holder concentration (rug-pull risk
    # signal) and social mention velocity (buzz signal). Only called for
    # the top N tokens by liquidity per cycle - see poll_once - since
    # these are per-token API calls against rate-limited third-party
    # services. Never raises: a missing key, a 429, or an unexpected
    # response shape just leaves the corresponding field as None.
    chain = tick.get("chain")
    contract = tick.get("token_contract_address")

    holder_data = None
    if chain == "solana" and contract:
        holder_data = await birdeye.fetch_token_overview(session, settings.birdeye_api_key, contract)
        (ENRICHMENT_HITS if holder_data else ENRICHMENT_ERRORS).labels(provider="birdeye").inc()
    elif chain in ("bsc", "ethereum") and contract:
        holder_data = await moralis.fetch_holder_concentration(
            session, settings.moralis_api_key, chain, contract
        )
        (ENRICHMENT_HITS if holder_data else ENRICHMENT_ERRORS).labels(provider="moralis").inc()

    if holder_data:
        tick["holder_count"] = holder_data.get("holder_count")
        tick["top10_concentration_pct"] = holder_data.get("top10_concentration_pct")

    mentions = await twitter.fetch_mention_count(session, settings.twitter_bearer_token, tick["symbol"])
    (ENRICHMENT_HITS if mentions is not None else ENRICHMENT_ERRORS).labels(provider="twitter").inc()
    if mentions is not None:
        tick["social_mentions_1h"] = mentions

    return tick


async def push_ticks(redis_client: redis.Redis, ticks: list[dict]) -> None:
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

    try:
        cg_ticks = await coingecko.fetch_meme_category(session, settings.coingecko_api_key)
        TICKS_FETCHED.labels(source="coingecko", chain="multi").inc(len(cg_ticks))
        all_ticks += cg_ticks
    except Exception as e:
        FETCH_ERRORS.labels(source="coingecko").inc()
        log.error("coingecko_fetch_failed", error=str(e))

    for chain in settings.tracked_chains:
        chain = chain.strip()
        if not chain:
            continue
        try:
            pairs = await dexscreener.fetch_trending_pairs(
                session, settings.dexscreener_base_url, chain
            )
            TICKS_FETCHED.labels(source="dexscreener", chain=chain).inc(len(pairs))

            before = len(pairs)
            pairs = [p for p in pairs if p["liquidity_usd"] >= settings.min_liquidity_usd]
            TICKS_FILTERED_LOW_LIQUIDITY.labels(chain=chain).inc(before - len(pairs))

            all_ticks += pairs
        except Exception as e:
            FETCH_ERRORS.labels(source="dexscreener").inc()
            log.error("dexscreener_fetch_failed", chain=chain, error=str(e))

    # Enrichment (holder concentration + social mentions) is per-token and
    # rate-limited against third-party APIs, so we only enrich the top N
    # tokens by liquidity each cycle rather than every token fetched.
    if settings.enrichment_limit > 0:
        enrichment_candidates = sorted(
            all_ticks, key=lambda t: t.get("liquidity_usd", 0), reverse=True
        )[: settings.enrichment_limit]
        await asyncio.gather(*(enrich_tick(session, t) for t in enrichment_candidates))

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
            except Exception as e:
                log.error("poll_cycle_failed", error=str(e))

            elapsed = time.monotonic() - start
            sleep_for = max(0, settings.poll_interval_seconds - elapsed)
            await asyncio.sleep(sleep_for)


if __name__ == "__main__":
    asyncio.run(main())
