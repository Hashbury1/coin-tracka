import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from models import HealthResponse
from prometheus_client import Counter
from prometheus_fastapi_instrumentator import Instrumentator
from routers import coins
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import text

from db import engine

RATE_LIMIT_PER_MINUTE = os.getenv("RATE_LIMIT_PER_MINUTE", "60")
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:8080").split(",")

limiter = Limiter(key_func=get_remote_address, default_limits=[f"{RATE_LIMIT_PER_MINUTE}/minute"])

RATE_LIMIT_HITS = Counter(
    "api_rate_limit_exceeded_total",
    "Number of requests rejected for exceeding the per-client rate limit",
)

app = FastAPI(
    title="Meme Coin Volatility Tracker API",
    description="Ranks tokens by volatility/momentum/liquidity. Not financial advice.",
    version="0.1.0",
)

app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    RATE_LIMIT_HITS.inc()
    return _rate_limit_exceeded_handler(request, exc)


app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(coins.router)

Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    db_status = "ok"
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_status = "unreachable"
    return HealthResponse(status="ok", database=db_status)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Never leak stack traces / internals to clients
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})