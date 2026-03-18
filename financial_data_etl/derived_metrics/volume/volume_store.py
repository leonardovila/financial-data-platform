from financial_data_etl.storage.tv_candles_store import _get_connection

def init_volume_schema():
    with _get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS volume_1d (
                symbol TEXT NOT NULL,
                ts INTEGER NOT NULL,
                volume_usd REAL,
                vol_sma_20 REAL,
                vol_sma_50 REAL,
                vol_sma_100 REAL,
                vol_sma_200 REAL,
                vol_gap_20 REAL,
                vol_gap_50 REAL,
                vol_gap_100 REAL,
                vol_gap_200 REAL,
                is_partial INTEGER,
                PRIMARY KEY (symbol, ts)
            );
        """)
        conn.commit()

def get_last_volume_ts(symbol: str):
    with _get_connection() as conn:
        row = conn.execute(
            """
            SELECT MAX(ts)
            FROM volume_1d
            WHERE symbol=?
            """,
            (symbol,),
        ).fetchone()
        return row[0] if row and row[0] is not None else None

def upsert_volume_rows(rows: list[dict], conn=None):
    if not rows:
        return

    _conn = conn if conn is not None else _get_connection()
    _conn.executemany(
        """
        INSERT OR REPLACE INTO volume_1d (
            symbol, ts,
            volume_usd,
            vol_sma_20, vol_sma_50, vol_sma_100, vol_sma_200,
            vol_gap_20, vol_gap_50, vol_gap_100, vol_gap_200,
            is_partial
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                r["symbol"], r["ts"],
                r["volume_usd"],
                r["vol_sma_20"], r["vol_sma_50"], r["vol_sma_100"], r["vol_sma_200"],
                r["vol_gap_20"], r["vol_gap_50"], r["vol_gap_100"], r["vol_gap_200"],
                r["is_partial"],
            )
            for r in rows
        ]
    )
    if conn is None:
        _conn.commit()
        _conn.close()