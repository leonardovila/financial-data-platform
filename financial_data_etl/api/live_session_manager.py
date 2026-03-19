"""
LiveSessionManager: singleton gatekeeper for the TradingView WebSocket (LIVE-04).

Manages exactly ONE persistent TradingView WebSocket connection. All live
stream subscribers share this connection via unique chart/quote session IDs.

Concurrency model:
  - asyncio.Lock serializes subscribe() setup (session init + ID assignment)
  - The stream itself runs OUTSIDE the lock (no blocking during recv)
  - _active_streams counter tracks live generators for safe idle shutdown
  - Idle watchdog closes the TV connection after IDLE_TIMEOUT_S of inactivity

This module is the single point of contact with TradingView for the live API.
The batch ETL uses its own separate connection pool (tv_websocket_scraper.py).
"""

from __future__ import annotations
from typing import Dict, Any, Optional, AsyncGenerator, Tuple
import asyncio
import time
import logging

from financial_data_etl.scraping_pipeline.tv_websocket_connection.call_execution.tradingview_ws import (
    open_session,
    close_session,
    subscribe_ohlcv_stream,
)

logger = logging.getLogger(__name__)

IDLE_TIMEOUT_S = 600    # 10 minutes — close TV connection if no active streams
IDLE_CHECK_INTERVAL = 60  # seconds between idle checks


