from financial_data_etl.scraping_pipeline.tv_websocket_connection.call_specification.call_builder import run_call_builder
from financial_data_etl.scraping_pipeline.tv_websocket_connection.call_specification.asset_catalog import load_assets_catalog
from financial_data_etl.scraping_pipeline.tv_websocket_connection.call_execution.call_executor import run_call_executor
from financial_data_etl.scraping_pipeline.fundamentals.fundamentals_extractor import extract_fundamentals_from_quote_raw
from financial_data_etl.scraping_pipeline.tv_websocket_connection.call_execution.tradingview_ws import close_global_ws_trace
from financial_data_etl.observability.run_context import RunContext

import time
import asyncio
from pathlib import Path
import json

# ----------- CONFIG -----------
WS_CONCURRENCY: int = 6
WS_JITTER_S: float = 0.12
PROVIDER = "tradingview"
# -------------------------------------------

async def run_scrape_tv_websocket_one(
    symbol: str,
    timeframe: str,
    n_candles: int,
    catalog: dict,
    ctx: RunContext,
):
    ctx.event("symbol_scrape_start", symbol=symbol)

    try:
        spec = run_call_builder(
            symbol=symbol,
            timeframe=timeframe,
            provider=PROVIDER,
            mode="backfill",
            n_candles_hint=n_candles,
            catalog=catalog,
        )

        raw = await run_call_executor(spec, ctx, stage="tv_websocket_scrape")

        body = raw["body"]
        candles = body.get("candles", [])
        fundamentals_raw = body.get("fundamentals_raw")
        fundamentals = extract_fundamentals_from_quote_raw(fundamentals_raw)

        # Acceso:
        # market_cap = fundamentals.get("market_cap")
        ctx.event(
            "symbol_scrape_success",
            symbol=symbol,
            candles=len(candles),
        )

        return {
            **body,
            "fundamentals": fundamentals,
        }

    except Exception as e:
        ctx.event(
            "symbol_scrape_error",
            symbol=symbol,
            error=str(e),
        )
        raise

async def run_scrape_tv_websocket_many(
    symbols: list[str],
    timeframe: str,
    n_candles: int,
    catalog: dict,
    ctx: RunContext,
    *,
    stage: str,
):

    sem = asyncio.Semaphore(WS_CONCURRENCY)

    async def worker(sym):
        async with sem:
            if WS_JITTER_S:
                await asyncio.sleep(WS_JITTER_S)
            try:
                body = await run_scrape_tv_websocket_one(sym, timeframe, n_candles, catalog, ctx)
                return ("OK", sym, body)
            except Exception as e:
                return ("ERR", sym, str(e))

    pairs = await asyncio.gather(*(worker(sym) for sym in symbols))

    results = {}
    failed_symbols = []

    for status, sym, payload in pairs:
        if status == "OK":
            results[sym] = payload
        else:
            failed_symbols.append(sym)

    total_candles = sum(len(v.get("candles", [])) for v in results.values())

    ctx.event(
        "tv_websocket_scrape_completed",
        stage=stage,
        symbols_requested=len(symbols),
        symbols_success=len(results),
        symbols_failed=len(failed_symbols),
        failed_symbols_total=len(failed_symbols),
        failed_symbols=failed_symbols[:50] if failed_symbols else None,
        total_candles=total_candles,
    )

    return results

def run_tv_websocket_scraper(
    symbols: list[str],
    timeframe: str,
    n_candles: int,
    ctx: RunContext,
    *,
    stage: str,
) -> dict:
    """
    Scrapea OHLCV RAW (TradingView) para múltiples símbolos; no persiste, no finaliza ctx.
    """
    ctx.event(
        "scrape_parameters",
        stage=stage,
        symbols=len(symbols),
        timeframe=timeframe,
        n_candles=n_candles,
    )

    catalog = load_assets_catalog()
    ctx.event("catalog_loaded", stage=stage, size=len(catalog))

    try:
        results = asyncio.run(
            run_scrape_tv_websocket_many(
                symbols,
                timeframe,
                n_candles,
                catalog,
                ctx,
                stage=stage,
            )
        )
    finally:
        close_global_ws_trace()
        
    return results