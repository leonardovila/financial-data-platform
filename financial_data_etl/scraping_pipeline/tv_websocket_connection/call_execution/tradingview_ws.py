"""
TradingView WebSocket tunnel.

Refactored for:
  BP-004: Multiplexed OHLCV + fundamentals (overlapped I/O in single recv loop)
  BP-005: Strict timeouts on every recv/send (no more 12-hour hangs)
  BP-014: Per-session trace files (no global shared state)
  BP-017: Connection retry with exponential backoff
"""

from __future__ import annotations
from typing import Dict, Any, Optional, AsyncGenerator, Tuple, List
import json, re, asyncio, itertools, websockets
from pathlib import Path
from datetime import datetime
from financial_data_etl.scraping_pipeline.tv_websocket_connection.parsing.ohlcv_parser import parse_ohlcv

# ──────────────────────────────────────────────────────────────────────────────
# TIMEOUTS & RETRY CONFIG
# ──────────────────────────────────────────────────────────────────────────────
RECV_TIMEOUT = 30       # seconds per ws.recv()
SEND_TIMEOUT = 10       # seconds per ws.send()
SYMBOL_TIMEOUT = 60     # seconds for entire per-symbol multiplexed request
CONNECT_MAX_RETRIES = 3 # retries on connection failure with backoff

# ──────────────────────────────────────────────────────────────────────────────
# PER-SESSION TRACE FILES (BP-014)
# Each open_session() creates its own file. No global shared state.
# ──────────────────────────────────────────────────────────────────────────────
_trace_counter = itertools.count()


def _create_per_session_trace_file():
    logs_dir = Path("ws_traces")
    logs_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    n = next(_trace_counter)
    trace_path = logs_dir / f"WS_TRACE_{ts}_{n}.txt"
    return trace_path.open("w", encoding="utf-8")


def close_global_ws_trace():
    """No-op: trace files are now per-session, closed in close_session()."""
    pass


# ──────────────────────────────────────────────────────────────────────────────
# LOW-LEVEL SEND (BP-005: timeout-protected)
# ──────────────────────────────────────────────────────────────────────────────

async def send_to_tradingview(websocket, message_dict, trace_file=None):
    message_json = json.dumps(message_dict)
    payload = f"~m~{len(message_json)}~m~{message_json}"
    if trace_file:
        trace_file.write("SEND:\n")
        trace_file.write(json.dumps(message_dict) + "\n\n")
    await asyncio.wait_for(websocket.send(payload), timeout=SEND_TIMEOUT)


# ──────────────────────────────────────────────────────────────────────────────
# CONNECTION (BP-017: retry with exponential backoff)
# ──────────────────────────────────────────────────────────────────────────────

async def connect_to_tradingview(timeout_s: int = 15, trace_file=None):
    uri = "wss://data.tradingview.com/socket.io/websocket?from=chart%2F&date=2025_03_31-11_22&type=chart"

    for attempt in range(CONNECT_MAX_RETRIES + 1):
        try:
            websocket = await websockets.connect(
                uri,
                extra_headers={
                    "Origin": "https://www.tradingview.com",
                    "User-Agent": "Mozilla/5.0"
                },
                open_timeout=timeout_s,
            )

            rawMessage = await asyncio.wait_for(websocket.recv(), timeout=timeout_s)
            if trace_file:
                trace_file.write("HANDSHAKE RECEIVE RAW:\n")
                trace_file.write(rawMessage + "\n\n")

            sessionIdMatch = re.search(r'"session_id":"([^"]+)"', rawMessage)
            if not sessionIdMatch:
                await websocket.close()
                raise RuntimeError("No session_id en handshake de TradingView")

            chartSession = f"cs_{sessionIdMatch.group(1)}"
            if trace_file:
                trace_file.write(f"SESSION_ID: {chartSession}\n\n")
            return websocket, chartSession

        except Exception as e:
            if attempt < CONNECT_MAX_RETRIES:
                backoff = 1 * (2 ** attempt)  # 1s, 2s, 4s
                if trace_file:
                    trace_file.write(f"CONNECT RETRY {attempt + 1}/{CONNECT_MAX_RETRIES} after {backoff}s: {e}\n\n")
                await asyncio.sleep(backoff)
            else:
                raise


# ──────────────────────────────────────────────────────────────────────────────
# SESSION MANAGEMENT (BP-014: per-session trace lifecycle)
# ──────────────────────────────────────────────────────────────────────────────

