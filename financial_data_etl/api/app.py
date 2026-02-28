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

@app.get("/")
def root():
    return {"status": "api ok"}

@app.get("/symbols")
def get_symbols():
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT DISTINCT symbol FROM tv_candles_raw ORDER BY symbol"
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()

@app.get("/ohlcv/history/{symbol}")
def get_ohlcv_history(symbol: str, limit: int = 4500):
    """
    Returns historical OHLCV candles for a given symbol.
    Max 4500 rows. Default timeframe: 1d.
    """

    # Hard cap
    limit = min(limit, 4500)

    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT ts, open, high, low, close, volume
            FROM tv_candles_raw
            WHERE symbol = ?
              AND timeframe = '1d'
              AND is_partial = 0
            ORDER BY ts DESC
            LIMIT ?
            """,
            (symbol.upper(), limit),
        ).fetchall()

        # Reverse to ascending time for chart consumption
        rows = rows[::-1]

        return [
            {
                "time": r[0],     # unix timestamp (seconds)
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
        # SQLite rows accesibles por nombre
        conn.row_factory = __import__("sqlite3").Row

        row = conn.execute(
            """
            SELECT *
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
            #"company_name": row["company_name"],
            "market_cap": row["market_cap"],
            "pe_ttm": row["pe_ttm"],
            "eps_ttm": row["eps_ttm"],
            "shares_outstanding": row["shares_outstanding"],
            "sector": row["sector"],
            "industry": row["industry"],
        }
    finally:
        conn.close()