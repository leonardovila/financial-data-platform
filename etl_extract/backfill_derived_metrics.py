"""
Backfill histórico de métricas derivadas (one-off)
===================================================
Propósito:
  Los runners de derived_metrics (volatility/performance/momentum) procesan
  solo las últimas 258 barras por símbolo (ventana diseñada para update diario).
  Esto dejó las tablas *_1d con ~12k filas vs 305k filas de tv_candles_raw.

  Este script reconstruye el histórico completo:
    1. Lee TODO tv_candles_raw (timeframe=1d) de una sola vez.
    2. Computa las 3 métricas sobre el DataFrame completo.
    3. Upsert a volatility_1d / performance_1d / momentum_1d.

Idempotente: los upserts reemplazan filas existentes por (symbol, ts).

Requisitos:
  DATABASE_URL en env (postgresql://...?sslmode=require)
"""

from __future__ import annotations

import math
import os
import time

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

from financial_data_etl.derived_metrics.momentum.momentum_store import (
    init_momentum_schema,
    upsert_momentum_rows,
)
from financial_data_etl.derived_metrics.price_performance.price_performance_store import (
    init_performance_schema,
    upsert_performance_rows,
)
from financial_data_etl.derived_metrics.volatility.volatility_store import (
    init_volatility_schema,
    upsert_volatility_rows,
)
from financial_data_etl.storage.database import get_connection

# ── Constantes idénticas a los runners originales ──────────────────────────────

VOL_WINDOWS = {
    "vol_1w": 5,
    "vol_1m": 21,
    "vol_3m": 63,
    "vol_6m": 126,
    "vol_1y": 252,
}
ANNUALIZATION_FACTOR = math.sqrt(252)

LAGS = {
    "ret_1d": 1,
    "ret_1w": 5,
    "ret_1m": 21,
    "ret_3m": 63,
    "ret_6m": 126,
    "ret_1y": 252,
}

RSI_PERIOD = 14
SMA_WINDOWS = [20, 50, 200]
HIGH_WINDOWS = {
    "high_dist_1m": 20,
    "high_dist_1y": 252,
}


# ── Lectura única ──────────────────────────────────────────────────────────────

def load_all_candles() -> pd.DataFrame:
    url = os.environ["DATABASE_URL"]
    engine = create_engine(url)
    q = """
        SELECT symbol, ts, high, low, close, is_partial
        FROM tv_candles_raw
        WHERE timeframe = '1d'
          AND ts IS NOT NULL
          AND close IS NOT NULL
          AND high IS NOT NULL
          AND low IS NOT NULL
        ORDER BY symbol, ts ASC
    """
    print("[load] SELECT tv_candles_raw WHERE timeframe='1d' (sin LIMIT)...")
    t0 = time.time()
    with engine.connect() as conn:
        df = pd.read_sql(text(q), conn)
    elapsed = time.time() - t0
    print(f"[load]   {len(df):,} filas, {df['symbol'].nunique():,} símbolos, {elapsed:.1f}s")
    return df


# ── Cálculos (mismas fórmulas que los runners) ────────────────────────────────

