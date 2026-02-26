from __future__ import annotations
from typing import Any, Dict, List, Tuple
from financial_data_etl.storage.tv_candles_store import _get_connection
from financial_data_etl.derived_metrics.price_performance.price_performance_store import (
    init_performance_schema,
    get_last_perf_ts,
    upsert_performance_rows,
)

# trading-days aproximado
LAGS = {
    "ret_1d": 1,
    "ret_1w": 5,
    "ret_1m": 21,
    "ret_3m": 63,
    "ret_6m": 126,
    "ret_1y": 252,
}

OVERLAP_BARS = 5  # recalcular cola defensiva
MAX_LAG = max(LAGS.values())  # 252
WINDOW_BARS = MAX_LAG + OVERLAP_BARS + 1

def _load_closes_window_1d(symbol: str, bootstrap: bool) -> List[Tuple[int, float]]:
    with _get_connection() as conn:

        if bootstrap:
            rows = conn.execute(
                """
                SELECT ts, close, is_partial
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
                SELECT ts, close, is_partial
                FROM (
                    SELECT ts, close, is_partial
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
    for ts, close, is_partial in rows:
        if ts is None or close is None:
            continue
        result.append((int(ts), float(close), int(is_partial)))

    return result

def _compute_returns_series(closes: List[Tuple[int, float, int]]) -> List[Dict[str, Any]]:
    """
    closes: asc por ts.
    Devuelve rows para performance_1d.
    """
    ts_list = [x[0] for x in closes]
    c_list = [x[1] for x in closes]
    partial_list = [x[2] for x in closes]

    out: List[Dict[str, Any]] = []

    for i in range(len(c_list)):
        c0 = c_list[i]
        row: Dict[str, Any] = {
            "ts": ts_list[i],
            "is_partial": partial_list[i],
        }

        for col, lag in LAGS.items():
            j = i - lag
            if j >= 0 and c_list[j] not in (0.0, None):
                row[col] = (c0 / c_list[j]) - 1.0
            else:
                row[col] = None

        out.append(row)

    return out

def run_price_performance_1d(symbols: List[str], ctx=None) -> None:
    """
    Incremental:
    - Si performance no tiene nada para el símbolo: compute full.
    - Si tiene: compute desde (last_perf_idx - OVERLAP_BARS) hasta el final.
    """
    if not symbols:
        return
    
    total_symbols_processed = 0
    total_bootstrap = 0
    total_rows_upserted = 0

    init_performance_schema()

    for symbol in symbols:

        last_perf = get_last_perf_ts(symbol)
        bootstrap = last_perf is None

        if bootstrap:
            total_bootstrap += 1

        closes = _load_closes_window_1d(symbol, bootstrap)

        if not closes:
            continue

        perf_rows = _compute_returns_series(closes)

        # Siempre upsert toda la ventana recalculada
        final_rows = []
        for r in perf_rows:
            final_rows.append(
                {
                    "symbol": symbol,
                    "ts": r["ts"],
                    "ret_1d": r["ret_1d"],
                    "ret_1w": r["ret_1w"],
                    "ret_1m": r["ret_1m"],
                    "ret_3m": r["ret_3m"],
                    "ret_6m": r["ret_6m"],
                    "ret_1y": r["ret_1y"],
                    "is_partial": r["is_partial"],
                }
            )

        upsert_performance_rows(final_rows)

        total_symbols_processed += 1
        total_rows_upserted += len(final_rows)
    
    if ctx is not None:
        ctx.event(
            "derived_price_performance_summary",
            symbols_processed=total_symbols_processed,
            bootstrap_symbols=total_bootstrap,
            rows_upserted=total_rows_upserted,
        )