async def open_session(trace: bool = True) -> Dict[str, Any]:
    trace_file = _create_per_session_trace_file() if trace else None

    ws, chart = await connect_to_tradingview(trace_file=trace_file)

    if not ws or not chart:
        if trace_file:
            trace_file.write("ERROR: can not open session\n")
            trace_file.close()
        raise RuntimeError("can not open session TradingView session")

    if trace_file:
        trace_file.write(f"\nSESSION ESTABLISHED\n")
        trace_file.write(f"CHART_ID: {chart}\n\n")

    return {
        "ws": ws,
        "chart_id": chart,
        "trace_file": trace_file,
    }


async def close_session(session: Dict[str, Any]) -> None:
    try:
        await session["ws"].close()
    except Exception:
        pass
    finally:
        tf = session.get("trace_file")
        if tf:
            try:
                tf.write("\nSESSION CLOSED\n")
                tf.flush()
                tf.close()
            except Exception:
                pass


# ──────────────────────────────────────────────────────────────────────────────
# MULTIPLEXED OHLCV + FUNDAMENTALS (BP-004 + BP-005)
#
# Architecture:
#   1. Fire ALL send commands upfront (3 chart + 3 quote) — no waiting between
#   2. Single receive loop routes messages by type (timescale_update vs qsd)
#   3. Loop exits when BOTH ohlcv_done AND quote_done
#   4. Every recv() is timeout-protected (BP-005: RECV_TIMEOUT)
#   5. Entire operation is timeout-protected (BP-005: SYMBOL_TIMEOUT)
# ──────────────────────────────────────────────────────────────────────────────

_TF_ALIAS_FOR_TV = {
    "1d": "1D", "1h": "1H", "1m": "1M", "5m": "5M",
    "15m": "15M", "30m": "30M", "2h": "2H", "4h": "4H", "1w": "1W",
}


async def _request_ohlcv_and_fundamentals_impl(
    session: Dict[str, Any],
    provider_symbol: str,
    timeframe: str,
    n: int,
) -> Dict[str, Any]:
    ws = session["ws"]
    trace_file = session.get("trace_file")
    chart_id = session["chart_id"]
    quote_id = session.get("quote_id", "qs_multiplexer_full_1")
    tf_tv = _TF_ALIAS_FOR_TV.get(timeframe, timeframe.upper())

    # ── FIRE ALL REQUESTS UPFRONT (overlapped I/O) ──

    # Chart (OHLCV)
    await send_to_tradingview(ws, {"m": "chart_create_session", "p": [chart_id]}, trace_file)
    await send_to_tradingview(ws, {"m": "resolve_symbol", "p": [chart_id, "s1", provider_symbol]}, trace_file)
    await send_to_tradingview(ws, {
        "m": "create_series",
        "p": [chart_id, "sds_1", "s1", "s1", tf_tv, n, ""]
    }, trace_file)

    # Quote (Fundamentals) — sent IMMEDIATELY after chart, no waiting for chart response
    await send_to_tradingview(ws, {"m": "quote_create_session", "p": [quote_id]}, trace_file)
    await send_to_tradingview(ws, {
        "m": "quote_set_fields",
        "p": [
            quote_id,
            "market_cap_basic",
            "market_cap_calc",
            "total_shares_outstanding_current",
            "total_shares_outstanding_calculated",
            "price_earnings_ttm",
            "earnings_per_share_basic_ttm",
            "industry",
            "sector",
        ],
    }, trace_file)
    await send_to_tradingview(ws, {
        "m": "quote_add_symbols",
        "p": [
            quote_id,
            f"={{\"adjustment\":\"splits\",\"currency-id\":\"USD\",\"symbol\":\"{provider_symbol}\"}}",
        ],
    }, trace_file)

    # ── UNIFIED RECEIVE LOOP: route by message type ──
    ohlcv_payload = None
    company_name: Optional[str] = None
    quote_snapshot: Dict[str, Any] = {}
    ohlcv_done = False
    quote_done = False

    while not (ohlcv_done and quote_done):
        message = await asyncio.wait_for(ws.recv(), timeout=RECV_TIMEOUT)

        if trace_file:
            trace_file.write("RECEIVE RAW:\n")
            trace_file.write(message + "\n\n")

        # ── TV KEEPALIVE: echo ~h~N pings immediately ──
        for ping_match in re.finditer(r"~h~\d+", message):
            ping = ping_match.group(0)
            pong = f"~m~{len(ping)}~m~{ping}"
            try:
                await ws.send(pong)
            except Exception:
                pass

        for chunk in re.split(r"~m~\d+~m~", message)[1:]:
            if not chunk.strip():
                continue

            try:
                payload = json.loads(chunk)
            except json.JSONDecodeError:
                continue

            mtype = payload.get("m")

            # ── OHLCV responses ──
            if mtype == "symbol_resolved":
                p = payload.get("p")
                if isinstance(p, list) and len(p) >= 3:
                    meta = p[2]
                    if isinstance(meta, dict):
                        company_name = meta.get("local_description") or meta.get("description")

            elif mtype == "timescale_update":
                if trace_file:
                    trace_file.write("TIMESCALE_UPDATE DETECTED\n\n")
                ohlcv_payload = payload
                ohlcv_done = True

            # ── Quote/Fundamentals responses ──
            elif mtype == "qsd":
                p = payload.get("p")
                if isinstance(p, list) and len(p) >= 2:
                    second = p[1]
                    if isinstance(second, dict):
                        v = second.get("v")
                        if isinstance(v, dict):
                            quote_snapshot.update(v)

            elif mtype == "quote_completed":
                quote_done = True

    candles = parse_ohlcv(ohlcv_payload)

    return {
        "symbol": provider_symbol,
        "timeframe": timeframe,
        "candles": candles,
        "fundamentals_raw": quote_snapshot,
        "company_name": company_name,
    }


