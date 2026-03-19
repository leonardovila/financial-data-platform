"""
Live in-memory compute kernels (LIVE-03).

Pure functions: DataFrame in → metrics dict out.
Zero SQLite. Zero disk. Zero schema init.

Mathematical purity guarantee: constants (LAGS, VOL_WINDOWS, SMA_WINDOWS,
ANNUALIZATION_FACTOR) are IMPORTED from the batch runners — not duplicated.
If the batch math changes, the live math changes identically.
"""

from __future__ import annotations
import math
from typing import Dict, Any, Optional
import pandas as pd
import numpy as np

# ── Import constants from the batch runners (single source of truth) ──
from financial_data_etl.derived_metrics.price_performance.price_performance_runner import LAGS
from financial_data_etl.derived_metrics.volatility.volatility_runner import (
    VOL_WINDOWS,
    ANNUALIZATION_FACTOR,
)
from financial_data_etl.derived_metrics.volume.volume_runner import SMA_WINDOWS


def _safe(val: float) -> Optional[float]:
    """Convert NaN / inf / -inf to None for JSON serialization."""
    if isinstance(val, float) and (val != val or math.isinf(val)):
        return None
    return val


# ──────────────────────────────────────────────────────────────────────────────
# PERFORMANCE: returns relative to N-day-ago close
#
# Batch math (price_performance_runner.py:70-74):
#   shifted = grouped_close.shift(lag)
#   safe_shifted = shifted.where(shifted != 0.0)
#   df[col] = df["close"] / safe_shifted - 1.0
#
# Live equivalent: O(1) per lag via direct index arithmetic.
# close.shift(lag).iloc[-1] == close.iloc[-1-lag]  (mathematically identical)
# ──────────────────────────────────────────────────────────────────────────────

