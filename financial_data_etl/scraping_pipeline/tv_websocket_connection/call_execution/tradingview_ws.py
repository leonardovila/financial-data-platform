from __future__ import annotations
from typing import Dict, Any, Optional
import json, re, websockets
from pathlib import Path
from datetime import datetime
from financial_data_etl.scraping_pipeline.tv_websocket_connection.parsing.ohlcv_parser import parse_ohlcv

# Explicitamente decido no agregar ctx aca. Este modulo, es el tunel que conecta con el ws y donde se trae la data raw
# Aclarado eso, genera su propio logging con .txt con dumps que registran la comunicacion con el ws

# Global trace file (1 per execution)
_GLOBAL_WS_TRACE_FILE = None
def _create_ws_trace_file() -> Optional[Any]:
    global _GLOBAL_WS_TRACE_FILE

    if _GLOBAL_WS_TRACE_FILE is not None:
        return _GLOBAL_WS_TRACE_FILE

    logs_dir = Path("ws_traces")
    logs_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    trace_path = logs_dir / f"WS_TRACE_{ts}.txt"

    _GLOBAL_WS_TRACE_FILE = trace_path.open("w", encoding="utf-8")
    return _GLOBAL_WS_TRACE_FILE

def close_global_ws_trace():
    global _GLOBAL_WS_TRACE_FILE
    if _GLOBAL_WS_TRACE_FILE:
        _GLOBAL_WS_TRACE_FILE.write("\nEXECUTION FINISHED\n")
        _GLOBAL_WS_TRACE_FILE.close()
        _GLOBAL_WS_TRACE_FILE = None

async def send_to_tradingview(websocket, message_dict, trace_file=None):
    message_json = json.dumps(message_dict)
    payload = f"~m~{len(message_json)}~m~{message_json}"
    if trace_file:
        trace_file.write("SEND:\n")
        trace_file.write(json.dumps(message_dict) + "\n\n")
    await websocket.send(payload)

async def request_quote_snapshot(
    session: Dict[str, Any],
    provider_symbol: str,
) -> Dict[str, Any]:
    ws = session["ws"]
    trace_file = session.get("trace_file")

    quote_session = "qs_multiplexer_full_1"

    # 1) create quote session
    await send_to_tradingview(
        ws,
        {"m": "quote_create_session", "p": [quote_session]},
        trace_file=trace_file,
    )

    # 2) set fields (pedimos más de lo que usamos)
    await send_to_tradingview(
        ws,
        {
            "m": "quote_set_fields",
            "p": [
                quote_session,
                "market_cap_basic",
                "market_cap_calc",
                "total_shares_outstanding_current",
                "total_shares_outstanding_calculated",
                "price_earnings_ttm",
                "earnings_per_share_basic_ttm",
                "industry",
                "sector",
            ],
        },
        trace_file=trace_file,
    )

    # 3) add symbol
    await send_to_tradingview(
        ws,
        {
            "m": "quote_add_symbols",
            "p": [
                quote_session,
                f"={{\"adjustment\":\"splits\",\"currency-id\":\"USD\",\"symbol\":\"{provider_symbol}\"}}",
            ],
        },
        trace_file=trace_file,
    )

    # 4) esperar qsd
    snapshot: Dict[str, Any] = {}

    while True:
        message = await ws.recv()

        if trace_file:
            trace_file.write("RECEIVE RAW:\n")
            trace_file.write(message + "\n\n")

        splitMessages = re.split(r"~m~\d+~m~", message)[1:]

        for chunk in splitMessages:
            if not chunk.strip():
                continue

            try:
                payload = json.loads(chunk)
            except json.JSONDecodeError:
                continue

            mtype = payload.get("m")

            if mtype == "qsd":
                p = payload.get("p")
                if isinstance(p, list) and len(p) >= 2:
                    second = p[1]
                    if isinstance(second, dict):
                        v = second.get("v")
                        if isinstance(v, dict):
                            # 🔥 MERGEAMOS
                            snapshot.update(v)

            elif mtype == "quote_completed":
                return {
                    "symbol": provider_symbol,
                    "raw": snapshot,
                }