async def request_ohlcv_and_fundamentals(
    session: Dict[str, Any],
    provider_symbol: str,
    timeframe: str,
    n: int,
) -> Dict[str, Any]:
    """Multiplexed OHLCV + fundamentals with overall per-symbol timeout."""
    return await asyncio.wait_for(
        _request_ohlcv_and_fundamentals_impl(session, provider_symbol, timeframe, n),
        timeout=SYMBOL_TIMEOUT,
    )


# ──────────────────────────────────────────────────────────────────────────────
# CLEANUP (timeout-protected sends)
# ──────────────────────────────────────────────────────────────────────────────

async def cleanup_chart_and_quote(session: Dict[str, Any]) -> None:
    """Delete chart and quote sessions so the connection can be reused."""
    ws = session["ws"]
    trace_file = session.get("trace_file")
    chart_id = session.get("chart_id")
    quote_id = session.get("quote_id", "qs_multiplexer_full_1")

    try:
        await send_to_tradingview(ws, {"m": "chart_delete_session", "p": [chart_id]}, trace_file)
    except Exception:
        pass
    try:
        await send_to_tradingview(ws, {"m": "quote_delete_session", "p": [quote_id]}, trace_file)
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# BATCH MULTIPLEXING: N symbols over 1 WebSocket
#
# Architecture:
#   1. Fire 6 × N send commands (3 chart + 3 quote per symbol), all upfront
#   2. Single receive loop routes messages by session ID in p[0]
#   3. Each symbol tracked independently (ohlcv_done + quote_done)
#   4. Loop exits when ALL symbols complete, or on deadline/timeout
#   5. Returns partial results on timeout (completed = success, rest = failure)
# ──────────────────────────────────────────────────────────────────────────────

BATCH_TIMEOUT = 90  # seconds for entire batch of N symbols

_QUOTE_FIELDS = [
    "market_cap_basic",
    "market_cap_calc",
    "total_shares_outstanding_current",
    "total_shares_outstanding_calculated",
    "price_earnings_ttm",
    "earnings_per_share_basic_ttm",
    "industry",
    "sector",
]


