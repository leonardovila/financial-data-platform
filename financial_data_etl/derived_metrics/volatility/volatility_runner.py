from __future__ import annotations
import math
from typing import Any, Dict, List, Tuple
from financial_data_etl.storage.tv_candles_store import _get_connection
from financial_data_etl.derived_metrics.volatility.volatility_store import (
    init_volatility_schema,
    get_last_vol_ts,
    upsert_volatility_rows,
)

VOL_WINDOWS = {
    "vol_1w": 5,
    "vol_1m": 21,
    "vol_3m": 63,
    "vol_6m": 126,
    "vol_1y": 252,
}

OVERLAP_BARS = 5
MAX_LAG = max(VOL_WINDOWS.values())
WINDOW_BARS = MAX_LAG + OVERLAP_BARS + 1
ANNUALIZATION_FACTOR = math.sqrt(252)

def _load_ohlc_window_1d(symbol: str, bootstrap: bool) -> List[Tuple[int, float, float, float]]:
    """
    Returns: [(ts, high, low, close)]
    """
    with _get_connection() as conn:

        if bootstrap:
            rows = conn.execute(
                """
                SELECT ts, high, low, close, is_partial
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
                SELECT ts, high, low, close, is_partial
                FROM (
                    SELECT ts, high, low, close, is_partial
                    FROM tv_candles_raw
                    WHERE timeframe='1d'
                      AND symbol=?
                    ORDER BY ts DESC
                    LIMIT ?
                )
                ORDER BY ts ASC
                """,
                (symbol, WINDOW_BARS),
            ).fetchall()

    result = []
    for ts, high, low, close, is_partial in rows:
        if ts is None or close is None or high is None or low is None:
            continue
        result.append((int(ts), float(high), float(low), float(close), int(is_partial)))

    return result


def _compute_volatility_series(data: List[Tuple[int, float, float, float, int]]) -> List[Dict[str, Any]]:
    """
    data: asc por ts.
    """
    out: List[Dict[str, Any]] = []

    ts_list = [x[0] for x in data]
    high_list = [x[1] for x in data]
    low_list = [x[2] for x in data]
    close_list = [x[3] for x in data]
    partial_list = [x[4] for x in data]

    # log returns
    log_returns: List[float] = [None]
    for i in range(1, len(close_list)):
        prev = close_list[i - 1]
        curr = close_list[i]
        if prev and prev > 0:
            log_returns.append(math.log(curr / prev))
        else:
            log_returns.append(None)

    for i in range(len(data)):
        row: Dict[str, Any] = {
            "ts": ts_list[i],
            "is_partial": partial_list[i],
        }

        # range intraday
        row["range_intraday"] = (
            (high_list[i] - low_list[i]) / close_list[i]
            if close_list[i] != 0
            else None
        )

        for col, window in VOL_WINDOWS.items():
            if i < window or any(log_returns[j] is None for j in range(i - window + 1, i + 1)):
                row[col] = None
            else:
                window_slice = log_returns[i - window + 1 : i + 1]
                mean = sum(window_slice) / window
                variance = sum((x - mean) ** 2 for x in window_slice) / (window - 1)
                std = math.sqrt(variance)
                row[col] = std * ANNUALIZATION_FACTOR

        out.append(row)

    return out

def run_volatility_1d(symbols: List[str], ctx=None) -> None:
    if not symbols:
        return
    
    total_symbols_processed = 0
    total_bootstrap = 0
    total_rows_upserted = 0

    init_volatility_schema()

    for symbol in symbols:

        last_vol = get_last_vol_ts(symbol)
        bootstrap = last_vol is None

        if bootstrap:
            total_bootstrap += 1

        data = _load_ohlc_window_1d(symbol, bootstrap)

        if not data:
            continue

        vol_rows = _compute_volatility_series(data)

        final_rows = []
        for r in vol_rows:
            final_rows.append(
                {
                    "symbol": symbol,
                    "ts": r["ts"],
                    "range_intraday": r["range_intraday"],
                    "vol_1w": r["vol_1w"],
                    "vol_1m": r["vol_1m"],
                    "vol_3m": r["vol_3m"],
                    "vol_6m": r["vol_6m"],
                    "vol_1y": r["vol_1y"],
                    "is_partial": r["is_partial"],
                }
            )

        upsert_volatility_rows(final_rows)

        total_symbols_processed += 1
        total_rows_upserted += len(final_rows)
    
    if ctx is not None:
        ctx.event(
            "derived_volatility_summary",
            symbols_processed=total_symbols_processed,
            bootstrap_symbols=total_bootstrap,
            rows_upserted=total_rows_upserted,
        )