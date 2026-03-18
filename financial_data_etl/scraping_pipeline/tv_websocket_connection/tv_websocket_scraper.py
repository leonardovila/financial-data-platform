"""
Pool-based TradingView WebSocket scraper.

Architecture:
  - An asyncio.Queue holds (symbol, n_candles) work items.
  - N persistent workers each open ONE WebSocket connection and drain
    symbols from the queue, reusing the connection across symbols.
  - Unique chart/quote session IDs per symbol prevent server-side collisions.
  - Explicit session cleanup between symbols allows connection reuse.
  - On connection death: reconnect and retry the failed symbol.
"""

from financial_data_etl.scraping_pipeline.tv_websocket_connection.call_specification.call_builder import run_call_builder
from financial_data_etl.scraping_pipeline.tv_websocket_connection.call_specification.asset_catalog import load_assets_catalog
from financial_data_etl.scraping_pipeline.tv_websocket_connection.call_execution.call_executor import run_call_executor_pooled
from financial_data_etl.scraping_pipeline.fundamentals.fundamentals_extractor import extract_fundamentals_from_quote_raw
from financial_data_etl.scraping_pipeline.tv_websocket_connection.call_execution.tradingview_ws import (
    open_session,
    close_session,
    cleanup_chart_and_quote,
    close_global_ws_trace,
)
from financial_data_etl.observability.run_context import RunContext

import asyncio
import os
import websockets

# ----------- CONFIG -----------
WS_POOL_SIZE: int = int(os.environ.get("WS_POOL_SIZE", "20"))
PROVIDER = "tradingview"
MAX_RETRIES_PER_SYMBOL = 2
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
):
    """
    Persistent worker: opens ONE WebSocket session, pulls symbols from queue,
    processes each without closing the connection. Reconnects on failure.
    """
    session = None
    base_chart_id = None
    counter = 0

    while True:
        try:
            symbol, n_candles = queue.get_nowait()
        except asyncio.QueueEmpty:
            break

        success = False
        last_error = None

        for attempt in range(MAX_RETRIES_PER_SYMBOL + 1):
            try:
                # Open / reconnect session if needed
                if session is None:
                    session = await open_session()
                    base_chart_id = session["chart_id"]
                    counter = 0

                # Unique session IDs for this symbol (prevent server-side collisions)
                counter += 1
                session["chart_id"] = f"{base_chart_id}_{counter}"
                session["quote_id"] = f"qs_w{worker_id}_{counter}"

                ctx.event("symbol_scrape_start", stage=stage, symbol=symbol, worker=worker_id)

                spec = run_call_builder(
                    symbol=symbol,
                    timeframe=timeframe,
                    provider=PROVIDER,
                    mode="backfill",
                    n_candles_hint=n_candles,
                    catalog=catalog,
                )

                raw = await run_call_executor_pooled(spec, session, ctx, stage=stage)
                body = raw["body"]
                candles = body.get("candles", [])
                fundamentals_raw = body.get("fundamentals_raw")
                fundamentals = extract_fundamentals_from_quote_raw(fundamentals_raw)

                ctx.event(
                    "symbol_scrape_success",
                    stage=stage,
                    symbol=symbol,
                    candles=len(candles),
                    worker=worker_id,
                )

                results[symbol] = {**body, "fundamentals": fundamentals}
                success = True

                # Cleanup chart/quote sessions so next symbol can reuse the connection
                await cleanup_chart_and_quote(session)
                break  # success, exit retry loop

            except (
                websockets.ConnectionClosed,
                websockets.ConnectionClosedError,
                ConnectionError,
                OSError,
            ) as e:
                # Connection died — close, nullify, retry with fresh connection
                last_error = e
                ctx.event(
                    "ws_connection_lost",
                    stage=stage,
                    symbol=symbol,
                    worker=worker_id,
                    attempt=attempt + 1,
                    error=str(e),
                    level="WARNING",
                )
                try:
                    if session:
                        await close_session(session)
                except Exception:
                    pass
                session = None

            except Exception as e:
                # Non-connection error (parse error, unknown symbol, etc.)
                last_error = e
                # Try to cleanup so connection stays usable
                try:
                    if session:
                        await cleanup_chart_and_quote(session)
                except Exception:
                    try:
                        if session:
                            await close_session(session)
                    except Exception:
                        pass
                    session = None
                break  # don't retry non-connection errors

        if not success:
            ctx.event(
                "symbol_scrape_error",
                stage=stage,
                symbol=symbol,
                error=str(last_error),
                worker=worker_id,
            )
            failures.append(symbol)

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
            _pool_worker(i, queue, catalog, timeframe, ctx, results, failures, stage)
        )
        for i in range(pool_size)
    ]

    await asyncio.gather(*workers)
    return results, failures


def run_tv_websocket_scraper(
    plan: dict,
    timeframe: str,
    ctx: RunContext,
    *,
    stage: str,
) -> dict:
    """
    Pool-based scraper: persistent WS connections drain a symbol queue.

    Args:
        plan: {symbol: n_candles} — each symbol with its own candle count.
        timeframe: e.g. "1d"
        ctx: RunContext for observability.
        stage: stage name for logging.

    Returns:
        dict: {symbol: body_with_fundamentals}
    """
    ctx.event(
        "scrape_parameters",
        stage=stage,
        symbols=len(plan),
        timeframe=timeframe,
        pool_size=WS_POOL_SIZE,
    )

    catalog = load_assets_catalog()
    ctx.event("catalog_loaded", stage=stage, size=len(catalog))

    try:
        results, failures = asyncio.run(
            _run_pool(plan, timeframe, catalog, ctx, stage)
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
    )

    return results
