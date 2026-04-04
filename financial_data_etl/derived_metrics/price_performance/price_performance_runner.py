"""
Mega-batch price performance runner.

Architecture:
  1. ONE bulk SQL read for all symbols
  2. ONE pandas DataFrame
  3. Vectorized groupby returns (shift + division)
  4. ONE bulk upsert via single connection
"""

from __future__ import annotations
from typing import List
import pandas as pd
from financial_data_etl.storage.database import get_connection, fetchall, PH
from financial_data_etl.derived_metrics.price_performance.price_performance_store import (
    init_performance_schema,
    upsert_performance_rows,
)

LAGS = {
    "ret_1d": 1,
    "ret_1w": 5,
    "ret_1m": 21,
    "ret_3m": 63,
    "ret_6m": 126,
    "ret_1y": 252,
}

OVERLAP_BARS = 5
MAX_LAG = max(LAGS.values())  # 252
WINDOW_BARS = MAX_LAG + OVERLAP_BARS + 1  # 258


def run_price_performance_1d(symbols: List[str], ctx=None) -> None:
    if not symbols:
        return

    init_performance_schema()
    total_symbols = 0
    total_rows = 0

    conn = get_connection()
    try:
        # ── BULK READ: one windowed query, all symbols ──
        ph_list = ",".join(PH for _ in symbols)
        raw = fetchall(conn,
            f"""
            SELECT symbol, ts, close, is_partial
            FROM (
                SELECT symbol, ts, close, is_partial,
                       ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY ts DESC) AS rn
                FROM tv_candles_raw
                WHERE timeframe='1d'
                  AND symbol IN ({ph_list})
                  AND ts IS NOT NULL AND close IS NOT NULL
            ) sub
            WHERE rn <= {PH}
            ORDER BY symbol, ts ASC
            """,
            symbols + [WINDOW_BARS],
        )

        if not raw:
            return

        # ── ONE MEGA-DATAFRAME ──
        df = pd.DataFrame(raw, columns=["symbol", "ts", "close", "is_partial"])

        # ── VECTORIZED GROUPBY RETURNS ──
        grouped_close = df.groupby("symbol")["close"]
        for col, lag in LAGS.items():
            shifted = grouped_close.shift(lag)
            safe_shifted = shifted.where(shifted != 0.0)
            df[col] = df["close"] / safe_shifted - 1.0

        # ── OUTPUT PREP ──
        out_cols = ["symbol", "ts", "is_partial"] + list(LAGS.keys())
        df["ts"] = df["ts"].astype(int)
        df["is_partial"] = df["is_partial"].astype(int)
        records = df[out_cols].to_dict("records")
        for row in records:
            for key, val in row.items():
                if isinstance(val, float) and val != val:
                    row[key] = None

        # ── BULK WRITE: one connection, one executemany ──
        upsert_performance_rows(records, conn=conn)
        conn.commit()

        total_symbols = int(df["symbol"].nunique())
        total_rows = len(records)

    finally:
        conn.close()

    if ctx:
        ctx.event(
            "derived_price_performance_summary",
            symbols_processed=total_symbols,
            rows_upserted=total_rows,
        )
