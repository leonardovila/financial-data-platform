"""
LIVE-04 Verification Script: LiveSessionManager

Deterministic tests using mocks — no real TradingView connection.
Proves: lock serialization, session reuse, reconnection, idle timeout,
and concurrent subscribe() safety.

Usage:
    python test_live_session_manager.py
"""

import asyncio
import sys
import time
from unittest.mock import AsyncMock, patch, MagicMock
from financial_data_etl.api.live_session_manager import (
    LiveSessionManager,
    IDLE_TIMEOUT_S,
    IDLE_CHECK_INTERVAL,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_mock_session(chart_id="cs_mock_123"):
    """Create a mock session dict mimicking open_session() return."""
    return {
        "ws": MagicMock(),
        "chart_id": chart_id,
        "trace_file": None,
    }


async def _mock_stream(*args, **kwargs):
    """Mock subscribe_ohlcv_stream: yields 3 events then stops."""
    yield ("seed", [[1700000000, 150.0, 155.0, 148.0, 152.0, 1e6]])
    yield ("company_name", "Mock Inc")
    yield ("fundamentals", {"market_cap_basic": 3e12})


async def _mock_stream_slow(*args, **kwargs):
    """Mock stream that yields one event, then waits (simulates live streaming)."""
    yield ("seed", [[1700000000, 150.0, 155.0, 148.0, 152.0, 1e6]])
    await asyncio.sleep(0.5)
    yield ("tick", [[1700000000, 150.0, 156.0, 149.0, 155.0, 2e6]])


# ── Tests ────────────────────────────────────────────────────────────────────

async def test_lazy_init():
    """Session is NOT opened at construction time."""
    mgr = LiveSessionManager()
    assert not mgr.is_connected, "Should not be connected at init"
    assert mgr.active_streams == 0
    await mgr.close()
    print("[PASS] test_lazy_init: no connection at construction")


async def test_first_subscribe_opens_session():
    """First subscribe() lazily opens the TV connection."""
    mgr = LiveSessionManager()

    with patch(
        "financial_data_etl.api.live_session_manager.open_session",
        new_callable=AsyncMock,
        return_value=_make_mock_session(),
    ) as mock_open, patch(
        "financial_data_etl.api.live_session_manager.subscribe_ohlcv_stream",
        side_effect=_mock_stream,
    ):
        events = []
        async for event_type, data in mgr.subscribe("NASDAQ:AAPL", "1d"):
            events.append(event_type)

        # open_session called exactly once
        assert mock_open.call_count == 1, f"Expected 1 open_session call, got {mock_open.call_count}"
        assert mgr.is_connected
        assert len(events) == 3  # seed, company_name, fundamentals
        assert mgr.stats()["total_subscribes"] == 1

    await mgr.close()
    print("[PASS] test_first_subscribe_opens_session: lazy init works, 1 open_session call")


async def test_session_reuse_across_subscribes():
    """Multiple subscribe() calls reuse the SAME WS connection."""
    mgr = LiveSessionManager()

    with patch(
        "financial_data_etl.api.live_session_manager.open_session",
        new_callable=AsyncMock,
        return_value=_make_mock_session(),
    ) as mock_open, patch(
        "financial_data_etl.api.live_session_manager.subscribe_ohlcv_stream",
        side_effect=_mock_stream,
    ) as mock_stream_fn:
        # First subscribe
        async for _ in mgr.subscribe("NASDAQ:AAPL", "1d"):
            pass

        # Second subscribe (symbol switch)
        async for _ in mgr.subscribe("NASDAQ:MSFT", "1d"):
            pass

        # Third subscribe
        async for _ in mgr.subscribe("NASDAQ:TSLA", "1d"):
            pass

        # open_session called ONCE, not 3 times
        assert mock_open.call_count == 1, f"Expected 1 open_session, got {mock_open.call_count}"
        # subscribe_ohlcv_stream called 3 times with different chart/quote IDs
        assert mock_stream_fn.call_count == 3
        assert mgr.stats()["total_subscribes"] == 3
        assert mgr.stats()["counter"] == 3

        # Verify each call got unique chart/quote IDs
        sessions_used = [call.args[0] for call in mock_stream_fn.call_args_list]
        chart_ids = [s["chart_id"] for s in sessions_used]
        quote_ids = [s["quote_id"] for s in sessions_used]
        assert len(set(chart_ids)) == 3, f"Chart IDs must be unique: {chart_ids}"
        assert len(set(quote_ids)) == 3, f"Quote IDs must be unique: {quote_ids}"

    await mgr.close()
    print("[PASS] test_session_reuse_across_subscribes: 1 connection, 3 subscribes, unique IDs")


async def test_lock_serializes_concurrent_subscribes():
    """Two concurrent subscribe() calls serialize through the Lock —
    only ONE open_session() handshake occurs."""
    mgr = LiveSessionManager()
    handshake_count = 0

    async def slow_open_session(trace=True):
        nonlocal handshake_count
        handshake_count += 1
        await asyncio.sleep(0.1)  # simulate network latency
        return _make_mock_session()

    with patch(
        "financial_data_etl.api.live_session_manager.open_session",
        side_effect=slow_open_session,
    ), patch(
        "financial_data_etl.api.live_session_manager.subscribe_ohlcv_stream",
        side_effect=_mock_stream,
    ):
        async def consumer(label):
            events = []
            async for event_type, data in mgr.subscribe(f"NASDAQ:{label}", "1d"):
                events.append(event_type)
            return events

        # Launch two subscribes concurrently
        results = await asyncio.gather(consumer("AAPL"), consumer("MSFT"))

        # Both should complete with events
        assert len(results[0]) == 3
        assert len(results[1]) == 3

        # But open_session was called ONLY ONCE (second subscribe found _session already set)
        assert handshake_count == 1, f"Expected 1 handshake, got {handshake_count}"

    await mgr.close()
    print("[PASS] test_lock_serializes_concurrent_subscribes: 2 concurrent subs, 1 handshake")


async def test_active_streams_tracking():
    """_active_streams is correctly incremented/decremented."""
    mgr = LiveSessionManager()

    with patch(
        "financial_data_etl.api.live_session_manager.open_session",
        new_callable=AsyncMock,
        return_value=_make_mock_session(),
    ), patch(
        "financial_data_etl.api.live_session_manager.subscribe_ohlcv_stream",
        side_effect=_mock_stream_slow,
    ):
        assert mgr.active_streams == 0

        async def consumer():
            async for _ in mgr.subscribe("NASDAQ:AAPL", "1d"):
                pass

        # Start consumer in background
        task = asyncio.create_task(consumer())
        await asyncio.sleep(0.05)  # let it start

        assert mgr.active_streams == 1, f"Expected 1 active stream, got {mgr.active_streams}"

        await task  # wait for it to finish

        assert mgr.active_streams == 0, f"Expected 0 active streams after finish, got {mgr.active_streams}"

    await mgr.close()
    print("[PASS] test_active_streams_tracking: correctly incremented and decremented")


async def test_reconnect_resets_session():
    """reconnect() closes the dead session; next subscribe() reopens."""
    mgr = LiveSessionManager()
    open_count = 0

    async def counting_open(trace=True):
        nonlocal open_count
        open_count += 1
        return _make_mock_session(f"cs_attempt_{open_count}")

    with patch(
        "financial_data_etl.api.live_session_manager.open_session",
        side_effect=counting_open,
    ), patch(
        "financial_data_etl.api.live_session_manager.close_session",
        new_callable=AsyncMock,
    ) as mock_close, patch(
        "financial_data_etl.api.live_session_manager.subscribe_ohlcv_stream",
        side_effect=_mock_stream,
    ):
        # First subscribe opens session
        async for _ in mgr.subscribe("NASDAQ:AAPL", "1d"):
            pass
        assert open_count == 1
        assert mgr.is_connected

        # Simulate connection death
        await mgr.reconnect()
        assert not mgr.is_connected, "Session should be None after reconnect"
        assert mock_close.call_count == 1
        assert mgr.stats()["reconnect_count"] == 1

        # Next subscribe opens a fresh session
        async for _ in mgr.subscribe("NASDAQ:AAPL", "1d"):
            pass
        assert open_count == 2, "Should have opened a second session"
        assert mgr.is_connected

    await mgr.close()
    print("[PASS] test_reconnect_resets_session: dead session closed, fresh one opened")


async def test_idle_watchdog_closes_connection():
    """Idle watchdog closes the TV connection after timeout with no streams."""
    # Use tiny timeouts for testing
    import financial_data_etl.api.live_session_manager as mod
    original_timeout = mod.IDLE_TIMEOUT_S
    original_interval = mod.IDLE_CHECK_INTERVAL
    mod.IDLE_TIMEOUT_S = 0.2     # 200ms idle timeout
    mod.IDLE_CHECK_INTERVAL = 0.1  # check every 100ms

    try:
        mgr = LiveSessionManager()

        with patch(
            "financial_data_etl.api.live_session_manager.open_session",
            new_callable=AsyncMock,
            return_value=_make_mock_session(),
        ), patch(
            "financial_data_etl.api.live_session_manager.close_session",
            new_callable=AsyncMock,
        ) as mock_close, patch(
            "financial_data_etl.api.live_session_manager.subscribe_ohlcv_stream",
            side_effect=_mock_stream,
        ):
            # Subscribe and consume (stream ends quickly)
            async for _ in mgr.subscribe("NASDAQ:AAPL", "1d"):
                pass

            assert mgr.is_connected, "Should be connected after subscribe"
            assert mgr.active_streams == 0, "No active streams after consume"

            # Wait for idle timeout to trigger
            await asyncio.sleep(0.5)

            # Watchdog should have closed the session
            assert not mgr.is_connected, "Watchdog should have closed idle session"
            assert mock_close.call_count == 1, "close_session should be called by watchdog"

        await mgr.close()

    finally:
        mod.IDLE_TIMEOUT_S = original_timeout
        mod.IDLE_CHECK_INTERVAL = original_interval

    print("[PASS] test_idle_watchdog_closes_connection: idle session closed after timeout")


async def test_watchdog_does_not_close_active_stream():
    """Idle watchdog does NOT close the connection while a stream is active."""
    import financial_data_etl.api.live_session_manager as mod
    original_timeout = mod.IDLE_TIMEOUT_S
    original_interval = mod.IDLE_CHECK_INTERVAL
    mod.IDLE_TIMEOUT_S = 0.1     # 100ms idle timeout
    mod.IDLE_CHECK_INTERVAL = 0.05  # check every 50ms

    try:
        mgr = LiveSessionManager()

        async def long_mock_stream(*args, **kwargs):
            yield ("seed", [[1700000000, 150.0, 155.0, 148.0, 152.0, 1e6]])
            # Stream stays alive for 400ms (well past idle timeout)
            await asyncio.sleep(0.4)
            yield ("tick", [[1700000000, 150.0, 156.0, 149.0, 155.0, 2e6]])

        with patch(
            "financial_data_etl.api.live_session_manager.open_session",
            new_callable=AsyncMock,
            return_value=_make_mock_session(),
        ), patch(
            "financial_data_etl.api.live_session_manager.close_session",
            new_callable=AsyncMock,
        ) as mock_close, patch(
            "financial_data_etl.api.live_session_manager.subscribe_ohlcv_stream",
            side_effect=long_mock_stream,
        ):
            events = []
            async for event_type, data in mgr.subscribe("NASDAQ:AAPL", "1d"):
                events.append(event_type)

            # Stream ran for 400ms past the 100ms idle timeout.
            # Watchdog should NOT have closed it because _active_streams == 1.
            assert len(events) == 2, f"Expected 2 events, got {len(events)}"
            # close_session should NOT have been called by watchdog during stream
            assert mock_close.call_count == 0, (
                f"Watchdog should not close during active stream, but close_session called {mock_close.call_count} times"
            )

        await mgr.close()

    finally:
        mod.IDLE_TIMEOUT_S = original_timeout
        mod.IDLE_CHECK_INTERVAL = original_interval

    print("[PASS] test_watchdog_does_not_close_active_stream: active stream protected from watchdog")


async def test_close_is_final():
    """After close(), subscribe() raises RuntimeError."""
    mgr = LiveSessionManager()
    await mgr.close()

    try:
        async for _ in mgr.subscribe("NASDAQ:AAPL", "1d"):
            pass
        assert False, "Should have raised RuntimeError"
    except RuntimeError as e:
        assert "closed" in str(e).lower()

    print("[PASS] test_close_is_final: subscribe after close raises RuntimeError")


async def test_stats():
    """stats() returns well-formed monitoring dict."""
    mgr = LiveSessionManager()

    with patch(
        "financial_data_etl.api.live_session_manager.open_session",
        new_callable=AsyncMock,
        return_value=_make_mock_session(),
    ), patch(
        "financial_data_etl.api.live_session_manager.subscribe_ohlcv_stream",
        side_effect=_mock_stream,
    ):
        async for _ in mgr.subscribe("NASDAQ:AAPL", "1d"):
            pass

        s = mgr.stats()
        assert s["alive"] is True
        assert s["total_subscribes"] == 1
        assert s["counter"] == 1
        assert s["active_streams"] == 0
        assert s["reconnect_count"] == 0
        assert s["connected_since"] is not None
        assert s["closed"] is False

    await mgr.close()
    print("[PASS] test_stats: monitoring dict is well-formed")


async def test_unique_ids_per_subscribe():
    """Each subscribe creates session IDs that contain the counter."""
    mgr = LiveSessionManager()

    with patch(
        "financial_data_etl.api.live_session_manager.open_session",
        new_callable=AsyncMock,
        return_value=_make_mock_session("cs_base"),
    ), patch(
        "financial_data_etl.api.live_session_manager.subscribe_ohlcv_stream",
        side_effect=_mock_stream,
    ) as mock_fn:
        for i in range(5):
            async for _ in mgr.subscribe("NASDAQ:AAPL", "1d"):
                pass

        # Verify IDs
        for i, call in enumerate(mock_fn.call_args_list):
            session = call.args[0]
            expected_chart = f"cs_base_live_{i + 1}"
            expected_quote = f"qs_live_{i + 1}"
            assert session["chart_id"] == expected_chart, (
                f"Call {i}: expected chart_id={expected_chart}, got {session['chart_id']}"
            )
            assert session["quote_id"] == expected_quote, (
                f"Call {i}: expected quote_id={expected_quote}, got {session['quote_id']}"
            )

    await mgr.close()
    print("[PASS] test_unique_ids_per_subscribe: 5 subscribes with correct incrementing IDs")


# ── Runner ───────────────────────────────────────────────────────────────────

async def run_all():
    tests = [
        test_lazy_init,
        test_first_subscribe_opens_session,
        test_session_reuse_across_subscribes,
        test_lock_serializes_concurrent_subscribes,
        test_active_streams_tracking,
        test_reconnect_resets_session,
        test_idle_watchdog_closes_connection,
        test_watchdog_does_not_close_active_stream,
        test_close_is_final,
        test_stats,
        test_unique_ids_per_subscribe,
    ]

    print(f"\n{'='*65}")
    print(f"  LIVE-04 TEST SUITE: LiveSessionManager")
    print(f"  (deterministic mocks — no real TradingView connection)")
    print(f"{'='*65}\n")

    passed = 0
    failed = 0

    for test in tests:
        try:
            await test()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"[FAIL] {test.__name__}: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'='*65}")
    print(f"  RESULTS: {passed} passed, {failed} failed out of {len(tests)}")
    print(f"{'='*65}\n")

    return failed


if __name__ == "__main__":
    failed = asyncio.run(run_all())
    sys.exit(1 if failed > 0 else 0)
