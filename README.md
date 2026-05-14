# financial-data-etl

Full-stack financial data platform: event-driven ETL, real-time WebSocket streaming, and a three-layer z-score anomaly detector across 700+ US equities.

**Live:** [app.leonardovila.com/financial](https://app.leonardovila.com/financial/)

**700+ tickers** | **8,000+ trading days per symbol** | **Sub-second live latency** | **Daily automated refresh**

---

## What This Does

Two products share a single ingestion layer:

1. **Operational Dashboard** at [`/financial/`](https://app.leonardovila.com/financial/) — live OHLCV chart streamed via TradingView WebSocket, with derived metrics (performance, volatility, momentum) computed in-process at sub-millisecond latency.
2. **Advanced Analytics** at [`/financial/avanzadas/`](https://app.leonardovila.com/financial/avanzadas/) — daily outlier detection powered by a three-layer z-score stack (`z_intra` / `z_cross` / `z_of_z`) materialized in BigQuery by dbt. Nine ranking boards surface the most statistically unusual assets across the S&P 500, Nasdaq 100, Russell 2000, and crypto.

The architecture spans AWS and GCP by design: AWS handles OLTP storage and compute orchestration (ECS Fargate, Lambda, RDS, S3), while GCP provides columnar analytics via BigQuery. A dedicated scraping node with residential IP ensures reliable TradingView WebSocket access — its only job is to collect raw market data and push it to S3.

---

## Architecture Overview

```
┌──────────────────────── INGESTION (event-driven) ───────────────────────────┐
│                                                                             │
│  Scraping Node           S3 Raw                    Lambda          ECS      │
│  (systemd timer)         (gzipped JSONL             (S3 event      Fargate  │
│       │                   per symbol)                trigger)       Task    │
│       ▼                       │                        │             │      │
│  TradingView WS ──► s3://…/raw/tv/symbol={SYM}/ ──► _DONE_ ──► main_runner│
│  6 persistent conn    ingestion_date=YYYY-MM-DD/     marker    ┌──────────┐│
│  700+ tickers          data.jsonl.gz                           │ persist  ││
│  chunks of 50                                                  │ OHLCV +  ││
│                                                                │ fundmtls ││
│                                                                │ to RDS   ││
│                                                                └────┬─────┘│
│                                                                     │      │
│                                                          ┌──────────▼─────┐│
│                                                          │ Derived Metrics││
│                                                          │ performance    ││
│                                                          │ volatility     ││
│                                                          │ momentum       ││
│                                                          │ (parallel)     ││
│                                                          └────────────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────── ANALYTICS — dbt MEDALLION (BigQuery) ───────────────────┐
│                                                                             │
│  Bronze (S3 Parquet)  ──►  staging/    ──►  intermediate/  ──►  marts/     │
│  dt=YYYY-MM-DD             8 models         4 models           5 models    │
│  Hive partitioned          typed,           z_intra (252d)     Kimball     │
│                            tested           z_cross (daily)    star schema │
│                                             z_of_z (meta)      + z-scores │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌───────────────────────── SERVING — FastAPI + React ──────────────────────────┐
│                                                                              │
│  FastAPI                                                                     │
│    REST   /ohlcv, /fundamentals, /performance, /volatility, /momentum (RDS) │
│    WS     /ws/live/{symbol} — seed (258 historical bars) + edge (live ticks)│
│    BQ     /analytics/anomalies, /zscore-history, /universe (BigQuery + TTL) │
│                                                                              │
│  React 19                                                                    │
│    /financial/            → Dashboard (chart + metrics + live ticks)         │
│    /financial/avanzadas/  → 9 ranking boards + dense multi-metric table     │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Three-Layer Z-Score Stack

The core analytical differentiator. Computed per `(symbol, date, metric)` across 9 financial metrics inside `fact_derived_metrics`:

| Layer | Question it answers | Baseline |
|-------|---------------------|----------|
| `z_intra` | How unusual is this asset **vs its own 252-day history**? | Rolling per-symbol mean and standard deviation |
| `z_cross` | How unusual is this asset **vs the rest of the universe today**? | Cross-section snapshot across all assets |
| `z_of_z` | Is the intra-asset anomaly itself extreme relative to the universe? | Cross-section of `z_intra` values |

A stock that is 2-sigma overbought on RSI is interesting. A stock whose overbought-ness is itself 2-sigma extreme relative to the universe — that is an outlier worth investigating. `|z_of_z|` drives rankings on [`/financial/avanzadas/`](https://app.leonardovila.com/financial/avanzadas/).

**Metrics tracked across all three z-score layers:** `ret_1d`, `ret_1m`, `vol_1m`, `vol_3m`, `rsi_14`, `sma_50_gap`, `sma_200_gap`, `range_intraday`, `high_dist_1y`.

---

## Event-Driven Ingestion Pipeline

The ingestion pipeline is fully automated and event-driven. One marker file triggers the entire chain — from raw WebSocket capture to materialized analytics tables.

### Flow

1. **Scraping node** runs on a systemd timer (Mon–Fri, post-market close). Opens 6 persistent TradingView WebSocket connections and drains 700+ tickers in chunks of 50 via `asyncio.Queue`. Raw WebSocket frames are written as gzipped JSONL to S3, one file per symbol per day.
2. **Marker file** (`_DONE_{date}.txt`) lands in S3 after the last chunk uploads.
3. **Lambda** catches the S3 event (filtered by prefix `raw/tv/_DONE_` + suffix `.txt`), parses the ingestion date, and launches an ECS Fargate task.
4. **Fargate task** (`main_runner.py`) streams raw data from S3 in batches of 50, persists OHLCV candles and fundamentals to RDS, computes derived metrics, and refreshes the BigQuery warehouse via bronze export + dbt run.

### Seven-Stage Orchestrator

| Stage | Name | Action |
|-------|------|--------|
| 1 | Universe Resolution | Load 700+ tickers from catalog with TradingView provider mappings |
| 2 | Increment Plan | Query RDS for last timestamp per symbol. Bootstrap = 4,500 bars; catchup = 1–600 bars |
| 3 | Raw Ingestion | Stream gzipped JSONL from S3 in batches of 50 symbols |
| 4 | OHLCV Persistence | Bulk insert with calendar-aware partial-bar detection (`exchange_calendars`) |
| 5 | Fundamentals Persistence | Market cap, P/E, EPS, shares outstanding, sector, industry |
| 6 | Derived Metrics | `ThreadPoolExecutor(3)` runs performance + volatility + momentum in parallel. Each: 1 bulk read → pandas vectorized groupby → 1 bulk write |
| 7 | Finalize | Bronze export to BigQuery, dbt refresh (staging → intermediate → marts), execution report |

### Derived Metrics

Three families of metrics computed over a 258-bar rolling window:

- **Price Performance**: trailing returns at 1d, 1w, 1m, 3m, 6m, 1y lags
- **Volatility**: annualized log-return standard deviation at 1w, 1m, 3m, 6m, 1y windows + intraday range
- **Momentum**: RSI-14 (Wilder EWM), SMA gaps at 20/50/100/200 periods, Donchian 52-week high distance

---

## Medallion Data Warehouse

Bronze → Silver → Gold in BigQuery, orchestrated by dbt.

### Layers

| Layer | Dataset | Models | Purpose |
|-------|---------|--------|---------|
| **Bronze** | `financial_raw` | — | Raw replica from RDS via S3 Parquet (Hive-partitioned by `dt=YYYY-MM-DD`) |
| **Silver** | `financial_staging` | `stg_tv_candles`, `stg_fundamentals`, `stg_performance`, `stg_volatility`, `stg_momentum`, `stg_assets`, `stg_dates` | Typed, deduplicated, tested views over bronze |
| **Intermediate** | `financial_staging` | `int_asset_daily`, `int_intra_asset_zscores`, `int_cross_asset_zscores`, `int_z_of_z` | Single-purpose transforms: daily metric spine → rolling z-scores → cross-section z-scores → meta-anomaly detection |
| **Gold** | `financial_marts` | `dim_date`, `dim_asset`, `fact_ohlcv`, `fact_fundamentals`, `fact_derived_metrics` | Kimball star schema. Fact tables materialized with clustering by `asset_key`. `fact_derived_metrics` carries raw metrics + all three z-score layers (27 z-score columns) |

### Data Quality

- **dbt tests**: `unique_combination_of_columns` on all composite primary keys, `accepted_range` on bounded metrics (RSI ∈ [0, 100], volatility ≥ 0), `relationships` between facts and dimensions, `not_null` on key columns
- **Code-level**: calendar-aware partial-bar detection via `exchange_calendars`, `is_partial` flag propagated from ingestion through bronze export

---

## Real-Time Streaming Engine

The live dashboard uses a **Seed & Edge** pattern:

- **Seed**: on WebSocket connection, the server loads 258 historical bars from RDS and computes the full metric set (performance, volatility, momentum). This one-time payload cold-starts the chart with complete context.
- **Edge**: every subsequent TradingView tick updates a 258-row in-memory DataFrame. Metrics are recomputed in-process in <1ms — no database round-trips on the hot path.

### Batch–Live Parity

The live computation module imports constants directly from the batch runners (same lag windows, same RSI period, same annualization factor). Mathematical parity between batch and live metrics is guaranteed by construction, not by testing.

### WebSocket Protocol

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

Symbol switching happens over the existing socket — no reconnection required. A transition lock drops stale ticks from the previous symbol until the new seed arrives.

### Security

- **Origin validation**: pre-accept check against `ALLOWED_ORIGINS` whitelist
- **Internal API auth**: bearer token for `/internal/*` endpoints (Secrets Manager)
- **Rate limiting**: `MAX_CONNECTIONS` cap on concurrent WebSocket sessions
- **Zombie protection**: 2h hard TTL, 5min idle warning, 10min idle disconnect, dead-stream detection after 5 consecutive heartbeats with no data

---

## API Reference

| Route | Type | Source | Purpose |
|-------|------|--------|---------|
| `GET /symbols` | REST | RDS | Full symbol catalog (TTL 300s) |
| `GET /ohlcv/history/{symbol}` | REST | RDS | Historical daily candles (up to 4,500 bars) |
| `GET /fundamentals/{symbol}` | REST | RDS | Market cap, P/E, EPS, shares, sector, industry |
| `GET /performance/1d/{symbol}` | REST | RDS | Trailing returns: 1d → 1y |
| `GET /volatility/1d/{symbol}` | REST | RDS | Annualized volatility: 1w → 1y + intraday range |
| `GET /momentum/1d/{symbol}` | REST | RDS | RSI-14, SMA gaps, Donchian distance |
| `WS /ws/live/{symbol}` | WebSocket | RDS + TV | Seed & edge live streaming |
| `GET /analytics/anomalies` | REST | BigQuery | Top-N outliers ranked by \|z_of_z\| per metric (TTL cached) |
| `GET /analytics/zscore-history/{symbol}` | REST | BigQuery | 252-day time series of all three z-score layers |
| `GET /analytics/universe` | REST | BigQuery | Outlier counts by metric + sector distribution snapshot |

BigQuery endpoints use a lazy-initialized singleton client with in-process TTL caching — the UI can poll without hitting BigQuery on every request.

---

## Frontend — React 19

**Live:** [app.leonardovila.com/financial](https://app.leonardovila.com/financial/)

Built with React 19, TypeScript 5.9 (strict mode), Vite 8, Tailwind 4 (CSS-first, no config file), Zustand 5, and TradingView's lightweight-charts v5. No component library, no React Router (5-line mini-router for 2 routes), no React Query.

### Dashboard (`/financial/`)

A single Zustand store owns the entire WebSocket lifecycle: connect, switch symbol, reconnect with exponential backoff (1s → 16s), pause on tab hidden (Visibility API), resume on tab visible. Components subscribe to narrow state slices to minimize re-renders. The chart uses Zustand's vanilla `subscribe()` API to push data imperatively — ticks never enter React's render cycle.

- **SymbolSearch**: searchable dropdown with keyboard navigation and live price preview
- **FundamentalsBar**: horizontal ticker tape (market cap, P/E, EPS, shares, sector)
- **Chart**: TradingView lightweight-charts v5 with OHLCV candles + volume overlay
- **TickStack**: live tick feed as a ring buffer (50 desktop / 20 mobile)
- **MetricsGrid**: three tabbed cards (Performance / Volatility / Momentum) with flash-on-change animation. Mobile: scroll-snap + `IntersectionObserver` tab sync
- **StatusBar**: connection status dot + tick counter + relative timestamp

### Advanced Analytics (`/financial/avanzadas/`)

Nine `RankingBoard` components in a responsive grid, each fetching `/analytics/anomalies` for a different metric and rendering the top outliers ranked by `|z_of_z|`. Metrics covered: RSI (overbought/oversold), 1M/3M volatility, 1M return (gainers/losers), SMA-200 gap, 52-week high distance, intraday range. Every card includes an `InfoTooltip` explaining what the ranking measures.

A dense multi-metric table below lets users select any metric and browse the full `fact_derived_metrics` surface with all three z-score layers color-coded by magnitude.

### Mobile-First

Base font 12px scaling to 14px at desktop breakpoints. Touch-aware tick history cap, `safe-area-inset-bottom` for iOS, `IntersectionObserver`-driven tab sync for swipeable metric cards, Visibility API gating on WebSocket reconnect.

---

## Infrastructure

| Layer | Service | Role |
|-------|---------|------|
| **Scraping** | Dedicated VPS (residential IP, systemd timer) | TradingView WebSocket access, raw data to S3 |
| **Storage (raw)** | AWS S3 | Gzipped JSONL per symbol, Hive-partitioned Parquet bronze export |
| **Orchestration** | AWS Lambda + EventBridge | S3 event trigger parses marker file, launches Fargate task |
| **Compute** | AWS ECS Fargate | ETL processing (512 CPU / 1 GB) + API serving (256 CPU / 512 MB) |
| **OLTP** | AWS RDS PostgreSQL | Candles, fundamentals, derived metrics (5 tables) |
| **Secrets** | AWS Secrets Manager | Database URL, API tokens, GCP service account key |
| **Analytics DWH** | GCP BigQuery + dbt | Medallion warehouse: staging → intermediate → marts (17 models) |
| **CDN** | AWS CloudFront | Static React SPA + API distribution |
| **Monitoring** | AWS CloudWatch | ECS task logs, Lambda execution logs |

### Observability

Structured JSON logging via `run_context.py`. Each ETL run emits two artifacts:
- **JSONL event stream**: append-only, one JSON object per line. Stage spans measured with `perf_counter` (nanosecond precision). Thread-safe via `ContextVar` span stack.
- **JSON execution report**: run summary with per-stage status, duration, row counts, and error tracebacks.

---

## Technology Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Ingestion | Python, asyncio, TradingView WebSocket | 3.11 |
| OLTP | PostgreSQL | 16 |
| Analytics | BigQuery + dbt (dbt_utils) | dbt 1.7+ |
| Orchestration | AWS Lambda + ECS Fargate + EventBridge | — |
| API | FastAPI + Uvicorn | 0.110+ |
| Frontend | React + TypeScript (strict) | 19.2 / 5.9 |
| Build | Vite | 8.0 |
| Styling | Tailwind CSS (CSS-first) | 4.2 |
| State | Zustand | 5.0 |
| Charting | TradingView lightweight-charts | 5.1 |
| Metrics | pandas + numpy (vectorized) | 2.0+ |
| Calendar | exchange_calendars | 4.13+ |

---

## Project Structure

```
financial-data-etl/
├── financial_data_etl/               # Python package
│   ├── main_runner.py                # 7-stage ETL orchestrator
│   ├── vps_scraper/                  # Scraping node: WS capture → S3 upload
│   │   ├── runner.py                 # Entrypoint: lockfile → catalog → API plan → chunked scrape → marker
│   │   ├── chunk_orchestrator.py     # 700+ tickers in chunks of 50, raw_capture callback
│   │   └── s3_uploader.py           # gzipped JSONL + _DONE_ marker to S3
│   ├── scraping_pipeline/            # TradingView WebSocket client + parsers
│   ├── derived_metrics/              # Performance / volatility / momentum runners
│   ├── storage/                      # DB adapter (PostgreSQL / SQLite), row builders, S3 reader
│   ├── api/
│   │   ├── app.py                    # FastAPI: REST + WebSocket + analytics endpoints
│   │   ├── bq_analytics.py           # BigQuery lazy singleton + TTL cache
│   │   ├── live_seed.py              # Cold-start: 258 historical bars from RDS
│   │   ├── live_state.py             # 258-row in-memory DataFrame
│   │   ├── live_compute.py           # Pure metric math (<1ms per tick)
│   │   └── live_session_manager.py   # Per-subscriber TradingView session
│   ├── universe/                     # 700+ ticker catalog with provider mappings
│   └── observability/
│       └── run_context.py            # Structured JSONL logging + execution reports
│
├── etl_extract/                      # RDS → S3 → BigQuery bridge
│   ├── extract_to_s3.py              # RDS → Parquet (Hive-partitioned by date)
│   └── load_to_bigquery.py           # S3 Parquet → BigQuery raw tables
│
├── financial_dwh/                    # dbt project (BigQuery)
│   └── models/
│       ├── staging/                  # 8 models: typed, deduplicated, tested views
│       ├── intermediate/             # 4 models: z_intra, z_cross, z_of_z computation
│       └── marts/                    # 5 models: Kimball star schema + z-score layers
│
├── frontend/                         # React 19 + Vite 8 + TypeScript + Tailwind 4
│   └── src/
│       ├── App.tsx                   # Mini-router (2 routes, 5 LOC)
│       ├── layouts/                  # Dashboard + AdvancedAnalyticsPage
│       ├── components/               # Chart, TickStack, MetricsGrid, RankingBoard, ...
│       ├── stores/wsStore.ts         # Zustand: WS lifecycle + state slices
│       └── types/ws.ts              # Discriminated union WS protocol
│
├── aws/                              # Infrastructure definitions
│   ├── ecs/                          # API + ETL + utility task definitions
│   ├── lambda/                       # S3 marker → ECS trigger
│   ├── s3/                           # Bucket policies + event notifications
│   ├── cloudfront/                   # CDN distribution config
│   └── iam/                          # Task roles + scraper policies
│
└── catalog.json                      # 700+ tickers with TradingView provider mappings
```

---

## Key Constants

```python
LAGS       = {"ret_1d": 1, "ret_1w": 5, "ret_1m": 21, "ret_3m": 63, "ret_6m": 126, "ret_1y": 252}
VOL_WINDOWS = {"vol_1w": 5, "vol_1m": 21, "vol_3m": 63, "vol_6m": 126, "vol_1y": 252}
SMA_WINDOWS = [20, 50, 100, 200]
ANNUALIZATION_FACTOR = sqrt(252)    # ≈ 15.87

MAX_BARS           = 258            # max(252, 200) + overlap — universal window size
RECV_TIMEOUT       = 30             # WebSocket receive timeout (seconds)
SEND_TIMEOUT       = 10             # WebSocket send timeout (seconds)
SYMBOL_TIMEOUT     = 60             # Per-symbol scraping timeout (seconds)
CONNECT_MAX_RETRIES = 3             # Exponential backoff: 1s, 2s, 4s
```

---

## OLTP Schema (RDS)

| Table | Primary Key | Description |
|-------|-------------|-------------|
| `tv_candles_raw` | `(symbol, timeframe, ts)` | Daily OHLCV candles with partial-bar detection |
| `fundamentals_snapshot` | `(symbol, as_of_ts)` | Market cap, P/E, EPS, shares, sector, industry |
| `performance_1d` | `(symbol, timeframe, ts)` | Trailing returns: ret_1d → ret_1y |
| `volatility_1d` | `(symbol, timeframe, ts)` | Annualized volatility + intraday range |
| `momentum_1d` | `(symbol, timeframe, ts)` | RSI-14, SMA gaps, Donchian 52w high distance |

## Analytical Schema (BigQuery — `financial_marts`)

| Model | Grain | Description |
|-------|-------|-------------|
| `dim_date` | day | Business-day calendar with trading-day flag |
| `dim_asset` | symbol | Sector, market-cap tier, listing metadata |
| `fact_ohlcv` | symbol × day | Clean daily OHLCV, clustered by `asset_key` |
| `fact_fundamentals` | symbol × day | Forward-filled fundamental snapshots |
| `fact_derived_metrics` | symbol × day | 19 raw metrics + 9 `z_intra` + 9 `z_cross` + 9 `z_of_z` columns |
