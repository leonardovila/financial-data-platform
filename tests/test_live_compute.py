"""
P0_02 Test 2 — Live metrics correctness + sub-millisecond SLA.

Why this test exists:
  `compute_all_metrics_live()` is the core of the live streaming API — it
  recomputes performance + volatility + volume metrics in-memory on every
  WebSocket tick. The README sells this as "zero-I/O submillisecond recompute".
  That SLA *is the product*.

  This test enforces two invariants that future refactors must not break:
    1. MATH CORRECTNESS — live metrics must match the batch runners' formulas
       to double-precision tolerance (verified by `test_*_math_matches_batch`).
       If someone changes the RSI or volatility formula by accident, this fails.
    2. PERFORMANCE SLA — `test_benchmark_sla_submillisecond` hard-asserts that
       the full compute finishes in <5ms (generous margin over the ~1ms target).
       If someone introduces a Python loop or a pd.apply() that kills the SLA,
       this test fails at PR time — *before* it reaches prod and breaks the
       live streaming pitch.

  All tests are deterministic — no network, no SQLite, reproducible seed.

Ported from standalone_tests/test_live_compute.py (LIVE-03 verification
script) to proper pytest format as part of P0_02.
"""

import time

import numpy as np
import pandas as pd

from financial_data_etl.api.live_compute import (
    ANNUALIZATION_FACTOR,
    LAGS,
    SMA_WINDOWS,
    VOL_WINDOWS,
    compute_all_metrics_live,
    compute_performance_live,
    compute_volatility_live,
    compute_volume_live,
)


def _make_df(n: int = 258, start_ts: int = 1_700_000_000, interval: int = 86400) -> pd.DataFrame:
    """Generate a realistic 258-row daily OHLCV DataFrame (deterministic seed)."""
    np.random.seed(42)
    ts = [start_ts + i * interval for i in range(n)]
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
# PERFORMANCE (RETURNS) TESTS
# ══════════════════════════════════════════════════════════════════════════════

def test_performance_basic():
    """compute_performance_live returns all return fields as floats on a full window."""
    df = _make_df(258)
    result = compute_performance_live(df)

    for col in LAGS:
        assert col in result, f"Missing key: {col}"
        assert result[col] is not None, f"{col} should not be None with 258 bars"
        assert isinstance(result[col], float), f"{col} should be float, got {type(result[col])}"


def test_performance_math_matches_batch():
    """Live returns must match the batch runner's vectorized formula to 1e-12."""
    df = _make_df(258)
    close = df["close"]

    live_result = compute_performance_live(df)

    for col, lag in LAGS.items():
        shifted = close.shift(lag)
        safe_shifted = shifted.where(shifted != 0.0)
        batch_val = float(close.iloc[-1] / safe_shifted.iloc[-1] - 1.0)
        live_val = live_result[col]

        assert abs(batch_val - live_val) < 1e-12, (
            f"{col}: batch={batch_val} vs live={live_val}"
        )


def test_performance_insufficient_data():
    """With only 10 bars, long-lag returns gracefully degrade to None."""
    df = _make_df(10)
    result = compute_performance_live(df)

    assert result["ret_1d"] is not None, "ret_1d (lag=1) should work with 10 bars"
    assert result["ret_1w"] is not None, "ret_1w (lag=5) should work with 10 bars"
    assert result["ret_1m"] is None, "ret_1m (lag=21) should be None with 10 bars"
    assert result["ret_1y"] is None, "ret_1y (lag=252) should be None with 10 bars"


# ══════════════════════════════════════════════════════════════════════════════
# VOLATILITY TESTS
# ══════════════════════════════════════════════════════════════════════════════

def test_volatility_basic():
    """compute_volatility_live returns range_intraday + all volatility windows."""
    df = _make_df(258)
    result = compute_volatility_live(df)

    assert "range_intraday" in result
    for col in VOL_WINDOWS:
        assert col in result, f"Missing key: {col}"
        assert result[col] is not None, f"{col} should not be None with 258 bars"


def test_volatility_math_matches_batch():
    """Live volatility must match the batch runner's rolling log-return std to 1e-10."""
    df = _make_df(258)
    close = df["close"]

    prev_close = close.shift(1)
    log_ret = np.log(close / prev_close.where(prev_close > 0))
    log_ret = log_ret.where(np.isfinite(log_ret))

    live_result = compute_volatility_live(df)

    for col, window in VOL_WINDOWS.items():
        batch_series = log_ret.rolling(window=window, min_periods=window).std()
        batch_val = float(batch_series.iloc[-1] * ANNUALIZATION_FACTOR)
        live_val = live_result[col]

        assert abs(batch_val - live_val) < 1e-10, (
            f"{col}: batch={batch_val} vs live={live_val}"
        )

    batch_range = float((df["high"].iloc[-1] - df["low"].iloc[-1]) / close.iloc[-1])
    assert abs(batch_range - live_result["range_intraday"]) < 1e-12


