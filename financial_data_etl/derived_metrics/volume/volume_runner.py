"""
Mega-batch volume runner.

Architecture:
  1. ONE bulk SQL read for all symbols
  2. ONE pandas DataFrame
  3. Vectorized groupby rolling mean (SMA) + gap computation
  4. ONE bulk upsert via single connection
"""

from __future__ import annotations
from typing import List
import pandas as pd
from financial_data_etl.storage.database import get_connection, fetchall, PH
from financial_data_etl.derived_metrics.volume.volume_store import (
    init_volume_schema,
    upsert_volume_rows,
)

SMA_WINDOWS = [20, 50, 100, 200]

OVERLAP_BARS = 5
MAX_WINDOW = max(SMA_WINDOWS) + OVERLAP_BARS + 1  # 206


def run_volume_1d(symbols: List[str], ctx=None) -> None:
    if not symbols:
        return

    init_volume_schema()
    total_symbols = 0
    total_rows = 0

    conn = get_connection()
    try:
        # ── BULK READ: one windowed query, all symbols ──
        ph_list = ",".join(PH for _ in symbols)
        raw = fetchall(conn,
            f"""
            SELECT symbol, ts, close, volume, is_partial
            FROM (
                SELECT symbol, ts, close, volume, is_partial,
                       ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY ts DESC) AS rn
                FROM tv_candles_raw
                WHERE timeframe='1d'
                  AND symbol IN ({ph_list})
                  AND ts IS NOT NULL AND close IS NOT NULL AND volume IS NOT NULL
            ) sub
            WHERE rn <= {PH}
            ORDER BY symbol, ts ASC
            """,
            symbols + [MAX_WINDOW],
        )

        if not raw:
            return

        # ── ONE MEGA-DATAFRAME ──
        df = pd.DataFrame(raw, columns=["symbol", "ts", "close", "volume", "is_partial"])
        df["volume_usd"] = df["close"] * df["volume"]

        # ── ROLLING SMA + GAP (per group) ──
        grouped_vusd = df.groupby("symbol")["volume_usd"]
        for w in SMA_WINDOWS:
            sma_col = f"vol_sma_{w}"
            gap_col = f"vol_gap_{w}"
            sma = grouped_vusd.rolling(window=w, min_periods=w).mean().droplevel(0)
            df[sma_col] = sma
            safe_sma = sma.where(sma != 0)
            df[gap_col] = df["volume_usd"] / safe_sma - 1.0

        # ── OUTPUT PREP ──
        out_cols = ["symbol", "ts", "volume_usd",
                    "vol_sma_20", "vol_sma_50", "vol_sma_100", "vol_sma_200",
                    "vol_gap_20", "vol_gap_50", "vol_gap_100", "vol_gap_200",
                    "is_partial"]
        df["ts"] = df["ts"].astype(int)
        df["is_partial"] = df["is_partial"].astype(int)
        records = df[out_cols].to_dict("records")
        for row in records:
            for key, val in row.items():
                if isinstance(val, float) and val != val:
                    row[key] = None

        # ── BULK WRITE: one connection, one executemany ──
        upsert_volume_rows(records, conn=conn)
        conn.commit()

        total_symbols = int(df["symbol"].nunique())
        total_rows = len(records)

    finally:
        conn.close()

    if ctx:
        ctx.event(
            "derived_volume_summary",
            symbols_processed=total_symbols,
            rows_upserted=total_rows,
        )
