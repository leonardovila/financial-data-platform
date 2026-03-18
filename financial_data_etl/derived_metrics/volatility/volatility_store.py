from __future__ import annotations

from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional

from financial_data_etl.storage.paths import DB_PATH

def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn

def init_volatility_schema() -> None:
    with _get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS volatility_1d (
                symbol TEXT NOT NULL,
                ts INTEGER NOT NULL,
                range_intraday REAL,
                vol_1w REAL,
                vol_1m REAL,
                vol_3m REAL,
                vol_6m REAL,
                vol_1y REAL,
                is_partial INTEGER NOT NULL,
                computed_at INTEGER NOT NULL,
                PRIMARY KEY (symbol, ts)
            );
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_volatility_symbol_ts
            ON volatility_1d(symbol, ts);
            """
        )


def get_last_vol_ts(symbol: str) -> Optional[int]:
    with _get_connection() as conn:
        row = conn.execute(
            "SELECT MAX(ts) FROM volatility_1d WHERE symbol=?",
            (symbol,),
        ).fetchone()
        return int(row[0]) if row and row[0] is not None else None


def upsert_volatility_rows(rows: List[Dict[str, Any]], chunk_size: int = 9000, conn=None) -> None:
    if not rows:
        return

    now = int(time.time())
    _conn = conn if conn is not None else _get_connection()

    def chunker(seq, size):
        for i in range(0, len(seq), size):
            yield seq[i : i + size]

    for chunk in chunker(rows, chunk_size):
        values = []
        for r in chunk:
            values.append(
                (
                    r["symbol"],
                    r["ts"],
                    r.get("range_intraday"),
                    r.get("vol_1w"),
                    r.get("vol_1m"),
                    r.get("vol_3m"),
                    r.get("vol_6m"),
                    r.get("vol_1y"),
                    r.get("is_partial", 0),
                    now,
                )
            )

        _conn.executemany(
            """
            INSERT INTO volatility_1d (
                symbol, ts,
                range_intraday,
                vol_1w, vol_1m, vol_3m, vol_6m, vol_1y,
                is_partial,
                computed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, ts)
            DO UPDATE SET
                range_intraday=excluded.range_intraday,
                vol_1w=excluded.vol_1w,
                vol_1m=excluded.vol_1m,
                vol_3m=excluded.vol_3m,
                vol_6m=excluded.vol_6m,
                vol_1y=excluded.vol_1y,
                is_partial=excluded.is_partial,
                computed_at=excluded.computed_at;
            """,
            values,
        )

    if conn is None:
        _conn.commit()
        _conn.close()