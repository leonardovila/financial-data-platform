from __future__ import annotations

import time
from typing import Any, Dict, List

from financial_data_etl.storage.database import (
    get_connection, transaction, execute, executemany, fetchone, PH,
)


def init_performance_schema() -> None:
    with transaction() as conn:
        execute(conn, """
            CREATE TABLE IF NOT EXISTS performance_1d (
                symbol TEXT NOT NULL,
                ts BIGINT NOT NULL,
                ret_1d DOUBLE PRECISION,
                ret_1w DOUBLE PRECISION,
                ret_1m DOUBLE PRECISION,
                ret_3m DOUBLE PRECISION,
                ret_6m DOUBLE PRECISION,
                ret_1y DOUBLE PRECISION,
                is_partial INTEGER NOT NULL,
                computed_at BIGINT NOT NULL,
                PRIMARY KEY (symbol, ts)
            );
        """)
        execute(conn, """
            CREATE INDEX IF NOT EXISTS idx_performance_symbol_ts
            ON performance_1d(symbol, ts);
        """)


def get_last_perf_ts(symbol: str):
    conn = get_connection()
    try:
        row = fetchone(conn, f"SELECT MAX(ts) FROM performance_1d WHERE symbol={PH}", (symbol,))
        return int(row[0]) if row and row[0] is not None else None
    finally:
        conn.close()


def upsert_performance_rows(rows: List[Dict[str, Any]], chunk_size: int = 9000, conn=None) -> None:
    if not rows:
        return

    now = int(time.time())
    _conn = conn if conn is not None else get_connection()

    def chunker(seq, size):
        for i in range(0, len(seq), size):
            yield seq[i : i + size]

    for chunk in chunker(rows, chunk_size):
        values = []
        for r in chunk:
            values.append((
                r["symbol"], r["ts"],
                r.get("ret_1d"), r.get("ret_1w"), r.get("ret_1m"),
                r.get("ret_3m"), r.get("ret_6m"), r.get("ret_1y"),
                r.get("is_partial", 0), now,
            ))

        executemany(_conn, f"""
            INSERT INTO performance_1d (
                symbol, ts,
                ret_1d, ret_1w, ret_1m, ret_3m, ret_6m, ret_1y,
                is_partial, computed_at
            )
            VALUES ({PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH})
            ON CONFLICT(symbol, ts)
            DO UPDATE SET
                ret_1d=EXCLUDED.ret_1d,
                ret_1w=EXCLUDED.ret_1w,
                ret_1m=EXCLUDED.ret_1m,
                ret_3m=EXCLUDED.ret_3m,
                ret_6m=EXCLUDED.ret_6m,
                ret_1y=EXCLUDED.ret_1y,
                is_partial=EXCLUDED.is_partial,
                computed_at=EXCLUDED.computed_at
        """, values)

    if conn is None:
        _conn.commit()
        _conn.close()
