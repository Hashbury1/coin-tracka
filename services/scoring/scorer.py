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


def composite_score(vol_score: float, mom_score: float, liq_score: float) -> float:
    total_weight = WEIGHT_VOLATILITY + WEIGHT_MOMENTUM + WEIGHT_LIQUIDITY
    raw = (
        vol_score * WEIGHT_VOLATILITY
        + mom_score * WEIGHT_MOMENTUM
        + liq_score * WEIGHT_LIQUIDITY
    )
    return round(raw / total_weight, 2)


def score_token(
    prices: list[float],
    volumes: list[float],
    liquidity_usd: float,
    min_liquidity_usd: float = 20_000,
) -> dict:
    """Convenience wrapper returning all four scores for a token's window."""
    v = volatility_score(prices)
    m = momentum_score(prices, volumes)
    l = liquidity_score(liquidity_usd, min_liquidity_usd)
    c = composite_score(v, m, l)
    return {
        "volatility_score": v,
        "momentum_score": m,
        "liquidity_score": l,
        "composite_score": c,
    }
