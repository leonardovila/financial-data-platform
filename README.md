# Summary

financial_data_etl is an incremental end-to-end data pipeline for US equity market data.
It extracts historical data from TradingView, persists structured time-series into SQLite, and computes multi-horizon derived metrics.

# Quick Start – Local Installation

## Requirements

- Python ≥ 3.10
- Git installed
- Internet connection (required to fetch market data)

## 1. Clone the repository

Open a terminal and navigate to the directory where you want to download the project (for example, your Desktop):

```bash
git clone https://github.com/leonardovila/financial-data-etl.git
cd financial-data-etl
```

You are now inside the project root directory.

## 2. Create and activate a virtual environment

Using a dedicated virtual environment is strongly recommended to isolate dependencies.

### Windows (PowerShell)

```bash
python -m venv .venv
.venv\Scripts\activate
```

### macOS / Linux

```bash
python -m venv .venv
source .venv/bin/activate
```

After activation, your terminal should display `(.venv)` at the beginning of the line.

## 3. Install the project (editable mode)

```bash
pip install -e .
```

This installs:

- The `financial_data_etl` package
- All required dependencies defined in `pyproject.toml`

## 4. Run a test execution

Execute a test run using a single asset:

```bash
python -m financial_data_etl.main_runner --assets NVDA
```

If everything is configured correctly, the system will:

- Fetch historical market data from TradingView
- Persist OHLCV and fundamentals into SQLite
- Compute derived metrics (price performance, volatility, volume)
- Generate structured logs and runtime artifacts

## Expected Output

After successful execution, the project root directory will contain:

#### `financial_data_etl.db`

SQLite database containing all persisted tables (extracted market data, fundamentals, derived metrics).

#### `logs/`

Structured execution logs generated through the internal run context system.

#### `ws_traces/`

Raw websocket traces from TradingView sessions.

#### `catalog.json`

Local runtime copy of the equity catalog (~2400+ US-listed equities).

---

# Understanding the Output

After execution, the generated SQLite database contains both extracted market data and derived metrics.

## Why are there NULL values in some columns?

In tables such as `performance_1d`, `volatility_1d`, and `volume_1d`, some columns may contain `NULL` values at the beginning of the dataset.

This is expected behavior.

Many derived metrics require a minimum historical window before they can be computed. For example:

- A 1-month metric requires approximately one month of prior data.
- A 1-year metric requires approximately one year of prior data.

Until sufficient historical data is available, those fields will remain `NULL` by design.

This does not indicate a system error.

## Table Overview

### `tv_candles_raw`

Original daily market data (Open, High, Low, Close, Volume) extracted from TradingView.  
All derived metrics are computed from this table.

### `fundamentals_snapshot`

Fundamental data extracted from TradingView (market cap, shares outstanding, sector, industry, etc.).

### `performance_1d`

Multi-horizon price performance metrics (returns over different time windows).

### `volatility_1d`

Rolling volatility metrics computed from daily price movements.

### `volume_1d`

Derived volume-based metrics calculated from raw trading volume.

---

# System Overview

This system performs a complete end-to-end data workflow for market data:

1. It scrapes raw market and fundamental data from TradingView.
2. It cleans and normalizes the collected data.
3. It persists the cleaned data into a local database.
4. It computes additional derived metrics based on the original data.
5. It stores those derived metrics alongside the original data.

The result is a structured dataset that includes both source data and analytical outputs, enabling further analysis or integration with other tools.

---

# How to Use

The pipeline can be executed in different modes depending on the scope of data you want to process.

## 1. Run for selected assets

You can specify one or multiple tickers using the `--assets` flag:

```bash
python -m financial_data_etl.main_runner --assets NVDA
python -m financial_data_etl.main_runner --assets NVDA TSLA COST KO
```

This will scrape, process, and persist data only for the specified symbols.

---

## 2. Run for an entire index (universe)

You can execute the pipeline for predefined US equity indexes:

- `--spx` → S&P 500  
- `--ndx` → Nasdaq 100  
- `--rut` → Russell 2000  
- `--dji` → Dow Jones Industrial Average  

Example:

```bash
python -m financial_data_etl.main_runner --dji
```

The Dow Jones index contains 30 equities, making it a good option for testing a full-index execution with moderate load.

---

## 3. Running multiple indexes

You may combine index flags:

```bash
python -m financial_data_etl.main_runner --spx --ndx
```

Keep in mind that running large indexes simultaneously (e.g., S&P 500 + Russell 2000) will significantly increase execution time and system load, as thousands of equities may be processed.

---

## 4. Updating index composition

Index compositions may change over time due to additions or removals of constituents.

To refresh the local catalog with the latest index composition, use:

```bash
python -m financial_data_etl.main_runner --spx --update-universe
```

When `--update-universe` is enabled:

- The system retrieves the current index composition.
- The local catalog is updated accordingly.
- Subsequent runs will reflect the updated universe.

This ensures that the system remains aligned with real-world index changes.