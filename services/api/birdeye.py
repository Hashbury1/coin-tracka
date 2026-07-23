"""
Birdeye adapter — Solana-specific on-chain analytics. Used to pull holder
concentration, the single strongest available rug-pull signal: if a
handful of wallets hold most of the supply, they can dump on retail buyers
at any moment regardless of how "hot" the token looks on price charts.

Docs: https://docs.birdeye.so/reference/get_defi-token-overview
Free tier requires an API key (sign up at birdeye.so) but has no cost.
"""

import structlog
from aiohttp import ClientSession, ClientTimeout
from tenacity import retry, stop_after_attempt, wait_exponential

log = structlog.get_logger(__name__)

TIMEOUT = ClientTimeout(total=8)
BASE_URL = "https://public-api.birdeye.so"


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=4))
async def fetch_token_overview(session: ClientSession, api_key: str, token_address: str) -> dict | None:
    """
    Fetch holder count and concentration for a single Solana token address.
    Returns None on failure or missing data rather than raising, since this
    is a best-effort enrichment step that shouldn't break ingestion if
    Birdeye is down or the key is missing/invalid.
    """
    if not api_key:
        return None

    url = f"{BASE_URL}/defi/token_overview"
    params = {"address": token_address}
    headers = {"X-API-KEY": api_key, "x-chain": "solana"}

    try:
        async with session.get(url, params=params, headers=headers, timeout=TIMEOUT) as resp:
            if resp.status == 429:
                log.warning("birdeye_rate_limited", token_address=token_address)
                return None
            resp.raise_for_status()
            data = await resp.json()
    except Exception as e:  # noqa: BLE001 - enrichment failure should never break ingestion
        log.warning("birdeye_fetch_failed", token_address=token_address, error=str(e))
        return None

    payload = (data or {}).get("data") or {}
    holder_count = payload.get("holder")
    if holder_count is None:
        return None

    top10_pct = await _fetch_top10_concentration(session, api_key, token_address)

    return {
        "holder_count": int(holder_count),
        "top10_concentration_pct": top10_pct,
    }


async def _fetch_top10_concentration(
    session: ClientSession, api_key: str, token_address: str
) -> float | None:
    """
    Fetches the top holders list and sums the top 10's share of supply.
    Separate call from the overview endpoint since Birdeye splits these —
    kept as its own function so a failure here doesn't lose the holder
    count we already got.
    """
    url = f"{BASE_URL}/defi/token_holder"
    params = {"address": token_address, "offset": 0, "limit": 10}
    headers = {"X-API-KEY": api_key, "x-chain": "solana"}

    try:
        async with session.get(url, params=params, headers=headers, timeout=TIMEOUT) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
    except Exception as e:  # noqa: BLE001
        log.warning("birdeye_holder_list_failed", token_address=token_address, error=str(e))
        return None

    items = ((data or {}).get("data") or {}).get("items") or []
    if not items:
        return None

    total_pct = sum(float(h.get("percentage", 0) or 0) for h in items)
    return round(total_pct, 2)