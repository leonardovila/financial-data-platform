# financial-data-etl

Full-stack financial data platform: batch ETL pipeline (2,425 symbols) + real-time WebSocket streaming + React terminal UI.

**Live:** [leonardovila.com/financial](https://leonardovila.com/financial/)

---

## Architecture Overview

The system has two execution modes that share the same data layer:

```
┌─────────────────────────────────────────────────────────────────────┐
│                     MODE 1: BATCH ETL (cron)                        │
│                                                                     │
│  catalog.json ─→ increment_plan ─→ WS Pool (6 conn) ─→ SQLite     │
│  (2,425 syms)    (bootstrap/catchup)  (asyncio.Queue)    (WAL)     │
│                                                                     │
│  SQLite ─→ Pandas groupby ─→ performance_1d / volatility_1d /     │
│             (vectorized)       volume_1d (bulk executemany)         │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                  MODE 2: LIVE STREAMING (FastAPI)                    │
│                                                                     │
│  Browser WS ──→ /ws/live/{symbol}                                  │
│                    │                                                │
│                    ├─ SEED: SQLite → 4,500 bars + metrics (5-15ms) │
│                    │                                                │
│                    └─ EDGE: TradingView WS → in-memory DataFrame   │
│                             → compute_all_metrics_live (<1ms)       │
│                             → send_json({type:'tick', ...})         │
│                                                                     │
│  React UI ←── Zustand store ←── seed/tick/fundamentals/heartbeat   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Directory Structure

```
financial-data-etl/
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
│   │   ├── tv_candles_store.py       # tv_candles_raw upsert
│   │   ├── ohlcv_row_builder.py      # Candle normalization + partial bar detection
│   │   ├── ohlcv_base_store.py       # Batch persist orchestration
│   │   └── paths.py                  # DB_PATH constant
│   │
│   ├── api/                          # FastAPI live streaming layer
│   │   ├── app.py                    # 8 REST + 1 WS endpoint + security + lifespan
│   │   ├── db.py                     # SQLite connection factory (WAL + busy_timeout)
│   │   ├── live_seed.py              # Cold-start: 5 SQL queries → full chart payload
│   │   ├── live_state.py             # LiveSymbolState: 258-row in-memory DataFrame
│   │   ├── live_compute.py           # Pure math: performance + volatility + volume (<1ms)
│   │   └── live_session_manager.py   # Dedicated TV WS per subscriber
│   │
│   └── observability/
│       └── run_context.py            # Structured JSON logging
│
├── frontend/                         # React + TypeScript + Vite
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
├── bottlenecks.json                  # 20 architectural bottlenecks (19 closed)
├── TECHNICAL_SHOWCASE.json           # Full engineering audit document
└── tasks_for_websocket_production.json # Live streaming implementation roadmap
```

---

## Quick Start

### Requirements

- Python >= 3.11
- Node.js >= 18 (for frontend)

### 1. Backend Setup

```bash
git clone https://github.com/leonardovila/financial-data-etl.git
cd financial-data-etl

python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/Mac: source .venv/bin/activate

pip install -e .
```

### 2. Run Batch ETL (single asset test)

```bash
python -m financial_data_etl.main_runner --assets NVDA
```

Full index runs:

```bash
python -m financial_data_etl.main_runner --dji          # Dow Jones (30 symbols)
python -m financial_data_etl.main_runner --spx           # S&P 500
python -m financial_data_etl.main_runner --spx --ndx     # S&P 500 + Nasdaq 100
```

### 3. Start Live API

```bash
# Development (all security bypassed):
DEBUG=1 uvicorn financial_data_etl.api.app:app --port 8000

# Production:
ALLOWED_ORIGINS=https://yourdomain.com uvicorn financial_data_etl.api.app:app --port 9999
```

### 4. Frontend Development

```bash
cd frontend
npm install
npm run dev    # → http://localhost:5173
```

Requires `.env.development`:
```
VITE_WS_URL=ws://localhost:8000
VITE_API_URL=http://localhost:8000
```

Production build:
```bash
npm run build  # Uses .env.production for domain URLs
```

---

## Batch ETL Pipeline (main_runner.py)

Seven sequential stages, stage 6 parallelized:

| Stage | Name | Action |
|-------|------|--------|
| 1 | Universe Resolution | Load catalog.json → 2,425 tickers |
| 2 | Increment Plan | Query SQLite → determine n_candles per symbol (bootstrap=4500, catchup=3-25) |
| 3 | WebSocket Scraping | 6 persistent connections drain asyncio.Queue. Multiplexed OHLCV+fundamentals per symbol. 3-layer timeout (recv=30s, send=10s, symbol=60s) |
| 4 | OHLCV Persistence | Bulk executemany(). Calendar-aware partial bar detection (exchange_calendars cached per exchange) |
| 5 | Fundamentals Persistence | Extract market_cap, P/E, EPS, shares, sector, industry → bulk upsert |
| 6 | Derived Metrics | **ThreadPoolExecutor(3)** runs price_performance + volatility + volume **in parallel**. Each: 1 bulk SQL read (ROW_NUMBER PARTITION BY) → 1 Pandas DataFrame → groupby().rolling() → 1 bulk write |
| 7 | Finalize | Close DB, output execution report |

**Key optimization:** 21,600 individual SQL queries → 6 total (1 read + 1 write × 3 runners).

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

## SQLite Schema

All tables use WAL mode with `busy_timeout=5000`.

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
| `WS_POOL_SIZE` | 20 | WebSocket connection pool size (TradingView caps at 6) |
| `SYMBOLS_PER_BATCH` | 1 | Symbols multiplexed per connection per batch cycle |
| `DEBUG` | (unset) | Set to `1` to bypass CORS + origin checks |
| `ALLOWED_ORIGINS` | localhost:3000,5173 | Comma-separated origin whitelist |
| `LIVE_DEMO_TOKEN` | (unset) | If set, require `?token=xxx` on WS connections |

---

## Production Deployment (VPS)

```
Nginx (443 SSL) ─→ /financial/       → static React (Vite build)
                 ─→ /financial-api/  → proxy_pass :9999 (FastAPI REST)
                 ─→ /ws/             → proxy_pass :9999 (WebSocket upgrade)
```

Backend:
```bash
ALLOWED_ORIGINS=https://yourdomain.com \
  uvicorn financial_data_etl.api.app:app --host 127.0.0.1 --port 9999
```

Frontend `.env.production`:
```
VITE_API_URL=https://yourdomain.com/financial-api
VITE_WS_URL=wss://yourdomain.com
```

---

## Companion Documents

| File | Purpose |
|------|---------|
| `TECHNICAL_SHOWCASE.json` | Complete engineering audit: stack, lifecycle, optimizations, justifications |
| `bottlenecks.json` | 20 cataloged architectural bottlenecks with resolution history |
| `tasks_for_websocket_production.json` | Live streaming implementation roadmap (LIVE-01 → LIVE-10) |
| `FRONTEND_PLAN.json` | Frontend component plan (FRONT-001 → FRONT-010) |
