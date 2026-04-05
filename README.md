# financial-data-etl

Full-stack financial data platform: batch ETL pipeline (2,425 symbols) + real-time WebSocket streaming + React terminal UI.

Dockerized. Runs on PostgreSQL (production) with SQLite fallback (dev/legacy). Currently deployed on VPS, designed for AWS migration (ECS Fargate + RDS).

**Live:** [leonardovila.com/financial](https://leonardovila.com/financial/)

---

## Architecture Overview

The system has two execution modes sharing the same data layer, packaged as Docker containers:

```
┌─────────────────────────────────────────────────────────────────────┐
│                        DOCKER COMPOSE STACK                         │
│                                                                     │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────────┐     │
│  │ postgres  │  │ api       │  │ etl       │  │ frontend      │     │
│  │ (PG 16)   │  │ (FastAPI) │  │ (on-demand│  │ (Nginx+React) │     │
│  │           │  │           │  │  runner)  │  │               │     │
│  │ :5432     │  │ :8000     │  │           │  │ :3000         │     │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘  └───────────────┘     │ 
│        │              │              │                              │
│        └──── DATABASE_URL ───────────┘                              │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                     MODE 1: BATCH ETL (cron)                        │
│                                                                     │
│  catalog.json ─→ increment_plan ─→ WS Pool (6 conn) ─→ PostgreSQL   │
│  (2,425 syms)    (bootstrap/catchup)  (asyncio.Queue)               │
│                                                                     │
│  PostgreSQL ─→ Pandas groupby ─→ performance_1d / volatility_1d /   │
│                 (vectorized)       volume_1d (bulk executemany)     │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                  MODE 2: LIVE STREAMING (FastAPI)                   │
│                                                                     │
│  Browser WS ──→ /ws/live/{symbol}                                   │
│                    │                                                │
│                    ├─ SEED: DB → 4,500 bars + metrics (5-15ms)      │
│                    │                                                │
│                    └─ EDGE: TradingView WS → in-memory DataFrame    │
│                             → compute_all_metrics_live (<1ms)       │
│                             → send_json({type:'tick', ...})         │
│                                                                     │
│  React UI ←── Zustand store ←── seed/tick/fundamentals/heartbeat    │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Directory Structure

```
financial-data-etl/
├── Dockerfile                        # Multi-stage backend image (API + ETL)
├── docker-compose.yml                # Full stack: postgres + api + etl + frontend
├── .env.example                      # Template for Docker env vars
│
├── financial_data_etl/               # Python package
│   ├── main_runner.py                # Batch ETL orchestrator (7 stages)
│   │
│   ├── scraping_pipeline/
│   │   └── tv_websocket_connection/
│   │       ├── call_execution/
│   │       │   └── tradingview_ws.py       # WS protocol: batch multiplexing + live stream generator
│   │       ├── call_specification/
│   │       │   ├── asset_catalog.py        # catalog.json loader + provider symbol resolution
│   │       │   ├── call_builder.py         # CallSpec factory
│   │       │   └── timeframes_registry.py  # Timeframe constants
│   │       ├── parsing/
│   │       │   └── ohlcv_parser.py         # TradingView → [ts, o, h, l, c, v]
│   │       └── tv_websocket_scraper.py     # Pool workers + asyncio.Queue + batch orchestration
│   │
│   ├── derived_metrics/
│   │   ├── price_performance/
│   │   │   ├── price_performance_runner.py # LAGS: ret_1d→ret_1y (Pandas pct_change)
│   │   │   └── price_performance_store.py  # Bulk SQL read/write
│   │   ├── volatility/
│   │   │   ├── volatility_runner.py        # VOL_WINDOWS: vol_1w→vol_1y (rolling std of log returns)
│   │   │   └── volatility_store.py
│   │   └── volume/
│   │       ├── volume_runner.py            # SMA_WINDOWS: [20, 50, 100, 200] + gap %
│   │       └── volume_store.py
│   │
│   ├── storage/
│   │   ├── database.py               # DB adapter — engine-agnostic (PostgreSQL / SQLite)
│   │   ├── tv_candles_store.py       # tv_candles_raw upsert
│   │   ├── ohlcv_row_builder.py      # Candle normalization + partial bar detection
│   │   ├── ohlcv_base_store.py       # Batch persist orchestration
│   │   └── paths.py                  # DB_PATH constant (SQLite fallback)
│   │
│   ├── api/                          # FastAPI live streaming layer
│   │   ├── app.py                    # 8 REST + 1 WS endpoint + security + lifespan
│   │   ├── live_seed.py              # Cold-start: 5 SQL queries → full chart payload
│   │   ├── live_state.py             # LiveSymbolState: 258-row in-memory DataFrame
│   │   ├── live_compute.py           # Pure math: performance + volatility + volume (<1ms)
│   │   └── live_session_manager.py   # Dedicated TV WS per subscriber
│   │
│   └── observability/
│       └── run_context.py            # Structured JSON logging
│
├── frontend/                         # React + TypeScript + Vite
│   ├── Dockerfile                    # Multi-stage: npm build → Nginx static server
│   └── src/
│       ├── store/
│       │   └── wsStore.ts            # Zustand: WS lifecycle, reconnection, state slices
│       ├── components/
│       │   ├── Chart.tsx             # Lightweight Charts v5 (autoSize, O(1) update)
│       │   ├── TickStack.tsx         # Live feed: GPU slideIn, 50 desktop / 20 mobile
│       │   ├── MetricsGrid.tsx       # Perf + Vol + Volume cards (scroll-snap tabs mobile)
│       │   ├── MetricCard.tsx        # Individual metric card
│       │   ├── FundamentalsBar.tsx   # Mkt Cap, P/E, EPS, Sector
│       │   ├── SymbolSearch.tsx      # Inline search with autocomplete
│       │   └── StatusBar.tsx         # Connection status, symbol, tick count
│       ├── lib/
│       │   └── formatters.ts         # Currency, percent, compact number formatting
│       └── types/
│           └── market.ts             # TypeScript interfaces for all WS payloads
│
├── catalog.json                      # 2,425 symbols with provider mappings
```

---

## Quick Start (Docker)

### Requirements

- Docker + Docker Compose

### 1. Configure environment

```bash
git clone https://github.com/leonardovila/financial-data-etl.git
cd financial-data-etl
cp .env.example .env
# Edit .env with your PostgreSQL credentials
```

`.env.example`:
```
POSTGRES_USER=forge
POSTGRES_PASSWORD=your_password_here
POSTGRES_DB=financial_data
DATABASE_URL=postgresql://forge:your_password_here@postgres:5432/financial_data
```

### 2. Start the stack

```bash
docker compose up -d          # Starts: postgres + api + frontend
```

This brings up:
- **PostgreSQL 16** on `:5432` (data persisted in `pg_data` volume)
- **FastAPI** on `:8000` (live streaming API)
- **Nginx + React** on `:3000` (frontend SPA)

### 3. Run Batch ETL

The ETL runs on demand (not as a persistent service):

```bash
docker compose run etl --assets NVDA                # Single asset test
docker compose run etl --dji                        # Dow Jones (30 symbols)
docker compose run etl --spx                        # S&P 500
docker compose run etl --spx --ndx                  # S&P 500 + Nasdaq 100
```

### 4. Stop everything

```bash
docker compose down            # Stops containers (data persists in pg_data volume)
docker compose down -v         # Stops containers AND deletes PostgreSQL data
```

### Local development (without Docker)

For running outside Docker (e.g., debugging), set `DATABASE_URL` to point to a running PostgreSQL instance, or leave it unset to fall back to SQLite:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .

# With PostgreSQL:
DATABASE_URL=postgresql://user:pass@localhost:5432/financial_data \
  uvicorn financial_data_etl.api.app:app --port 8000

# With SQLite (legacy, no DATABASE_URL needed):
uvicorn financial_data_etl.api.app:app --port 8000
```

Frontend dev server:
```bash
cd frontend && npm install && npm run dev    # → http://localhost:5173
```

---

## Batch ETL Pipeline (main_runner.py)

Seven sequential stages, stage 6 parallelized:

| Stage | Name | Action |
|-------|------|--------|
| 1 | Universe Resolution | Load catalog.json → 2,425 tickers |
| 2 | Increment Plan | Query DB → determine n_candles per symbol (bootstrap=4500, catchup=3-25) |
| 3 | WebSocket Scraping | 6 persistent connections drain asyncio.Queue. Multiplexed OHLCV+fundamentals per symbol. 3-layer timeout (recv=30s, send=10s, symbol=60s) |
| 4 | OHLCV Persistence | Bulk executemany(). Calendar-aware partial bar detection (exchange_calendars cached per exchange) |
| 5 | Fundamentals Persistence | Extract market_cap, P/E, EPS, shares, sector, industry → bulk upsert |
| 6 | Derived Metrics | **ThreadPoolExecutor(3)** runs price_performance + volatility + volume **in parallel**. Each: 1 bulk SQL read (ROW_NUMBER PARTITION BY) → 1 Pandas DataFrame → groupby().rolling() → 1 bulk write |
| 7 | Finalize | Close DB, output execution report |

**Key optimization:** SQL queries → 6 total (1 read + 1 write × 3 runners).

---

## Live Streaming API

### Endpoints

| Route | Type | Purpose |
|-------|------|---------|
| `GET /` | REST | Health check |
| `GET /symbols` | REST | All symbols with company names (TTL cached 300s) |
| `GET /ohlcv/history/{symbol}` | REST | Historical candles (max 4500) |
| `GET /fundamentals/{symbol}` | REST | Latest fundamentals snapshot |
| `GET /performance/1d/{symbol}` | REST | Price performance metrics |
| `GET /volatility/1d/{symbol}` | REST | Volatility metrics |
| `GET /volume/1d/{symbol}` | REST | Volume metrics |
| **`WS /ws/live/{symbol}`** | **WebSocket** | **Seed & Edge live streaming** |
| `GET /ws/stats` | REST | Active connections monitor |

### WebSocket Protocol

**Client → Server:**
```json
{"action": "switch", "symbol": "TSLA"}
{"action": "ping"}
```

**Server → Client:**
```json
{"type": "seed", "symbol": "AAPL", "chart_candles": [...], "fundamentals": {...}, "metrics": {...}}
{"type": "tick", "candle": {...}, "metrics": {"performance": {...}, "volatility": {...}, "volume": {...}}}
{"type": "fundamentals", "data": {...}}
{"type": "company_name", "name": "Apple Inc"}
{"type": "heartbeat"}
{"type": "session_expired"}
{"type": "idle_warning"}
```

### Security

- **Origin validation:** Pre-accept check against `ALLOWED_ORIGINS` whitelist
- **Demo token:** Optional `?token=xxx` query param (env: `LIVE_DEMO_TOKEN`)
- **Connection limit:** MAX_CONNECTIONS=5
- **Zombie protection:** 2h hard TTL, 5min idle warning, 10min idle disconnect
- **CORS:** Conditional — `["*"]` only in `DEBUG=1` mode

---

## Storage Architecture

### Database adapter (`storage/database.py`)

Single point of contact for all DB operations. Every store and runner imports from `database.py` — no module touches `sqlite3` or `psycopg2` directly.

Engine selection is driven by one env var:

| `DATABASE_URL` | Engine | Use case |
|---|---|---|
| `postgresql://...` | psycopg2 (TCP) | Production (Docker, VPS, AWS RDS) |
| absent / file path | sqlite3 (local file, WAL mode) | Dev / legacy fallback |

The adapter exposes engine-agnostic primitives: `get_connection()`, `transaction()`, `execute()`, `executemany()`, `fetchall()`, `fetchone()`, and a runtime placeholder (`PH`) that swaps `?` ↔ `%s` transparently. Stores write standard SQL and never branch on engine type.

### Schema

| Table | Primary Key | Description |
|-------|-------------|-------------|
| `tv_candles_raw` | `(symbol, timeframe, ts)` | Daily OHLCV candles |
| `fundamentals_snapshot` | `(symbol, as_of_ts)` | Market cap, P/E, EPS, sector, industry |
| `performance_1d` | `(symbol, timeframe, ts)` | ret_1d, ret_1w, ret_1m, ret_3m, ret_6m, ret_1y |
| `volatility_1d` | `(symbol, timeframe, ts)` | range_intraday, vol_1w→vol_1y (annualized, ddof=1) |
| `volume_1d` | `(symbol, timeframe, ts)` | volume_usd, vol_sma_20→200, vol_gap_20→200 |

---

## Key Constants

```python
# Derived metrics windows
LAGS = {"ret_1d": 1, "ret_1w": 5, "ret_1m": 21, "ret_3m": 63, "ret_6m": 126, "ret_1y": 252}
VOL_WINDOWS = {"vol_1w": 5, "vol_1m": 21, "vol_3m": 63, "vol_6m": 126, "vol_1y": 252}
SMA_WINDOWS = [20, 50, 100, 200]
ANNUALIZATION_FACTOR = sqrt(252)  # ≈ 15.87

# Live state
MAX_BARS = 258  # Buffer for all metric windows: max(252, 200) + overlap

# WebSocket timeouts
RECV_TIMEOUT = 30       # per ws.recv()
SEND_TIMEOUT = 10       # per ws.send()
SYMBOL_TIMEOUT = 60     # per-symbol outer timeout
CONNECT_MAX_RETRIES = 3 # exponential backoff: 1s, 2s, 4s
STREAM_RECV_TIMEOUT = 45  # live stream (more generous for quiet markets)
```

---

## CLI Reference

```bash
# Single assets
python -m financial_data_etl.main_runner --assets NVDA TSLA COST

# Index universes
python -m financial_data_etl.main_runner --spx          # S&P 500
python -m financial_data_etl.main_runner --ndx          # Nasdaq 100
python -m financial_data_etl.main_runner --rut          # Russell 2000
python -m financial_data_etl.main_runner --dji          # Dow Jones 30

# Combined
python -m financial_data_etl.main_runner --spx --ndx

# Update catalog with latest index composition
python -m financial_data_etl.main_runner --spx --update-universe
```

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | (unset) | `postgresql://...` → PostgreSQL. Absent → SQLite fallback |
| `POSTGRES_USER` | — | PostgreSQL user (Docker Compose) |
| `POSTGRES_PASSWORD` | — | PostgreSQL password (Docker Compose) |
| `POSTGRES_DB` | — | PostgreSQL database name (Docker Compose) |
| `WS_POOL_SIZE` | 20 | WebSocket connection pool size (TradingView caps at 6) |
| `SYMBOLS_PER_BATCH` | 1 | Symbols multiplexed per connection per batch cycle |
| `DEBUG` | (unset) | Set to `1` to bypass CORS + origin checks |
| `ALLOWED_ORIGINS` | localhost:3000,5173 | Comma-separated origin whitelist |
| `LIVE_DEMO_TOKEN` | (unset) | If set, require `?token=xxx` on WS connections |

---

## Docker Images

### Backend (`Dockerfile`)

Multi-stage build (builder → runtime). Single image, two entrypoints:

| Mode | Command | Equivalent AWS service |
|------|---------|------------------------|
| API | `uvicorn financial_data_etl.api.app:app` (default CMD) | ECS Fargate Service (always-on) |
| ETL | `python -m financial_data_etl.main_runner` (override entrypoint) | ECS Fargate Task (EventBridge/cron) |

Runtime dependencies: `python:3.11-slim` + `libpq5` (psycopg2). Runs as non-root user `app`.

### Frontend (`frontend/Dockerfile`)

Multi-stage: `node:20-alpine` builds Vite → `nginx:alpine` serves static files (~5MB RAM). In AWS, this container is replaced entirely by S3 + CloudFront.

Build-time args `VITE_API_URL` and `VITE_WS_URL` are baked into the JS bundle at compile time.

---

## Production Deployment (VPS)

```
Nginx (443 SSL) ─→ /financial/       → static React (Vite build)
                 ─→ /financial-api/  → proxy_pass :9999 (FastAPI REST)
                 ─→ /ws/             → proxy_pass :9999 (WebSocket upgrade)
```

Backend:
```bash
DATABASE_URL=postgresql://user:pass@localhost:5432/financial_data \
ALLOWED_ORIGINS=https://yourdomain.com \
  uvicorn financial_data_etl.api.app:app --host 127.0.0.1 --port 9999
```

Frontend `.env.production`:
```
VITE_API_URL=https://yourdomain.com/financial-api
VITE_WS_URL=wss://yourdomain.com
```

### AWS Target Architecture

Each Docker service maps 1:1 to an AWS managed service:

| Docker service | AWS service | Notes |
|---|---|---|
| `postgres` | RDS PostgreSQL (Multi-AZ) | Managed backups, failover |
| `api` | ECS Fargate Service | Always-on, auto-scaling |
| `etl` | ECS Fargate Task | Triggered by EventBridge (cron) |
| `frontend` | S3 + CloudFront | No container needed — static hosting |
| `pg_data` volume | EBS (via RDS) | Managed by RDS, no manual config |

---
