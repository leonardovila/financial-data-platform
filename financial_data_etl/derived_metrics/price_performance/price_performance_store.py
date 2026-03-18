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

def init_performance_schema() -> None:
    with _get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS performance_1d (
                symbol TEXT NOT NULL,
                ts INTEGER NOT NULL,
                ret_1d REAL,
                ret_1w REAL,
                ret_1m REAL,
                ret_3m REAL,
                ret_6m REAL,
                ret_1y REAL,
                is_partial INTEGER NOT NULL,
                computed_at INTEGER NOT NULL,
                PRIMARY KEY (symbol, ts)
            );
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_performance_symbol_ts
            ON performance_1d(symbol, ts);
            """
        )

def get_last_perf_ts(symbol: str) -> Optional[int]:
    with _get_connection() as conn:
        row = conn.execute(
            "SELECT MAX(ts) FROM performance_1d WHERE symbol=?",
            (symbol,),
        ).fetchone()
        return int(row[0]) if row and row[0] is not None else None


def upsert_performance_rows(rows: List[Dict[str, Any]], chunk_size: int = 9000, conn=None) -> None:
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
                    r.get("ret_1d"),
                    r.get("ret_1w"),
                    r.get("ret_1m"),
                    r.get("ret_3m"),
                    r.get("ret_6m"),
                    r.get("ret_1y"),
                    r.get("is_partial", 0),
                    now,
                )
            )

        _conn.executemany(
            """
            INSERT INTO performance_1d (
                symbol, ts,
                ret_1d, ret_1w, ret_1m, ret_3m, ret_6m, ret_1y,
                is_partial,
                computed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, ts)
            DO UPDATE SET
                ret_1d=excluded.ret_1d,
                ret_1w=excluded.ret_1w,
                ret_1m=excluded.ret_1m,
                ret_3m=excluded.ret_3m,
                ret_6m=excluded.ret_6m,
                ret_1y=excluded.ret_1y,
                is_partial=excluded.is_partial,
                computed_at=excluded.computed_at;
            """,
            values,
        )

    if conn is None:
        _conn.commit()
        _conn.close()