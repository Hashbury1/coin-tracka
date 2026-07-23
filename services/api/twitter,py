"""
X (Twitter) API adapter — social mention velocity as a "buzz" signal.

IMPORTANT: X's free API tier has no search access at all. The recent-search
endpoint used here requires at minimum the paid Basic tier
(https://developer.x.com/en/products/x-api — pricing changes over time,
check current tiers). Until a paid bearer token is configured, this
adapter is a documented no-op: enrich_tick will simply skip the social
signal and scoring falls back to volatility+momentum+liquidity only.

Docs: https://docs.x.com/x-api/posts/recent-search
"""

import structlog
from aiohttp import ClientSession, ClientTimeout
from tenacity import retry, stop_after_attempt, wait_exponential

log = structlog.get_logger(__name__)

TIMEOUT = ClientTimeout(total=8)
BASE_URL = "https://api.x.com/2/tweets/counts/recent"


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=4))
async def fetch_mention_count(session: ClientSession, bearer_token: str, symbol: str) -> int | None:
    """
    Fetch how many posts mentioned this token's symbol/cashtag in the last
    hour. Returns None if no bearer token is configured, the request fails,
    or the account doesn't have search access (common on free tier) —
    this must never raise and break ingestion over a missing/invalid key.
    """
    if not bearer_token:
        return None

    headers = {"Authorization": f"Bearer {bearer_token}"}
    # Cashtag search (e.g. "$DOGE") is far more precise than a bare keyword
    # search, since meme coin symbols frequently collide with common words.
    params = {"query": f"${symbol} -is:retweet", "granularity": "hour"}

    try:
        async with session.get(BASE_URL, params=params, headers=headers, timeout=TIMEOUT) as resp:
            if resp.status == 403:
                log.warning(
                    "twitter_api_access_denied",
                    symbol=symbol,
                    hint="Free tier has no search access — requires paid Basic tier or above",
                )
                return None
            if resp.status == 429:
                log.warning("twitter_rate_limited", symbol=symbol)
                return None
            resp.raise_for_status()
            data = await resp.json()
    except Exception as e:  # noqa: BLE001
        log.warning("twitter_fetch_failed", symbol=symbol, error=str(e))
        return None

    buckets = data.get("data") or []
    if not buckets:
        return 0

    # Most recent hourly bucket
    return int(buckets[-1].get("tweet_count", 0))