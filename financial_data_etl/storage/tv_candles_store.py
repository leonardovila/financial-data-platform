from pathlib import Path
import sqlite3
from typing import Optional, Dict, Any, List
import time


# DB estable en /financial_data_etl
from financial_data_etl.storage.paths import DB_PATH
# ==============================
# Connection
# ==============================

def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


# ==============================
# Schema
# ==============================

def init_tv_candles_schema() -> None:
    """
    Crea la tabla base de time series si no existe.
    """
    with _get_connection() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS tv_candles_raw (
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            ts INTEGER NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            is_partial INTEGER DEFAULT 0,
            ingested_at INTEGER NOT NULL,
            PRIMARY KEY (symbol, timeframe, ts)
        );
        """)

# ==============================
# Incremental state
# ==============================

def get_last_timestamp(symbol: str, timeframe: str) -> Optional[int]:
    """
    Devuelve el último timestamp completo (is_partial = 0).
    """
    with _get_connection() as conn:
        cur = conn.execute("""
            SELECT MAX(ts)
            FROM tv_candles_raw
            WHERE symbol = ?
              AND timeframe = ?
        """, (symbol, timeframe))

        row = cur.fetchone()
        return row[0] if row and row[0] is not None else None
        #AND is_partial = 0 -> esto veremos luego

# ==============================
# Persistence
# ==============================

def upsert_rows(rows: List[Dict[str, Any]], chunk_size: int = 9000) -> None:
    """
    Upsert batch multi-symbol con chunking interno.
    """
    if not rows:
        return

    now = int(time.time())

    def chunker(seq, size):
        for i in range(0, len(seq), size):
            yield seq[i:i + size]

    with _get_connection() as conn:
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

            conn.executemany("""
            INSERT INTO tv_candles_raw (
                symbol, timeframe, ts,
                open, high, low, close, volume,
                is_partial, ingested_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, timeframe, ts)
            DO UPDATE SET
                open=excluded.open,
                high=excluded.high,
                low=excluded.low,
                close=excluded.close,
                volume=excluded.volume,
                is_partial=excluded.is_partial,
                ingested_at=excluded.ingested_at;
            """, values)