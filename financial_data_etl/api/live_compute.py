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
from financial_data_etl.derived_metrics.momentum.momentum_runner import (
    RSI_PERIOD,
    SMA_WINDOWS,
    HIGH_WINDOWS,
)


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
# MOMENTUM: RSI + SMA gaps + Donchian high distances
#
# Batch math (momentum_runner.py): see module-level constants RSI_PERIOD,
# SMA_WINDOWS, HIGH_WINDOWS imported above. The batch path uses
# groupby+ewm/rolling; the live path applies the same primitives to a
# single-symbol DataFrame, so the results converge mathematically when both
# see the same trailing window of bars.
#
# RSI 14 caveat: ewm is path-dependent. Live and batch must operate on the
# same trailing 258-bar slice for the result to match within 1e-10. This
# holds in production because LiveSymbolState keeps exactly that many bars.
# ──────────────────────────────────────────────────────────────────────────────

def compute_momentum_live(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Compute momentum metrics for the LAST bar.

    Args:
        df: DataFrame with columns 'high', 'close', sorted by ts ASC.

    Returns:
        {rsi_14,
         sma_20_gap, sma_50_gap, sma_200_gap,
         high_dist_1m, high_dist_1y} — float or None.
    """
    keys = ["rsi_14"] + [f"sma_{w}_gap" for w in SMA_WINDOWS] + list(HIGH_WINDOWS.keys())

    n = len(df)
    if n == 0:
        return {k: None for k in keys}

    close = df["close"]
    high = df["high"]
    last_close = float(close.iloc[-1])

    result: Dict[str, Any] = {}

    # ── RSI 14 (Wilder/EWM, single-symbol slice) ──
    if n > RSI_PERIOD:
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_gain = gain.ewm(alpha=1 / RSI_PERIOD, adjust=False, min_periods=RSI_PERIOD).mean()
        avg_loss = loss.ewm(alpha=1 / RSI_PERIOD, adjust=False, min_periods=RSI_PERIOD).mean()
        last_avg_gain = float(avg_gain.iloc[-1])
        last_avg_loss = float(avg_loss.iloc[-1])
        if last_avg_gain != last_avg_gain or last_avg_loss != last_avg_loss:
            # NaN propagation: not enough warmup
            result["rsi_14"] = None
        elif last_avg_loss == 0.0:
            # All gains, no losses → RSI saturates to 100 (matches batch)
            result["rsi_14"] = 100.0 if last_avg_gain > 0 else None
        else:
            rs = last_avg_gain / last_avg_loss
            result["rsi_14"] = _safe(100 - (100 / (1 + rs)))
    else:
        result["rsi_14"] = None

    # ── SMA gaps: O(w) slice + mean ──
    for w in SMA_WINDOWS:
        col = f"sma_{w}_gap"
        if n >= w:
            window_slice = close.iloc[-w:]
            if not window_slice.isna().any():
                sma = float(window_slice.mean())
                if sma != 0.0:
                    result[col] = _safe(last_close / sma - 1.0)
                else:
                    result[col] = None
            else:
                result[col] = None
        else:
            result[col] = None

    # ── High distance (Donchian): O(w) slice + max ──
    for col, w in HIGH_WINDOWS.items():
        if n >= w:
            window_slice = high.iloc[-w:]
            if not window_slice.isna().any():
                max_high = float(window_slice.max())
                if max_high > 0:
                    result[col] = _safe(last_close / max_high - 1.0)
                else:
                    result[col] = None
            else:
                result[col] = None
        else:
            result[col] = None

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
            "momentum": {rsi_14, sma_20_gap, ..., high_dist_1m, high_dist_1y},
        }
    """
    return {
        "performance": compute_performance_live(df),
        "volatility": compute_volatility_live(df),
        "momentum": compute_momentum_live(df),
    }
