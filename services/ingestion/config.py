import os
from dataclasses import dataclass, field


@dataclass
class Settings:
    redis_host: str = os.getenv("REDIS_HOST", "localhost")
    redis_port: int = int(os.getenv("REDIS_PORT", "6379"))
    stream_name: str = os.getenv("REDIS_STREAM_NAME", "raw_ticks")

    coingecko_api_key: str = os.getenv("COINGECKO_API_KEY", "")
    dexscreener_base_url: str = os.getenv(
        "DEXSCREENER_BASE_URL", "https://api.dexscreener.com/latest"
    )

    poll_interval_seconds: int = int(os.getenv("POLL_INTERVAL_SECONDS", "30"))
    tracked_chains: list[str] = field(
        default_factory=lambda: os.getenv("TRACKED_CHAINS", "solana,bsc").split(",")
    )
    min_liquidity_usd: float = float(os.getenv("MIN_LIQUIDITY_USD", "20000"))

    # --- Enrichment sources (holder concentration + social buzz) ---
    # All optional: if a key is blank, that enrichment step is skipped
    # entirely and scoring falls back to price/volume/liquidity signals.
    birdeye_api_key: str = os.getenv("BIRDEYE_API_KEY", "")
    moralis_api_key: str = os.getenv("MORALIS_API_KEY", "")
    twitter_bearer_token: str = os.getenv("TWITTER_BEARER_TOKEN", "")

    # Enrichment calls are per-token and rate-limited, so we only enrich
    # the top N tokens by liquidity each cycle rather than every token.
    enrichment_limit: int = int(os.getenv("ENRICHMENT_LIMIT", "15"))


settings = Settings()