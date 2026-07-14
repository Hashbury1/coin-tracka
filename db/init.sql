-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Master token registry
CREATE TABLE IF NOT EXISTS tokens (
    token_id        TEXT PRIMARY KEY,      -- e.g. "solana:dexpairaddress" or coingecko id
    symbol          TEXT NOT NULL,
    name            TEXT NOT NULL,
    chain           TEXT NOT NULL,
    source          TEXT NOT NULL,          -- 'coingecko' | 'dexscreener'
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Raw price/volume ticks (append-only, high write volume)
CREATE TABLE IF NOT EXISTS ticks (
    time            TIMESTAMPTZ NOT NULL,
    token_id        TEXT NOT NULL REFERENCES tokens(token_id),
    price_usd       DOUBLE PRECISION NOT NULL,
    volume_24h_usd  DOUBLE PRECISION,
    liquidity_usd   DOUBLE PRECISION,
    market_cap_usd  DOUBLE PRECISION,
    PRIMARY KEY (time, token_id)
);

SELECT create_hypertable('ticks', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_ticks_token_time ON ticks (token_id, time DESC);

-- Computed scores, one row per token per scoring run
CREATE TABLE IF NOT EXISTS scores (
    time                TIMESTAMPTZ NOT NULL,
    token_id            TEXT NOT NULL REFERENCES tokens(token_id),
    volatility_score    DOUBLE PRECISION NOT NULL,
    momentum_score      DOUBLE PRECISION NOT NULL,
    liquidity_score     DOUBLE PRECISION NOT NULL,
    composite_score     DOUBLE PRECISION NOT NULL,
    window_label        TEXT NOT NULL,      -- '5m' | '1h' | '24h'
    PRIMARY KEY (time, token_id, window_label)
);

SELECT create_hypertable('scores', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_scores_composite ON scores (window_label, time DESC, composite_score DESC);

-- Retention: keep raw ticks 30 days, scores 90 days (tune for production)
SELECT add_retention_policy('ticks', INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_retention_policy('scores', INTERVAL '90 days', if_not_exists => TRUE);