def compute_performance_live(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Compute price performance returns for the LAST bar.

    Args:
        df: DataFrame with column 'close', sorted by ts ASC.

    Returns:
        {ret_1d, ret_1w, ret_1m, ret_3m, ret_6m, ret_1y} — all float or None.
    """
    close = df["close"]
    n = len(close)
    if n == 0:
        return {col: None for col in LAGS}

    current = float(close.iloc[-1])
    result: Dict[str, Any] = {}

    for col, lag in LAGS.items():
        if n > lag:
            past = float(close.iloc[-1 - lag])
            if past != 0.0:
                result[col] = _safe(current / past - 1.0)
            else:
                result[col] = None
        else:
            result[col] = None

    return result


# ──────────────────────────────────────────────────────────────────────────────
# VOLATILITY: annualized rolling std of log returns + intraday range
#
# Batch math (volatility_runner.py:72-85):
#   prev_close = df.groupby("symbol")["close"].shift(1)
#   log_ret = np.log(df["close"] / prev_close.where(prev_close > 0))
#   log_ret = log_ret.where(np.isfinite(log_ret))
#   df["range_intraday"] = ((df["high"] - df["low"]) / df["close"])
#   for col, window in VOL_WINDOWS.items():
#       rolled = grouped_lr.rolling(window=window, min_periods=window).std()
#       df[col] = rolled.droplevel(0) * ANNUALIZATION_FACTOR
#
# Live equivalent: compute log_ret series once (O(n)), then O(window) std
# for each window by slicing the last `window` values.
# rolling(w, min_periods=w).std().iloc[-1] == log_ret.iloc[-w:].std(ddof=1)
# ONLY when all w values are non-NaN (matching min_periods=w behavior).
# ──────────────────────────────────────────────────────────────────────────────

def compute_volatility_live(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Compute annualized volatility metrics for the LAST bar.

    Args:
        df: DataFrame with columns 'high', 'low', 'close', sorted by ts ASC.

    Returns:
        {range_intraday, vol_1w, vol_1m, vol_3m, vol_6m, vol_1y} — float or None.
    """
    n = len(df)
    if n < 2:
        return {"range_intraday": None, **{col: None for col in VOL_WINDOWS}}

    close = df["close"]
    high = df["high"]
    low = df["low"]

    # ── Range intraday (last bar only) ──
    last_close = float(close.iloc[-1])
    if last_close != 0.0:
        range_intraday = _safe(
            float((high.iloc[-1] - low.iloc[-1]) / last_close)
        )
    else:
        range_intraday = None

    # ── Log returns: O(n) series computation ──
    prev_close = close.shift(1)
    safe_prev = prev_close.where(prev_close > 0)
    log_ret = np.log(close / safe_prev)
    log_ret = log_ret.where(np.isfinite(log_ret))

    # ── Rolling std per window: O(window) slice + std ──
    result: Dict[str, Any] = {"range_intraday": range_intraday}

    for col, window in VOL_WINDOWS.items():
        if n > window:
            window_slice = log_ret.iloc[-window:]
            # Match min_periods=window: ALL values must be non-NaN
            if not window_slice.isna().any():
                vol = float(window_slice.std(ddof=1)) * ANNUALIZATION_FACTOR
                result[col] = _safe(vol)
            else:
                result[col] = None
        else:
            result[col] = None

    return result


# ──────────────────────────────────────────────────────────────────────────────
# VOLUME: volume_usd SMA + gap (deviation from SMA)
#
# Batch math (volume_runner.py:60-70):
#   df["volume_usd"] = df["close"] * df["volume"]
#   for w in SMA_WINDOWS:
#       sma = grouped_vusd.rolling(window=w, min_periods=w).mean().droplevel(0)
#       df[f"vol_sma_{w}"] = sma
#       safe_sma = sma.where(sma != 0)
#       df[f"vol_gap_{w}"] = df["volume_usd"] / safe_sma - 1.0
#
# Live equivalent: compute volume_usd once (O(n)), then O(window) mean
# for each SMA window.
# rolling(w, min_periods=w).mean().iloc[-1] == volume_usd.iloc[-w:].mean()
# ONLY when all w values are non-NaN.
# ──────────────────────────────────────────────────────────────────────────────

def compute_volume_live(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Compute volume metrics for the LAST bar.

    Args:
        df: DataFrame with columns 'close', 'volume', sorted by ts ASC.

    Returns:
        {volume_usd, vol_sma_20, vol_sma_50, vol_sma_100, vol_sma_200,
         vol_gap_20, vol_gap_50, vol_gap_100, vol_gap_200} — float or None.
    """
    n = len(df)
    if n == 0:
        keys = ["volume_usd"]
        for w in SMA_WINDOWS:
            keys += [f"vol_sma_{w}", f"vol_gap_{w}"]
        return {k: None for k in keys}

    # ── Volume USD: O(n) once ──
    volume_usd_series = df["close"] * df["volume"]
    current_vusd = float(volume_usd_series.iloc[-1])

    result: Dict[str, Any] = {"volume_usd": _safe(current_vusd)}

    # ── SMA + gap per window: O(window) slice + mean ──
    for w in SMA_WINDOWS:
        sma_col = f"vol_sma_{w}"
        gap_col = f"vol_gap_{w}"

        if n >= w:
            window_slice = volume_usd_series.iloc[-w:]
            # Match min_periods=w: ALL values must be non-NaN
            if not window_slice.isna().any():
                sma = float(window_slice.mean())
                result[sma_col] = _safe(sma)
                if sma != 0.0:
                    result[gap_col] = _safe(current_vusd / sma - 1.0)
                else:
                    result[gap_col] = None
            else:
                result[sma_col] = None
                result[gap_col] = None
        else:
            result[sma_col] = None
            result[gap_col] = None

    return result


# ──────────────────────────────────────────────────────────────────────────────
# UNIFIED ENTRY POINT: all 3 metrics in one call
# ──────────────────────────────────────────────────────────────────────────────

def compute_all_metrics_live(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Compute all derived metrics for the LAST bar of a single-symbol DataFrame.

    This is the single entry point called by LiveSymbolState.compute_metrics()
    via loop.run_in_executor(). The df should be a COPY (get_df_snapshot())
    to avoid data races with concurrent tick updates.

    Args:
        df: DataFrame with columns [ts, open, high, low, close, volume],
            sorted by ts ASC, max 258 rows.

    Returns:
        {
            "performance": {ret_1d, ret_1w, ...},
            "volatility": {range_intraday, vol_1w, ...},
            "volume": {volume_usd, vol_sma_20, vol_gap_20, ...},
        }
    """
    return {
        "performance": compute_performance_live(df),
        "volatility": compute_volatility_live(df),
        "volume": compute_volume_live(df),
    }
