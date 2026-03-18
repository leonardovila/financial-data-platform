"""
Ejecuta una CallSpec contra el proveedor correspondiente.
No construye especificaciones.
No abre múltiples sesiones.
No hace orquestación.
"""

from datetime import datetime
from typing import Dict, Any
import time

from financial_data_etl.scraping_pipeline.tv_websocket_connection.call_specification.call_spec import CallSpec
from financial_data_etl.scraping_pipeline.tv_websocket_connection.call_execution.tradingview_ws import (
    open_session,
    close_session,
    request_ohlcv_and_fundamentals
)

async def run_call_executor(spec: CallSpec, ctx, *, stage: str) -> Dict[str, Any]:
    """
    Ejecuta una CallSpec y devuelve el payload crudo estructurado.
    """

    if spec.provider != "tradingview":
        raise ValueError(f"Proveedor no soportado: {spec.provider}")
    
    ctx.event(
        "call_executor_start",
        stage=stage,
        provider=spec.provider,
        symbol=spec.provider_symbol,
        timeframe=spec.timeframe,
        mode=spec.mode,
        n_candles=spec.n_candles_hint,
    )

    try:
        session = await open_session()
    except Exception as e:
        ctx.event(
            "call_executor_error",
            level="ERROR",
            stage=stage,
            symbol=spec.provider_symbol,
            phase="open_session",
            error=str(e),
        )
        raise

    ctx.event(
        "ws_session_opened",
        stage=stage,
        symbol=spec.provider_symbol,
        session_id=session.get("session_id"),
    )

    try:
        t0 = time.perf_counter()
        payload = await _execute_tradingview(spec, session)
        duration = time.perf_counter() - t0

        candles = payload.get("candles", []) if isinstance(payload, dict) else []
        ctx.event(
            "ws_response_received",
            stage=stage,
            symbol=spec.provider_symbol,
            candles=len(candles),
            duration_s=round(duration, 6),
        )
    except Exception as e:
        ctx.event(
            "call_executor_error",
            level="ERROR",
            stage=stage,
            symbol=spec.provider_symbol,
            phase="execute",
            error=str(e),
        )
        raise
    finally:
        await close_session(session)
        ctx.event(
            "ws_session_closed",
            stage=stage,
            symbol=spec.provider_symbol,
        )

    return {
        "provider": spec.provider,
        "fetched_at": datetime.now().isoformat(),
        "spec": spec.to_dict(),
        "body": payload,
    }

async def run_call_executor_pooled(spec: CallSpec, session, ctx, *, stage: str) -> Dict[str, Any]:
    """
    Execute a CallSpec using a pre-existing session (for connection pool workers).
    Does NOT open or close the session — that is the pool's responsibility.
    """
    if spec.provider != "tradingview":
        raise ValueError(f"Proveedor no soportado: {spec.provider}")

    t0 = time.perf_counter()
    payload = await _execute_tradingview(spec, session)
    duration = time.perf_counter() - t0

    candles = payload.get("candles", []) if isinstance(payload, dict) else []
    ctx.event(
        "ws_response_received",
        stage=stage,
        symbol=spec.provider_symbol,
        candles=len(candles),
        duration_s=round(duration, 6),
    )

    return {
        "provider": spec.provider,
        "fetched_at": datetime.now().isoformat(),
        "spec": spec.to_dict(),
        "body": payload,
    }


async def _execute_tradingview(spec: CallSpec, session) -> Dict[str, Any]:

    if spec.mode in ("backfill", "catchup"):
        n = spec.n_candles_hint or 500
        return await request_ohlcv_and_fundamentals(
            session,
            spec.provider_symbol,
            spec.timeframe,
            n=n,
        )

    elif spec.mode == "realtime":
        raise NotImplementedError("Modo realtime aún no implementado.")

    else:
        raise ValueError(f"Modo no soportado: {spec.mode}")
