from fastapi import APIRouter, Depends, Query
from models import RankedToken, RankedTokenResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_session

router = APIRouter(prefix="/api/v1/coins", tags=["coins"])

LATEST_SCORES_QUERY = text(
    """
    SELECT DISTINCT ON (s.token_id)
        s.token_id, t.symbol, t.name, t.chain,
        s.volatility_score, s.momentum_score, s.liquidity_score, s.composite_score,
        s.time AS as_of,
        latest_tick.price_usd
    FROM scores s
    JOIN tokens t ON t.token_id = s.token_id
    JOIN LATERAL (
        SELECT price_usd FROM ticks
        WHERE ticks.token_id = s.token_id
        ORDER BY time DESC LIMIT 1
    ) latest_tick ON true
    WHERE s.composite_score >= :min_score
    ORDER BY s.token_id, s.time DESC
    """
)


@router.get("/ranked", response_model=RankedTokenResponse)
async def get_ranked_coins(
    limit: int = Query(default=20, le=100),
    min_score: float = Query(default=0, ge=0, le=100),
    session: AsyncSession = Depends(get_session),
):
    """
    Returns tokens ranked by composite score (volatility + momentum,
    liquidity-weighted), most recent scoring run only, highest score first.
    """
    rows = (await session.execute(LATEST_SCORES_QUERY, {"min_score": min_score})).mappings().all()
    rows_sorted = sorted(rows, key=lambda r: r["composite_score"], reverse=True)[:limit]

    results = [
        RankedToken(
            token_id=r["token_id"],
            symbol=r["symbol"],
            name=r["name"],
            chain=r["chain"],
            price_usd=r["price_usd"],
            volatility_score=r["volatility_score"],
            momentum_score=r["momentum_score"],
            liquidity_score=r["liquidity_score"],
            composite_score=r["composite_score"],
            as_of=r["as_of"].isoformat(),
        )
        for r in rows_sorted
    ]

    return RankedTokenResponse(count=len(results), results=results)


@router.get("/{token_id:path}/history")
async def get_token_history(token_id: str, hours: int = 24, session: AsyncSession = Depends(get_session)):
    """Returns raw price history for a single token — powers the dashboard chart."""
    query = text(
        """
        SELECT time, price_usd, volume_24h_usd
        FROM ticks
        WHERE token_id = :token_id AND time > now() - (:hours || ' hours')::interval
        ORDER BY time ASC
        """
    )
    rows = (await session.execute(query, {"token_id": token_id, "hours": hours})).mappings().all()
    return {
        "token_id": token_id,
        "points": [
            {"time": r["time"].isoformat(), "price_usd": r["price_usd"], "volume": r["volume_24h_usd"]}
            for r in rows
        ],
    }
