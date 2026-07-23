"""
Scoring engine — pure functions, no I/O, so this is trivially unit-testable
(see tests/test_scorer.py). Keeping the math separate from the Redis/DB
plumbing in worker.py is a deliberate separation-of-concerns choice worth
mentioning in an interview.
"""

import math
import os

import numpy as np

WEIGHT_VOLATILITY = float(os.getenv("WEIGHT_VOLATILITY", "0.4"))
WEIGHT_MOMENTUM = float(os.getenv("WEIGHT_MOMENTUM", "0.4"))
WEIGHT_LIQUIDITY = float(os.getenv("WEIGHT_LIQUIDITY", "0.2"))
# Both default to 0 so composite_score behaves exactly as before unless
# you explicitly opt in by setting these in .env once enrichment data
# (holder concentration / social mentions) is flowing.
WEIGHT_HOLDER_SAFETY = float(os.getenv("WEIGHT_HOLDER_SAFETY", "0.0"))
WEIGHT_SOCIAL = float(os.getenv("WEIGHT_SOCIAL", "0.0"))


def log_returns(prices: list[float]) -> np.ndarray:
    """Compute log returns from a price series. Needs at least 2 points."""
    arr = np.array(prices, dtype=float)
    arr = arr[arr > 0]  # guard against bad zero/negative price data
    if len(arr) < 2:
        return np.array([])
    return np.diff(np.log(arr))


def volatility_score(prices: list[float]) -> float:
    """
    Stddev of log returns, scaled to a 0-100 score via a soft cap.
    Higher = more volatile. This is the core "meme coin energy" signal.
    """
    returns = log_returns(prices)
    if len(returns) == 0:
        return 0.0
    stddev = float(np.std(returns))
    # Soft cap: 10% stddev per tick maps to ~100. tanh keeps it bounded.
    return round(100 * math.tanh(stddev / 0.10), 2)


def momentum_score(prices: list[float], volumes: list[float]) -> float:
    """
    Combines price rate-of-change with a volume-spike ratio
    (current volume vs the average of the window). Rewards tokens that
    are moving AND being traded, not just noisy on low volume.
    """
    if len(prices) < 2:
        return 0.0

    roc = (prices[-1] - prices[0]) / prices[0] if prices[0] else 0.0
    roc_component = 50 * math.tanh(roc / 0.20)  # 20% move -> large swing

    volume_component = 0.0
    if volumes and len(volumes) >= 2:
        avg_vol = float(np.mean(volumes[:-1])) or 1.0
        spike_ratio = volumes[-1] / avg_vol
        volume_component = 50 * math.tanh((spike_ratio - 1) / 2)

    return round(max(0.0, roc_component + volume_component), 2)


def liquidity_score(liquidity_usd: float, min_liquidity_usd: float = 20_000) -> float:
    """
    Normalizes liquidity into a 0-100 confidence score. This is a RISK
    signal, not a "goodness" signal - a token with low liquidity gets a
    low score here, pulling its composite score down (rug-pull mitigation).
    """
    if liquidity_usd <= 0:
        return 0.0
    if liquidity_usd < min_liquidity_usd:
        return round(20 * (liquidity_usd / min_liquidity_usd), 2)
    # log-scale above the floor, capped at 100
    return round(min(100.0, 40 + 15 * math.log10(liquidity_usd / min_liquidity_usd + 1)), 2)


def holder_safety_score(holder_count: int | None, top10_concentration_pct: float | None) -> float | None:
    """
    Risk signal, same spirit as liquidity_score: high concentration in a
    handful of wallets means a small group can dump on everyone else at
    any time, regardless of how good the price action looks. Returns None
    (rather than a fake neutral score) when no holder data was fetched for
    this token, so composite_score can correctly exclude it from the
    weighted average instead of silently treating "unknown" as "safe".
    """
    if holder_count is None and top10_concentration_pct is None:
        return None

    components = []

    if top10_concentration_pct is not None:
        # e.g. top 10 wallets holding 80% -> score of 20 (risky);
        # holding 10% -> score of 90 (broadly distributed, safer)
        components.append(max(0.0, 100 - top10_concentration_pct))

    if holder_count is not None and holder_count > 0:
        # Diminishing-returns log scale: 10 holders -> ~20, 1000 -> ~60, 100k -> ~100
        components.append(min(100.0, 20 * math.log10(holder_count + 1)))

    if not components:
        return None
    return round(sum(components) / len(components), 2)


def social_score(mentions_1h: int | None) -> float | None:
    """
    Social mention velocity as a buzz signal. Meme coins are frequently
    driven more by social momentum than by any on-chain fundamental, so
    this is deliberately kept as a separate, optional dimension rather
    than folded into momentum_score - it only reflects volume of chatter,
    not whether that chatter is positive or negative.
    """
    if mentions_1h is None:
        return None
    return round(100 * math.tanh(mentions_1h / 200), 2)


def composite_score(
    vol_score: float,
    mom_score: float,
    liq_score: float,
    holder_score: float | None = None,
    buzz_score: float | None = None,
) -> float:
    """
    Weighted average across whichever dimensions actually have data.
    holder_score/buzz_score are None when no enrichment data was fetched
    for a token (e.g. Birdeye/Moralis/X keys not configured, or the token
    fell outside the per-cycle enrichment limit) - in that case their
    weights are excluded from the denominator entirely, rather than
    treating a missing signal as a zero and unfairly dragging the score down.
    """
    weighted_sum = vol_score * WEIGHT_VOLATILITY + mom_score * WEIGHT_MOMENTUM + liq_score * WEIGHT_LIQUIDITY
    total_weight = WEIGHT_VOLATILITY + WEIGHT_MOMENTUM + WEIGHT_LIQUIDITY

    if holder_score is not None and WEIGHT_HOLDER_SAFETY > 0:
        weighted_sum += holder_score * WEIGHT_HOLDER_SAFETY
        total_weight += WEIGHT_HOLDER_SAFETY

    if buzz_score is not None and WEIGHT_SOCIAL > 0:
        weighted_sum += buzz_score * WEIGHT_SOCIAL
        total_weight += WEIGHT_SOCIAL

    if total_weight == 0:
        return 0.0
    return round(weighted_sum / total_weight, 2)


def score_token(
    prices: list[float],
    volumes: list[float],
    liquidity_usd: float,
    min_liquidity_usd: float = 20_000,
    holder_count: int | None = None,
    top10_concentration_pct: float | None = None,
    social_mentions_1h: int | None = None,
) -> dict:
    """Convenience wrapper returning every score dimension for a token's window."""
    v = volatility_score(prices)
    m = momentum_score(prices, volumes)
    l = liquidity_score(liquidity_usd, min_liquidity_usd)
    h = holder_safety_score(holder_count, top10_concentration_pct)
    s = social_score(social_mentions_1h)
    c = composite_score(v, m, l, h, s)
    return {
        "volatility_score": v,
        "momentum_score": m,
        "liquidity_score": l,
        "holder_safety_score": h,
        "social_score": s,
        "composite_score": c,
    }