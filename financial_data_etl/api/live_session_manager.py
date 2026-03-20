"""
LiveSessionManager: gatekeeper for TradingView WebSocket connections (LIVE-04).

Each subscribe() call opens its OWN dedicated TV WebSocket connection.
This eliminates the concurrent recv() crash that occurs when a shared socket
is read by two generators simultaneously (symbol switch, page reload).

With MAX_CONNECTIONS=5, we have at most 5 TV connections — trivial load.

Concurrency model:
  - Each subscriber is fully isolated: own socket, own recv loop, own cleanup
  - _active_streams counter tracks live generators for stats/monitoring
  - No asyncio.Lock needed — no shared mutable socket state
"""

from __future__ import annotations
from typing import Dict, Any, AsyncGenerator, Tuple
import asyncio
import random
import string
import time
import logging

from financial_data_etl.scraping_pipeline.tv_websocket_connection.call_execution.tradingview_ws import (
    open_session,
    close_session,
    subscribe_ohlcv_stream,
)

logger = logging.getLogger(__name__)


class LiveSessionManager:
    """
    Gatekeeper for TradingView WebSocket connections.

    Usage (inside a FastAPI WebSocket handler):

        async for event_type, data in manager.subscribe("NASDAQ:AAPL", "1d"):
            ...

    Each subscribe() opens a dedicated TV connection and closes it on exit.
    """

    def __init__(self) -> None:
        self._active_streams: int = 0
        self._total_subscribes: int = 0
        self._last_subscribe_ts: float = 0.0
        self._closed: bool = False

    async def subscribe(
        self,
        provider_symbol: str,
        timeframe: str,
        n_initial: int = 3,
    ) -> AsyncGenerator[Tuple[str, Any], None]:
        """
        Subscribe to a symbol's live stream via a DEDICATED TV connection.

        Opens its own WebSocket to TradingView on entry, closes it on exit.
        No shared socket — no concurrent recv() conflicts.
        """
        if self._closed:
            raise RuntimeError("LiveSessionManager is closed")

        # ── OPEN DEDICATED SESSION ──
        session = await open_session(trace=False)
        rand_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=12))
        stream_session = {
            "ws": session["ws"],
            "trace_file": session.get("trace_file"),
            "chart_id": f"cs_{rand_id}",
            "quote_id": f"qs_{rand_id}",
        }
        self._last_subscribe_ts = time.monotonic()
        self._total_subscribes += 1
        self._active_streams += 1

        logger.info(
            "TV subscribe: %s (stream_id=%s, active=%d)",
            provider_symbol, rand_id, self._active_streams,
        )

        # ── STREAM PHASE ──
        try:
            async for event in subscribe_ohlcv_stream(
                stream_session, provider_symbol, timeframe, n_initial
            ):
                yield event
        finally:
            # ── CLEANUP: close THIS session (generator exit, break, error) ──
            self._active_streams -= 1
            try:
                await close_session(session)
            except Exception:
                pass
            logger.info(
                "TV unsubscribe: %s (stream_id=%s, active=%d)",
                provider_symbol, rand_id, self._active_streams,
            )

    async def close(self) -> None:
        """Clean shutdown (FastAPI shutdown hook). Marks manager as closed."""
        self._closed = True
        logger.info("LiveSessionManager closed (active_streams=%d)", self._active_streams)

    def stats(self) -> Dict[str, Any]:
        """Return current state for /ws/stats monitoring endpoint."""
        return {
            "active_streams": self._active_streams,
            "total_subscribes": self._total_subscribes,
            "last_subscribe_ts": self._last_subscribe_ts,
            "closed": self._closed,
        }
