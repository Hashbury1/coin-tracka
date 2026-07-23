"""
Moralis adapter — EVM-chain (BSC, Ethereum) holder analytics. Birdeye
only covers Solana, so this fills the same "holder concentration" signal
for the other chains we track.

Docs: https://docs.moralis.io/web3-data-api/evm/reference/get-token-holders
Free tier: 40k requests/month at time of writing — plenty for enriching
only the top N tokens per cycle, not every token every cycle.
"""

import structlog
from aiohttp import ClientSession, ClientTimeout
from tenacity import retry, stop_after_attempt, wait_exponential

log = structlog.get_logger(__name__)

TIMEOUT = ClientTimeout(total=8)
BASE_URL = "https://deep-index.moralis.io/api/v2.2"

CHAIN_ID_MAP = {
    "bsc": "0x38",
    "ethereum": "0x1",
}


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=4))
async def fetch_holder_concentration(
    session: ClientSession, api_key: str, chain: str, token_address: str
) -> dict | None:
    """
    Fetch holder count and top-10 concentration for an EVM token.
    Returns None on failure/missing data/unsupported chain — this is a
    best-effort enrichment step, never allowed to break ingestion.
    """
    if not api_key or chain not in CHAIN_ID_MAP:
        return None

    chain_id = CHAIN_ID_MAP[chain]
    headers = {"X-API-Key": api_key, "accept": "application/json"}

    stats_url = f"{BASE_URL}/erc20/{token_address}/holders"
    try:
        async with session.get(
            stats_url, params={"chain": chain_id}, headers=headers, timeout=TIMEOUT
        ) as resp:
            if resp.status == 429:
                log.warning("moralis_rate_limited", token_address=token_address)
                return None
            resp.raise_for_status()
            stats = await resp.json()
    except Exception as e:  # noqa: BLE001
        log.warning("moralis_holder_stats_failed", token_address=token_address, error=str(e))
        return None

    holder_count = stats.get("totalHolders")
    if holder_count is None:
        return None

    top10_pct = await _fetch_top10_concentration(session, headers, chain_id, token_address)

    return {
        "holder_count": int(holder_count),
        "top10_concentration_pct": top10_pct,
    }


async def _fetch_top10_concentration(
    session: ClientSession,
    headers: dict,
    chain_id: str,
    token_address: str,
) -> float | None:
    """Fetches the top-10 holder list by balance and sums their share of supply."""
    url = f"{BASE_URL}/erc20/{token_address}/owners"
    params = {"chain": chain_id, "order": "DESC", "limit": 10}

    try:
        async with session.get(url, params=params, headers=headers, timeout=TIMEOUT) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
    except Exception as e:  # noqa: BLE001
        log.warning("moralis_owners_failed", token_address=token_address, error=str(e))
        return None

    owners = data.get("result") or []
    if not owners:
        return None

    total_pct = sum(float(o.get("percentage_relative_to_total_supply", 0) or 0) for o in owners)
    return round(total_pct, 2)