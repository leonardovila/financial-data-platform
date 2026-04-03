"""
LIVE-01 Verification Script: subscribe_ohlcv_stream()

Connects to TradingView, subscribes to a symbol, and prints every event
yielded by the async generator. Proves the Seed & Edge flow works.

Usage:
    python test_live_stream.py              # defaults to AAPL, 1d, 3 initial candles
    python test_live_stream.py MSFT         # custom symbol
    python test_live_stream.py BTCUSD 1m 5  # crypto 1-minute with 5 initial candles

Press Ctrl+C to stop. The finally block should print cleanup confirmation.
"""

import asyncio
import sys
import time
import json

from financial_data_etl.scraping_pipeline.tv_websocket_connection.call_execution.tradingview_ws import (
    open_session,
    close_session,
    subscribe_ohlcv_stream,
)
from financial_data_etl.scraping_pipeline.tv_websocket_connection.call_specification.asset_catalog import (
    load_assets_catalog,
)
from financial_data_etl.scraping_pipeline.tv_websocket_connection.call_specification.call_builder import (
    run_call_builder,
)


def _format_candle(c):
    """Format a single candle [ts, o, h, l, c, v] for display."""
    from datetime import datetime, timezone
    ts = int(c[0])
    dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    return f"  {dt} | O={c[1]:.2f} H={c[2]:.2f} L={c[3]:.2f} C={c[4]:.2f} V={c[5]:,.0f}"


async def run_test(symbol: str, timeframe: str, n_initial: int, max_events: int = 50):
    print(f"\n{'='*70}")
    print(f"  LIVE-01 TEST: subscribe_ohlcv_stream()")
    print(f"  Symbol: {symbol} | Timeframe: {timeframe} | Initial candles: {n_initial}")
    print(f"  Max events: {max_events} (or Ctrl+C to stop)")
    print(f"{'='*70}\n")

    # Resolve provider symbol (e.g., AAPL -> NASDAQ:AAPL)
    catalog = load_assets_catalog()
    spec = run_call_builder(
        symbol=symbol,
        timeframe=timeframe,
        provider="tradingview",
        mode="backfill",
        n_candles_hint=n_initial,
        catalog=catalog,
    )
    provider_symbol = spec.provider_symbol
    print(f"[SETUP] Provider symbol: {provider_symbol}")

    # Open a TradingView session (no trace file for clean output)
    print("[SETUP] Connecting to TradingView...")
    session = await open_session(trace=False)
    print(f"[SETUP] Session opened. Chart ID: {session['chart_id']}")

    # Assign unique IDs for the live stream
    session["chart_id"] = f"{session['chart_id']}_live"
    session["quote_id"] = "qs_live_test_1"

    event_count = 0
    t_start = time.perf_counter()

    try:
        print(f"[STREAM] Subscribing to {provider_symbol}...\n")

        async for event_type, data in subscribe_ohlcv_stream(
            session, provider_symbol, timeframe, n_initial
        ):
            event_count += 1
            elapsed = time.perf_counter() - t_start

            if event_type == "seed":
                print(f"[{elapsed:7.2f}s] SEED: {len(data)} candles received")
                # Show last 3 candles
                for c in data[-3:]:
                    print(_format_candle(c))
                print()

            elif event_type == "tick":
                print(f"[{elapsed:7.2f}s] TICK: {len(data)} bar(s) updated")
                for c in data:
                    print(_format_candle(c))

            elif event_type == "company_name":
                print(f"[{elapsed:7.2f}s] COMPANY: {data}")

            elif event_type == "fundamentals":
                fields = list(data.keys())
                mcap = data.get("market_cap_basic")
                pe = data.get("price_earnings_ttm")
                sector = data.get("sector")
                print(f"[{elapsed:7.2f}s] FUNDAMENTALS: {len(fields)} fields")
                print(f"  Market Cap: {mcap:,.0f}" if mcap else "  Market Cap: N/A")
                print(f"  P/E TTM: {pe:.2f}" if pe else "  P/E TTM: N/A")
                print(f"  Sector: {sector}" if sector else "  Sector: N/A")
                print()

            elif event_type == "heartbeat":
                print(f"[{elapsed:7.2f}s] HEARTBEAT: no data for 45s (market may be closed)")

            if event_count >= max_events:
                print(f"\n[DONE] Reached max_events ({max_events}). Stopping.")
                break

    except KeyboardInterrupt:
        print(f"\n[INTERRUPTED] Ctrl+C after {event_count} events.")

    except Exception as e:
        print(f"\n[ERROR] {type(e).__name__}: {e}")

    finally:
        # The async generator's finally block runs here (cleanup sends)
        # Then we close the session
        elapsed = time.perf_counter() - t_start
        print(f"\n[CLEANUP] Closing session after {elapsed:.2f}s, {event_count} events...")
        await close_session(session)
        print("[CLEANUP] Session closed. TV chart/quote sessions were cleaned up by the generator's finally block.")
        print(f"\n{'='*70}")
        print(f"  RESULT: {'PASS' if event_count > 0 else 'FAIL'}")
        print(f"  Events received: {event_count}")
        print(f"  Total time: {elapsed:.2f}s")
        print(f"{'='*70}\n")


if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    timeframe = sys.argv[2] if len(sys.argv) > 2 else "1d"
    n_initial = int(sys.argv[3]) if len(sys.argv) > 3 else 3

    asyncio.run(run_test(symbol, timeframe, n_initial))
