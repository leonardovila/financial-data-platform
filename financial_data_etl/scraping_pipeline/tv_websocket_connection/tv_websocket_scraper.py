"""
Pool-based TradingView WebSocket scraper with batch multiplexing.

Architecture:
  - An asyncio.Queue holds (symbol, n_candles) work items.
  - N persistent workers (WS_POOL_SIZE) each open ONE WebSocket connection.
  - Each worker pulls SYMBOLS_PER_BATCH items from the queue at once.
  - All symbols in the batch are fired concurrently over the SINGLE connection
    using unique chart/quote session IDs per symbol.
  - A unified receive loop routes the chaotic incoming stream back to the
    correct symbol by matching session IDs in p[0].
  - 6 connections × 50 symbols/batch = 300 symbols in-flight simultaneously.
"""

from financial_data_etl.scraping_pipeline.tv_websocket_connection.call_specification.call_builder import run_call_builder
from financial_data_etl.scraping_pipeline.tv_websocket_connection.call_specification.asset_catalog import load_assets_catalog
from financial_data_etl.scraping_pipeline.fundamentals.fundamentals_extractor import extract_fundamentals_from_quote_raw
from financial_data_etl.scraping_pipeline.tv_websocket_connection.call_execution.tradingview_ws import (
    open_session,
    close_session,
    request_batch_multiplexed,
    cleanup_batch_sessions,
    close_global_ws_trace,
)
from financial_data_etl.observability.run_context import RunContext

import asyncio
import os
import websockets

# ----------- CONFIG -----------
WS_POOL_SIZE: int = int(os.environ.get("WS_POOL_SIZE", "20"))
SYMBOLS_PER_BATCH: int = int(os.environ.get("SYMBOLS_PER_BATCH", "1"))
PROVIDER = "tradingview"
MAX_BATCH_RETRIES = 3  # max reconnections per worker before giving up on requeuing
# -------------------------------------------


async def _pool_worker(
    worker_id: int,
    queue: asyncio.Queue,
    catalog: dict,
    timeframe: str,
    ctx: RunContext,
    results: dict,
    failures: list,
    stage: str,
    raw_capture=None,
):
    """
    Persistent worker: opens ONE WebSocket, pulls batches of up to
    SYMBOLS_PER_BATCH symbols, fires them ALL concurrently over the
    single connection, collects results via session-ID routing.
    """
    session = None
    base_chart_id = None
    counter = 0
    reconnect_count = 0

    while True:
        # ── PULL BATCH FROM QUEUE ──
        batch = []
        while len(batch) < SYMBOLS_PER_BATCH:
            try:
                batch.append(queue.get_nowait())
            except asyncio.QueueEmpty:
                break

        if not batch:
            break

        batch_specs = []

        try:
            # ── OPEN / RECONNECT ──
            if session is None:
                session = await open_session()
                base_chart_id = session["chart_id"]
                counter = 0

            # ── BUILD BATCH SPECS WITH UNIQUE SESSION IDs ──
            sym_map = {}  # provider_symbol -> original symbol

            for symbol, n_candles in batch:
                counter += 1
                spec = run_call_builder(
                    symbol=symbol,
                    timeframe=timeframe,
                    provider=PROVIDER,
                    mode="backfill",
                    n_candles_hint=n_candles,
                    catalog=catalog,
                )
                batch_specs.append({
                    "provider_symbol": spec.provider_symbol,
                    "chart_id": f"{base_chart_id}_{counter}",
                    "quote_id": f"qs_w{worker_id}_{counter}",
                    "timeframe": timeframe,
                    "n_candles": n_candles,
                })
                sym_map[spec.provider_symbol] = symbol

            ctx.event(
                "batch_scrape_start",
                stage=stage,
                worker=worker_id,
                batch_size=len(batch_specs),
            )

            # ── EXECUTE MULTIPLEXED BATCH ──
            batch_results, batch_fails = await request_batch_multiplexed(
                session, batch_specs, raw_capture=raw_capture
            )

            # ── PROCESS RESULTS ──
            for prov_sym, body in batch_results.items():
                orig = sym_map[prov_sym]
                fundamentals_raw = body.get("fundamentals_raw")
                fundamentals = extract_fundamentals_from_quote_raw(fundamentals_raw)
                results[orig] = {**body, "fundamentals": fundamentals}
                ctx.event(
                    "symbol_scrape_success",
                    stage=stage,
                    symbol=orig,
                    candles=len(body.get("candles", [])),
                    worker=worker_id,
                )

            for prov_sym in batch_fails:
                orig = sym_map.get(prov_sym, prov_sym)
                failures.append(orig)
                ctx.event(
                    "symbol_scrape_error",
                    stage=stage,
                    symbol=orig,
                    error="batch_incomplete",
                    worker=worker_id,
                )

            ctx.event(
                "batch_scrape_done",
                stage=stage,
                worker=worker_id,
                success=len(batch_results),
                failed=len(batch_fails),
            )

            # ── CLEANUP ALL SESSIONS FROM THIS BATCH ──
            await cleanup_batch_sessions(session, batch_specs)

        except (
            websockets.ConnectionClosed,
            websockets.ConnectionClosedError,
            ConnectionError,
            OSError,
            asyncio.TimeoutError,
        ) as e:
            # Connection died or timed out — close, will reconnect on next iteration
            ctx.event(
                "ws_connection_lost",
                stage=stage,
                worker=worker_id,
                error=str(e),
                batch_size=len(batch),
                level="WARNING",
            )
            try:
                if session:
                    await close_session(session)
            except Exception:
                pass
            session = None
            reconnect_count += 1

            # Identify which symbols did NOT complete in this batch
            incomplete = [(sym, nc) for sym, nc in batch if sym not in results]

            if reconnect_count <= MAX_BATCH_RETRIES and incomplete:
                # Requeue for retry — this worker (or another) will pick them up
                for item in incomplete:
                    await queue.put(item)
                ctx.event(
                    "batch_requeued",
                    stage=stage,
                    worker=worker_id,
                    requeued=len(incomplete),
                    reconnect_count=reconnect_count,
                )
            else:
                # Exceeded retry limit — permanent failures
                for sym, _ in incomplete:
                    failures.append(sym)
                ctx.event(
                    "batch_symbols_lost",
                    stage=stage,
                    worker=worker_id,
                    lost=len(incomplete),
                    reconnect_count=reconnect_count,
                    level="ERROR",
                )

        except Exception as e:
            ctx.event(
                "batch_scrape_error",
                stage=stage,
                worker=worker_id,
                error=str(e),
                level="ERROR",
            )

            # Mark un-completed symbols as failed
            for symbol, _ in batch:
                if symbol not in results:
                    failures.append(symbol)

            # Try cleanup; if that fails, force reconnect
            try:
                if session and batch_specs:
                    await cleanup_batch_sessions(session, batch_specs)
            except Exception:
                try:
                    if session:
                        await close_session(session)
                except Exception:
                    pass
                session = None

        for _ in batch:
            queue.task_done()

    # Worker done — close its persistent session
    if session:
        try:
            await close_session(session)
        except Exception:
            pass


