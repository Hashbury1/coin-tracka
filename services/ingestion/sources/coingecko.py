"""
CoinGecko source adapter — used for tokens that ARE listed (secondary signal,
useful for cross-checking price and for the more established meme coins
like DOGE, SHIB, PEPE).

Docs: https://docs.coingecko.com/reference/coins-markets
"""

import structlog
from aiohttp import ClientSession, ClientTimeout
from tenacity import retry, stop_after_attempt, wait_exponential

log = structlog.get_logger(__name__)

TIMEOUT = ClientTimeout(total=10)
BASE_URL = "https://api.coingecko.com/api/v3"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def fetch_meme_category(session: ClientSession, api_key: str = "") -> list[dict]:
    """
    Fetch all tokens in CoinGecko's 'meme-token' category, sorted by 24h volume.
    """
    url = f"{BASE_URL}/coins/markets"
    params = {
        "vs_currency": "usd",
        "category": "meme-token",
        "order": "volume_desc",
        "per_page": "100",
        "page": "1",
        "price_change_percentage": "1h,24h",
    }
    headers = {"x-cg-demo-api-key": api_key} if api_key else {}

    async with session.get(url, params=params, headers=headers, timeout=TIMEOUT) as resp:
        resp.raise_for_status()
        data = await resp.json()

    normalized = []
    for coin in data:
        try:
            normalized.append(
                {
                    "token_id": f"coingecko:{coin['id']}",
                    "symbol": coin["symbol"].upper(),
                    "name": coin["name"],
                    "chain": "multi",
                    "source": "coingecko",
                    "price_usd": float(coin.get("current_price") or 0),
                    "volume_24h_usd": float(coin.get("total_volume") or 0),
                    "liquidity_usd": float(coin.get("total_volume") or 0),  # proxy
                    "market_cap_usd": float(coin.get("market_cap") or 0),
                }
            )
        except (KeyError, TypeError, ValueError) as e:
            log.warning("skipping_malformed_coin", error=str(e))
            continue

    log.info("coingecko_fetch_complete", count=len(normalized))
    return normalized