async def request_historic_ohlcv(websocket, chartSession, num_candles, symbol, timeframe, trace_file=None):
    # 1) handshake / crear serie
    await send_to_tradingview(websocket, {"m": "chart_create_session", "p": [chartSession]}, trace_file=trace_file)
    await send_to_tradingview(websocket, {"m": "resolve_symbol", "p": [chartSession, "s1", symbol]}, trace_file=trace_file)
    await send_to_tradingview(websocket, {
        "m": "create_series",
        "p": [chartSession, "sds_1", "s1", "s1", timeframe, num_candles, ""]
    }, trace_file=trace_file)

    # 2) loop de recepción hasta encontrar timescale_update
    data = None
    try:
        while True:
            message = await websocket.recv()
            if trace_file:
                trace_file.write("RECEIVE RAW:\n")
                trace_file.write(message + "\n\n")
            splitMessages = re.split(r"~m~\d+~m~", message)[1:]
            for chunk in splitMessages:
                if not chunk.strip():
                    continue
                try:
                    payload = json.loads(chunk)
                except json.JSONDecodeError:
                        continue

                if payload.get("m") == "timescale_update":
                    if trace_file:
                        trace_file.write("TIMESCALE_UPDATE DETECTED\n\n")
                    return payload
    except websockets.ConnectionClosed as e:
        raise

async def connect_to_tradingview(timeout_s: int = 15, trace_file=None):
    # La fecha en el querystring no importa funcionalmente; dejamos un valor fijo válido.
    uri = "wss://data.tradingview.com/socket.io/websocket?from=chart%2F&date=2025_03_31-11_22&type=chart"
    websocket = await websockets.connect(
        uri,
        extra_headers={
            "Origin": "https://www.tradingview.com",
            "User-Agent": "Mozilla/5.0"
        },
        open_timeout=timeout_s,
    )

    rawMessage = await websocket.recv()
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

# ──────────────────────────────────────────────────────────────────────────────
# CAPA ADAPTADORA (lo que usa call_executor)
# ──────────────────────────────────────────────────────────────────────────────

async def open_session(trace: bool = True) -> Dict[str, Any]:
    trace_file = _create_ws_trace_file()

    ws, chart = await connect_to_tradingview(trace_file=trace_file)

    if not ws or not chart:
        trace_file.write("ERROR: can not open session\n")
        trace_file.close()
        raise RuntimeError("can not open session TradingView session")

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
    except Exception as e:
        pass
    finally:
        tf = session.get("trace_file")
        if tf:
            tf.write("\nSESSION CLOSED\n")
            tf.flush()

# Mapeo simple de TF a lo que espera tu WS
_TF_ALIAS_FOR_TV = {"1d": "1D", "1h": "1H", "1m": "1M", "5m": "5M", "15m": "15M", "30m": "30M", "2h": "2H", "4h": "4H", "1w": "1W"}

async def request_ohlcv_and_fundamentals(
    session: Dict[str, Any],
    provider_symbol: str,
    timeframe: str,
    n: int,
) -> Dict[str, Any]:

    tf_tv = _TF_ALIAS_FOR_TV.get(timeframe, timeframe.upper())

    # 1️⃣ OHLCV
    data = await request_historic_ohlcv(
        session["ws"],
        session["chart_id"],
        n,
        provider_symbol,
        tf_tv,
        trace_file=session.get("trace_file"),
    )

    candles = parse_ohlcv(data)

    # 2️⃣ FUNDAMENTALS (MISMA SESIÓN)
    fundamentals = await request_quote_snapshot(
        session,
        provider_symbol,
    )

    return {
        "symbol": provider_symbol,
        "timeframe": timeframe,
        "candles": candles,
        "fundamentals_raw": fundamentals.get("raw"),
    }
