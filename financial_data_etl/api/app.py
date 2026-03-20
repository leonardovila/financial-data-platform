"""
financial-data-etl API: REST endpoints + Seed & Edge live WebSocket.

REST endpoints (unchanged from batch ETL era):
  GET /symbols, /ohlcv/history/{symbol}, /fundamentals/{symbol},
      /performance/1d/{symbol}, /volatility/1d/{symbol}, /volume/1d/{symbol}

Live WebSocket (LIVE-06):
  WS /ws/live/{symbol} — Seed & Edge event-driven streaming

Monitoring:
  GET /ws/stats — active connections and TV session pool status
"""

import sqlite3
import time
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from urllib.parse import parse_qs

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from financial_data_etl.api.db import get_connection
from financial_data_etl.api.live_session_manager import LiveSessionManager
from financial_data_etl.api.live_state import LiveSymbolState
from financial_data_etl.api.live_seed import load_historical_seed
from financial_data_etl.api.live_compute import compute_all_metrics_live
from financial_data_etl.scraping_pipeline.tv_websocket_connection.call_specification.asset_catalog import (
    load_assets_catalog,
    resolve_provider_symbol,
    validate_symbol,
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# LIVE WS CONSTANTS
# ──────────────────────────────────────────────────────────────────────────────
MAX_CONNECTIONS = 5           # concurrent WS limit (PoW demo)
MAX_SESSION_DURATION = 7200   # 2 hours hard TTL
IDLE_WARN_TIMEOUT = 300       # 5 min without client message → idle warning
IDLE_DISCONNECT_TIMEOUT = 600 # 10 min without client message → disconnect
MAX_CONSECUTIVE_HEARTBEATS = 5  # 5 × 45s = 225s of no TV data → assume dead

# ──────────────────────────────────────────────────────────────────────────────
# SECURITY CONFIG (LIVE-09)
# ──────────────────────────────────────────────────────────────────────────────
_DEBUG = os.environ.get("DEBUG", "").lower() in ("1", "true", "yes")

# ALLOWED_ORIGINS: comma-separated whitelist. Defaults to dev-friendly list.
_ALLOWED_ORIGINS_RAW = os.environ.get(
    "ALLOWED_ORIGINS",
    "http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000,http://127.0.0.1:5173",
)
ALLOWED_ORIGINS = [o.strip() for o in _ALLOWED_ORIGINS_RAW.split(",") if o.strip()]

# WS Origin validation: extracted hostnames for fast lookup
_WS_ALLOWED_HOSTS = {"localhost", "127.0.0.1"}
for _orig in ALLOWED_ORIGINS:
    # Extract host from "http(s)://host(:port)"
    _h = _orig.split("://", 1)[-1].split(":")[0].split("/")[0]
    if _h:
        _WS_ALLOWED_HOSTS.add(_h)

# Optional demo token — if set, WS connections must pass ?token=xxx
LIVE_DEMO_TOKEN = os.environ.get("LIVE_DEMO_TOKEN")


# ──────────────────────────────────────────────────────────────────────────────
# LIFECYCLE: startup + shutdown (LIVE-07 folded in)
# ──────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── STARTUP ──
    app.state.catalog = load_assets_catalog()
    app.state.session_manager = LiveSessionManager()
    app.state.active_connections: dict[int, dict] = {}  # id(ws) → metadata
    logger.info("API startup: catalog loaded (%d symbols), session manager ready",
                len(app.state.catalog))
    yield
    # ── SHUTDOWN ──
    await app.state.session_manager.close()
    logger.info("API shutdown: session manager closed")


app = FastAPI(title="financial-data-etl api", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _DEBUG else ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ══════════════════════════════════════════════════════════════════════════════
# REST ENDPOINTS (unchanged)
# ══════════════════════════════════════════════════════════════════════════════

# ── TTL cache for /symbols ──
_symbols_cache: list | None = None
_symbols_cache_ts: float = 0.0
_SYMBOLS_TTL = 300


@app.get("/")
def root():
    return {"status": "api ok"}


@app.get("/symbols")
def get_symbols():
    global _symbols_cache, _symbols_cache_ts

    now = time.monotonic()
    if _symbols_cache is not None and (now - _symbols_cache_ts) < _SYMBOLS_TTL:
        return _symbols_cache

    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT DISTINCT symbol FROM tv_candles_raw ORDER BY symbol"
        ).fetchall()
        _symbols_cache = [r[0] for r in rows]
        _symbols_cache_ts = now
        return _symbols_cache
    finally:
        conn.close()


@app.get("/ohlcv/history/{symbol}")
def get_ohlcv_history(symbol: str, limit: int = 4500):
    limit = min(limit, 4500)
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT ts, open, high, low, close, volume
            FROM (
                SELECT ts, open, high, low, close, volume
                FROM tv_candles_raw
                WHERE symbol = ?
                  AND timeframe = '1d'
                  AND is_partial = 0
                ORDER BY ts DESC
                LIMIT ?
            )
            ORDER BY ts ASC
            """,
            (symbol.upper(), limit),
        ).fetchall()
        return [
            {"time": r[0], "open": r[1], "high": r[2],
             "low": r[3], "close": r[4], "volume": r[5]}
            for r in rows
        ]
    finally:
        conn.close()


@app.get("/fundamentals/{symbol}")
def get_latest_fundamentals(symbol: str):
    conn = get_connection()
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT symbol, as_of_ts, company_name, market_cap,
                   pe_ttm, eps_ttm, shares_outstanding, sector, industry
            FROM fundamentals_snapshot
            WHERE symbol = ?
            ORDER BY as_of_ts DESC
            LIMIT 1
            """,
            (symbol.upper(),),
        ).fetchone()
        if not row:
            return {"symbol": symbol.upper(), "data": None}
        return {
            "symbol": row["symbol"], "as_of_ts": row["as_of_ts"],
            "company_name": row["company_name"], "market_cap": row["market_cap"],
            "pe_ttm": row["pe_ttm"], "eps_ttm": row["eps_ttm"],
            "shares_outstanding": row["shares_outstanding"],
            "sector": row["sector"], "industry": row["industry"],
        }
    finally:
        conn.close()


