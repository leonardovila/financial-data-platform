import sqlite3
import time
from fastapi import FastAPI
from financial_data_etl.api.db import get_connection
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="financial-data-etl api")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── TTL cache for /symbols (symbols change at most once per ETL run) ──
_symbols_cache: list | None = None
_symbols_cache_ts: float = 0.0
_SYMBOLS_TTL = 300  # 5 minutes


@app.get("/")
def root():
    return {"status": "api ok"}


@app.get("/symbols")
def get_symbols():
    global _symbols_cache, _symbols_cache_ts

    now = time.monotonic()
    if _symbols_cache is not None and (now - _symbols_cache_ts) < _SYMBOLS_TTL:
        return _symbols_cache

    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT DISTINCT symbol FROM tv_candles_raw ORDER BY symbol"
        ).fetchall()
        _symbols_cache = [r[0] for r in rows]
        _symbols_cache_ts = now
        return _symbols_cache
    finally:
        conn.close()


@app.get("/ohlcv/history/{symbol}")
def get_ohlcv_history(symbol: str, limit: int = 4500):
    """
    Returns historical OHLCV candles for a given symbol.
    Max 4500 rows. Default timeframe: 1d.
    """
    limit = min(limit, 4500)

    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT ts, open, high, low, close, volume
            FROM (
                SELECT ts, open, high, low, close, volume
                FROM tv_candles_raw
                WHERE symbol = ?
                  AND timeframe = '1d'
                  AND is_partial = 0
                ORDER BY ts DESC
                LIMIT ?
            )
            ORDER BY ts ASC
            """,
            (symbol.upper(), limit),
        ).fetchall()

        return [
            {
                "time": r[0],
                "open": r[1],
                "high": r[2],
                "low": r[3],
                "close": r[4],
                "volume": r[5],
            }
            for r in rows
        ]

    finally:
        conn.close()


@app.get("/fundamentals/{symbol}")
def get_latest_fundamentals(symbol: str):
    conn = get_connection()
    try:
        conn.row_factory = sqlite3.Row

        row = conn.execute(
            """
            SELECT symbol, as_of_ts, company_name, market_cap,
                   pe_ttm, eps_ttm, shares_outstanding, sector, industry
            FROM fundamentals_snapshot
            WHERE symbol = ?
            ORDER BY as_of_ts DESC
            LIMIT 1
            """,
            (symbol.upper(),),
        ).fetchone()

        if not row:
            return {"symbol": symbol.upper(), "data": None}

        return {
            "symbol": row["symbol"],
            "as_of_ts": row["as_of_ts"],
            "company_name": row["company_name"],
            "market_cap": row["market_cap"],
            "pe_ttm": row["pe_ttm"],
            "eps_ttm": row["eps_ttm"],
            "shares_outstanding": row["shares_outstanding"],
            "sector": row["sector"],
            "industry": row["industry"],
        }
    finally:
        conn.close()


@app.get("/performance/1d/{symbol}")
def get_latest_performance_1d(symbol: str):
    conn = get_connection()
    try:
        conn.row_factory = sqlite3.Row

        row = conn.execute(
            """
            SELECT symbol, ts, ret_1d, ret_1w, ret_1m, ret_3m, ret_6m, ret_1y, computed_at
            FROM performance_1d
            WHERE symbol = ?
              AND is_partial = 0
            ORDER BY ts DESC
            LIMIT 1
            """,
            (symbol.upper(),),
        ).fetchone()

        if not row:
            return {"symbol": symbol.upper(), "data": None}

        return {
            "symbol": row["symbol"],
            "ts": row["ts"],
            "ret_1d": row["ret_1d"],
            "ret_1w": row["ret_1w"],
            "ret_1m": row["ret_1m"],
            "ret_3m": row["ret_3m"],
            "ret_6m": row["ret_6m"],
            "ret_1y": row["ret_1y"],
            "computed_at": row["computed_at"],
        }

    finally:
        conn.close()


@app.get("/volatility/1d/{symbol}")
def get_latest_volatility_1d(symbol: str):
    conn = get_connection()
    try:
        conn.row_factory = sqlite3.Row

        row = conn.execute(
            """
            SELECT symbol, ts, range_intraday, vol_1w, vol_1m, vol_3m, vol_6m, vol_1y, computed_at
            FROM volatility_1d
            WHERE symbol = ?
              AND is_partial = 0
            ORDER BY ts DESC
            LIMIT 1
            """,
            (symbol.upper(),),
        ).fetchone()

        if not row:
            return {"symbol": symbol.upper(), "data": None}

        return {
            "symbol": row["symbol"],
            "ts": row["ts"],
            "range_intraday": row["range_intraday"],
            "vol_1w": row["vol_1w"],
            "vol_1m": row["vol_1m"],
            "vol_3m": row["vol_3m"],
            "vol_6m": row["vol_6m"],
            "vol_1y": row["vol_1y"],
            "computed_at": row["computed_at"],
        }

    finally:
        conn.close()


@app.get("/volume/1d/{symbol}")
def get_latest_volume_1d(symbol: str):
    conn = get_connection()
    try:
        conn.row_factory = sqlite3.Row

        row = conn.execute(
            """
            SELECT symbol, ts, volume_usd, vol_sma_20, vol_sma_50, vol_sma_100, vol_sma_200,
                   vol_gap_20, vol_gap_50, vol_gap_100, vol_gap_200
            FROM volume_1d
            WHERE symbol = ?
              AND is_partial = 0
            ORDER BY ts DESC
            LIMIT 1
            """,
            (symbol.upper(),),
        ).fetchone()

        if not row:
            return {"symbol": symbol.upper(), "data": None}

        return {
            "symbol": row["symbol"],
            "ts": row["ts"],
            "volume_usd": row["volume_usd"],
            "vol_sma_20": row["vol_sma_20"],
            "vol_sma_50": row["vol_sma_50"],
            "vol_sma_100": row["vol_sma_100"],
            "vol_sma_200": row["vol_sma_200"],
            "vol_gap_20": row["vol_gap_20"],
            "vol_gap_50": row["vol_gap_50"],
            "vol_gap_100": row["vol_gap_100"],
            "vol_gap_200": row["vol_gap_200"],
        }

    finally:
        conn.close()
