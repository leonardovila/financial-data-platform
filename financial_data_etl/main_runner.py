from financial_data_etl.scraping_pipeline.tv_websocket_connection.tv_websocket_scraper import run_tv_websocket_scraper
from financial_data_etl.universe.universe_service import resolve_and_cache_universe
from financial_data_etl.storage.increment_planner import build_increment_plan
from financial_data_etl.storage.ohlcv_base_store import persist_ohlcv_base
from financial_data_etl.storage.fundamentals_store import persist_fundamentals_snapshot
from financial_data_etl.derived_metrics.price_performance.price_performance_runner import run_price_performance_1d
from financial_data_etl.derived_metrics.volatility.volatility_runner import run_volatility_1d
from financial_data_etl.derived_metrics.volume.volume_runner import run_volume_1d
from financial_data_etl.observability.run_context import RunContext

import argparse
from typing import List, Optional

from financial_data_etl.storage.paths import DB_PATH

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

    return parser

def parse_cli(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    return args

def main(argv: Optional[List[str]] = None) -> int:
    args = parse_cli(argv)
    ctx = RunContext(run_name="financial_data_etl_main", console=True)
    status = "success"

    try:
        # -------------------------
        # 1️⃣ Resolver universo
        # -------------------------
        with ctx.span("universe_resolve"):
            symbols = resolve_and_cache_universe(args, ctx=ctx)

        if not symbols:
            raise RuntimeError("No symbols resolved.")

        # -------------------------
        # 2️⃣ Build incremental plan
        # -------------------------
        timeframe = "1d"

        with ctx.span("increment_plan", symbols=len(symbols), timeframe=timeframe):
            plan = build_increment_plan(symbols, timeframe=timeframe, ctx=ctx)

        # -------------------------
        # 3️⃣ Scrape (pool-based, all symbols in one pass)
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

                def _run_volum():
                    with ctx.span("derived_volume_1d", symbols=len(derived_symbols)):
                        run_volume_1d(derived_symbols, ctx=ctx)

                # Disparamos los 3 cálculos de Pandas al mismo tiempo usando los hilos de la CPU
                with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                    futures = [
                        executor.submit(_run_perf),
                        executor.submit(_run_volat),
                        executor.submit(_run_volum)
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