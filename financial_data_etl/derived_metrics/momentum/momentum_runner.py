"""
Mega-batch momentum runner.

Architecture:
  1. ONE bulk SQL read for all symbols
  2. ONE pandas DataFrame
  3. Vectorized groupby rolling/ewm computations
  4. ONE bulk upsert via single connection

Metrics computed (the canonical "Momentum" tab — replaces the old Volume tab):
  - rsi_14:        14-period RSI, Wilder smoothing via ewm(alpha=1/14, adjust=False).
  - sma_20_gap:    (close - SMA_20) / SMA_20    — short-term mean reversion signal
  - sma_50_gap:    (close - SMA_50) / SMA_50    — medium-term trend signal
  - sma_200_gap:   (close - SMA_200) / SMA_200  — bull/bear regime line
  - high_dist_1m:  (close - max_high_20d) / max_high_20d   — Donchian 20 distance
  - high_dist_1y:  (close - max_high_252d) / max_high_252d — 52-week high distance
"""

from __future__ import annotations
from typing import List
import pandas as pd
from financial_data_etl.storage.database import get_connection, fetchall, PH
from financial_data_etl.derived_metrics.momentum.momentum_store import (
    init_momentum_schema,
    upsert_momentum_rows,
)

RSI_PERIOD = 14
SMA_WINDOWS = [20, 50, 200]
HIGH_WINDOWS = {
    "high_dist_1m": 20,
    "high_dist_1y": 252,
}

OVERLAP_BARS = 5
MAX_WINDOW = max(max(SMA_WINDOWS), max(HIGH_WINDOWS.values())) + OVERLAP_BARS + 1  # 258


def run_momentum_1d(symbols: List[str], ctx=None) -> None:
    if not symbols:
        return

    init_momentum_schema()
    total_symbols = 0
    total_rows = 0

    conn = get_connection()
    try:
        # ── BULK READ: one windowed query, all symbols ──
        ph_list = ",".join(PH for _ in symbols)
        raw = fetchall(conn,
            f"""
            SELECT symbol, ts, high, close, is_partial
            FROM (
                SELECT symbol, ts, high, close, is_partial,
                       ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY ts DESC) AS rn
                FROM tv_candles_raw
                WHERE timeframe='1d'
                  AND symbol IN ({ph_list})
                  AND ts IS NOT NULL AND close IS NOT NULL AND high IS NOT NULL
            ) sub
            WHERE rn <= {PH}
            ORDER BY symbol, ts ASC
            """,
            symbols + [MAX_WINDOW],
        )

        if not raw:
            return

        # ── ONE MEGA-DATAFRAME ──
        df = pd.DataFrame(raw, columns=["symbol", "ts", "high", "close", "is_partial"])

        grouped_close = df.groupby("symbol")["close"]
        grouped_high = df.groupby("symbol")["high"]

        # ── RSI 14 (Wilder/EWM, per group, no cross-symbol leakage) ──
        delta = grouped_close.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        df["_gain"] = gain
        df["_loss"] = loss

        avg_gain = df.groupby("symbol")["_gain"].transform(
            lambda s: s.ewm(alpha=1 / RSI_PERIOD, adjust=False, min_periods=RSI_PERIOD).mean()
        )
        avg_loss = df.groupby("symbol")["_loss"].transform(
            lambda s: s.ewm(alpha=1 / RSI_PERIOD, adjust=False, min_periods=RSI_PERIOD).mean()
        )
        rs = avg_gain / avg_loss.where(avg_loss > 0)
        df["rsi_14"] = 100 - (100 / (1 + rs))

        # ── SMA gaps (price) ──
        for w in SMA_WINDOWS:
            sma = grouped_close.rolling(window=w, min_periods=w).mean().droplevel(0)
            safe_sma = sma.where(sma != 0)
            df[f"sma_{w}_gap"] = df["close"] / safe_sma - 1.0

        # ── High distance (Donchian) ──
        for col, w in HIGH_WINDOWS.items():
            max_high = grouped_high.rolling(window=w, min_periods=w).max().droplevel(0)
            safe_max = max_high.where(max_high > 0)
            df[col] = df["close"] / safe_max - 1.0

        # ── OUTPUT PREP ──
        out_cols = [
            "symbol", "ts", "is_partial",
            "rsi_14",
            "sma_20_gap", "sma_50_gap", "sma_200_gap",
            "high_dist_1m", "high_dist_1y",
        ]
        df["ts"] = df["ts"].astype(int)
        df["is_partial"] = df["is_partial"].astype(int)
        records = df[out_cols].to_dict("records")
        for row in records:
            for key, val in row.items():
                if isinstance(val, float) and val != val:
                    row[key] = None

        # ── BULK WRITE: one connection, one executemany ──
        upsert_momentum_rows(records, conn=conn)
        conn.commit()

        total_symbols = int(df["symbol"].nunique())
        total_rows = len(records)

    finally:
        conn.close()

    if ctx:
        ctx.event(
            "derived_momentum_summary",
            symbols_processed=total_symbols,
            rows_upserted=total_rows,
        )