def test_volatility_insufficient_data():
    """Short DataFrame gracefully degrades long-window volatilities to None."""
    df = _make_df(10)
    result = compute_volatility_live(df)

    assert result["range_intraday"] is not None
    assert result["vol_1w"] is not None, "vol_1w (window=5) should work with 10 bars"
    assert result["vol_1m"] is None, "vol_1m (window=21) should be None with 10 bars"
    assert result["vol_1y"] is None, "vol_1y (window=252) should be None with 10 bars"


# ══════════════════════════════════════════════════════════════════════════════
# VOLUME TESTS
# ══════════════════════════════════════════════════════════════════════════════

def test_volume_basic():
    """compute_volume_live returns volume_usd + all SMA + all gap fields."""
    df = _make_df(258)
    result = compute_volume_live(df)

    assert result["volume_usd"] is not None
    for w in SMA_WINDOWS:
        assert f"vol_sma_{w}" in result
        assert f"vol_gap_{w}" in result
        assert result[f"vol_sma_{w}"] is not None


def test_volume_math_matches_batch():
    """Live volume SMAs and gaps must match the batch runner's rolling mean."""
    df = _make_df(258)
    volume_usd = df["close"] * df["volume"]

    live_result = compute_volume_live(df)

    assert abs(float(volume_usd.iloc[-1]) - live_result["volume_usd"]) < 1e-6

    for w in SMA_WINDOWS:
        batch_sma = float(volume_usd.rolling(window=w, min_periods=w).mean().iloc[-1])
        live_sma = live_result[f"vol_sma_{w}"]
        assert abs(batch_sma - live_sma) < 1e-6, (
            f"vol_sma_{w}: batch={batch_sma} vs live={live_sma}"
        )

        batch_gap = float(volume_usd.iloc[-1] / batch_sma - 1.0)
        live_gap = live_result[f"vol_gap_{w}"]
        assert abs(batch_gap - live_gap) < 1e-10


def test_volume_insufficient_data():
    """Short DataFrame gracefully degrades long-window SMAs to None."""
    df = _make_df(10)
    result = compute_volume_live(df)

    assert result["volume_usd"] is not None
    assert result["vol_sma_200"] is None
    assert result["vol_gap_200"] is None


# ══════════════════════════════════════════════════════════════════════════════
# UNIFIED OUTPUT CONTRACT + EDGE CASES
# ══════════════════════════════════════════════════════════════════════════════

def test_compute_all_structure_is_json_safe():
    """The unified output must be a nested dict of floats-or-None (JSON serializable)."""
    df = _make_df(258)
    result = compute_all_metrics_live(df)

    assert "performance" in result
    assert "volatility" in result
    assert "volume" in result
    assert len(result["performance"]) == 6
    assert len(result["volatility"]) == 6
    assert len(result["volume"]) == 9

    for section_name, section in result.items():
        for key, val in section.items():
            assert val is None or isinstance(val, float), (
                f"{section_name}.{key} is {type(val)}, expected float or None"
            )


def test_empty_df_returns_all_none_without_crashing():
    """Empty DataFrame must return all-None (no crash) — protects the WS seed path."""
    df = pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
    result = compute_all_metrics_live(df)

    for section in result.values():
        for val in section.values():
            assert val is None


def test_single_row_graceful_degradation():
    """Single-row DataFrame: volume_usd present, performance/volatility windows None."""
    df = _make_df(1)
    result = compute_all_metrics_live(df)

    assert all(v is None for v in result["performance"].values())
    assert result["volatility"]["range_intraday"] is None
    assert result["volume"]["volume_usd"] is not None


# ══════════════════════════════════════════════════════════════════════════════
# PERFORMANCE SLA — THE CROWN JEWEL
# ══════════════════════════════════════════════════════════════════════════════

def test_benchmark_sla_submillisecond():
    """
    HARD SLA GATE: compute_all_metrics_live() must run in <5ms for 258 rows.

    The production target is ~1ms (zero-I/O submillisecond), but CI runners
    vary widely in CPU performance. 5ms is a generous ceiling that still
    catches catastrophic regressions (e.g., someone accidentally adding a
    Python-level loop or a pd.apply() over rows).

    If this fails in CI, something in live_compute.py has broken the
    vectorized fast path — investigate before merging.
    """
    df = _make_df(258)

    # Warm up (JIT caches, pandas internal caches)
    for _ in range(200):
        compute_all_metrics_live(df)

    iterations = 2_000
    t0 = time.perf_counter()
    for _ in range(iterations):
        compute_all_metrics_live(df)
    elapsed = time.perf_counter() - t0

    avg_ms = (elapsed / iterations) * 1000

    assert avg_ms < 5.0, (
        f"SLA VIOLATION: compute_all_metrics_live avg {avg_ms:.3f}ms > 5ms budget. "
        f"Something in live_compute.py has lost the vectorized fast path."
    )
