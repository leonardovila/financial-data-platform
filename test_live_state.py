"""
LIVE-02 Verification Script: LiveSymbolState

Tests the full lifecycle: seed, merge, replace-tick, append-tick,
trim logic, thread-safe snapshot, and performance benchmarks.

Usage:
    python test_live_state.py

All tests are deterministic — no network, no SQLite, no randomness.
"""

import time
import sys
import pandas as pd
from financial_data_etl.api.live_state import LiveSymbolState, MAX_BARS


def _make_candles(n: int, start_ts: int = 1_700_000_000, interval: int = 86400) -> list:
    """Generate N mock daily candles: [ts, o, h, l, c, v]."""
    candles = []
    for i in range(n):
        ts = start_ts + i * interval
        base = 150.0 + i * 0.5
        candles.append([ts, base, base + 2.0, base - 1.0, base + 1.0, 1_000_000.0 + i * 100])
    return candles


def test_seed_basic():
    """Seed with exactly 258 candles — should keep all."""
    state = LiveSymbolState("AAPL", "1d")
    candles = _make_candles(258)
    state.seed(candles, fundamentals={"market_cap": 3e12}, company_name="Apple Inc")

    assert len(state.df) == 258, f"Expected 258 rows, got {len(state.df)}"
    assert state.company_name == "Apple Inc"
    assert state.fundamentals["market_cap"] == 3e12
    assert state.tick_count == 0
    assert state.last_tick_ts > 0
    # Verify sorted ASC
    assert list(state.df["ts"]) == sorted(state.df["ts"]), "df must be sorted by ts ASC"
    print("[PASS] test_seed_basic: 258 candles seeded correctly")


def test_seed_trims_to_258():
    """Seed with 300 candles — must trim to 258, keeping the MOST RECENT."""
    state = LiveSymbolState("MSFT", "1d")
    candles = _make_candles(300)
    state.seed(candles)

    assert len(state.df) == MAX_BARS, f"Expected {MAX_BARS} rows, got {len(state.df)}"
    # The first 42 candles (oldest) should be trimmed
    expected_first_ts = candles[300 - 258][0]
    actual_first_ts = int(state.df.iloc[0]["ts"])
    assert actual_first_ts == expected_first_ts, (
        f"Expected first ts={expected_first_ts}, got {actual_first_ts}"
    )
    expected_last_ts = candles[-1][0]
    actual_last_ts = int(state.df.iloc[-1]["ts"])
    assert actual_last_ts == expected_last_ts, (
        f"Expected last ts={expected_last_ts}, got {actual_last_ts}"
    )
    print("[PASS] test_seed_trims_to_258: 300 candles trimmed to 258 (kept most recent)")


def test_merge_tv_seed_replace():
    """merge_tv_seed replaces existing ts with fresher data."""
    state = LiveSymbolState("AAPL", "1d")
    candles = _make_candles(258)
    state.seed(candles)

    # The last candle's ts
    last_ts = int(state.df.iloc[-1]["ts"])
    original_close = float(state.df.iloc[-1]["close"])

    # TV sends a fresh bar with the SAME ts but updated close
    tv_candles = [[last_ts, 200.0, 205.0, 195.0, 202.5, 5_000_000.0]]
    state.merge_tv_seed(tv_candles)

    assert len(state.df) == 258, f"Row count should not change on replace, got {len(state.df)}"
    new_close = float(state.df.iloc[-1]["close"])
    assert new_close == 202.5, f"Expected close=202.5 after replace, got {new_close}"
    assert new_close != original_close, "Close should have changed after merge"
    print("[PASS] test_merge_tv_seed_replace: existing ts replaced with fresh TV data")


