"""
Live Seed layer (LIVE-05): one-time SQLite read for cold-start payload.

Queries the database ONCE when a client connects, then NEVER again.
Returns everything the frontend needs to draw the full chart and display
the latest batch-computed metrics before the live Edge stream takes over.

Thread-safe: creates and destroys its own connection inside the function.
Called via loop.run_in_executor(None, load_historical_seed, symbol).
"""

from __future__ import annotations
import sqlite3
from typing import Dict, Any, List, Optional
from financial_data_etl.api.db import get_connection


def _safe_float(val) -> float | None:
    """Cast to float, return None if not a valid number."""
    if val is None:
        return None
    try:
        f = float(val)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


# Fields that MUST be numeric floats in the JSON payload
_NUMERIC_FIELDS = {
    "market_cap", "pe_ttm", "eps_ttm", "shares_outstanding",
    "ret_1d", "ret_1w", "ret_1m", "ret_3m", "ret_6m", "ret_1y",
    "range_intraday", "vol_1w", "vol_1m", "vol_3m", "vol_6m", "vol_1y",
    "volume_usd", "vol_sma_20", "vol_sma_50", "vol_sma_100", "vol_sma_200",
    "vol_gap_20", "vol_gap_50", "vol_gap_100", "vol_gap_200",
}


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """Convert a sqlite3.Row to a plain dict, casting numeric fields to float."""
    d: Dict[str, Any] = {}
    for k in row.keys():
        v = row[k]
        if k in _NUMERIC_FIELDS:
            d[k] = _safe_float(v)
        else:
            d[k] = v
    return d


def load_historical_seed(symbol: str) -> Dict[str, Any]:
    """
    Load the full cold-start payload for a symbol from SQLite.

    Executes 5 indexed queries on a single connection, then closes it.
    Expected latency: 5-15ms on WAL-mode SQLite.

    Returns:
        {
            "symbol": "AAPL",
            "chart_candles": [[ts, o, h, l, c, v], ...],  # up to 4500 bars
            "company_name": "Apple Inc" | None,
            "fundamentals": {...} | None,
            "metrics": {
                "performance": {...} | None,
                "volatility": {...} | None,
                "volume": {...} | None,
            },
        }
    """
    sym = symbol.upper()
    conn = get_connection()
    conn.row_factory = sqlite3.Row

    try:
        # ── Q1: OHLCV chart data (up to 4500 bars, ASC for frontend) ──
        chart_rows = conn.execute(
            """
            SELECT ts, open, high, low, close, volume
            FROM (
                SELECT ts, open, high, low, close, volume
                FROM tv_candles_raw
                WHERE symbol = ? AND timeframe = '1d' AND is_partial = 0
                ORDER BY ts DESC
                LIMIT 4500
            )
            ORDER BY ts ASC
            """,
            (sym,),
        ).fetchall()

        chart_candles: List[List] = [
            [r["ts"], r["open"], r["high"], r["low"], r["close"], r["volume"]]
            for r in chart_rows
        ]

        # ── Q2: Fundamentals (latest snapshot) ──
        fund_row = conn.execute(
            """
            SELECT symbol, as_of_ts, company_name, market_cap,
                   pe_ttm, eps_ttm, shares_outstanding, sector, industry
            FROM fundamentals_snapshot
            WHERE symbol = ?
            ORDER BY as_of_ts DESC
            LIMIT 1
            """,
            (sym,),
        ).fetchone()

        fundamentals: Optional[Dict[str, Any]] = None
        company_name: Optional[str] = None
        if fund_row:
            fundamentals = _row_to_dict(fund_row)
            company_name = fund_row["company_name"]

        # ── Q3: Performance (latest non-partial) ──
        perf_row = conn.execute(
            """
            SELECT symbol, ts, ret_1d, ret_1w, ret_1m, ret_3m, ret_6m, ret_1y, computed_at
            FROM performance_1d
            WHERE symbol = ? AND is_partial = 0
            ORDER BY ts DESC
            LIMIT 1
            """,
            (sym,),
        ).fetchone()

        performance: Optional[Dict[str, Any]] = _row_to_dict(perf_row) if perf_row else None

        # ── Q4: Volatility (latest non-partial) ──
        vol_row = conn.execute(
            """
            SELECT symbol, ts, range_intraday, vol_1w, vol_1m, vol_3m, vol_6m, vol_1y, computed_at
            FROM volatility_1d
            WHERE symbol = ? AND is_partial = 0
            ORDER BY ts DESC
            LIMIT 1
            """,
            (sym,),
        ).fetchone()

        volatility: Optional[Dict[str, Any]] = _row_to_dict(vol_row) if vol_row else None

        # ── Q5: Volume (latest non-partial) ──
        volume_row = conn.execute(
            """
            SELECT symbol, ts, volume_usd, vol_sma_20, vol_sma_50, vol_sma_100, vol_sma_200,
                   vol_gap_20, vol_gap_50, vol_gap_100, vol_gap_200
            FROM volume_1d
            WHERE symbol = ? AND is_partial = 0
            ORDER BY ts DESC
            LIMIT 1
            """,
            (sym,),
        ).fetchone()

        volume: Optional[Dict[str, Any]] = _row_to_dict(volume_row) if volume_row else None

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
            "volume": volume,
        },
    }
