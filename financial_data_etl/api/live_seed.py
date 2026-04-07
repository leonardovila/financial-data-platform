"""
Live Seed layer: one-time DB read for cold-start payload.

Queries the database ONCE when a client connects, then NEVER again.
Returns everything the frontend needs to draw the full chart and display
the latest batch-computed metrics before the live Edge stream takes over.

Thread-safe: creates and destroys its own connection inside the function.
Called via loop.run_in_executor(None, load_historical_seed, symbol).
"""

from __future__ import annotations
from typing import Dict, Any, List, Optional

from financial_data_etl.storage.database import (
    get_dict_connection, fetchall, fetchone_dict, PH,
)


def _safe_float(val) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


_NUMERIC_FIELDS = {
    "market_cap", "pe_ttm", "eps_ttm", "shares_outstanding",
    "ret_1d", "ret_1w", "ret_1m", "ret_3m", "ret_6m", "ret_1y",
    "range_intraday", "vol_1w", "vol_1m", "vol_3m", "vol_6m", "vol_1y",
    "rsi_14", "sma_20_gap", "sma_50_gap", "sma_200_gap",
    "high_dist_1m", "high_dist_1y",
}


def _row_to_dict(row) -> Dict[str, Any]:
    """Convert a row (dict or Row) to a plain dict, casting numeric fields."""
    d: Dict[str, Any] = {}
    keys = row.keys() if hasattr(row, 'keys') else row
    for k in keys:
        v = row[k]
        if k in _NUMERIC_FIELDS:
            d[k] = _safe_float(v)
        else:
            d[k] = v
    return d


def load_historical_seed(symbol: str) -> Dict[str, Any]:
    """
    Load the full cold-start payload for a symbol from the database.

    Executes 5 indexed queries on a single connection, then closes it.

    Returns:
        {
            "symbol": "AAPL",
            "chart_candles": [[ts, o, h, l, c, v], ...],
            "company_name": "Apple Inc" | None,
            "fundamentals": {...} | None,
            "metrics": {
                "performance": {...} | None,
                "volatility": {...} | None,
                "momentum": {...} | None,
            },
        }
    """
    sym = symbol.upper()
    conn = get_dict_connection()

    try:
        # ── Q1: OHLCV chart data (up to 4500 bars, ASC for frontend) ──
        chart_rows = fetchall(conn, f"""
            SELECT ts, open, high, low, close, volume
            FROM (
                SELECT ts, open, high, low, close, volume
                FROM tv_candles_raw
                WHERE symbol = {PH} AND timeframe = '1d' AND is_partial = 0
                ORDER BY ts DESC
                LIMIT 4500
            ) sub
            ORDER BY ts ASC
        """, (sym,))

        chart_candles: List[List] = [
            [r["ts"], r["open"], r["high"], r["low"], r["close"], r["volume"]]
            if hasattr(r, '__getitem__') and hasattr(r, 'keys')
            else list(r)
            for r in chart_rows
        ]

        # ── Q2: Fundamentals (latest snapshot) ──
        fund_row = fetchone_dict(conn, f"""
            SELECT symbol, as_of_ts, company_name, market_cap,
                   pe_ttm, eps_ttm, shares_outstanding, sector, industry
            FROM fundamentals_snapshot
            WHERE symbol = {PH}
            ORDER BY as_of_ts DESC
            LIMIT 1
        """, (sym,))

        fundamentals: Optional[Dict[str, Any]] = None
        company_name: Optional[str] = None
        if fund_row:
            fundamentals = _row_to_dict(fund_row)
            company_name = fund_row["company_name"]

        # ── Q3: Performance (latest non-partial) ──
        perf_row = fetchone_dict(conn, f"""
            SELECT symbol, ts, ret_1d, ret_1w, ret_1m, ret_3m, ret_6m, ret_1y, computed_at
            FROM performance_1d
            WHERE symbol = {PH} AND is_partial = 0
            ORDER BY ts DESC
            LIMIT 1
        """, (sym,))

        performance: Optional[Dict[str, Any]] = _row_to_dict(perf_row) if perf_row else None

        # ── Q4: Volatility (latest non-partial) ──
        vol_row = fetchone_dict(conn, f"""
            SELECT symbol, ts, range_intraday, vol_1w, vol_1m, vol_3m, vol_6m, vol_1y, computed_at
            FROM volatility_1d
            WHERE symbol = {PH} AND is_partial = 0
            ORDER BY ts DESC
            LIMIT 1
        """, (sym,))

        volatility: Optional[Dict[str, Any]] = _row_to_dict(vol_row) if vol_row else None

        # ── Q5: Momentum (latest non-partial) ──
        momentum_row = fetchone_dict(conn, f"""
            SELECT symbol, ts, rsi_14, sma_20_gap, sma_50_gap, sma_200_gap,
                   high_dist_1m, high_dist_1y
            FROM momentum_1d
            WHERE symbol = {PH} AND is_partial = 0
            ORDER BY ts DESC
            LIMIT 1
        """, (sym,))

        momentum: Optional[Dict[str, Any]] = _row_to_dict(momentum_row) if momentum_row else None

    finally:
        conn.close()

    return {
        "symbol": sym,
        "chart_candles": chart_candles,
        "company_name": company_name,
        "fundamentals": fundamentals,
        "metrics": {
            "performance": performance,
            "volatility": volatility,
            "momentum": momentum,
        },
    }
