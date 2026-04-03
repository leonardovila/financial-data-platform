"""
LIVE-05 Verification Script: load_historical_seed()

Runs against the REAL local SQLite database.
Validates structure, data presence, and execution speed.

Usage:
    python test_live_seed.py              # defaults to AAPL
    python test_live_seed.py MSFT         # custom symbol
"""

import sys
import time
import json
from datetime import datetime, timezone
from financial_data_etl.api.live_seed import load_historical_seed
from financial_data_etl.storage.paths import DB_PATH


def test_structure_and_data(symbol: str):
    """Validate the returned dict has all required keys and data."""
    print(f"\n--- load_historical_seed('{symbol}') ---\n")

    t0 = time.perf_counter()
    seed = load_historical_seed(symbol)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    print(f"[TIMING] Execution: {elapsed_ms:.2f}ms")

    # ── Structure checks ──
    assert "symbol" in seed, "Missing 'symbol'"
    assert "chart_candles" in seed, "Missing 'chart_candles'"
    assert "company_name" in seed, "Missing 'company_name'"
    assert "fundamentals" in seed, "Missing 'fundamentals'"
    assert "metrics" in seed, "Missing 'metrics'"
    assert "performance" in seed["metrics"], "Missing 'metrics.performance'"
    assert "volatility" in seed["metrics"], "Missing 'metrics.volatility'"
    assert "volume" in seed["metrics"], "Missing 'metrics.volume'"
    print("[PASS] Structure: all required keys present")

    # ── Chart candles ──
    candles = seed["chart_candles"]
    assert isinstance(candles, list), "chart_candles must be a list"
    n_candles = len(candles)
    print(f"\n[DATA] Chart candles: {n_candles} bars")
    if n_candles > 0:
        assert len(candles[0]) == 6, f"Each candle must have 6 fields, got {len(candles[0])}"
        first = candles[0]
        last = candles[-1]
        first_dt = datetime.fromtimestamp(first[0], tz=timezone.utc).strftime("%Y-%m-%d")
        last_dt = datetime.fromtimestamp(last[0], tz=timezone.utc).strftime("%Y-%m-%d")
        print(f"  First: {first_dt} O={first[1]:.2f} H={first[2]:.2f} L={first[3]:.2f} C={first[4]:.2f} V={first[5]:,.0f}")
        print(f"  Last:  {last_dt} O={last[1]:.2f} H={last[2]:.2f} L={last[3]:.2f} C={last[4]:.2f} V={last[5]:,.0f}")

        # Verify ascending order
        ts_list = [c[0] for c in candles]
        assert ts_list == sorted(ts_list), "Candles must be in ts ASC order"
        print("  Order: ASC verified")
    print(f"[PASS] Chart candles: {n_candles} bars, ASC order")

    # ── Company name ──
    print(f"\n[DATA] Company name: {seed['company_name']}")

    # ── Fundamentals ──
    fund = seed["fundamentals"]
    if fund:
        print(f"[DATA] Fundamentals:")
        for k, v in fund.items():
            if isinstance(v, float) and v > 1e9:
                print(f"  {k}: {v:,.0f}")
            else:
                print(f"  {k}: {v}")
        print(f"[PASS] Fundamentals: {len(fund)} fields")
    else:
        print("[WARN] Fundamentals: None (no data in DB)")

    # ── Metrics ──
    for section_name in ["performance", "volatility", "volume"]:
        section = seed["metrics"][section_name]
        if section:
            fields = {k: v for k, v in section.items() if k not in ("symbol", "ts", "computed_at")}
            print(f"[DATA] {section_name}: {fields}")
            print(f"[PASS] {section_name}: {len(section)} fields")
        else:
            print(f"[WARN] {section_name}: None (no pre-computed data)")

    # ── Performance assertion ──
    if elapsed_ms <= 20:
        print(f"\n[PASS] Performance: {elapsed_ms:.2f}ms is within budget (target: <20ms)")
    else:
        print(f"\n[WARN] Performance: {elapsed_ms:.2f}ms exceeds 20ms budget")

    return seed, elapsed_ms


def test_benchmark(symbol: str, iterations: int = 100):
    """Benchmark load_historical_seed over many iterations."""
    # Warm up
    for _ in range(5):
        load_historical_seed(symbol)

    t0 = time.perf_counter()
    for _ in range(iterations):
        load_historical_seed(symbol)
    elapsed = time.perf_counter() - t0

    avg_ms = (elapsed / iterations) * 1000
    print(f"\n[PERF] Benchmark: {avg_ms:.2f}ms avg over {iterations} iterations")
    if avg_ms <= 20:
        print(f"[PASS] Benchmark: {avg_ms:.2f}ms is within budget")
    else:
        print(f"[WARN] Benchmark: {avg_ms:.2f}ms exceeds budget")
    return avg_ms


def test_unknown_symbol():
    """Unknown symbol should return empty candles and None metrics, not crash."""
    seed = load_historical_seed("ZZZZZZ_FAKE")
    assert seed["symbol"] == "ZZZZZZ_FAKE"
    assert seed["chart_candles"] == []
    assert seed["fundamentals"] is None
    assert seed["metrics"]["performance"] is None
    assert seed["metrics"]["volatility"] is None
    assert seed["metrics"]["volume"] is None
    print("[PASS] Unknown symbol: empty candles, None metrics, no crash")


def test_json_serializable(symbol: str):
    """Entire seed dict must be JSON-serializable for WebSocket send."""
    seed = load_historical_seed(symbol)
    try:
        json_str = json.dumps(seed)
        size_kb = len(json_str) / 1024
        print(f"[PASS] JSON serializable: {size_kb:.1f}KB payload")
    except (TypeError, ValueError) as e:
        print(f"[FAIL] JSON serialization failed: {e}")
        raise


if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else "AAPL"

    print(f"{'='*65}")
    print(f"  LIVE-05 TEST SUITE: load_historical_seed()")
    print(f"  Database: {DB_PATH}")
    print(f"  Symbol: {symbol}")
    print(f"{'='*65}")

    passed = 0
    failed = 0

    tests = [
        ("structure_and_data", lambda: test_structure_and_data(symbol)),
        ("benchmark", lambda: test_benchmark(symbol)),
        ("unknown_symbol", lambda: test_unknown_symbol()),
        ("json_serializable", lambda: test_json_serializable(symbol)),
    ]

    for name, fn in tests:
        try:
            fn()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"[FAIL] {name}: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'='*65}")
    print(f"  RESULTS: {passed} passed, {failed} failed out of {len(tests)}")
    print(f"{'='*65}\n")

    sys.exit(1 if failed > 0 else 0)
