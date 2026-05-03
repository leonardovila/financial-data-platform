"""
Read raw VPS-captured JSONL.gz files from S3 and reconstruct the
{symbol: body} dict that run_tv_websocket_scraper would have returned.

Used by main_runner.py when USE_VPS_RAW=true. The VPS scraper produces
one .jsonl.gz per symbol per ingestion_date with all the raw WS chunks.
We list those files, parse each chunk back through the SAME parsers the
WebSocket scraper uses (parse_ohlcv + extract_fundamentals_from_quote_raw),
and hand the result to persist_ohlcv_base / persist_fundamentals_snapshot
without changing them at all.
"""
from __future__ import annotations

import gzip
import io
import json
import logging
from typing import Dict, List, Optional, Tuple

import boto3
from botocore.config import Config

from financial_data_etl.scraping_pipeline.fundamentals.fundamentals_extractor import (
    extract_fundamentals_from_quote_raw,
)
from financial_data_etl.scraping_pipeline.tv_websocket_connection.call_specification.asset_catalog import (
    load_assets_catalog,
)
from financial_data_etl.scraping_pipeline.tv_websocket_connection.parsing.ohlcv_parser import (
    parse_ohlcv,
)

logger = logging.getLogger(__name__)
_BOTO_CONFIG = Config(retries={"max_attempts": 5, "mode": "standard"})


def _s3_client(region: str):
    return boto3.client("s3", region_name=region, config=_BOTO_CONFIG)


def _list_symbol_keys(
    client, bucket: str, prefix: str, ingestion_date: str
) -> List[Tuple[str, str]]:
    """Return [(symbol, key), ...] for every data.jsonl.gz of this date."""
    suffix = f"/ingestion_date={ingestion_date}/data.jsonl.gz"
    prefix_clean = prefix.strip("/")
    out: List[Tuple[str, str]] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=f"{prefix_clean}/symbol="):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not key.endswith(suffix):
                continue
            try:
                seg = next(s for s in key.split("/") if s.startswith("symbol="))
                symbol = seg.split("=", 1)[1]
            except StopIteration:
                continue
            out.append((symbol, key))
    return out


def _reassemble_body(
    raw_chunks: List[str],
    *,
    timeframe: str,
    provider_symbol: str,
) -> Optional[dict]:
    """
    Reduce the list of raw WS chunks to a body dict in the same shape that
    request_batch_multiplexed produces:
        {symbol, timeframe, candles, fundamentals_raw, company_name, fundamentals}
    """
    ohlcv_payload = None
    company_name: Optional[str] = None
    quote_snapshot: Dict = {}

    for raw in raw_chunks:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        mtype = payload.get("m")
        p = payload.get("p", [])
        if mtype == "symbol_resolved":
            if len(p) >= 3 and isinstance(p[2], dict):
                company_name = (
                    p[2].get("local_description") or p[2].get("description")
                )
        elif mtype == "timescale_update":
            # Last one wins (in practice TV sends a single timescale_update
            # per symbol per request).
            ohlcv_payload = payload
        elif mtype == "qsd":
            if len(p) >= 2 and isinstance(p[1], dict):
                v = p[1].get("v")
                if isinstance(v, dict):
                    quote_snapshot.update(v)

    if ohlcv_payload is None:
        return None

    candles = parse_ohlcv(ohlcv_payload)
    if not candles:
        return None

    fundamentals = extract_fundamentals_from_quote_raw(quote_snapshot)

    return {
        "symbol": provider_symbol,
        "timeframe": timeframe,
        "candles": candles,
        "fundamentals_raw": quote_snapshot,
        "company_name": company_name,
        "fundamentals": fundamentals,
    }


def stream_raw_batches_from_s3(
    *,
    bucket: str,
    prefix: str,
    ingestion_date: str,
    timeframe: str,
    region: str = "us-east-2",
    batch_size: int = 50,
):
    """
    Generator: yields {symbol: body} dicts of up to `batch_size` symbols at
    a time.

    Memory stays bounded at ~`batch_size` symbols' worth of candles regardless
    of how many files live in S3 — caller is expected to persist + drop the
    batch reference between iterations. This is what lets the Fargate
    processor task run on a small (256/512) profile even on bootstrap days.
    """
    catalog = load_assets_catalog()
    client = _s3_client(region)

    keys = _list_symbol_keys(client, bucket, prefix, ingestion_date)
    logger.info(
        "stream_raw_batches: %d files under s3://%s/%s for ingestion_date=%s, batch_size=%d",
        len(keys), bucket, prefix.strip("/"), ingestion_date, batch_size,
    )

    batch: Dict[str, dict] = {}
    processed = 0
    skipped = 0
    for symbol, key in keys:
        cfg = catalog.get(symbol)
        if not cfg:
            skipped += 1
            logger.warning("stream_raw_batches: %s not in catalog, skipping %s", symbol, key)
            continue
        provider_symbol = (
            cfg.get("provider_symbol", {}).get("tradingview") or symbol
        )
        try:
            obj = client.get_object(Bucket=bucket, Key=key)
            raw_bytes = obj["Body"].read()
            with gzip.GzipFile(fileobj=io.BytesIO(raw_bytes), mode="rb") as gz:
                text = gz.read().decode("utf-8")
            chunks = [line for line in text.splitlines() if line.strip()]
            body = _reassemble_body(
                chunks, timeframe=timeframe, provider_symbol=provider_symbol
            )
            if body is None:
                skipped += 1
                logger.warning("stream_raw_batches: no usable OHLCV in %s", key)
                continue
            batch[symbol] = body
            processed += 1
            if len(batch) >= batch_size:
                yield batch
                batch = {}
        except Exception as e:
            skipped += 1
            logger.error("stream_raw_batches: failed to process %s: %s", key, e)
            continue

    if batch:
        yield batch

    logger.info(
        "stream_raw_batches done: processed=%d skipped=%d (of %d files)",
        processed, skipped, len(keys),
    )


def read_raw_from_s3(
    *,
    bucket: str,
    prefix: str,
    ingestion_date: str,
    timeframe: str,
    region: str = "us-east-2",
) -> Dict[str, dict]:
    """
    Eager wrapper around stream_raw_batches_from_s3 — loads ALL symbols into
    one dict and returns it. Kept for backward compatibility / one-off scripts.
    For the Fargate processor use stream_raw_batches_from_s3 instead so the
    memory footprint stays bounded.
    """
    out: Dict[str, dict] = {}
    for batch in stream_raw_batches_from_s3(
        bucket=bucket,
        prefix=prefix,
        ingestion_date=ingestion_date,
        timeframe=timeframe,
        region=region,
        batch_size=10**9,  # effectively no batching
    ):
        out.update(batch)
    logger.info("read_raw_from_s3 (eager wrapper): %d symbols loaded", len(out))
    return out