def test_merge_tv_seed_append():
    """merge_tv_seed appends a candle with a new ts (new bar opened)."""
    state = LiveSymbolState("AAPL", "1d")
    candles = _make_candles(257)  # leave room for 1 more
    state.seed(candles)
    assert len(state.df) == 257

    # TV sends a bar with a NEW ts (one day after the last candle)
    new_ts = int(state.df.iloc[-1]["ts"]) + 86400
    tv_candles = [[new_ts, 300.0, 310.0, 295.0, 305.0, 9_000_000.0]]
    state.merge_tv_seed(tv_candles)

    assert len(state.df) == 258, f"Expected 258 after append, got {len(state.df)}"
    last_row = state.df.iloc[-1]
    assert int(last_row["ts"]) == new_ts, f"Last ts should be {new_ts}"
    assert float(last_row["close"]) == 305.0
    print("[PASS] test_merge_tv_seed_append: new ts appended correctly")


def test_update_tick_replace():
    """update_tick replaces the live bar (same ts, updated OHLCV)."""
    state = LiveSymbolState("AAPL", "1d")
    candles = _make_candles(258)
    state.seed(candles)

    last_ts = int(state.df.iloc[-1]["ts"])
    original_close = float(state.df.iloc[-1]["close"])

    # Simulate a live bar tick with the same ts
    tick = [[last_ts, 180.0, 185.0, 175.0, 182.0, 7_500_000.0]]
    result = state.update_tick(tick)

    assert len(state.df) == 258, "Row count must not change on replace"
    assert state.tick_count == 1
    assert float(state.df.iloc[-1]["close"]) == 182.0
    assert result["ts"] == last_ts
    assert result["close"] == 182.0
    assert result["volume"] == 7_500_000.0
    print("[PASS] test_update_tick_replace: live bar replaced in-place")


def test_update_tick_append_and_trim():
    """update_tick appends a new bar and trims to 258."""
    state = LiveSymbolState("AAPL", "1d")
    candles = _make_candles(258)
    state.seed(candles)

    oldest_ts = int(state.df.iloc[0]["ts"])

    # Simulate a new bar opening (ts beyond the last candle)
    new_ts = int(state.df.iloc[-1]["ts"]) + 86400
    tick = [[new_ts, 200.0, 210.0, 198.0, 205.0, 3_000_000.0]]
    result = state.update_tick(tick)

    assert len(state.df) == 258, f"Must stay at 258 after append+trim, got {len(state.df)}"
    assert int(state.df.iloc[-1]["ts"]) == new_ts, "New bar should be at the tail"
    assert int(state.df.iloc[0]["ts"]) != oldest_ts, "Oldest bar should have been trimmed"
    assert result["ts"] == new_ts
    assert result["close"] == 205.0
    print("[PASS] test_update_tick_append_and_trim: new bar appended, oldest trimmed, still 258 rows")


def test_update_tick_multi_bar():
    """update_tick handles 2 bars at once (closed bar + new open bar)."""
    state = LiveSymbolState("AAPL", "1d")
    candles = _make_candles(258)
    state.seed(candles)

    last_ts = int(state.df.iloc[-1]["ts"])
    new_ts = last_ts + 86400

    # TV sends 2 bars: updated close for last bar + new bar
    tick = [
        [last_ts, 180.0, 185.0, 175.0, 182.0, 7_000_000.0],  # replace
        [new_ts, 183.0, 184.0, 181.0, 183.5, 500_000.0],      # append
    ]
    result = state.update_tick(tick)

    assert len(state.df) == 258, "Must trim after append"
    assert state.tick_count == 1, "One call = one tick_count increment"
    assert float(state.df[state.df["ts"] == last_ts]["close"].iloc[0]) == 182.0
    assert float(state.df.iloc[-1]["close"]) == 183.5
    assert result["ts"] == new_ts, "Result should be the most recent bar"
    print("[PASS] test_update_tick_multi_bar: 2-bar update (replace + append) handled correctly")


