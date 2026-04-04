from typing import Optional, Dict, Any, List
import time

from financial_data_etl.storage.database import (
    get_connection, transaction, execute, executemany, fetchone, PH,
)


# ==============================
# Schema
# ==============================

def init_tv_candles_schema() -> None:
    with transaction() as conn:
        execute(conn, """
        CREATE TABLE IF NOT EXISTS tv_candles_raw (
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            ts BIGINT NOT NULL,
            open DOUBLE PRECISION,
            high DOUBLE PRECISION,
            low DOUBLE PRECISION,
            close DOUBLE PRECISION,
            volume DOUBLE PRECISION,
            is_partial INTEGER DEFAULT 0,
            ingested_at BIGINT NOT NULL,
            PRIMARY KEY (symbol, timeframe, ts)
        );
        """)

# ==============================
# Incremental state
# ==============================

def get_last_timestamp(symbol: str, timeframe: str) -> Optional[int]:
    conn = get_connection()
    try:
        row = fetchone(conn, f"""
            SELECT MAX(ts)
            FROM tv_candles_raw
            WHERE symbol = {PH}
              AND timeframe = {PH}
        """, (symbol, timeframe))
        return row[0] if row and row[0] is not None else None
    finally:
        conn.close()

# ==============================
# Persistence
# ==============================

def upsert_rows(rows: List[Dict[str, Any]], chunk_size: int = 9000) -> None:
    if not rows:
        return

    now = int(time.time())

    def chunker(seq, size):
        for i in range(0, len(seq), size):
            yield seq[i:i + size]

    with transaction() as conn:
        for chunk in chunker(rows, chunk_size):

            values = []
            for r in chunk:
                values.append((
                    r["symbol"],
                    r["timeframe"],
                    r["ts"],
                    r.get("open"),
                    r.get("high"),
                    r.get("low"),
                    r.get("close"),
                    r.get("volume"),
                    1 if r.get("is_partial") else 0,
                    now,
                ))

            executemany(conn, f"""
            INSERT INTO tv_candles_raw (
                symbol, timeframe, ts,
                open, high, low, close, volume,
                is_partial, ingested_at
            )
            VALUES ({PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH})
            ON CONFLICT(symbol, timeframe, ts)
            DO UPDATE SET
                open=EXCLUDED.open,
                high=EXCLUDED.high,
                low=EXCLUDED.low,
                close=EXCLUDED.close,
                volume=EXCLUDED.volume,
                is_partial=EXCLUDED.is_partial,
                ingested_at=EXCLUDED.ingested_at
            """, values)