async def request_batch_multiplexed(
    session: Dict[str, Any],
    batch_items: list,
) -> tuple:
    """
    Multiplexed multi-symbol request over a single WebSocket connection.

    Args:
        session: open WS session from open_session()
        batch_items: list of dicts, each with keys:
            provider_symbol, chart_id, quote_id, timeframe, n_candles

    Returns:
        (successes, failures) where:
        - successes: {provider_symbol: body_dict}
        - failures: [provider_symbol, ...]
    """
    ws = session["ws"]
    trace_file = session.get("trace_file")

    # ── PER-SYMBOL STATE + ROUTING TABLES ──
    states: Dict[str, Dict[str, Any]] = {}
    chart_route: Dict[str, Dict[str, Any]] = {}
    quote_route: Dict[str, Dict[str, Any]] = {}

    for bi in batch_items:
        state = {
            "provider_symbol": bi["provider_symbol"],
            "timeframe": bi["timeframe"],
            "ohlcv_payload": None,
            "company_name": None,
            "quote_snapshot": {},
            "ohlcv_done": False,
            "quote_done": False,
        }
        states[bi["provider_symbol"]] = state
        chart_route[bi["chart_id"]] = state
        quote_route[bi["quote_id"]] = state

    # ── FIRE ALL SENDS UPFRONT (N×6 messages) ──
    for bi in batch_items:
        cid = bi["chart_id"]
        qid = bi["quote_id"]
        sym = bi["provider_symbol"]
        tf_tv = _TF_ALIAS_FOR_TV.get(bi["timeframe"], bi["timeframe"].upper())
        n = bi["n_candles"]

        # Chart (OHLCV) — 3 sends
        await send_to_tradingview(ws, {"m": "chart_create_session", "p": [cid]}, trace_file)
        await send_to_tradingview(ws, {"m": "resolve_symbol", "p": [cid, "s1", sym]}, trace_file)
        await send_to_tradingview(ws, {
            "m": "create_series",
            "p": [cid, "sds_1", "s1", "s1", tf_tv, n, ""],
        }, trace_file)

        # Quote (Fundamentals) — 3 sends
        await send_to_tradingview(ws, {"m": "quote_create_session", "p": [qid]}, trace_file)
        await send_to_tradingview(ws, {
            "m": "quote_set_fields",
            "p": [qid] + _QUOTE_FIELDS,
        }, trace_file)
        await send_to_tradingview(ws, {
            "m": "quote_add_symbols",
            "p": [
                qid,
                f"={{\"adjustment\":\"splits\",\"currency-id\":\"USD\",\"symbol\":\"{sym}\"}}",
            ],
        }, trace_file)

    # ── UNIFIED RECEIVE LOOP WITH DEADLINE ──
    pending = len(batch_items)
    loop = asyncio.get_event_loop()
    deadline = loop.time() + BATCH_TIMEOUT

    while pending > 0:
        remaining = deadline - loop.time()
        if remaining <= 0:
            break

        try:
            message = await asyncio.wait_for(
                ws.recv(), timeout=min(RECV_TIMEOUT, remaining)
            )
        except asyncio.TimeoutError:
            break

        if trace_file:
            trace_file.write("RECEIVE RAW:\n")
            trace_file.write(message + "\n\n")

        # ── TV KEEPALIVE: echo ~h~N pings immediately ──
        for ping_match in re.finditer(r"~h~\d+", message):
            ping = ping_match.group(0)
            pong = f"~m~{len(ping)}~m~{ping}"
            try:
                await ws.send(pong)
            except Exception:
                pass

        for chunk in re.split(r"~m~\d+~m~", message)[1:]:
            if not chunk.strip():
                continue
            try:
                payload = json.loads(chunk)
            except json.JSONDecodeError:
                continue

            mtype = payload.get("m")
            p = payload.get("p", [])
            sid = p[0] if p else None

            # ── OHLCV responses (routed by chart_id) ──
            if mtype == "symbol_resolved" and sid in chart_route:
                state = chart_route[sid]
                if len(p) >= 3 and isinstance(p[2], dict):
                    state["company_name"] = (
                        p[2].get("local_description") or p[2].get("description")
                    )

            elif mtype == "timescale_update" and sid in chart_route:
                state = chart_route[sid]
                if not state["ohlcv_done"]:
                    state["ohlcv_payload"] = payload
                    state["ohlcv_done"] = True
                    if trace_file:
                        trace_file.write(
                            f"TIMESCALE_UPDATE for {state['provider_symbol']}\n\n"
                        )
                    if state["quote_done"]:
                        pending -= 1

            # ── Quote/Fundamentals responses (routed by quote_id) ──
            elif mtype == "qsd" and sid in quote_route:
                state = quote_route[sid]
                if len(p) >= 2 and isinstance(p[1], dict):
                    v = p[1].get("v")
                    if isinstance(v, dict):
                        state["quote_snapshot"].update(v)

            elif mtype == "quote_completed" and sid in quote_route:
                state = quote_route[sid]
                if not state["quote_done"]:
                    state["quote_done"] = True
                    if state["ohlcv_done"]:
                        pending -= 1

    # ── BUILD RESULTS ──
    successes: Dict[str, Dict[str, Any]] = {}
    failures: list = []

    for sym, state in states.items():
        if state["ohlcv_done"] and state["quote_done"] and state["ohlcv_payload"]:
            candles = parse_ohlcv(state["ohlcv_payload"])
            successes[sym] = {
                "symbol": sym,
                "timeframe": state["timeframe"],
                "candles": candles,
                "fundamentals_raw": state["quote_snapshot"],
                "company_name": state["company_name"],
            }
        else:
            failures.append(sym)

    return successes, failures