@app.get("/performance/1d/{symbol}")
def get_latest_performance_1d(symbol: str):
    conn = get_connection()
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT symbol, ts, ret_1d, ret_1w, ret_1m, ret_3m, ret_6m, ret_1y, computed_at
            FROM performance_1d
            WHERE symbol = ? AND is_partial = 0
            ORDER BY ts DESC LIMIT 1
            """,
            (symbol.upper(),),
        ).fetchone()
        if not row:
            return {"symbol": symbol.upper(), "data": None}
        return {
            "symbol": row["symbol"], "ts": row["ts"],
            "ret_1d": row["ret_1d"], "ret_1w": row["ret_1w"],
            "ret_1m": row["ret_1m"], "ret_3m": row["ret_3m"],
            "ret_6m": row["ret_6m"], "ret_1y": row["ret_1y"],
            "computed_at": row["computed_at"],
        }
    finally:
        conn.close()


@app.get("/volatility/1d/{symbol}")
def get_latest_volatility_1d(symbol: str):
    conn = get_connection()
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT symbol, ts, range_intraday, vol_1w, vol_1m, vol_3m, vol_6m, vol_1y, computed_at
            FROM volatility_1d
            WHERE symbol = ? AND is_partial = 0
            ORDER BY ts DESC LIMIT 1
            """,
            (symbol.upper(),),
        ).fetchone()
        if not row:
            return {"symbol": symbol.upper(), "data": None}
        return {
            "symbol": row["symbol"], "ts": row["ts"],
            "range_intraday": row["range_intraday"],
            "vol_1w": row["vol_1w"], "vol_1m": row["vol_1m"],
            "vol_3m": row["vol_3m"], "vol_6m": row["vol_6m"],
            "vol_1y": row["vol_1y"], "computed_at": row["computed_at"],
        }
    finally:
        conn.close()