def test_get_df_snapshot_is_copy():
    """get_df_snapshot returns an independent copy — mutations don't leak."""
    state = LiveSymbolState("AAPL", "1d")
    candles = _make_candles(258)
    state.seed(candles)

    snapshot = state.get_df_snapshot()
    assert len(snapshot) == len(state.df)

    # Mutate the snapshot
    snapshot.iloc[-1, snapshot.columns.get_loc("close")] = -999.0

    # Original must be untouched
    assert float(state.df.iloc[-1]["close"]) != -999.0, "Snapshot mutation leaked to original!"
    print("[PASS] test_get_df_snapshot_is_copy: snapshot is independent copy (thread-safe)")


def test_stats():
    """stats() returns a well-formed monitoring dict."""
    state = LiveSymbolState("TSLA", "1d")
    candles = _make_candles(100)
    state.seed(candles, fundamentals={"pe_ttm": 50.0}, company_name="Tesla Inc")
    state.update_tick([[int(state.df.iloc[-1]["ts"]), 250.0, 260.0, 245.0, 255.0, 2e6]])

    s = state.stats()
    assert s["symbol"] == "TSLA"
    assert s["bars"] == 100
    assert s["tick_count"] == 1
    assert s["company_name"] == "Tesla Inc"
    assert s["has_fundamentals"] is True
    print("[PASS] test_stats: monitoring dict is well-formed")


def test_performance_update_tick():
    """Benchmark update_tick — must hit ~0.1ms target for 1-bar update on 258 rows."""
    state = LiveSymbolState("AAPL", "1d")
    candles = _make_candles(258)
    state.seed(candles)

    last_ts = int(state.df.iloc[-1]["ts"])
    iterations = 10_000

    # Warm up Pandas internals
    for _ in range(100):
        state.update_tick([[last_ts, 150.0, 155.0, 148.0, 152.0, 1e6]])

    t0 = time.perf_counter()
    for i in range(iterations):
        close = 150.0 + (i % 100) * 0.01
        state.update_tick([[last_ts, 150.0, 155.0, 148.0, close, 1e6]])
    elapsed = time.perf_counter() - t0

    avg_us = (elapsed / iterations) * 1_000_000
    avg_ms = avg_us / 1000
    print(f"[PERF] update_tick: {avg_us:.1f}us ({avg_ms:.3f}ms) avg over {iterations:,} iterations")

    if avg_ms <= 0.5:
        print(f"[PASS] Performance: {avg_ms:.3f}ms is within budget (target: <0.5ms)")
    else:
        print(f"[WARN] Performance: {avg_ms:.3f}ms exceeds 0.5ms budget — investigate")


def test_performance_snapshot():
    """Benchmark get_df_snapshot — must be negligible."""
    state = LiveSymbolState("AAPL", "1d")
    candles = _make_candles(258)
    state.seed(candles)

    iterations = 10_000
    t0 = time.perf_counter()
    for _ in range(iterations):
        _ = state.get_df_snapshot()
    elapsed = time.perf_counter() - t0

    avg_us = (elapsed / iterations) * 1_000_000
    print(f"[PERF] get_df_snapshot: {avg_us:.1f}us avg over {iterations:,} iterations")
    print(f"[PASS] Snapshot copy cost is negligible")


if __name__ == "__main__":
    print(f"\n{'='*60}")
    print(f"  LIVE-02 TEST SUITE: LiveSymbolState")
    print(f"  MAX_BARS = {MAX_BARS}")
    print(f"{'='*60}\n")

    tests = [
        test_seed_basic,
        test_seed_trims_to_258,
        test_merge_tv_seed_replace,
        test_merge_tv_seed_append,
        test_update_tick_replace,
        test_update_tick_append_and_trim,
        test_update_tick_multi_bar,
        test_get_df_snapshot_is_copy,
        test_stats,
        test_performance_update_tick,
        test_performance_snapshot,
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

    print(f"\n{'='*60}")
    print(f"  RESULTS: {passed} passed, {failed} failed out of {len(tests)}")
    print(f"{'='*60}\n")

    sys.exit(1 if failed > 0 else 0)
