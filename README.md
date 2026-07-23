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
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000 (login: value of `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` in `.env`, defaults to `admin`/`admin`)

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
8. ✅ Observability: Prometheus + Grafana + alert rules
9. ⬜ Social sentiment signal (Reddit/Twitter mention velocity)

## Enrichment sources (holder concentration + social buzz)

Beyond price/volume/liquidity, the pipeline can optionally enrich the top
N tokens by liquidity each cycle (`ENRICHMENT_LIMIT` in `.env`, default 15)
with two additional signals:

| Source | Chain coverage | Signal | Key required |
|---|---|---|---|
| **Birdeye** | Solana | Holder count + top-10 wallet concentration | Free tier at birdeye.so |
| **Moralis** | BSC, Ethereum | Same, via `/erc20/{address}/holders` and `/owners` | Free tier (40k req/mo) at moralis.io |
| **X (Twitter) API** | All | Mention velocity (cashtag search, last hour) | **Free tier has no search access** — requires the paid Basic tier or above |

All three are fully optional — leave the corresponding key blank in `.env`
and that adapter becomes a documented no-op (`services/ingestion/sources/{birdeye,moralis,twitter}.py`),
returning `None` rather than raising, so ingestion runs exactly as before.

Holder concentration feeds a new `holder_safety_score` (high concentration
in a few wallets = low score = higher rug-pull risk), and mention count
feeds `social_score`. Both default to `WEIGHT_HOLDER_SAFETY=0` /
`WEIGHT_SOCIAL=0` in `.env` — meaning they're computed and returned by the
API whenever data is available, but excluded from `composite_score` until
you deliberately opt in by raising those weights above 0. This keeps the
existing volatility/momentum/liquidity behavior unchanged by default while
making the new signals easy to turn on.

## Observability

Every service exposes Prometheus metrics; Grafana is pre-provisioned with a
dashboard on first boot (no manual setup needed).

| Service   | Metrics endpoint                | What it tracks |
|-----------|----------------------------------|----------------|
| API       | `http://localhost:8000/metrics`  | Request rate/latency by route and status (via `prometheus-fastapi-instrumentator`), rate-limit rejections |
| Ingestion | `http://localhost:9101/metrics`  | Ticks fetched/pushed, fetch errors by source, low-liquidity filter rate, poll cycle duration |
| Scoring   | `http://localhost:9102/metrics`  | Tokens scored, cycle duration, DB connect retries, seconds since last successful cycle |

Open **http://localhost:3000** (Grafana) and the "Meme Coin Tracker — System
Health" dashboard is already there under the default org, pulling from the
auto-provisioned Prometheus datasource.

Alert rules live in `infra/prometheus/alerts.yml` and are loaded by
Prometheus automatically. They cover: any service being unreachable
(`ServiceDown`), ingestion producing no ticks for 5 minutes, scoring going
stale for 3+ minutes (the metric end users would actually notice — stale
rankings), elevated upstream fetch error rates, API 5xx rate above 5%, and
repeated DB connection retries. These are visible under **Alerts** in
Prometheus's own UI (http://localhost:9090/alerts) — wiring them to a real
notification channel (Slack/PagerDuty via Alertmanager) is a natural next
step for a real production deployment, intentionally left out here to keep
the local setup dependency-light.

## Known operational caveat

On some Docker Engine versions (observed on Docker Engine + Arch Linux,
outside Docker Desktop), `docker compose restart <service>` does not
reliably refresh that container's embedded DNS resolution for other
services on the same network — you may see `Name or service not known`
errors for a service that was working fine moments earlier. This isn't a
bug in this project; it's Docker's networking layer not always
re-registering DNS state on a lightweight `restart`. The scoring worker's
retry-with-backoff (`services/scoring/worker.py::create_db_pool`) and
Compose's `restart: unless-stopped` policy exist specifically to absorb
this class of transient failure in production, and are why the container
recovers on its own after a few attempts. If you need to force a clean
reconnect immediately during local dev, use:

```bash
docker compose up -d --force-recreate <service>
```

instead of `docker compose restart <service>` — this fully recreates the
container's network attachment rather than just restarting its process.

## Security notes

- API keys are never committed; `.env` is gitignored, secrets are injected via
  environment variables (swap for AWS Secrets Manager / Vault in production).
- The public API is rate-limited per client IP (see `services/api/main.py`).
- Dependency and container image scanning run in CI (see workflow file).
- All external HTTP calls have timeouts and retry/backoff — a single flaky
  upstream API cannot take the ingestion worker down.