def compute_volatility(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    grouped_close = df.groupby("symbol")["close"]
    prev_close = grouped_close.shift(1)
    log_ret = np.log(df["close"] / prev_close.where(prev_close > 0))
    log_ret = log_ret.where(np.isfinite(log_ret))
    df["_log_ret"] = log_ret

    df["range_intraday"] = ((df["high"] - df["low"]) / df["close"]).where(df["close"] != 0)

    grouped_lr = df.groupby("symbol")["_log_ret"]
    for col, window in VOL_WINDOWS.items():
        rolled = grouped_lr.rolling(window=window, min_periods=window).std()
        df[col] = rolled.droplevel(0) * ANNUALIZATION_FACTOR
    return df


def compute_performance(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    grouped_close = df.groupby("symbol")["close"]
    for col, lag in LAGS.items():
        shifted = grouped_close.shift(lag)
        safe_shifted = shifted.where(shifted != 0.0)
        df[col] = df["close"] / safe_shifted - 1.0
    return df


def compute_momentum(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    grouped_close = df.groupby("symbol")["close"]
    grouped_high = df.groupby("symbol")["high"]

    # RSI 14 (Wilder vía EWM)
    delta = grouped_close.diff()
    df["_gain"] = delta.clip(lower=0)
    df["_loss"] = (-delta).clip(lower=0)
    avg_gain = df.groupby("symbol")["_gain"].transform(
        lambda s: s.ewm(alpha=1 / RSI_PERIOD, adjust=False, min_periods=RSI_PERIOD).mean()
    )
    avg_loss = df.groupby("symbol")["_loss"].transform(
        lambda s: s.ewm(alpha=1 / RSI_PERIOD, adjust=False, min_periods=RSI_PERIOD).mean()
    )
    rs = avg_gain / avg_loss.where(avg_loss > 0)
    df["rsi_14"] = 100 - (100 / (1 + rs))

    # SMA gaps
    for w in SMA_WINDOWS:
        sma = grouped_close.rolling(window=w, min_periods=w).mean().droplevel(0)
        df[f"sma_{w}_gap"] = df["close"] / sma.where(sma != 0) - 1.0

    # High distances
    for col, w in HIGH_WINDOWS.items():
        max_high = grouped_high.rolling(window=w, min_periods=w).max().droplevel(0)
        df[col] = df["close"] / max_high.where(max_high > 0) - 1.0

    return df


# ── Prep de records para el upsert ────────────────────────────────────────────

def records_from_df(df: pd.DataFrame, cols: list[str]) -> list[dict]:
    df = df.copy()
    df["ts"] = df["ts"].astype(int)
    df["is_partial"] = df["is_partial"].astype(int)
    records = df[cols].to_dict("records")
    # NaN → None
    for row in records:
        for key, val in row.items():
            if isinstance(val, float) and val != val:
                row[key] = None
    return records


# ── Upsert helpers con conexión dedicada ──────────────────────────────────────

def _upsert(upsert_fn, records, table_name):
    print(f"[upsert] {table_name}: {len(records):,} filas...")
    t0 = time.time()
    conn = get_connection()
    try:
        upsert_fn(records, conn=conn)
        conn.commit()
    finally:
        conn.close()
    print(f"[upsert]   done in {time.time() - t0:.1f}s")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("Backfill histórico de métricas derivadas")
    print("=" * 70)

    # Init schemas (idempotent)
    init_volatility_schema()
    init_performance_schema()
    init_momentum_schema()

    # Read once
    df = load_all_candles()
    if df.empty:
        print("[abort] tv_candles_raw vacía")
        return

    # ── VOLATILITY ──
    print("\n[compute] volatility...")
    t0 = time.time()
    df_v = compute_volatility(df)
    print(f"[compute]   done in {time.time() - t0:.1f}s")
    vol_cols = ["symbol", "ts", "is_partial", "range_intraday"] + list(VOL_WINDOWS.keys())
    _upsert(upsert_volatility_rows, records_from_df(df_v, vol_cols), "volatility_1d")
    del df_v

    # ── PERFORMANCE ──
    print("\n[compute] performance...")
    t0 = time.time()
    df_p = compute_performance(df)
    print(f"[compute]   done in {time.time() - t0:.1f}s")
    perf_cols = ["symbol", "ts", "is_partial"] + list(LAGS.keys())
    _upsert(upsert_performance_rows, records_from_df(df_p, perf_cols), "performance_1d")
    del df_p

    # ── MOMENTUM ──
    print("\n[compute] momentum...")
    t0 = time.time()
    df_m = compute_momentum(df)
    print(f"[compute]   done in {time.time() - t0:.1f}s")
    mom_cols = [
        "symbol", "ts", "is_partial",
        "rsi_14",
        "sma_20_gap", "sma_50_gap", "sma_200_gap",
        "high_dist_1m", "high_dist_1y",
    ]
    _upsert(upsert_momentum_rows, records_from_df(df_m, mom_cols), "momentum_1d")
    del df_m

    print("\n" + "=" * 70)
    print("BACKFILL DONE")
    print("=" * 70)


if __name__ == "__main__":
    main()