async def cleanup_batch_sessions(
    session: Dict[str, Any], batch_items: list
) -> None:
    """Delete all chart/quote sessions from a batch (fire-and-forget sends)."""
    ws = session["ws"]
    trace_file = session.get("trace_file")
    for bi in batch_items:
        try:
            await send_to_tradingview(
                ws, {"m": "chart_delete_session", "p": [bi["chart_id"]]}, trace_file
            )
        except Exception:
            pass
        try:
            await send_to_tradingview(
                ws, {"m": "quote_delete_session", "p": [bi["quote_id"]]}, trace_file
            )
        except Exception:
            pass


# ──────────────────────────────────────────────────────────────────────────────
# LIVE STREAM: Seed & Edge async generator (LIVE-01)
#
# Architecture:
#   1. Subscribe to ONE symbol: 3 chart sends + 3 quote sends
#   2. Yield ('seed', candles) on initial timescale_update
#   3. Yield ('tick', candles) on every subsequent 'du' (data update) push
#   4. Yield ('fundamentals', snapshot) once on quote_completed
#   5. Yield ('company_name', name) on symbol_resolved
#   6. Yield ('heartbeat', None) on RECV_TIMEOUT with no data
#   7. On ConnectionClosed: raise — caller handles reconnection
#   8. try/finally guarantees chart_delete_session + quote_delete_session
#      even on generator close (handler disconnect, GC, .aclose())
#
# This function does NOT modify any existing batch ETL code paths.
# ──────────────────────────────────────────────────────────────────────────────

STREAM_RECV_TIMEOUT = 45  # seconds — more generous than batch RECV_TIMEOUT
                          # because the live stream may go quiet during low
                          # market activity (pre-market, post-hours, weekends)


