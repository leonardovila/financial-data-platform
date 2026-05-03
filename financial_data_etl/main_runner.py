from financial_data_etl.scraping_pipeline.tv_websocket_connection.tv_websocket_scraper import run_tv_websocket_scraper
from financial_data_etl.universe.universe_service import resolve_and_cache_universe
from financial_data_etl.storage.increment_planner import build_increment_plan
from financial_data_etl.storage.ohlcv_base_store import persist_ohlcv_base
from financial_data_etl.storage.fundamentals_store import persist_fundamentals_snapshot
from financial_data_etl.derived_metrics.price_performance.price_performance_runner import run_price_performance_1d
from financial_data_etl.derived_metrics.volatility.volatility_runner import run_volatility_1d
from financial_data_etl.derived_metrics.momentum.momentum_runner import run_momentum_1d
from financial_data_etl.observability.run_context import RunContext

import argparse
import os
from datetime import datetime, timezone
from typing import List, Optional

from financial_data_etl.storage.paths import DB_PATH


def _use_vps_raw() -> bool:
    """USE_VPS_RAW=true switches step 3 from live scrape to S3 raw read."""
    return os.environ.get("USE_VPS_RAW", "false").lower() in ("1", "true", "yes")

def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="financial_data_etl",
        description="financial_data_etl entrypoint (CLI flags only; execution wired later).",
    )

    # Universo por índices (se pueden combinar)
    parser.add_argument("--spx", action="store_true", help="Universe: S&P 500")
    parser.add_argument("--ndx", action="store_true", help="Universe: Nasdaq 100")
    parser.add_argument("--rut", action="store_true", help="Universe: Russell 2000")
    parser.add_argument("--dji", action="store_true", help="Universe: Dow Jones Industrial Average")
    
    parser.add_argument(
        "--update-universe",
        action="store_true",
        help="Force update universe from screener and persist snapshot.",
    )

    # Universo por assets explícitos
    parser.add_argument(
        "--assets",
        nargs="+",
        metavar="SYMBOL",
        help="Universe: explicit assets list. Example: --assets AAPL MSFT BTCUSDT",
    )

    # NUEVO: Control de timeframe
    parser.add_argument(
        "--timeframe",
        type=str,
        default="1d",
        help="Resolución temporal de las velas (ej. 1d, 5m). Por defecto: 1d."
    )

    return parser

def parse_cli(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    return args

def main(argv: Optional[List[str]] = None) -> int:
    # In USE_VPS_RAW mode the task is launched by the Lambda dispatcher with
    # NO CLI args (only env vars), so universe + plan resolution from --spx
    # / --assets does not apply and would crash. We branch BEFORE parsing
    # the CLI args for that mode.
    use_vps_raw = _use_vps_raw()

    if use_vps_raw:
        args = argparse.Namespace(timeframe=os.environ.get("VPS_TIMEFRAME", "1d"))
    else:
        args = parse_cli(argv)

    ctx = RunContext(run_name="financial_data_etl_main", console=True)
    status = "success"

    try:
        if use_vps_raw:
            # The VPS already scraped the raw and dropped one .jsonl.gz per
            # symbol in S3. Skip universe + plan resolution (those are
            # consumed by the live scraper, not by the S3 reader) and read
            # the raw files directly. Persist + derived steps below stay
            # exactly as in the live-scrape flow.
            from financial_data_etl.storage.raw_s3_reader import read_raw_from_s3

            timeframe = args.timeframe
            bucket = os.environ.get("VPS_S3_BUCKET", "leonardovila-financial-raw")
            prefix = os.environ.get("VPS_S3_PREFIX", "raw/tv")
            ingestion_date = os.environ.get(
                "INGESTION_DATE",
                datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            )
            with ctx.span(
                "read_raw_from_s3",
                timeframe=timeframe,
                bucket=bucket,
                prefix=prefix,
                ingestion_date=ingestion_date,
            ):
                all_batch_data = read_raw_from_s3(
                    bucket=bucket,
                    prefix=prefix,
                    ingestion_date=ingestion_date,
                    timeframe=timeframe,
                )
                ctx.event(
                    "read_raw_from_s3_summary",
                    stage="read_raw_from_s3",
                    symbols_loaded=len(all_batch_data),
                    ingestion_date=ingestion_date,
                )
                if not all_batch_data:
                    raise RuntimeError(
                        f"read_raw_from_s3 returned 0 symbols for ingestion_date={ingestion_date}."
                    )
        else:
            # -------------------------
            # 1️⃣ Resolver universo (live scrape only)
            # -------------------------
            with ctx.span("universe_resolve"):
                symbols = resolve_and_cache_universe(args, ctx=ctx)

            if not symbols:
                raise RuntimeError("No symbols resolved.")

            # -------------------------
            # 2️⃣ Build incremental plan (live scrape only)
            # -------------------------
            timeframe = args.timeframe

            with ctx.span("increment_plan", symbols=len(symbols), timeframe=timeframe):
                plan = build_increment_plan(symbols, timeframe=timeframe, ctx=ctx)

            # -------------------------
            # 3️⃣ Live scrape
            # -------------------------
            with ctx.span(
                "tv_websocket_scrape",
                timeframe=timeframe,
                symbols=len(plan),
            ):
                all_batch_data = run_tv_websocket_scraper(
                    plan=plan,
                    timeframe=timeframe,
                    ctx=ctx,
                    stage="tv_websocket_scrape",
                )

                ctx.event(
                    "tv_websocket_scrape_summary",
                    stage="tv_websocket_scrape",
                    symbols_requested=len(plan),
                    symbols_success=len(all_batch_data),
                )

                if not all_batch_data:
                    raise RuntimeError("tv_websocket_scrape returned 0 symbols (all_batch_data empty).")

        # 3B) PERSIST ONLY (ohlcv base)
        with ctx.span(
            "ohlcv_persist",
            timeframe=timeframe,
            symbols=len(all_batch_data),
        ):
            persist_ohlcv_base(all_batch_data, ctx)

        with ctx.span(
            "fundamentals_persist",
            symbols=len(all_batch_data),
        ):
            persist_fundamentals_snapshot(all_batch_data, ctx)

        derived_symbols = list(all_batch_data.keys())

        if timeframe == "1d": # financial_data_etl 1.0 esta pensado para adicionar metricas solamente en 1d para consistencia
            with ctx.span("derived_metrics", timeframe=timeframe, symbols=len(derived_symbols)):
                import concurrent.futures

                def _run_perf():
                    with ctx.span("derived_price_performance_1d", symbols=len(derived_symbols)):
                        run_price_performance_1d(derived_symbols, ctx=ctx)

                def _run_volat():
                    with ctx.span("derived_volatility_1d", symbols=len(derived_symbols)):
                        run_volatility_1d(derived_symbols, ctx=ctx)

                def _run_momentum():
                    with ctx.span("derived_momentum_1d", symbols=len(derived_symbols)):
                        run_momentum_1d(derived_symbols, ctx=ctx)

                # Disparamos los 3 cálculos de Pandas al mismo tiempo usando los hilos de la CPU
                with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                    futures = [
                        executor.submit(_run_perf),
                        executor.submit(_run_volat),
                        executor.submit(_run_momentum)
                    ]
                    # Esperamos a que terminen y capturamos cualquier error si SQLite se queja
                    for f in concurrent.futures.as_completed(futures):
                        f.result()

        return 0

    except Exception as e:
        status = "error"
        ctx.event("run_error", level="ERROR", error=str(e))
        raise

    finally:
        ctx.finalize(status=status)

if __name__ == "__main__":
    raise SystemExit(main())    