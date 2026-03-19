"""
LiveSymbolState: in-memory Pandas DataFrame container for the Seed & Edge
live streaming architecture (LIVE-02).

Holds the last MAX_BARS (258) bars of OHLCV for a single symbol entirely in
RAM. After the initial seed from SQLite, this class NEVER touches the disk.

Two core operations:
  - seed(): populate with historical candles (once per symbol/session)
  - update_tick(): replace or append live bar updates from TradingView 'du'

The DataFrame is the compute substrate for LIVE-03's pure metric functions.
"""

from __future__ import annotations
from typing import List, Dict, Any, Optional
import time
import pandas as pd

# 258 = max(252 vol_1y, 252 ret_1y, 200 sma_200) + 5 overlap + 1
# Enough for every derived metric window. Rows beyond this are trimmed.
MAX_BARS = 258

_DF_COLUMNS = ["ts", "open", "high", "low", "close", "volume"]


class LiveSymbolState:
    """
    In-memory OHLCV state for a single symbol's live stream.

    Owned by a single WebSocket handler coroutine. When the handler exits,
    this object and its DataFrame are garbage collected. No module-level
    references, no registry, no leak path.
    """

    __slots__ = (
        "symbol",
        "timeframe",
        "df",
        "fundamentals",
        "company_name",
        "last_tick_ts",
        "tick_count",
    )

    def __init__(self, symbol: str, timeframe: str = "1d"):
        self.symbol: str = symbol
        self.timeframe: str = timeframe
        self.df: pd.DataFrame = pd.DataFrame(columns=_DF_COLUMNS)
        self.fundamentals: Dict[str, Any] = {}
        self.company_name: Optional[str] = None
        self.last_tick_ts: float = 0.0
        self.tick_count: int = 0

    # ──────────────────────────────────────────────────────────────────────
    # SEED: one-time population from historical data
    # ──────────────────────────────────────────────────────────────────────

    def seed(
        self,
        candles: List[List[float]],
        fundamentals: Optional[Dict[str, Any]] = None,
        company_name: Optional[str] = None,
    ) -> None:
        """
        Populate the DataFrame from a list of candles [[ts,o,h,l,c,v], ...].

        Typically called ONCE after merging SQLite historical bars with the
        TV seed (3 fresh bars). Trims to MAX_BARS from the tail.
        """
        if not candles:
            return

        self.df = pd.DataFrame(candles, columns=_DF_COLUMNS)
        self.df["ts"] = self.df["ts"].astype("int64")
        self.df.sort_values("ts", inplace=True)
        self.df.reset_index(drop=True, inplace=True)

        # Trim to MAX_BARS (keep the most recent)
        if len(self.df) > MAX_BARS:
            self.df = self.df.iloc[-MAX_BARS:].reset_index(drop=True)

        if fundamentals is not None:
            self.fundamentals = fundamentals
        if company_name is not None:
            self.company_name = company_name

        self.tick_count = 0
        self.last_tick_ts = time.monotonic()

    # ──────────────────────────────────────────────────────────────────────
    # MERGE TV SEED: overlay fresh TV candles onto the SQLite base
    # ──────────────────────────────────────────────────────────────────────

    def merge_tv_seed(self, tv_candles: List[List[float]]) -> None:
        """
        Merge fresh candles from TradingView's initial timescale_update
        into the existing DataFrame. For each TV candle:
          - If ts matches an existing row → REPLACE (TV has fresher OHLCV)
          - If ts not found → APPEND (new bar since last batch ETL)

        Called after seed() with SQLite data, before the Edge loop starts.
        """
        if not tv_candles or self.df.empty:
            return

        # Index by ts for O(1) lookup
        self.df.set_index("ts", inplace=True)

        for candle in tv_candles:
            ts = int(candle[0])
            row_data = {
                "open": float(candle[1]),
                "high": float(candle[2]),
                "low": float(candle[3]),
                "close": float(candle[4]),
                "volume": float(candle[5]) if len(candle) > 5 else 0.0,
            }
            # O(1) replace or append via .loc on int64 index
            self.df.loc[ts] = row_data

        # Restore ts as column, sort, trim
        self.df.reset_index(inplace=True)
        self.df.rename(columns={"index": "ts"}, inplace=True)
        self.df.sort_values("ts", inplace=True)
        self.df.reset_index(drop=True, inplace=True)

        if len(self.df) > MAX_BARS:
            self.df = self.df.iloc[-MAX_BARS:].reset_index(drop=True)

    # ──────────────────────────────────────────────────────────────────────
    # UPDATE TICK: live bar replacement/append from TradingView 'du'
    # ──────────────────────────────────────────────────────────────────────

    def update_tick(self, updated_candles: List[List[float]]) -> Dict[str, Any]:
        """
        Apply live bar update(s) from a TradingView 'du' message.

        For each candle in updated_candles:
          - Same ts as existing row → REPLACE in-place (live bar OHLCV changed)
          - New ts → APPEND (new bar opened, e.g. market open of a new day)

        Returns the most recent candle as a dict for the WebSocket payload.

        Performance target: ~0.1ms for 1 bar update on 258 rows.
        """
        if not updated_candles:
            return {}

        # Set ts as index for O(1) .loc access
        self.df.set_index("ts", inplace=True)

        latest_candle = updated_candles[-1]  # the most recent bar

        for candle in updated_candles:
            ts = int(candle[0])
            row_data = {
                "open": float(candle[1]),
                "high": float(candle[2]),
                "low": float(candle[3]),
                "close": float(candle[4]),
                "volume": float(candle[5]) if len(candle) > 5 else 0.0,
            }
            # .loc[ts] = ... is O(1) on an int64 index:
            #   - If ts exists: replaces the row (live bar update)
            #   - If ts is new: appends a new row (new bar opened)
            self.df.loc[ts] = row_data

        # Restore ts as column, sort, trim
        self.df.reset_index(inplace=True)
        self.df.rename(columns={"index": "ts"}, inplace=True)
        self.df.sort_values("ts", inplace=True)
        self.df.reset_index(drop=True, inplace=True)

        if len(self.df) > MAX_BARS:
            self.df = self.df.iloc[-MAX_BARS:].reset_index(drop=True)

        # Update liveness tracking
        self.tick_count += 1
        self.last_tick_ts = time.monotonic()

        # Return the latest candle as a JSON-friendly dict
        ts = int(latest_candle[0])
        return {
            "ts": ts,
            "open": float(latest_candle[1]),
            "high": float(latest_candle[2]),
            "low": float(latest_candle[3]),
            "close": float(latest_candle[4]),
            "volume": float(latest_candle[5]) if len(latest_candle) > 5 else 0.0,
        }

    # ──────────────────────────────────────────────────────────────────────
    # COMPUTE METRICS: thread-safe snapshot for run_in_executor
    # ──────────────────────────────────────────────────────────────────────

    def get_df_snapshot(self) -> pd.DataFrame:
        """
        Return a COPY of the DataFrame for thread-safe metric computation.

        Called before loop.run_in_executor(None, compute_all_metrics_live, snapshot).
        The copy prevents data races if a tick update arrives on the event loop
        while the executor thread is mid-computation.

        Cost: ~12KB copy for 258 rows × 6 float64 columns. Negligible.
        """
        return self.df.copy()

    # ──────────────────────────────────────────────────────────────────────
    # OBSERVABILITY
    # ──────────────────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        """Return current state summary for /ws/stats monitoring endpoint."""
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "bars": len(self.df),
            "tick_count": self.tick_count,
            "last_tick_ts": self.last_tick_ts,
            "company_name": self.company_name,
            "has_fundamentals": bool(self.fundamentals),
        }
