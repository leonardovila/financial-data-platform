from typing import Dict, Any, List

from financial_data_etl.storage.ohlcv_row_builder import (
    run_ohlcv_row_builder,
    resolve_calendar_for_symbol,
    precompute_session_context,
)
from financial_data_etl.storage.tv_candles_store import upsert_rows
import exchange_calendars as xcals
import pandas as pd


def persist_ohlcv_base(batch_data: Dict[str, Dict[str, Any]], ctx) -> None:
    """
    Consume payload completo del scraper:
    {
        "AAPL": {...},
        "MSFT": {...},
        ...
    }

    1) Construye rows por símbolo
    2) Hace un único upsert batch
    """
    ctx.event(
        "ohlcv_persist_start",
        symbols=len(batch_data),
    )

    cal = resolve_calendar_for_symbol("AAPL")  # XNYS (majority of tickers)
    session_ctx = precompute_session_context(cal)

    ctx.event(
        "ohlcv_partial_context",
        now_exchange=str(session_ctx["now_exchange"]),
        current_session=str(session_ctx["current_session"]),
        session_close=str(session_ctx["session_close"]),
    )

    # Pre-compute session contexts for non-XNYS exchanges
    _session_ctx_cache = {"XNYS": session_ctx}

    all_rows: List[Dict] = []

    for ticker, body in batch_data.items():
        # Resolve the correct session context per-exchange (cached)
        ticker_cal = resolve_calendar_for_symbol(ticker)
        exchange_key = ticker_cal.name
        if exchange_key not in _session_ctx_cache:
            _session_ctx_cache[exchange_key] = precompute_session_context(ticker_cal)
        sym_session_ctx = _session_ctx_cache[exchange_key]

        rows = run_ohlcv_row_builder(ticker, body, ctx=ctx, session_ctx=sym_session_ctx)
        all_rows.extend(rows)

    ctx.event(
        "ohlcv_rows_built",
        total_rows=len(all_rows),
    )

    partial_rows = sum(row["is_partial"] for row in all_rows)

    ctx.event(
        "ohlcv_partial_distribution",
        total_rows=len(all_rows),
        partial_rows=partial_rows,
        partial_ratio=round(partial_rows / len(all_rows), 6) if all_rows else 0.0,
    )

    upsert_rows(all_rows)

    ctx.event(
        "ohlcv_upsert_completed",
        total_rows=len(all_rows),
    )