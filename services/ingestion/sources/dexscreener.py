"""
DEXScreener source adapter — this is the primary source for meme coins,
since most never get listed on centralized exchanges and live entirely
on-chain (Solana, BSC, Base, etc).

Docs: https://docs.dexscreener.com/api/reference
"""

import structlog
from aiohttp import ClientSession, ClientTimeout
from tenacity import retry, stop_after_attempt, wait_exponential

log = structlog.get_logger(__name__)

TIMEOUT = ClientTimeout(total=10)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def fetch_trending_pairs(session: ClientSession, base_url: str, chain: str) -> list[dict]:
    """
    Fetch trending/newest token pairs for a given chain.
    Returns a normalized list of tick dicts ready for the Redis stream.
    """
    # DEXScreener's search endpoint doubles as a "browse by chain" query
    # when given a broad query term; in production you'd combine this with
    # their token-boosts / latest-pairs endpoints for better coverage.
    url = f"{base_url}/dex/search"
    params = {"q": chain}

    async with session.get(url, params=params, timeout=TIMEOUT) as resp:
        resp.raise_for_status()
        data = await resp.json()

    pairs = data.get("pairs") or []
    normalized = []

    for pair in pairs:
        try:
            normalized.append(
                {
                    "token_id": f"{chain}:{pair['pairAddress']}",
                    "symbol": pair["baseToken"]["symbol"],
                    "name": pair["baseToken"]["name"],
                    "chain": chain,
                    "source": "dexscreener",
                    "price_usd": float(pair.get("priceUsd") or 0),
                    "volume_24h_usd": float((pair.get("volume") or {}).get("h24") or 0),
                    "liquidity_usd": float((pair.get("liquidity") or {}).get("usd") or 0),
                    "market_cap_usd": float(pair.get("fdv") or 0),
                }
            )
        except (KeyError, TypeError, ValueError) as e:
            log.warning("skipping_malformed_pair", error=str(e), chain=chain)
            continue

    log.info("dexscreener_fetch_complete", chain=chain, count=len(normalized))
    return normalized
