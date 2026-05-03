"""
VPS scraper entrypoint.

Run with:
    python -m financial_data_etl.vps_scraper.runner

Flow:
    1. Acquire process lockfile (anti-overlap with previous run).
    2. Load config from env vars.
    3. Read catalog_seed.txt and validate against catalog.json
       (warns + skips tickers with no provider_symbol entry).
    4. POST /internal/increment-plan to the Fargate API through the ALB.
       Returns {symbol: n_candles_to_fetch}. Symbols already up to date
       in RDS come back with n=0 and the API drops them.
    5. Run the chunked scrape (chunks of 50, sleep 50s between).
    6. Per chunk: capture raw WS chunks via the raw_capture hook,
       upload one data.jsonl.gz per symbol to S3.
    7. Upload _DONE_{date}.txt marker -> triggers Lambda dispatcher
       -> ECS RunTask -> Fargate processor consumes the day's files.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from financial_data_etl.observability.run_context import RunContext
from financial_data_etl.scraping_pipeline.tv_websocket_connection.call_specification.asset_catalog import (
    load_assets_catalog,
)
from financial_data_etl.storage.paths import PACKAGE_DIR

from financial_data_etl.vps_scraper.api_client import fetch_increment_plan
from financial_data_etl.vps_scraper.chunk_orchestrator import run_chunked_scrape
from financial_data_etl.vps_scraper.config import load_config
from financial_data_etl.vps_scraper.lockfile import file_lock


CATALOG_SEED_PATH = PACKAGE_DIR / "universe" / "storage" / "catalog_seed.txt"


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stdout,
    )


def _read_seed(path: Path) -> List[str]:
    if not path.exists():
        raise FileNotFoundError(f"catalog_seed.txt not found at {path}")
    out: List[str] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            t = line.strip()
            if t and not t.startswith("#"):
                out.append(t)
    return out


def _validate_against_catalog(seed: List[str], catalog: dict) -> List[str]:
    """Filter to seed entries that have a tradingview provider_symbol."""
    valid: List[str] = []
    missing: List[str] = []
    for sym in seed:
        cfg = catalog.get(sym)
        if not cfg:
            missing.append(sym)
            continue
        if "tradingview" not in cfg.get("provider_symbol", {}):
            missing.append(sym)
            continue
        valid.append(sym)
    if missing:
        logging.warning(
            "Skipping %d seed tickers without tradingview provider_symbol: %s",
            len(missing),
            missing[:20],
        )
    return valid


def main() -> int:
    _setup_logging()
    logger = logging.getLogger("vps_scraper.runner")

    config = load_config()
    ingestion_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    logger.info(
        "VPS scraper starting | ingestion_date=%s bucket=%s prefix=%s api=%s",
        ingestion_date, config.s3_bucket, config.s3_prefix, config.api_base_url,
    )

    with file_lock(config.lockfile_path):
        seed = _read_seed(CATALOG_SEED_PATH)
        logger.info("Seed loaded: %d tickers from %s", len(seed), CATALOG_SEED_PATH)

        catalog = load_assets_catalog()
        valid = _validate_against_catalog(seed, catalog)
        logger.info("Seed validated: %d/%d tickers have a tradingview provider_symbol",
                    len(valid), len(seed))

        if not valid:
            logger.error("No valid tickers after catalog validation. Aborting.")
            return 1

        plan = fetch_increment_plan(
            api_base_url=config.api_base_url,
            token=config.api_token,
            symbols=valid,
            timeframe=config.timeframe,
        )
        logger.info(
            "Increment plan received: %d symbols need scraping (%d filtered as up-to-date by API)",
            len(plan), len(valid) - len(plan),
        )

        if not plan:
            logger.info("Plan is empty (everything is up to date). Nothing to scrape.")
            # We still drop a marker so the processor can run derived metrics
            # against any leftover data — but for now we just skip; if RDS is
            # already current there is nothing for the processor to do either.
            return 0

        ctx = RunContext(run_name="vps_scraper", console=True)
        try:
            stats = run_chunked_scrape(
                plan=plan,
                config=config,
                ingestion_date=ingestion_date,
                ctx=ctx,
            )
            logger.info(
                "VPS scraper finished | uploaded=%d failed=%d total=%d",
                stats["uploaded_symbols"], stats["failed_symbols"], stats["total_symbols"],
            )
        finally:
            ctx.finalize(status="success")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