async def subscribe_ohlcv_stream(
    session: Dict[str, Any],
    provider_symbol: str,
    timeframe: str,
    n_initial: int = 3,
) -> AsyncGenerator[Tuple[str, Any], None]:
    """
    Async generator: subscribes to a TradingView symbol and STAYS connected,
    yielding live candle updates as TradingView pushes them.

    The caller consumes with:
        async for event_type, data in subscribe_ohlcv_stream(session, ...):
            if event_type == 'seed': ...
            elif event_type == 'tick': ...

    When the caller breaks or the generator is closed, the finally block
    sends chart_delete_session + quote_delete_session to clean up server-side.

    Yields:
        ('seed', List[List[float]])        — initial candles from timescale_update
        ('tick', List[List[float]])        — live bar update(s) from 'du' message
        ('fundamentals', Dict[str, Any])   — quote snapshot on quote_completed
        ('company_name', str)              — resolved company name
        ('heartbeat', None)                — timeout, no data (keepalive signal)

    Raises:
        websockets.ConnectionClosed — connection died, caller must reconnect
    """
    ws = session["ws"]
    trace_file = session.get("trace_file")
    chart_id = session["chart_id"]
    quote_id = session.get("quote_id", "qs_live_1")
    tf_tv = _TF_ALIAS_FOR_TV.get(timeframe, timeframe.upper())

    try:
        # ── SUBSCRIBE: fire 6 sends (3 chart + 3 quote) ──

        # Chart (OHLCV) — creates a persistent subscription
        await send_to_tradingview(
            ws, {"m": "chart_create_session", "p": [chart_id]}, trace_file
        )
        await send_to_tradingview(
            ws, {"m": "resolve_symbol", "p": [chart_id, "s1", provider_symbol]}, trace_file
        )
        await send_to_tradingview(ws, {
            "m": "create_series",
            "p": [chart_id, "sds_1", "s1", "s1", tf_tv, n_initial, ""],
        }, trace_file)

        # Quote (Fundamentals)
        await send_to_tradingview(
            ws, {"m": "quote_create_session", "p": [quote_id]}, trace_file
        )
        await send_to_tradingview(ws, {
            "m": "quote_set_fields",
            "p": [quote_id] + _QUOTE_FIELDS,
        }, trace_file)
        await send_to_tradingview(ws, {
            "m": "quote_add_symbols",
            "p": [
                quote_id,
                f"={{\"adjustment\":\"splits\",\"currency-id\":\"USD\",\"symbol\":\"{provider_symbol}\"}}",
            ],
        }, trace_file)

        if trace_file:
            trace_file.write(f"STREAM SUBSCRIBED: {provider_symbol} ({tf_tv}, n={n_initial})\n\n")

        # ── INFINITE RECEIVE LOOP: yield events as they arrive ──
        quote_snapshot: Dict[str, Any] = {}

        while True:
            try:
                message = await asyncio.wait_for(
                    ws.recv(), timeout=STREAM_RECV_TIMEOUT
                )
            except asyncio.TimeoutError:
                # No message for 45s — market may be closed or TV is quiet.
                # Yield heartbeat so the handler can send a keepalive to the
                # client and track liveness. Do NOT break — stay subscribed.
                yield ("heartbeat", None)
                continue

            if trace_file:
                trace_file.write("RECEIVE RAW:\n")
                trace_file.write(message + "\n\n")

            # ── TV KEEPALIVE: echo ~h~N pings immediately ──
            # TradingView sends periodic pings (format: ~m~L~m~~h~N).
            # Failure to echo = TV closes the connection with 1000 (OK).
            for ping_match in re.finditer(r"~h~\d+", message):
                ping = ping_match.group(0)
                pong = f"~m~{len(ping)}~m~{ping}"
                try:
                    await ws.send(pong)
                    if trace_file:
                        trace_file.write(f"PING-PONG: echoed {ping}\n\n")
                except Exception:
                    pass

            for chunk in re.split(r"~m~\d+~m~", message)[1:]:
                if not chunk.strip():
                    continue

                try:
                    payload = json.loads(chunk)
                except json.JSONDecodeError:
                    continue

                mtype = payload.get("m")
                p = payload.get("p", [])

                # ── SESSION GUARD: reject messages from stale/foreign sessions ──
                # On a shared WS, old chart sessions may still push du/timescale
                # messages after a symbol switch. p[0] is the chart or quote
                # session ID. Only process messages addressed to OUR sessions.
                if mtype in ("timescale_update", "du", "symbol_resolved"):
                    if not p or p[0] != chart_id:
                        if trace_file:
                            trace_file.write(
                                f"IGNORED {mtype}: session {p[0] if p else '?'} != {chart_id}\n\n"
                            )
                        continue
                elif mtype in ("qsd", "quote_completed"):
                    if not p or p[0] != quote_id:
                        continue

                # ── OHLCV: initial seed (full candle set) ──
                if mtype == "timescale_update":
                    candles = parse_ohlcv(payload)
                    if trace_file:
                        trace_file.write(
                            f"TIMESCALE_UPDATE: {len(candles)} candles for {provider_symbol}\n\n"
                        )
                    yield ("seed", candles)

                # ── OHLCV: live bar tick (incremental update) ──
                elif mtype == "du":
                    candles = parse_ohlcv(payload)
                    if candles:
                        if trace_file:
                            trace_file.write(
                                f"DU: {len(candles)} bar(s) updated for {provider_symbol}\n\n"
                            )
                        yield ("tick", candles)

                # ── Symbol metadata ──
                elif mtype == "symbol_resolved":
                    if isinstance(p, list) and len(p) >= 3:
                        meta = p[2]
                        if isinstance(meta, dict):
                            name = (
                                meta.get("local_description")
                                or meta.get("description")
                            )
                            if name:
                                yield ("company_name", name)

                # ── Fundamentals: accumulate qsd, yield on quote_completed ──
                elif mtype == "qsd":
                    p = payload.get("p")
                    if isinstance(p, list) and len(p) >= 2:
                        second = p[1]
                        if isinstance(second, dict):
                            v = second.get("v")
                            if isinstance(v, dict):
                                quote_snapshot.update(v)

                elif mtype == "quote_completed":
                    if quote_snapshot:
                        yield ("fundamentals", dict(quote_snapshot))

    finally:
        # ── CLEANUP: delete chart + quote sessions on ANY exit ──
        # Runs when: handler breaks out of 'async for', generator GC'd,
        # .aclose() called, or unhandled exception propagates.
        # Best-effort: if the WS is dead, sends will fail silently.
        try:
            await send_to_tradingview(
                ws, {"m": "chart_delete_session", "p": [chart_id]}, trace_file
            )
        except Exception:
            pass
        try:
            await send_to_tradingview(
                ws, {"m": "quote_delete_session", "p": [quote_id]}, trace_file
            )
        except Exception:
            pass

        if trace_file:
            try:
                trace_file.write(
                    f"STREAM CLOSED: {provider_symbol} — sessions cleaned up\n\n"
                )
            except Exception:
                pass
