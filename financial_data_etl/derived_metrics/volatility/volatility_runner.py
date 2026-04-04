"""
Mega-batch volatility runner.

Architecture:
  1. ONE bulk SQL read for all symbols
  2. ONE pandas DataFrame
  3. Vectorized groupby log-returns + rolling std (ddof=1) * sqrt(252)
  4. ONE bulk upsert via single connection
"""

from __future__ import annotations
import math
from typing import List
import pandas as pd
import numpy as np
from financial_data_etl.storage.database import get_connection, fetchall, PH
from financial_data_etl.derived_metrics.volatility.volatility_store import (
    init_volatility_schema,
    upsert_volatility_rows,
)

VOL_WINDOWS = {
    "vol_1w": 5,
    "vol_1m": 21,
    "vol_3m": 63,
    "vol_6m": 126,
    "vol_1y": 252,
}

OVERLAP_BARS = 5
MAX_LAG = max(VOL_WINDOWS.values())  # 252
WINDOW_BARS = MAX_LAG + OVERLAP_BARS + 1  # 258
ANNUALIZATION_FACTOR = math.sqrt(252)


def run_volatility_1d(symbols: List[str], ctx=None) -> None:
    if not symbols:
        return

    init_volatility_schema()
    total_symbols = 0
    total_rows = 0

    conn = get_connection()
    try:
        # ── BULK READ: one windowed query, all symbols ──
        ph_list = ",".join(PH for _ in symbols)
        raw = fetchall(conn,
            f"""
            SELECT symbol, ts, high, low, close, is_partial
            FROM (
                SELECT symbol, ts, high, low, close, is_partial,
                       ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY ts DESC) AS rn
                FROM tv_candles_raw
                WHERE timeframe='1d'
                  AND symbol IN ({ph_list})
                  AND ts IS NOT NULL AND close IS NOT NULL
                  AND high IS NOT NULL AND low IS NOT NULL
            ) sub
            WHERE rn <= {PH}
            ORDER BY symbol, ts ASC
            """,
            symbols + [WINDOW_BARS],
        )

        if not raw:
            return

        # ── ONE MEGA-DATAFRAME ──
        df = pd.DataFrame(raw, columns=["symbol", "ts", "high", "low", "close", "is_partial"])

        # ── LOG RETURNS (per group, no cross-symbol leakage) ──
        prev_close = df.groupby("symbol")["close"].shift(1)
        log_ret = np.log(df["close"] / prev_close.where(prev_close > 0))
        log_ret = log_ret.where(np.isfinite(log_ret))
        df["_log_ret"] = log_ret

        # ── RANGE INTRADAY ──
        df["range_intraday"] = ((df["high"] - df["low"]) / df["close"]).where(df["close"] != 0)

        # ── ROLLING ANNUALIZED VOLATILITY (per group) ──
        grouped_lr = df.groupby("symbol")["_log_ret"]
        for col, window in VOL_WINDOWS.items():
            rolled = grouped_lr.rolling(window=window, min_periods=window).std()
            df[col] = rolled.droplevel(0) * ANNUALIZATION_FACTOR

        # ── OUTPUT PREP ──
        metric_cols = ["range_intraday"] + list(VOL_WINDOWS.keys())
        out_cols = ["symbol", "ts", "is_partial"] + metric_cols
        df["ts"] = df["ts"].astype(int)
        df["is_partial"] = df["is_partial"].astype(int)
        records = df[out_cols].to_dict("records")
        for row in records:
            for key, val in row.items():
                if isinstance(val, float) and val != val:
                    row[key] = None

        # ── BULK WRITE: one connection, one executemany ──
        upsert_volatility_rows(records, conn=conn)
        conn.commit()

        total_symbols = int(df["symbol"].nunique())
        total_rows = len(records)

    finally:
        conn.close()

    if ctx:
        ctx.event(
            "derived_volatility_summary",
            symbols_processed=total_symbols,
            rows_upserted=total_rows,
        )
