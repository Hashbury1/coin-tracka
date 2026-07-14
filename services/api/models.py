from pydantic import BaseModel, Field


class RankedToken(BaseModel):
    token_id: str
    symbol: str
    name: str
    chain: str
    price_usd: float
    volatility_score: float
    momentum_score: float
    liquidity_score: float
    composite_score: float = Field(..., description="0-100, higher = more volatile+momentum, liquidity-weighted")
    as_of: str


class RankedTokenResponse(BaseModel):
    count: int
    disclaimer: str = (
        "Rankings reflect statistical volatility and momentum, not price predictions. "
        "This is not financial advice."
    )
    results: list[RankedToken]


class HealthResponse(BaseModel):
    status: str
    database: str