class LiveSessionManager:
    """
    Singleton gatekeeper for a persistent TradingView WebSocket connection.

    Usage (inside a FastAPI WebSocket handler):

        stream = manager.subscribe("NASDAQ:AAPL", "1d", n_initial=3)
        async for event_type, data in stream:
            ...

    Lifecycle:
        - Created at FastAPI startup (no connection opened yet — lazy init)
        - First subscribe() opens the TV WS connection
        - Subsequent subscribe() calls reuse the same WS with unique session IDs
        - Idle watchdog closes the WS if no streams active for 10 minutes
        - FastAPI shutdown calls manager.close()
    """

    def __init__(self) -> None:
        self._session: Optional[Dict[str, Any]] = None
        self._base_chart_id: Optional[str] = None
        self._counter: int = 0
        self._lock: asyncio.Lock = asyncio.Lock()
        self._active_streams: int = 0
        self._last_subscribe_ts: float = 0.0
        self._watchdog_task: Optional[asyncio.Task] = None
        self._closed: bool = False
        self._total_subscribes: int = 0
        self._reconnect_count: int = 0
        self._connected_since: Optional[float] = None

    # ──────────────────────────────────────────────────────────────────────
    # SUBSCRIBE: the public API — returns an async generator of events
    # ──────────────────────────────────────────────────────────────────────

    async def subscribe(
        self,
        provider_symbol: str,
        timeframe: str,
        n_initial: int = 3,
    ) -> AsyncGenerator[Tuple[str, Any], None]:
        """
        Subscribe to a symbol's live stream via the shared TV connection.

        Yields the same events as subscribe_ohlcv_stream():
            ('seed', candles), ('tick', candles), ('fundamentals', snapshot),
            ('company_name', name), ('heartbeat', None)

        The asyncio.Lock is held ONLY during session setup (~1ms if already
        connected, ~500ms on first connect). The actual stream runs outside
        the lock — recv() never blocks other coroutines from subscribing.
        """
        if self._closed:
            raise RuntimeError("LiveSessionManager is closed")

        # ── SETUP PHASE (under lock) ──
        async with self._lock:
            # Lazy init: open TV connection on first subscribe
            if self._session is None:
                logger.info("Opening TradingView WebSocket connection (lazy init)")
                self._session = await open_session(trace=False)
                self._base_chart_id = self._session["chart_id"]
                self._connected_since = time.monotonic()
                logger.info(
                    "TV connection established: base_chart_id=%s", self._base_chart_id
                )

                # Start idle watchdog if not running
                if self._watchdog_task is None or self._watchdog_task.done():
                    self._watchdog_task = asyncio.create_task(self._idle_watchdog())

            # Assign unique session IDs for this subscription
            import random
            import string
            self._counter += 1
            rand_str = ''.join(random.choices(string.ascii_lowercase + string.digits, k=12))
            stream_session = {
                "ws": self._session["ws"],
                "trace_file": self._session.get("trace_file"),
                "chart_id": f"cs_{rand_str}",
                "quote_id": f"qs_{rand_str}",
            }
            self._last_subscribe_ts = time.monotonic()
            self._total_subscribes += 1

        # ── STREAM PHASE (outside lock) ──
        self._active_streams += 1
        try:
            async for event in subscribe_ohlcv_stream(
                stream_session, provider_symbol, timeframe, n_initial
            ):
                yield event
        finally:
            self._active_streams -= 1

    # ──────────────────────────────────────────────────────────────────────
    # RECONNECT: reset the dead session, next subscribe() reopens
    # ──────────────────────────────────────────────────────────────────────

    async def reconnect(self) -> None:
        """
        Close the dead TV session and reset state.

        Called by the WS handler when subscribe_ohlcv_stream raises
        ConnectionClosed. The next subscribe() call will trigger a
        fresh open_session().
        """
        async with self._lock:
            if self._session is not None:
                logger.warning("Reconnecting: closing dead TV session")
                try:
                    await close_session(self._session)
                except Exception:
                    pass
                self._session = None
                self._base_chart_id = None
                self._connected_since = None
                self._reconnect_count += 1

    # ──────────────────────────────────────────────────────────────────────
    # CLOSE: clean shutdown (FastAPI shutdown hook)
    # ──────────────────────────────────────────────────────────────────────

    async def close(self) -> None:
        """
        Cleanly shut down: cancel watchdog, close TV connection.
        Called from FastAPI's shutdown event.
        """
        self._closed = True

        # Cancel the idle watchdog
        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except asyncio.CancelledError:
                pass
            self._watchdog_task = None

        # Close the TV session
        async with self._lock:
            if self._session is not None:
                logger.info("Shutting down: closing TV session")
                try:
                    await close_session(self._session)
                except Exception:
                    pass
                self._session = None
                self._base_chart_id = None
                self._connected_since = None

    # ──────────────────────────────────────────────────────────────────────
    # IDLE WATCHDOG: background task that closes idle connections
    # ──────────────────────────────────────────────────────────────────────

    async def _idle_watchdog(self) -> None:
        """
        Background task: checks every 60s if the TV connection has been
        idle (no active streams, no recent subscribes) for IDLE_TIMEOUT_S.
        If so, closes the connection to prevent zombie TV sessions overnight.
        """
        try:
            while True:
                await asyncio.sleep(IDLE_CHECK_INTERVAL)

                # Quick pre-check without lock (safe: single-threaded asyncio)
                if (
                    self._session is not None
                    and self._active_streams == 0
                    and time.monotonic() - self._last_subscribe_ts > IDLE_TIMEOUT_S
                ):
                    # Double-check under lock to prevent race with subscribe()
                    async with self._lock:
                        if (
                            self._session is not None
                            and self._active_streams == 0
                            and time.monotonic() - self._last_subscribe_ts > IDLE_TIMEOUT_S
                        ):
                            logger.info(
                                "Idle watchdog: no streams for %ds — closing TV connection",
                                IDLE_TIMEOUT_S,
                            )
                            try:
                                await close_session(self._session)
                            except Exception:
                                pass
                            self._session = None
                            self._base_chart_id = None
                            self._connected_since = None

        except asyncio.CancelledError:
            # Normal shutdown path — close() cancelled us
            pass

    # ──────────────────────────────────────────────────────────────────────
    # OBSERVABILITY
    # ──────────────────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        """Return current state for /ws/stats monitoring endpoint."""
        return {
            "alive": self._session is not None,
            "active_streams": self._active_streams,
            "total_subscribes": self._total_subscribes,
            "reconnect_count": self._reconnect_count,
            "counter": self._counter,
            "last_subscribe_ts": self._last_subscribe_ts,
            "connected_since": self._connected_since,
            "idle_timeout_s": IDLE_TIMEOUT_S,
            "closed": self._closed,
        }

    @property
    def is_connected(self) -> bool:
        """True if a TV WebSocket connection is currently open."""
        return self._session is not None

    @property
    def active_streams(self) -> int:
        """Number of currently active subscribe() generators."""
        return self._active_streams