@app.get("/volume/1d/{symbol}")
def get_latest_volume_1d(symbol: str):
    conn = get_connection()
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT symbol, ts, volume_usd, vol_sma_20, vol_sma_50, vol_sma_100, vol_sma_200,
                   vol_gap_20, vol_gap_50, vol_gap_100, vol_gap_200
            FROM volume_1d
            WHERE symbol = ? AND is_partial = 0
            ORDER BY ts DESC LIMIT 1
            """,
            (symbol.upper(),),
        ).fetchone()
        if not row:
            return {"symbol": symbol.upper(), "data": None}
        return {
            "symbol": row["symbol"], "ts": row["ts"],
            "volume_usd": row["volume_usd"],
            "vol_sma_20": row["vol_sma_20"], "vol_sma_50": row["vol_sma_50"],
            "vol_sma_100": row["vol_sma_100"], "vol_sma_200": row["vol_sma_200"],
            "vol_gap_20": row["vol_gap_20"], "vol_gap_50": row["vol_gap_50"],
            "vol_gap_100": row["vol_gap_100"], "vol_gap_200": row["vol_gap_200"],
        }
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# MONITORING ENDPOINT (LIVE-08)
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/ws/stats")
def ws_stats():
    conns = app.state.active_connections
    return {
        "active_connections": len(conns),
        "connections": list(conns.values()),
        "tv_session": app.state.session_manager.stats(),
    }


# ══════════════════════════════════════════════════════════════════════════════
# LIVE WEBSOCKET ENDPOINT (LIVE-06 — The Crown Jewel)
#
# Seed & Edge flow:
#   1. SEED: load_historical_seed() from SQLite → send full chart + metrics
#   2. EDGE: subscribe_ohlcv_stream() → update_tick() → compute → send tick
#   3. SWITCH: client sends {action:'switch', symbol:'TSLA'} → restart flow
#   4. ZOMBIE: hard TTL (2h), idle detection (5min), heartbeat death (5×45s)
# ══════════════════════════════════════════════════════════════════════════════

async def _validate_ws_security(websocket: WebSocket) -> bool:
    """
    Pre-accept security gate for WebSocket connections (LIVE-09).
    Returns True if the connection is authorized, False if rejected.

    Checks:
      1. Origin header against _WS_ALLOWED_HOSTS whitelist
      2. Demo token (if LIVE_DEMO_TOKEN env var is set)

    In DEBUG mode, origin validation is skipped.
    """
    client_host = websocket.client.host if websocket.client else "unknown"

    # ── ORIGIN VALIDATION ──
    if not _DEBUG:
        origin = websocket.headers.get("origin", "")
        if origin:
            # Extract hostname from "http(s)://host(:port)"
            origin_host = origin.split("://", 1)[-1].split(":")[0].split("/")[0]
        else:
            # No Origin header — browser WS always sends one; absence means
            # non-browser client. Allow only if from localhost.
            origin_host = client_host

        if origin_host not in _WS_ALLOWED_HOSTS:
            logger.warning(
                "SECURITY: WS rejected — invalid origin '%s' from %s",
                origin, client_host,
            )
            await websocket.close(code=4003, reason="Origin not allowed")
            return False

    # ── DEMO TOKEN ──
    if LIVE_DEMO_TOKEN:
        # Parse token from query string: /ws/live/AAPL?token=xxx
        qs = parse_qs(str(websocket.scope.get("query_string", b""), "utf-8"))
        provided_token = qs.get("token", [None])[0]

        if provided_token != LIVE_DEMO_TOKEN:
            logger.warning(
                "SECURITY: WS rejected — invalid/missing token from %s (origin: %s)",
                client_host, websocket.headers.get("origin", "none"),
            )
            await websocket.close(code=4001, reason="Invalid or missing token")
            return False

    return True


def _safe_float(val) -> float | None:
    """Cast to float, return None if not a valid number."""
    if val is None:
        return None
    try:
        f = float(val)
        if f != f:  # NaN check
            return None
        return f
    except (TypeError, ValueError):
        return None


def _normalize_fundamentals(raw: dict, symbol: str) -> dict:
    """
    Normalize TV raw quote fields to the frontend FundamentalsData contract.
    TV sends: market_cap_basic, price_earnings_ttm, earnings_per_share_basic_ttm, etc.
    Frontend expects: market_cap, pe_ttm, eps_ttm, etc. — all numerics as float.
    """
    return {
        "symbol": symbol,
        "as_of_ts": int(time.time()),
        "company_name": raw.get("local_description") or raw.get("description"),
        "market_cap": _safe_float(raw.get("market_cap_basic") or raw.get("market_cap_calc")),
        "pe_ttm": _safe_float(raw.get("price_earnings_ttm")),
        "eps_ttm": _safe_float(raw.get("earnings_per_share_basic_ttm")),
        "shares_outstanding": _safe_float(
            raw.get("total_shares_outstanding_current")
            or raw.get("total_shares_outstanding_calculated")
        ),
        "sector": raw.get("sector"),
        "industry": raw.get("industry"),
    }


def _resolve_provider(catalog: dict, symbol: str) -> str:
    """Resolve symbol → provider_symbol (e.g., AAPL → NASDAQ:AAPL)."""
    sym = symbol.upper()
    validate_symbol(catalog, sym)
    return resolve_provider_symbol(catalog, sym, "tradingview")


async def _listen_client(
    websocket: WebSocket,
    switch_event: asyncio.Event,
    switch_target: list,
    last_client_msg: list,
):
    """
    Concurrent listener for client messages (symbol switches, pings).
    Runs alongside the Edge loop. Sets switch_event when a switch is requested.
    """
    try:
        while True:
            data = await websocket.receive_json()
            last_client_msg[0] = time.monotonic()

            action = data.get("action")
            if action == "switch":
                new_sym = data.get("symbol", "").upper()
                if new_sym:
                    switch_target[0] = new_sym
                    switch_event.set()
            elif action == "ping":
                await websocket.send_json({"type": "pong"})
    except (WebSocketDisconnect, Exception):
        # Client disconnected or error — the main loop handles cleanup
        switch_event.set()  # unblock the main loop if it's waiting


@app.websocket("/ws/live/{symbol}")
async def ws_live(websocket: WebSocket, symbol: str):
    # ── SECURITY GATE (LIVE-09) ──
    if not await _validate_ws_security(websocket):
        return

    # ── CONNECTION GATE ──
    if len(app.state.active_connections) >= MAX_CONNECTIONS:
        await websocket.close(code=4029, reason="Too many connections")
        return

    await websocket.accept()

    catalog = app.state.catalog
    session_manager = app.state.session_manager
    loop = asyncio.get_event_loop()
    ws_id = id(websocket)
    session_start = time.monotonic()
    current_symbol = symbol.upper()

    # Register in active connections
    conn_meta = {
        "symbol": current_symbol,
        "connected_at": time.time(),
        "last_tick_at": None,
        "last_client_message_at": time.time(),
        "tick_count": 0,
    }
    app.state.active_connections[ws_id] = conn_meta

    listener_task = None

    try:
        while True:
            # ── CHECK HARD TTL ──
            if time.monotonic() - session_start > MAX_SESSION_DURATION:
                await websocket.send_json({"type": "session_expired"})
                break

            # ── RESOLVE PROVIDER SYMBOL ──
            try:
                provider_symbol = _resolve_provider(catalog, current_symbol)
            except ValueError as e:
                await websocket.send_json({
                    "type": "error",
                    "message": f"Unknown symbol: {current_symbol}",
                })
                break

            # ── SEED PHASE (one-time per symbol) ──
            seed_data = await loop.run_in_executor(
                None, load_historical_seed, current_symbol
            )

            await websocket.send_json({"type": "seed", **seed_data})

            # Initialize in-memory state
            state = LiveSymbolState(current_symbol, "1d")
            chart_candles = seed_data.get("chart_candles", [])
            if chart_candles:
                state.seed(
                    chart_candles[-258:],
                    fundamentals=seed_data.get("fundamentals"),
                    company_name=seed_data.get("company_name"),
                )

            # Update connection metadata
            conn_meta["symbol"] = current_symbol

            # ── EDGE PHASE (continuous) ──
            switch_event = asyncio.Event()
            switch_target = [None]  # mutable container for new symbol
            last_client_msg = [time.monotonic()]
            idle_warned = False
            consecutive_heartbeats = 0

            # Launch the client listener
            listener_task = asyncio.create_task(
                _listen_client(websocket, switch_event, switch_target, last_client_msg)
            )

            switched = False
            try:
                async for event_type, data in session_manager.subscribe(
                    provider_symbol, "1d", n_initial=3
                ):
                    # ── ZOMBIE CHECKS ──
                    now = time.monotonic()

                    # Hard TTL
                    if now - session_start > MAX_SESSION_DURATION:
                        await websocket.send_json({"type": "session_expired"})
                        break

                    # Idle detection
                    idle_s = now - last_client_msg[0]
                    if idle_s > IDLE_DISCONNECT_TIMEOUT:
                        await websocket.send_json({"type": "idle_disconnect"})
                        break
                    if idle_s > IDLE_WARN_TIMEOUT and not idle_warned:
                        await websocket.send_json({"type": "idle_warning"})
                        idle_warned = True

                    # Symbol switch requested?
                    if switch_event.is_set():
                        new_sym = switch_target[0]
                        if new_sym:
                            current_symbol = new_sym
                            switched = True
                        break

                    # ── ROUTE EVENTS ──
                    if event_type == "seed":
                        state.merge_tv_seed(data)

                    elif event_type == "tick":
                        consecutive_heartbeats = 0
                        live_candle = state.update_tick(data)

                        # Compute metrics in executor (thread-safe via df copy)
                        snapshot = state.get_df_snapshot()
                        metrics = await loop.run_in_executor(
                            None, compute_all_metrics_live, snapshot
                        )

                        await websocket.send_json({
                            "type": "tick",
                            "candle": live_candle,
                            "metrics": metrics,
                            "ts": time.time(),
                        })

                        conn_meta["tick_count"] += 1
                        conn_meta["last_tick_at"] = time.time()

                    elif event_type == "company_name":
                        state.company_name = data
                        await websocket.send_json({
                            "type": "company_name",
                            "name": data,
                        })

                    elif event_type == "fundamentals":
                        # TV sends raw keys (market_cap_basic, price_earnings_ttm, etc.)
                        # Normalize to the frontend contract (market_cap, pe_ttm, etc.)
                        normalized = _normalize_fundamentals(data, current_symbol)
                        state.fundamentals = normalized
                        await websocket.send_json({
                            "type": "fundamentals",
                            "data": normalized,
                        })

                    elif event_type == "heartbeat":
                        consecutive_heartbeats += 1
                        await websocket.send_json({"type": "heartbeat"})

                        if consecutive_heartbeats >= MAX_CONSECUTIVE_HEARTBEATS:
                            # Too many heartbeats — TV may be dead or market closed
                            # Don't disconnect, but log it
                            logger.warning(
                                "ws_live %s: %d consecutive heartbeats",
                                current_symbol, consecutive_heartbeats,
                            )

            finally:
                # Cancel the listener task for this symbol's edge phase
                if listener_task and not listener_task.done():
                    listener_task.cancel()
                    try:
                        await listener_task
                    except asyncio.CancelledError:
                        pass
                    listener_task = None

            # If we broke due to symbol switch, continue the while True loop
            if switched:
                continue
            # Otherwise (TTL, idle, error) — exit
            break

    except WebSocketDisconnect:
        logger.info("ws_live: client disconnected (%s)", current_symbol)

    except Exception as e:
        logger.error("ws_live: unexpected error: %s", e, exc_info=True)
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass

    finally:
        # ── CLEANUP (guaranteed) ──
        app.state.active_connections.pop(ws_id, None)

        if listener_task and not listener_task.done():
            listener_task.cancel()
            try:
                await listener_task
            except asyncio.CancelledError:
                pass

        logger.info(
            "ws_live: session ended for %s (ticks=%d, duration=%.0fs)",
            current_symbol,
            conn_meta.get("tick_count", 0),
            time.monotonic() - session_start,
        )
