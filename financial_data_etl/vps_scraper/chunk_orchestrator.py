"""
Chunk-by-chunk scrape orchestrator.

Splits the plan into chunks of N (default 50) symbols, runs the scraper
with a raw_capture callback that buffers WS chunks per symbol in memory,
uploads one gzipped JSONL per symbol to S3, sleeps between chunks
to keep TradingView happy, and finally drops the _DONE_ marker that
triggers the Lambda dispatcher.

The scraper itself is the existing run_tv_websocket_scraper — we just
hook into its raw_capture parameter (added in the same sprint) so the
WS chunks are captured BEFORE parsing. The VPS does no parsing.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List

from financial_data_etl.observability.run_context import RunContext
from financial_data_etl.scraping_pipeline.tv_websocket_connection.call_specification.asset_catalog import (
    load_assets_catalog,
)
from financial_data_etl.scraping_pipeline.tv_websocket_connection.tv_websocket_scraper import (
    run_tv_websocket_scraper,
)

from financial_data_etl.vps_scraper.config import VpsConfig
from financial_data_etl.vps_scraper.s3_uploader import (
    upload_done_marker,
    upload_symbol_raw,
)

logger = logging.getLogger(__name__)


def _build_provider_to_original_map(symbols: List[str], catalog: dict) -> Dict[str, str]:
    """Map TradingView provider_symbol (NASDAQ:AAPL) -> original ticker (AAPL)."""
    out: Dict[str, str] = {}
    for sym in symbols:
        cfg = catalog.get(sym)
        if not cfg:
            continue
        prov = cfg.get("provider_symbol", {}).get("tradingview")
        if prov:
            out[prov] = sym
    return out


def _chunk(seq: List[str], size: int) -> List[List[str]]:
    return [seq[i : i + size] for i in range(0, len(seq), size)]


def run_chunked_scrape(
    *,
    plan: Dict[str, int],
    config: VpsConfig,
    ingestion_date: str,
    ctx: RunContext,
) -> Dict[str, int]:
    """
    Iterate the plan in chunks; per chunk: scrape, upload-per-symbol, sleep.
    Returns a small stats dict for the run summary.
    """
    catalog = load_assets_catalog()
    symbols = sorted(plan.keys())
    chunks = _chunk(symbols, config.chunk_size)

    total_symbols = len(symbols)
    total_chunks = len(chunks)
    uploaded_symbols = 0
    failed_symbols = 0

    ctx.event(
        "vps_run_start",
        stage="vps_scrape",
        total_symbols=total_symbols,
        total_chunks=total_chunks,
        chunk_size=config.chunk_size,
        sleep_seconds=config.chunk_sleep_seconds,
        ingestion_date=ingestion_date,
    )

    for idx, chunk in enumerate(chunks):
        chunk_plan = {sym: plan[sym] for sym in chunk}
        prov_to_orig = _build_provider_to_original_map(chunk, catalog)

        # In-memory buffer per provider_symbol (NASDAQ:AAPL). One list of
        # raw JSON chunks per symbol — the scraper invokes the callback
        # once per parseable WS chunk routed to that symbol.
        raw_buffer: Dict[str, List[str]] = defaultdict(list)

        def capture(provider_symbol: str, raw_chunk: str) -> None:
            raw_buffer[provider_symbol].append(raw_chunk)

        ctx.event(
            "vps_chunk_start",
            stage="vps_scrape",
            chunk_idx=idx,
            chunk_total=total_chunks,
            chunk_size=len(chunk),
        )

        chunk_t0 = time.time()
        try:
            # The scraper returns parsed results too, but we ignore them —
            # the VPS's job is only to dump the raw to S3. Parsing happens
            # in the Fargate processor (USE_VPS_RAW=true mode).
            run_tv_websocket_scraper(
                plan=chunk_plan,
                timeframe=config.timeframe,
                ctx=ctx,
                stage=f"vps_scrape_chunk_{idx}",
                raw_capture=capture,
            )
        except Exception as e:
            ctx.event(
                "vps_chunk_error",
                stage="vps_scrape",
                chunk_idx=idx,
                error=str(e),
                level="ERROR",
            )
            # Continue with the next chunk — partial buffer (if any) is still uploaded below.

        chunk_uploaded = 0
        for provider_symbol, chunks_list in raw_buffer.items():
            orig = prov_to_orig.get(provider_symbol)
            if not orig:
                # Should not happen because the scraper only routes known symbols.
                continue
            try:
                upload_symbol_raw(
                    bucket=config.s3_bucket,
                    prefix=config.s3_prefix,
                    symbol=orig,
                    ingestion_date=ingestion_date,
                    raw_chunks=chunks_list,
                    region=config.aws_region,
                    profile=config.aws_profile,
                )
                chunk_uploaded += 1
            except Exception as e:
                failed_symbols += 1
                ctx.event(
                    "vps_upload_error",
                    stage="vps_scrape",
                    symbol=orig,
                    error=str(e),
                    level="ERROR",
                )

        uploaded_symbols += chunk_uploaded
        chunk_dt = time.time() - chunk_t0

        ctx.event(
            "vps_chunk_done",
            stage="vps_scrape",
            chunk_idx=idx,
            chunk_total=total_chunks,
            symbols_in_chunk=len(chunk),
            symbols_uploaded=chunk_uploaded,
            duration_seconds=round(chunk_dt, 2),
        )

        # Sleep between chunks (except after the last one)
        if idx < total_chunks - 1:
            time.sleep(config.chunk_sleep_seconds)

    # End-of-run marker — this is what triggers the Lambda dispatcher
    upload_done_marker(
        bucket=config.s3_bucket,
        prefix=config.s3_prefix,
        ingestion_date=ingestion_date,
        body_text=(
            f"ingestion_date={ingestion_date}\n"
            f"total_symbols={total_symbols}\n"
            f"uploaded_symbols={uploaded_symbols}\n"
            f"failed_symbols={failed_symbols}\n"
            f"finished_at_utc={datetime.now(timezone.utc).isoformat()}\n"
        ),
        region=config.aws_region,
        profile=config.aws_profile,
    )

    ctx.event(
        "vps_run_done",
        stage="vps_scrape",
        total_symbols=total_symbols,
        uploaded_symbols=uploaded_symbols,
        failed_symbols=failed_symbols,
    )

    return {
        "total_symbols": total_symbols,
        "uploaded_symbols": uploaded_symbols,
        "failed_symbols": failed_symbols,
    }
