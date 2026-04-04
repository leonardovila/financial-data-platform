from __future__ import annotations

import time
from typing import Any, Dict, List

from financial_data_etl.storage.database import (
    get_connection, transaction, execute, executemany, fetchone, PH,
)


def init_volatility_schema() -> None:
    with transaction() as conn:
        execute(conn, """
            CREATE TABLE IF NOT EXISTS volatility_1d (
                symbol TEXT NOT NULL,
                ts BIGINT NOT NULL,
                range_intraday DOUBLE PRECISION,
                vol_1w DOUBLE PRECISION,
                vol_1m DOUBLE PRECISION,
                vol_3m DOUBLE PRECISION,
                vol_6m DOUBLE PRECISION,
                vol_1y DOUBLE PRECISION,
                is_partial INTEGER NOT NULL,
                computed_at BIGINT NOT NULL,
                PRIMARY KEY (symbol, ts)
            );
        """)
        execute(conn, """
            CREATE INDEX IF NOT EXISTS idx_volatility_symbol_ts
            ON volatility_1d(symbol, ts);
        """)


def get_last_vol_ts(symbol: str):
    conn = get_connection()
    try:
        row = fetchone(conn, f"SELECT MAX(ts) FROM volatility_1d WHERE symbol={PH}", (symbol,))
        return int(row[0]) if row and row[0] is not None else None
    finally:
        conn.close()


def upsert_volatility_rows(rows: List[Dict[str, Any]], chunk_size: int = 9000, conn=None) -> None:
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
                r.get("range_intraday"),
                r.get("vol_1w"), r.get("vol_1m"),
                r.get("vol_3m"), r.get("vol_6m"), r.get("vol_1y"),
                r.get("is_partial", 0), now,
            ))

        executemany(_conn, f"""
            INSERT INTO volatility_1d (
                symbol, ts,
                range_intraday,
                vol_1w, vol_1m, vol_3m, vol_6m, vol_1y,
                is_partial, computed_at
            )
            VALUES ({PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH})
            ON CONFLICT(symbol, ts)
            DO UPDATE SET
                range_intraday=EXCLUDED.range_intraday,
                vol_1w=EXCLUDED.vol_1w,
                vol_1m=EXCLUDED.vol_1m,
                vol_3m=EXCLUDED.vol_3m,
                vol_6m=EXCLUDED.vol_6m,
                vol_1y=EXCLUDED.vol_1y,
                is_partial=EXCLUDED.is_partial,
                computed_at=EXCLUDED.computed_at
        """, values)

    if conn is None:
        _conn.commit()
        _conn.close()
