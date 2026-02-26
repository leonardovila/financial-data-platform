from typing import Dict, Any, List

from financial_data_etl.storage.ohlcv_row_builder import run_ohlcv_row_builder
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

    cal = xcals.get_calendar("XNYS")
    tz = cal.tz
    now_exchange = pd.Timestamp.now(tz=tz)

    ctx.event(
        "ohlcv_partial_context",
        now_exchange=str(now_exchange),
        current_session=str(cal.minute_to_session(now_exchange, direction="previous")),
        session_close=str(
            cal.session_close(
                cal.minute_to_session(now_exchange, direction="previous")
            )
        ),
    )

    all_rows: List[Dict] = []

    for ticker, body in batch_data.items():
        rows = run_ohlcv_row_builder(ticker, body, ctx=ctx)
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