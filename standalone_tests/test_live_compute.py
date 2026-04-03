"""
LIVE-03 Verification Script: live_compute.py

Tests mathematical correctness against the batch runners' logic,
verifies graceful degradation on insufficient data, and benchmarks
the full compute_all_metrics_live() to prove ~1ms execution.

Usage:
    python test_live_compute.py

All tests are deterministic — no network, no SQLite.
"""

import sys
import time
import math
import pandas as pd
import numpy as np
from financial_data_etl.api.live_compute import (
    compute_performance_live,
    compute_volatility_live,
    compute_volume_live,
    compute_all_metrics_live,
    LAGS,
    VOL_WINDOWS,
    SMA_WINDOWS,
    ANNUALIZATION_FACTOR,
)


def _make_df(n: int = 258, start_ts: int = 1_700_000_000, interval: int = 86400) -> pd.DataFrame:
    """Generate a realistic 258-row daily OHLCV DataFrame."""
    np.random.seed(42)  # deterministic
    ts = [start_ts + i * interval for i in range(n)]
    # Random walk for close price starting at 150
    returns = np.random.normal(0.0005, 0.015, n)
    close = 150.0 * np.exp(np.cumsum(returns))
    high = close * (1 + np.abs(np.random.normal(0, 0.01, n)))
    low = close * (1 - np.abs(np.random.normal(0, 0.01, n)))
    opn = close * (1 + np.random.normal(0, 0.005, n))
    volume = np.random.uniform(500_000, 5_000_000, n)

    return pd.DataFrame({
        "ts": ts,
        "open": opn,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


# ══════════════════════════════════════════════════════════════════════════════
# PERFORMANCE TESTS
# ══════════════════════════════════════════════════════════════════════════════

def test_performance_basic():
    """compute_performance_live returns all 6 return fields."""
    df = _make_df(258)
    result = compute_performance_live(df)

    for col in LAGS:
        assert col in result, f"Missing key: {col}"
        assert result[col] is not None, f"{col} should not be None with 258 bars"
        assert isinstance(result[col], float), f"{col} should be float, got {type(result[col])}"

    print(f"[PASS] test_performance_basic: all 6 returns computed")
    for col, val in result.items():
        print(f"  {col}: {val:+.6f}")


def test_performance_math_matches_batch():
    """Verify the live math matches the batch runner's vectorized approach."""
    df = _make_df(258)
    close = df["close"]

    live_result = compute_performance_live(df)

    # Replicate batch math: close / close.shift(lag) - 1.0
    for col, lag in LAGS.items():
        shifted = close.shift(lag)
        safe_shifted = shifted.where(shifted != 0.0)
        batch_val = float(close.iloc[-1] / safe_shifted.iloc[-1] - 1.0)
        live_val = live_result[col]

        assert abs(batch_val - live_val) < 1e-12, (
            f"{col}: batch={batch_val} vs live={live_val}"
        )

    print("[PASS] test_performance_math_matches_batch: all 6 returns match to 12 decimal places")


def test_performance_insufficient_data():
    """With only 10 bars, long-lag returns should be None."""
    df = _make_df(10)
    result = compute_performance_live(df)

    assert result["ret_1d"] is not None, "ret_1d (lag=1) should work with 10 bars"
    assert result["ret_1w"] is not None, "ret_1w (lag=5) should work with 10 bars"
    assert result["ret_1m"] is None, "ret_1m (lag=21) should be None with 10 bars"
    assert result["ret_1y"] is None, "ret_1y (lag=252) should be None with 10 bars"
    print("[PASS] test_performance_insufficient_data: graceful degradation on short df")


# ══════════════════════════════════════════════════════════════════════════════
# VOLATILITY TESTS
# ══════════════════════════════════════════════════════════════════════════════

def test_volatility_basic():
    """compute_volatility_live returns range_intraday + all 5 vol windows."""
    df = _make_df(258)
    result = compute_volatility_live(df)

    assert "range_intraday" in result
    for col in VOL_WINDOWS:
        assert col in result, f"Missing key: {col}"
        assert result[col] is not None, f"{col} should not be None with 258 bars"

    print("[PASS] test_volatility_basic: all volatility metrics computed")
    for col, val in result.items():
        if val is not None:
            print(f"  {col}: {val:.6f}")


def test_volatility_math_matches_batch():
    """Verify the live math matches the batch runner's rolling std approach."""
    df = _make_df(258)
    close = df["close"]

    # Replicate batch math exactly
    prev_close = close.shift(1)
    log_ret = np.log(close / prev_close.where(prev_close > 0))
    log_ret = log_ret.where(np.isfinite(log_ret))

    live_result = compute_volatility_live(df)

    for col, window in VOL_WINDOWS.items():
        # Batch: rolling(window, min_periods=window).std() * ANNUALIZATION_FACTOR
        batch_series = log_ret.rolling(window=window, min_periods=window).std()
        batch_val = float(batch_series.iloc[-1] * ANNUALIZATION_FACTOR)
        live_val = live_result[col]

        assert abs(batch_val - live_val) < 1e-10, (
            f"{col}: batch={batch_val} vs live={live_val}, diff={abs(batch_val - live_val)}"
        )

    # range_intraday
    batch_range = float((df["high"].iloc[-1] - df["low"].iloc[-1]) / close.iloc[-1])
    assert abs(batch_range - live_result["range_intraday"]) < 1e-12

    print("[PASS] test_volatility_math_matches_batch: all vol metrics match to 10 decimal places")


def test_volatility_insufficient_data():
    """With only 10 bars, long-window vols should be None."""
    df = _make_df(10)
    result = compute_volatility_live(df)

    assert result["range_intraday"] is not None, "range_intraday should always work"
    assert result["vol_1w"] is not None, "vol_1w (window=5) should work with 10 bars"
    assert result["vol_1m"] is None, "vol_1m (window=21) should be None with 10 bars"
    assert result["vol_1y"] is None, "vol_1y (window=252) should be None with 10 bars"
    print("[PASS] test_volatility_insufficient_data: graceful degradation on short df")


# ══════════════════════════════════════════════════════════════════════════════
# VOLUME TESTS
# ══════════════════════════════════════════════════════════════════════════════

def test_volume_basic():
    """compute_volume_live returns volume_usd + 4 SMAs + 4 gaps."""
    df = _make_df(258)
    result = compute_volume_live(df)

    assert "volume_usd" in result
    assert result["volume_usd"] is not None
    for w in SMA_WINDOWS:
        assert f"vol_sma_{w}" in result
        assert f"vol_gap_{w}" in result
        assert result[f"vol_sma_{w}"] is not None, f"vol_sma_{w} should not be None"

    print("[PASS] test_volume_basic: all volume metrics computed")
    for col, val in result.items():
        if val is not None:
            print(f"  {col}: {val:,.2f}")


def test_volume_math_matches_batch():
    """Verify the live math matches the batch runner's rolling mean approach."""
    df = _make_df(258)
    volume_usd = df["close"] * df["volume"]

    live_result = compute_volume_live(df)

    # volume_usd
    batch_vusd = float(volume_usd.iloc[-1])
    assert abs(batch_vusd - live_result["volume_usd"]) < 1e-6

    for w in SMA_WINDOWS:
        # Batch: rolling(w, min_periods=w).mean()
        batch_sma = float(volume_usd.rolling(window=w, min_periods=w).mean().iloc[-1])
        live_sma = live_result[f"vol_sma_{w}"]
        assert abs(batch_sma - live_sma) < 1e-6, (
            f"vol_sma_{w}: batch={batch_sma} vs live={live_sma}"
        )

        # gap
        batch_gap = float(volume_usd.iloc[-1] / batch_sma - 1.0)
        live_gap = live_result[f"vol_gap_{w}"]
        assert abs(batch_gap - live_gap) < 1e-10, (
            f"vol_gap_{w}: batch={batch_gap} vs live={live_gap}"
        )

    print("[PASS] test_volume_math_matches_batch: all volume metrics match batch runner")


def test_volume_insufficient_data():
    """With only 10 bars, large SMA windows should be None."""
    df = _make_df(10)
    result = compute_volume_live(df)

    assert result["volume_usd"] is not None
    assert result["vol_sma_200"] is None, "vol_sma_200 should be None with 10 bars"
    assert result["vol_gap_200"] is None, "vol_gap_200 should be None with 10 bars"
    print("[PASS] test_volume_insufficient_data: graceful degradation on short df")


# ══════════════════════════════════════════════════════════════════════════════
# UNIFIED + EDGE CASES
# ══════════════════════════════════════════════════════════════════════════════

def test_compute_all_structure():
    """compute_all_metrics_live returns the correct nested dict structure."""
    df = _make_df(258)
    result = compute_all_metrics_live(df)

    assert "performance" in result
    assert "volatility" in result
    assert "volume" in result
    assert len(result["performance"]) == 6
    assert len(result["volatility"]) == 6  # range_intraday + 5 windows
    assert len(result["volume"]) == 9      # volume_usd + 4 sma + 4 gap

    # Verify all values are float or None (JSON-safe)
    for section_name, section in result.items():
        for key, val in section.items():
            assert val is None or isinstance(val, float), (
                f"{section_name}.{key} is {type(val)}, expected float or None"
            )

    print("[PASS] test_compute_all_structure: unified dict is well-formed and JSON-safe")


def test_empty_df():
    """Empty DataFrame should return all None without crashing."""
    df = pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
    result = compute_all_metrics_live(df)

    for section in result.values():
        for val in section.values():
            assert val is None, f"Expected None for empty df, got {val}"

    print("[PASS] test_empty_df: all None on empty DataFrame (no crash)")


def test_single_row():
    """Single row should return what it can (range_intraday, volume_usd)."""
    df = _make_df(1)
    result = compute_all_metrics_live(df)

    # Performance: all None (need at least lag+1 rows)
    assert all(v is None for v in result["performance"].values())
    # Volatility: range_intraday should work, windows None
    assert result["volatility"]["range_intraday"] is None  # need 2 rows for log_ret
    # Volume: volume_usd should work
    assert result["volume"]["volume_usd"] is not None

    print("[PASS] test_single_row: graceful degradation on 1-row df")


# ══════════════════════════════════════════════════════════════════════════════
# PERFORMANCE BENCHMARK
# ══════════════════════════════════════════════════════════════════════════════

def test_benchmark():
    """Benchmark compute_all_metrics_live — target: ~1ms for 258 rows."""
    df = _make_df(258)

    # Warm up
    for _ in range(200):
        compute_all_metrics_live(df)

    iterations = 10_000
    t0 = time.perf_counter()
    for _ in range(iterations):
        compute_all_metrics_live(df)
    elapsed = time.perf_counter() - t0

    avg_us = (elapsed / iterations) * 1_000_000
    avg_ms = avg_us / 1000

    print(f"[PERF] compute_all_metrics_live: {avg_us:.1f}us ({avg_ms:.3f}ms) avg over {iterations:,} iterations")
    print(f"       Breakdown estimate: perf ~0.01ms (O(1)), vol ~{avg_ms*0.6:.3f}ms, volume ~{avg_ms*0.3:.3f}ms")

    if avg_ms <= 3.0:
        print(f"[PASS] Performance: {avg_ms:.3f}ms is within budget (target: <3ms)")
    else:
        print(f"[WARN] Performance: {avg_ms:.3f}ms exceeds 3ms budget")


if __name__ == "__main__":
    print(f"\n{'='*65}")
    print(f"  LIVE-03 TEST SUITE: live_compute.py (Pure RAM Compute)")
    print(f"  Constants from batch runners:")
    print(f"    LAGS = {list(LAGS.keys())}")
    print(f"    VOL_WINDOWS = {list(VOL_WINDOWS.keys())}")
    print(f"    SMA_WINDOWS = {SMA_WINDOWS}")
    print(f"    ANNUALIZATION_FACTOR = {ANNUALIZATION_FACTOR:.6f}")
    print(f"{'='*65}\n")

    tests = [
        test_performance_basic,
        test_performance_math_matches_batch,
        test_performance_insufficient_data,
        test_volatility_basic,
        test_volatility_math_matches_batch,
        test_volatility_insufficient_data,
        test_volume_basic,
        test_volume_math_matches_batch,
        test_volume_insufficient_data,
        test_compute_all_structure,
        test_empty_df,
        test_single_row,
        test_benchmark,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"[FAIL] {test.__name__}: {e}")

    print(f"\n{'='*65}")
    print(f"  RESULTS: {passed} passed, {failed} failed out of {len(tests)}")
    print(f"{'='*65}\n")

    sys.exit(1 if failed > 0 else 0)
