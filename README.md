# financial-data-etl

Full-stack financial data platform: batch ETL + real-time WebSocket streaming + medallion DWH (bronze/silver/gold) on BigQuery + React terminal UI.

Two products share the same ingest layer:

1. **Operational dashboard** at `/financial/` — live OHLCV chart (TradingView WS) + derived metrics.
2. **Analíticas Avanzadas** at `/financial/avanzadas/` — daily outlier detector powered by a three-layer z-score stack (`z_intra` / `z_cross` / `z_of_z`) computed in BigQuery by DBT.

Dockerized. Runs on PostgreSQL (OLTP) + S3 (bronze) + BigQuery (silver/gold). Currently deployed on VPS, in active migration to AWS (ECS Fargate + RDS + Lambda-orchestrated ETL).

**Live:** [leonardovila.com/financial](https://leonardovila.com/financial/)

---

## Architecture Overview

```
┌───────────────────────── INGEST (batch + stream) ────────────────────────────┐
│                                                                              │
│  catalog.json ──► TradingView WS pool (6 conn) ──► PostgreSQL (tv_candles,   │
│  (~50 symbols)     asyncio.Queue                  fundamentals, *_1d)        │
│                                                                              │
│  Browser WS ──► /ws/live/{symbol} ──► seed (DB) + edge (TV live)             │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────── BRONZE EXPORT (etl_extract/) ────────────────────────┐
│                                                                              │
│  PostgreSQL ──► extract_to_s3.py ──► s3://.../bronze/{table}/dt=YYYY-MM-DD/  │
│                 (Parquet + snapshot manifest)                                │
│                                                                              │
│  S3 bronze ──► load_to_bigquery.py ──► BigQuery raw tables (silver source)   │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌───────────────────── ANALYTICS — DBT MEDALLION (financial_dwh/) ─────────────┐
│                                                                              │
│  staging/       → typed, renamed, tested versions of bronze                  │
│  intermediate/  → returns, rolling vol, SMA gaps, 52w extremes               │
│  marts/         → dim_date, dim_asset, fact_ohlcv, fact_fundamentals,        │
│                   fact_derived_metrics (+ three-layer z-scores)              │
│                                                                              │
│  Gold serves:   z_intra (252d history per symbol)                            │
│                 z_cross (cross-section snapshot today)                       │
│                 z_of_z  (anomaly of anomaly)                                 │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌───────────────────────── SERVING — FastAPI + React ──────────────────────────┐
│                                                                              │
│  FastAPI  /ohlcv, /fundamentals, /performance, /volatility, /volume  (RDS)   │
│           /ws/live/{symbol}                                          (RDS+TV)│
│           /analytics/anomalies, /analytics/metrics                  (BigQuery│
│                                                                       + TTL) │
│                                                                              │
│  React    /financial/            → Dashboard (chart + metrics + WS)          │
│           /financial/avanzadas/  → Ranking boards + dense multi-metric table │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Directory Structure

```
financial-data-etl/
├── Dockerfile                        # Multi-stage backend image (API + ETL)
├── docker-compose.yml                # postgres + api + etl + frontend
├── apunte_sistema.md                 # High-level system overview (ES)
│
├── financial_data_etl/               # Python package (ingest + API)
│   ├── main_runner.py                # Batch ETL orchestrator (7 stages)
│   ├── scraping_pipeline/            # TradingView WS client + parsers
│   ├── derived_metrics/              # performance / volatility / volume runners
│   ├── storage/                      # DB adapter (PG / SQLite), row builders
│   ├── api/
│   │   ├── app.py                    # REST + WS endpoints
│   │   ├── bq_analytics.py           # BigQuery client (lazy singleton + TTL cache)
│   │   ├── live_seed.py              # Cold-start WS seed
│   │   ├── live_state.py             # 258-row in-memory DataFrame
│   │   ├── live_compute.py           # Pure metric math (<1ms)
│   │   └── live_session_manager.py   # Per-subscriber TV session
│   ├── universe/                     # Index composition refresh
│   └── observability/
│       └── run_context.py            # Structured JSON logging
│
├── etl_extract/                      # RDS → S3 → BigQuery bridge
│   ├── extract-config.json           # Per-table CDC config
│   ├── extract_to_s3.py              # RDS → Parquet partitioned by ingest date
│   ├── load_to_bigquery.py           # S3 → BigQuery external/native load
│   └── backfill_derived_metrics.py   # One-shot rebuild helper
│
├── financial_dwh/                    # DBT project (BigQuery)
│   ├── dbt_project.yml
│   ├── packages.yml                  # dbt_utils
│   ├── models/
│   │   ├── staging/                  # stg_tv_candles, stg_fundamentals, ...
│   │   ├── intermediate/             # int_returns, int_rolling_vol, int_sma_gaps
│   │   └── marts/                    # dim_* + fact_* (Kimball star schema)
│   ├── macros/
│   ├── tests/
│   └── seeds/
│
├── aws/                              # IaC scaffolding (JSON definitions)
│   ├── ecs/                          # api + etl + utility task definitions
│   ├── lambda/                       # EventBridge-triggered ETL launcher
│   ├── eventbridge/
│   ├── s3/                           # bronze bucket + lifecycle rules
│   ├── cloudfront/
│   └── github-actions/               # CI/CD workflows
│
├── gcp/
│   ├── bigquery/                     # Dataset/table DDL
│   └── bigquery-sa-key.json          # Service account key (gitignored)
│
├── frontend/                         # React 19 + Vite 8 + TS + Tailwind 4
│   ├── Dockerfile                    # Multi-stage: npm build → Nginx
│   └── src/
│       ├── App.tsx                   # Mini-router by window.location.pathname
│       ├── layouts/
│       │   ├── Dashboard.tsx                 # /financial/
│       │   └── AdvancedAnalyticsPage.tsx     # /financial/avanzadas/
│       ├── components/
│       │   ├── Chart.tsx                     # Lightweight Charts v5
│       │   ├── TickStack.tsx                 # Live tick feed
│       │   ├── MetricsGrid.tsx               # Perf / Vol / Volume cards
│       │   ├── MetricCard.tsx
│       │   ├── FundamentalsBar.tsx
│       │   ├── SymbolSearch.tsx
│       │   ├── StatusBar.tsx
│       │   ├── InfoTooltip.tsx               # Viewport-aware click-popover
│       │   ├── RankingBoard.tsx              # Per-metric outlier podium
│       │   └── AdvancedAnalytics.tsx         # Dense multi-metric table
│       ├── store/wsStore.ts                  # Zustand WS state
│       ├── lib/formatters.ts
│       └── types/market.ts
│
└── catalog.json                      # Symbol universe with provider mappings
```

---

## Quick Start (Docker)

### Requirements

- Docker + Docker Compose
- (For analytics) GCP service account key with BigQuery read access

### 1. Configure environment

```bash
git clone https://github.com/leonardovila/financial-data-etl.git
cd financial-data-etl
cp .env.example .env
# Edit .env with PostgreSQL credentials + GCP vars
```

`.env` essentials:
```
POSTGRES_USER=forge
POSTGRES_PASSWORD=your_password_here
POSTGRES_DB=financial_data
DATABASE_URL=postgresql://forge:your_password_here@postgres:5432/financial_data

# Analytics (Gold layer)
GCP_PROJECT=your-gcp-project
GOOGLE_APPLICATION_CREDENTIALS=/app/gcp/bigquery-sa-key.json
```

### 2. Start the stack

```bash
docker compose up -d          # postgres + api + frontend
```

Services:
- **PostgreSQL 16** `:5432` (persisted in `pg_data` volume)
- **FastAPI** `:8000` (REST + WS + analytics)
- **Nginx + React** `:3000` (SPA)

### 3. Run Batch ETL

```bash
docker compose run etl --assets NVDA                # Single asset test
docker compose run etl --dji                        # Dow Jones (30 symbols)
docker compose run etl --spx --ndx                  # S&P 500 + Nasdaq 100
```

### 4. Bronze export + DBT run (manual, pre-Lambda)

```bash
# Dump RDS → S3 Parquet (bronze)
python etl_extract/extract_to_s3.py

# Load bronze → BigQuery raw
python etl_extract/load_to_bigquery.py

# Transform silver + gold
cd financial_dwh && dbt deps && dbt run && dbt test
```

### 5. Stop everything

```bash
docker compose down            # Stops containers (data persists)
docker compose down -v         # Stops AND deletes PostgreSQL data
```

### Local development (without Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .

# With PostgreSQL + BigQuery analytics:
DATABASE_URL=postgresql://user:pass@localhost:5432/financial_data \
GCP_PROJECT=your-project \
GOOGLE_APPLICATION_CREDENTIALS=./gcp/bigquery-sa-key.json \
  uvicorn financial_data_etl.api.app:app --port 8000

# Frontend
cd frontend && npm install && npm run dev    # → http://localhost:5173
```

Vite dev proxy maps `/symbols`, `/ohlcv`, `/ws`, `/analytics` → `localhost:8000`.

---

## Batch ETL Pipeline (main_runner.py)

Seven sequential stages, stage 6 parallelized:

| Stage | Name | Action |
|-------|------|--------|
| 1 | Universe Resolution | Load catalog.json → symbol list |
| 2 | Increment Plan | Query DB → determine n_candles per symbol (bootstrap=4500, catchup=3-25) |
| 3 | WebSocket Scraping | 6 persistent TradingView connections drain asyncio.Queue. Multiplexed OHLCV + fundamentals. 3-layer timeout (recv=30s, send=10s, symbol=60s) |
| 4 | OHLCV Persistence | Bulk `executemany`. Calendar-aware partial-bar detection (exchange_calendars) |
| 5 | Fundamentals Persistence | market_cap, P/E, EPS, shares, sector, industry → bulk upsert |
| 6 | Derived Metrics | `ThreadPoolExecutor(3)` runs performance + volatility + volume **in parallel**. Each: 1 bulk read → Pandas groupby().rolling() → 1 bulk write |
| 7 | Finalize | Close DB, output execution report |

---

## Bronze → Silver → Gold (DBT Medallion)

### Bronze export (`etl_extract/`)

`extract_to_s3.py` reads incrementally from RDS per table config in `extract-config.json`, writes Parquet partitioned by `dt=YYYY-MM-DD` under `s3://<bucket>/bronze/<table>/`, and emits a snapshot manifest. `load_to_bigquery.py` then ingests those files into BigQuery raw tables.

### DBT layers (`financial_dwh/`)

| Layer | Models | Purpose |
|-------|--------|---------|
| `staging/` | `stg_tv_candles`, `stg_fundamentals`, `stg_*` | Typed, renamed, tested versions of bronze |
| `intermediate/` | `int_returns`, `int_rolling_vol`, `int_sma_gaps`, `int_52w_extremes` | Single-purpose transforms |
| `marts/` | `dim_date`, `dim_asset`, `fact_ohlcv`, `fact_fundamentals`, `fact_derived_metrics` | Kimball star schema + z-score layers |

### Three-layer z-score stack (gold)

Computed per `(symbol, as_of_date, metric)` inside `fact_derived_metrics`:

| Layer | Meaning | Baseline |
|-------|---------|----------|
| `z_intra` | How weird is this symbol **vs its own 252d history**? | Rolling per-symbol μ / σ |
| `z_cross` | How weird is this symbol **vs the rest of the universe today**? | Cross-section snapshot μ / σ |
| `z_of_z` | Anomaly of anomaly: is the intraday weirdness itself unusual? | Cross-section of `z_intra` |

`|z_of_z|` is what drives rankings on `/financial/avanzadas/`.

---

## Serving Layer — FastAPI

### REST + WS endpoints

| Route | Type | Source | Purpose |
|-------|------|--------|---------|
| `GET /` | REST | — | Health |
| `GET /symbols` | REST | RDS | All symbols (TTL 300s) |
| `GET /ohlcv/history/{symbol}` | REST | RDS | Historical candles (max 4500) |
| `GET /fundamentals/{symbol}` | REST | RDS | Latest fundamentals |
| `GET /performance/1d/{symbol}` | REST | RDS | Price performance |
| `GET /volatility/1d/{symbol}` | REST | RDS | Volatility metrics |
| `GET /volume/1d/{symbol}` | REST | RDS | Volume metrics |
| **`WS /ws/live/{symbol}`** | **WS** | **RDS + TV** | **Seed & edge live streaming** |
| `GET /analytics/anomalies` | REST | BigQuery | Ranked outliers per metric |
| `GET /analytics/metrics` | REST | BigQuery | Supported metric catalog |
| `GET /ws/stats` | REST | — | Active WS connections monitor |

### BigQuery client (`api/bq_analytics.py`)

Lazy-initialized singleton (first call pays cold-start, rest share). Each analytics query is wrapped in an in-process TTL cache so the UI polling doesn't hit BigQuery on every tab switch. Credentials via `GOOGLE_APPLICATION_CREDENTIALS`; project via `GCP_PROJECT`.

### WebSocket protocol

**Client → Server:**
```json
{"action": "switch", "symbol": "TSLA"}
{"action": "ping"}
```

**Server → Client:**
```json
{"type": "seed", "symbol": "AAPL", "chart_candles": [...], "fundamentals": {...}, "metrics": {...}}
{"type": "tick", "candle": {...}, "metrics": {...}}
{"type": "fundamentals", "data": {...}}
{"type": "company_name", "name": "Apple Inc"}
{"type": "heartbeat"}
{"type": "idle_warning"}
{"type": "session_expired"}
```

### Security

- Origin validation: pre-accept check against `ALLOWED_ORIGINS`
- Optional demo token `?token=xxx` (env: `LIVE_DEMO_TOKEN`)
- `MAX_CONNECTIONS=5`
- Zombie protection: 2h hard TTL, 5min idle warning, 10min idle disconnect
- CORS: `["*"]` only when `DEBUG=1`

---

## Frontend — React 19

### Routes

Mini-router in `App.tsx` switches on `window.location.pathname` (no react-router):

| Path | Component | Purpose |
|------|-----------|---------|
| `/financial/` | `Dashboard` | Chart + live ticks + metrics grid + fundamentals |
| `/financial/avanzadas/` | `AdvancedAnalyticsPage` | 3×3 ranking boards + dense multi-metric table |

### Dashboard

Driven by a single Zustand store (`wsStore.ts`) that owns the WS lifecycle (connect, switch, reconnect, tick reducer). Top-level components subscribe to narrow slices to minimize re-renders.

### Analíticas Avanzadas

Nine `RankingBoard`s arranged in a responsive 1/2/3-column grid, each hitting `/analytics/anomalies?metric=<m>` and rendering the top-3 by `|z_of_z|`. Metrics: RSI (pos/neg), 1M/3M vol, 1M return (pos/neg), SMA-200 gap, 52w high distance, intraday range. Every card has an `InfoTooltip` explaining the ranking. A dense multi-metric table below lets users browse the full `fact_derived_metrics` surface.

---

## Storage Architecture

### Database adapter (`storage/database.py`)

Single point of contact. No module touches `sqlite3` or `psycopg2` directly.

| `DATABASE_URL` | Engine | Use case |
|---|---|---|
| `postgresql://...` | psycopg2 (TCP) | Production (Docker, VPS, AWS RDS) |
| absent / file path | sqlite3 (WAL mode) | Dev / legacy fallback |

Exposes engine-agnostic primitives: `get_connection`, `transaction`, `execute`, `executemany`, `fetchall`, `fetchone`, and a runtime placeholder (`PH`) that swaps `?` ↔ `%s`.

### OLTP schema (RDS)

| Table | Primary Key | Description |
|-------|-------------|-------------|
| `tv_candles_raw` | `(symbol, timeframe, ts)` | Daily OHLCV candles |
| `fundamentals_snapshot` | `(symbol, as_of_ts)` | Market cap, P/E, EPS, sector, industry |
| `performance_1d` | `(symbol, timeframe, ts)` | ret_1d → ret_1y |
| `volatility_1d` | `(symbol, timeframe, ts)` | range_intraday, vol_1w → vol_1y (annualized) |
| `volume_1d` | `(symbol, timeframe, ts)` | volume_usd, vol_sma_{20,50,100,200}, vol_gap_* |

### Analytical schema (BigQuery — `financial_marts`)

| Model | Grain | Description |
|-------|-------|-------------|
| `dim_date` | day | Business-day calendar |
| `dim_asset` | symbol | Sector, tier, listing meta |
| `fact_ohlcv` | symbol × day | Clean OHLCV |
| `fact_fundamentals` | symbol × day | Forward-filled snapshots |
| `fact_derived_metrics` | symbol × day × metric | Metric value + `z_intra` + `z_cross` + `z_of_z` |

---

## Key Constants

```python
LAGS = {"ret_1d": 1, "ret_1w": 5, "ret_1m": 21, "ret_3m": 63, "ret_6m": 126, "ret_1y": 252}
VOL_WINDOWS = {"vol_1w": 5, "vol_1m": 21, "vol_3m": 63, "vol_6m": 126, "vol_1y": 252}
SMA_WINDOWS = [20, 50, 100, 200]
ANNUALIZATION_FACTOR = sqrt(252)  # ≈ 15.87

MAX_BARS = 258  # max(252, 200) + overlap

RECV_TIMEOUT = 30
SEND_TIMEOUT = 10
SYMBOL_TIMEOUT = 60
CONNECT_MAX_RETRIES = 3  # exponential backoff: 1s, 2s, 4s
STREAM_RECV_TIMEOUT = 45
```

---

## CLI Reference

```bash
# Batch ETL
python -m financial_data_etl.main_runner --assets NVDA TSLA COST
python -m financial_data_etl.main_runner --spx --ndx
python -m financial_data_etl.main_runner --spx --update-universe

# Bronze + BigQuery load
python etl_extract/extract_to_s3.py
python etl_extract/load_to_bigquery.py

# DBT
cd financial_dwh
dbt deps && dbt run && dbt test
dbt docs generate && dbt docs serve
```

### Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | (unset) | `postgresql://...` → PG; absent → SQLite |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | — | Docker Compose PG creds |
| `GCP_PROJECT` | (unset) | BigQuery project for analytics |
| `GOOGLE_APPLICATION_CREDENTIALS` | (unset) | Path to GCP service-account key |
| `WS_POOL_SIZE` | 20 | TradingView WS pool size (capped at 6) |
| `SYMBOLS_PER_BATCH` | 1 | Symbols per connection per batch cycle |
| `ALLOWED_ORIGINS` | localhost:3000,5173 | Comma-separated origin whitelist |
| `DEBUG` | (unset) | `1` to bypass CORS + origin checks |
| `LIVE_DEMO_TOKEN` | (unset) | If set, require `?token=xxx` on WS |

---

## Docker Images

### Backend (`Dockerfile`)

Multi-stage `python:3.11-slim` + `libpq5`. Single image, two entrypoints:

| Mode | Command | AWS equivalent |
|------|---------|----------------|
| API | `uvicorn financial_data_etl.api.app:app` (default CMD) | ECS Fargate Service |
| ETL | `python -m financial_data_etl.main_runner` (override) | ECS Fargate Task (EventBridge-triggered) |

Runs as non-root user `app`.

### Frontend (`frontend/Dockerfile`)

Multi-stage: `node:20-alpine` builds Vite → `nginx:alpine` serves static (~5MB RAM). In AWS, replaced by S3 + CloudFront. Build args `VITE_API_URL` / `VITE_WS_URL` are baked into the bundle at compile time.

---

## Production Deployment (current VPS)

```
Nginx (443 SSL) ─→ /financial/              → static React build
                 ─→ /financial-api/          → proxy_pass :9999 (FastAPI REST)
                 ─→ /financial-api/analytics → proxy_pass :9999 (BigQuery-backed)
                 ─→ /ws/                     → proxy_pass :9999 (WebSocket upgrade)
```

Backend launch:
```bash
DATABASE_URL=postgresql://user:pass@localhost:5432/financial_data \
GCP_PROJECT=<project> \
GOOGLE_APPLICATION_CREDENTIALS=/opt/financial/gcp-sa-key.json \
ALLOWED_ORIGINS=https://yourdomain.com \
  uvicorn financial_data_etl.api.app:app --host 127.0.0.1 --port 9999
```

Frontend `.env.production`:
```
VITE_API_URL=https://yourdomain.com/financial-api
VITE_WS_URL=wss://yourdomain.com
```

---

## AWS Target Architecture (migration in progress)

Each Docker service maps 1:1 to a managed AWS service. Scaffolding lives in `aws/`.

| Local service | AWS service | Status |
|---|---|---|
| `postgres` | RDS PostgreSQL (Multi-AZ) | ✅ provisioned |
| `api` | ECS Fargate Service (`aws/ecs/api-task-definition.json`) | 🟡 task def ready, ALB + SSL pending |
| `etl` | ECS Fargate Task (`aws/ecs/etl-task-definition.json`) | 🟡 triggered by Lambda (`aws/lambda/lambda-etl-trigger.py`) |
| Bronze export | ECS utility task + S3 bucket (`aws/s3/`) | ✅ scripts working, schedule pending |
| BigQuery load | Same utility task, Lambda scheduled | 🟡 manual for now |
| `frontend` | S3 + CloudFront (`aws/cloudfront/`) | 🟡 config ready, cutover pending |
| CI/CD | GitHub Actions (`aws/github-actions/`) | 🟡 workflows scaffolded |

EventBridge cron triggers the Lambda in `aws/lambda/`, which launches the ETL Fargate task with the appropriate universe from `etl_universe.txt`.

See `apunte_sistema.md` for a narrative walkthrough of every piece of the system.

---

## Observability

Structured JSON logging via `observability/run_context.py` (stage timers, row counts, errors). In production, logs ship to CloudWatch (AWS) or local files (VPS). DBT emits its own run/test artifacts under `financial_dwh/target/` (gitignored, regenerated by `dbt run`).
