# Meme Coin Volatility Tracker

A production-style, self-hosted system that ingests real-time crypto market data,
scores tokens on volatility/momentum/liquidity, and surfaces a ranked dashboard.

> **Not financial advice.** This project ranks tokens by statistical volatility and
> momentum signals. It does not predict price direction and should never be
> presented to end users as investment advice. This disclaimer is intentional —
> it's part of the design, and worth mentioning in an interview.

## Architecture

```
                 ┌──────────────┐
                 │  CoinGecko   │
                 │  DEXScreener │──┐
                 └──────────────┘  │
                                    ▼
                          ┌───────────────────┐
                          │  Ingestion Worker  │  (async polling, rate-limit aware)
                          │  services/ingestion│
                          └─────────┬──────────┘
                                    │ publishes raw ticks
                                    ▼
                          ┌───────────────────┐
                          │   Redis Streams    │
                          └─────────┬──────────┘
                                    │ consumes
                                    ▼
                          ┌───────────────────┐
                          │   Scoring Worker    │  (volatility / momentum / liquidity)
                          │  services/scoring    │
                          └─────────┬──────────┘
                                    │ writes
                                    ▼
                          ┌───────────────────┐
                          │  TimescaleDB        │  (time-series hypertables)
                          └─────────┬──────────┘
                                    │ reads
                                    ▼
                          ┌───────────────────┐
                          │   FastAPI            │  (public REST API)
                          │  services/api         │
                          └─────────┬──────────┘
                                    │
                                    ▼
                          ┌───────────────────┐
                          │  Frontend Dashboard  │
                          │  frontend/            │
                          └───────────────────┘
```

## Tech stack

| Layer          | Choice                          |
|----------------|----------------------------------|
| Ingestion      | Python 3.12, asyncio, aiohttp    |
| Queue          | Redis Streams                    |
| Scoring engine | Python, pandas, numpy            |
| Database       | TimescaleDB (Postgres 16)        |
| API            | FastAPI, SQLAlchemy (async)      |
| Frontend       | Vanilla JS + Chart.js (no build step, deploys anywhere) |
| Containers     | Docker / Docker Compose (local)  |
| CI/CD          | GitHub Actions                   |
| IaC            | Terraform (stub, cloud-agnostic layout) |

## Repo layout

```
meme-coin-tracker/
├── services/
│   ├── ingestion/   # polls external APIs, pushes raw ticks to Redis Streams
│   ├── scoring/      # consumes ticks, computes scores, writes to TimescaleDB
│   └── api/           # FastAPI app serving ranked coin data
├── db/
│   └── init.sql       # TimescaleDB schema + hypertables
├── frontend/           # static dashboard
├── infra/terraform/    # infra-as-code stub for cloud deploy
├── .github/workflows/  # CI/CD pipeline
├── tests/               # unit tests
└── docker-compose.yml
```

## Local setup

```bash
cp .env.example .env
# add a free CoinGecko API key (or leave blank to use the public rate-limited tier)
docker compose up --build
```

Services after startup:
- API: http://localhost:8000/docs (Swagger UI)
- Frontend: http://localhost:8080
- TimescaleDB: localhost:5433 (mapped from container port 5432 — 5432 is remapped
  to avoid clashing with a local Postgres install; internal container-to-container
  traffic still uses port 5432 via the `timescaledb` hostname, unaffected by this)
- Redis: localhost:6379

## Scoring model

For each token, over rolling windows (5m / 1h / 24h):

- **Volatility score** — annualized stddev of log returns
- **Momentum score** — rate of change + volume-spike ratio (current volume vs 24h average)
- **Liquidity filter** — tokens below a liquidity floor are excluded (rug-pull risk mitigation)
- **Composite score** — weighted, normalized 0–100, weights are configurable in `services/scoring/scorer.py`

The model is intentionally simple and explainable rather than a black box — this
is a deliberate design choice, and a good thing to walk through in an interview.

## Roadmap (build order used for this project)

1. ✅ Ingestion worker → Redis Streams (mocked source first, then real APIs)
2. ✅ Scoring worker → TimescaleDB
3. ✅ FastAPI read layer
4. ✅ Dashboard
5. ✅ Tests + GitHub Actions CI (unit tests + real docker-compose smoke test)
6. ✅ Stateless scoring worker (reads its rolling window from TimescaleDB
   each cycle instead of an in-memory buffer — safe to restart or scale
   to N replicas with zero coordination)
7. ⬜ Terraform apply to a real cloud target (AWS/GCP) + CD stage
8. ⬜ Observability: Prometheus + Grafana + alerting
9. ⬜ Social sentiment signal (Reddit/Twitter mention velocity)

## Security notes

- API keys are never committed; `.env` is gitignored, secrets are injected via
  environment variables (swap for AWS Secrets Manager / Vault in production).
- The public API is rate-limited per client IP (see `services/api/main.py`).
- Dependency and container image scanning run in CI (see workflow file).
- All external HTTP calls have timeouts and retry/backoff — a single flaky
  upstream API cannot take the ingestion worker down.