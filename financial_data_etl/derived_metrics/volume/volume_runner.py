from __future__ import annotations
from typing import Any, Dict, List, Tuple

from financial_data_etl.storage.tv_candles_store import _get_connection
from financial_data_etl.derived_metrics.volume.volume_store import (
    init_volume_schema,
    get_last_volume_ts,
    upsert_volume_rows,
)

OVERLAP_BARS = 5
MAX_WINDOW = 200 + OVERLAP_BARS + 1

SMA_WINDOWS = [20, 50, 100, 200]


def _load_volume_window_1d(symbol: str, bootstrap: bool):
    with _get_connection() as conn:

        if bootstrap:
            rows = conn.execute(
                """
                SELECT ts, close, volume, is_partial
                FROM tv_candles_raw
                WHERE timeframe='1d'
                  AND symbol=?
                ORDER BY ts ASC
                """,
                (symbol,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT ts, close, volume, is_partial
                FROM (
                    SELECT ts, close, volume, is_partial
                    FROM tv_candles_raw
                    WHERE timeframe='1d'
                      AND symbol=?
                    ORDER BY ts DESC
                    LIMIT ?
                )
                ORDER BY ts ASC
                """,
                (symbol, MAX_WINDOW),
            ).fetchall()

    return [
        (int(ts), float(close), float(volume), int(is_partial))
        for ts, close, volume, is_partial in rows
        if ts is not None and close is not None and volume is not None
    ]


def _sma(values: List[float], window: int):
    out = [None] * len(values)
    for i in range(len(values)):
        if i + 1 >= window:
            window_slice = values[i + 1 - window : i + 1]
            out[i] = sum(window_slice) / window
    return out


def run_volume_1d(symbols: List[str], ctx=None):

    if not symbols:
        return

    total_symbols_processed = 0
    total_bootstrap = 0
    total_rows_upserted = 0

    init_volume_schema()

    for symbol in symbols:

        last_ts = get_last_volume_ts(symbol)
        bootstrap = last_ts is None

        if bootstrap:
            total_bootstrap += 1

        rows = _load_volume_window_1d(symbol, bootstrap)

        if not rows:
            continue

        ts_list = [r[0] for r in rows]
        vol_usd = [r[1] * r[2] for r in rows]
        partial_list = [r[3] for r in rows]

        sma_map = {}
        for w in SMA_WINDOWS:
            sma_map[w] = _sma(vol_usd, w)

        final_rows = []

        for i in range(len(rows)):
            row = {
                "symbol": symbol,
                "ts": ts_list[i],
                "volume_usd": vol_usd[i],
                "vol_sma_20": sma_map[20][i],
                "vol_sma_50": sma_map[50][i],
                "vol_sma_100": sma_map[100][i],
                "vol_sma_200": sma_map[200][i],
                "vol_gap_20": (vol_usd[i] / sma_map[20][i] - 1.0) if sma_map[20][i] else None,
                "vol_gap_50": (vol_usd[i] / sma_map[50][i] - 1.0) if sma_map[50][i] else None,
                "vol_gap_100": (vol_usd[i] / sma_map[100][i] - 1.0) if sma_map[100][i] else None,
                "vol_gap_200": (vol_usd[i] / sma_map[200][i] - 1.0) if sma_map[200][i] else None,
                "is_partial": partial_list[i],
            }

            final_rows.append(row)

        upsert_volume_rows(final_rows)

        total_symbols_processed += 1
        total_rows_upserted += len(final_rows)

    if ctx:
        ctx.event(
            "derived_volume_summary",
            symbols_processed=total_symbols_processed,
            bootstrap_symbols=total_bootstrap,
            rows_upserted=total_rows_upserted,
        )