async def _run_pool(
    plan: dict,
    timeframe: str,
    catalog: dict,
    ctx: RunContext,
    stage: str,
    raw_capture=None,
) -> tuple:
    """Populate queue, launch pool workers, return (results, failures)."""
    queue = asyncio.Queue()
    for symbol, n_candles in plan.items():
        queue.put_nowait((symbol, n_candles))

    results = {}
    failures = []

    pool_size = min(WS_POOL_SIZE, len(plan))

    workers = [
        asyncio.create_task(
            _pool_worker(i, queue, catalog, timeframe, ctx, results, failures, stage, raw_capture=raw_capture)
        )
        for i in range(pool_size)
    ]

    await asyncio.gather(*workers)

    # Reconcile: a symbol may appear in failures from a first attempt
    # but succeed on retry. Remove any failure that ended up in results.
    reconciled_failures = [s for s in failures if s not in results]

    return results, reconciled_failures


def run_tv_websocket_scraper(
    plan: dict,
    timeframe: str,
    ctx: RunContext,
    *,
    stage: str,
    raw_capture=None,
) -> dict:
    """
    Pool-based scraper with batch multiplexing.

    Each of WS_POOL_SIZE workers opens ONE connection and fires
    SYMBOLS_PER_BATCH symbols concurrently per batch cycle.

    Args:
        plan: {symbol: n_candles}
        timeframe: e.g. "1d"
        ctx: RunContext for observability.
        stage: stage name for logging.
        raw_capture: optional callback (provider_symbol, raw_chunk_str) -> None.
            When provided, every parseable WS chunk routed to a known symbol
            is forwarded to this callback BEFORE parsing. Used by the VPS
            scraper to dump raw chunks to S3 without parsing them locally.

    Returns:
        dict: {symbol: body_with_fundamentals}
    """
    ctx.event(
        "scrape_parameters",
        stage=stage,
        symbols=len(plan),
        timeframe=timeframe,
        pool_size=WS_POOL_SIZE,
        batch_size=SYMBOLS_PER_BATCH,
    )

    catalog = load_assets_catalog()
    ctx.event("catalog_loaded", stage=stage, size=len(catalog))

    try:
        results, failures = asyncio.run(
            _run_pool(plan, timeframe, catalog, ctx, stage, raw_capture=raw_capture)
        )
    finally:
        close_global_ws_trace()

    total_candles = sum(len(v.get("candles", [])) for v in results.values())

    ctx.event(
        "tv_websocket_scrape_completed",
        stage=stage,
        symbols_requested=len(plan),
        symbols_success=len(results),
        symbols_failed=len(failures),
        failed_symbols=failures[:50] if failures else None,
        total_candles=total_candles,
        pool_size=WS_POOL_SIZE,
        batch_size=SYMBOLS_PER_BATCH,
    )

    return results
