from financial_data_etl.storage.database import (
    get_connection, transaction, execute, executemany, fetchone, PH,
)


def init_volume_schema():
    with transaction() as conn:
        execute(conn, """
            CREATE TABLE IF NOT EXISTS volume_1d (
                symbol TEXT NOT NULL,
                ts BIGINT NOT NULL,
                volume_usd DOUBLE PRECISION,
                vol_sma_20 DOUBLE PRECISION,
                vol_sma_50 DOUBLE PRECISION,
                vol_sma_100 DOUBLE PRECISION,
                vol_sma_200 DOUBLE PRECISION,
                vol_gap_20 DOUBLE PRECISION,
                vol_gap_50 DOUBLE PRECISION,
                vol_gap_100 DOUBLE PRECISION,
                vol_gap_200 DOUBLE PRECISION,
                is_partial INTEGER,
                PRIMARY KEY (symbol, ts)
            );
        """)


def get_last_volume_ts(symbol: str):
    conn = get_connection()
    try:
        row = fetchone(conn, f"SELECT MAX(ts) FROM volume_1d WHERE symbol={PH}", (symbol,))
        return row[0] if row and row[0] is not None else None
    finally:
        conn.close()


def upsert_volume_rows(rows: list[dict], conn=None):
    if not rows:
        return

    _conn = conn if conn is not None else get_connection()
    executemany(_conn, f"""
        INSERT INTO volume_1d (
            symbol, ts, volume_usd,
            vol_sma_20, vol_sma_50, vol_sma_100, vol_sma_200,
            vol_gap_20, vol_gap_50, vol_gap_100, vol_gap_200,
            is_partial
        ) VALUES ({PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH})
        ON CONFLICT(symbol, ts)
        DO UPDATE SET
            volume_usd=EXCLUDED.volume_usd,
            vol_sma_20=EXCLUDED.vol_sma_20,
            vol_sma_50=EXCLUDED.vol_sma_50,
            vol_sma_100=EXCLUDED.vol_sma_100,
            vol_sma_200=EXCLUDED.vol_sma_200,
            vol_gap_20=EXCLUDED.vol_gap_20,
            vol_gap_50=EXCLUDED.vol_gap_50,
            vol_gap_100=EXCLUDED.vol_gap_100,
            vol_gap_200=EXCLUDED.vol_gap_200,
            is_partial=EXCLUDED.is_partial
    """, [
        (
            r["symbol"], r["ts"], r["volume_usd"],
            r["vol_sma_20"], r["vol_sma_50"], r["vol_sma_100"], r["vol_sma_200"],
            r["vol_gap_20"], r["vol_gap_50"], r["vol_gap_100"], r["vol_gap_200"],
            r["is_partial"],
        )
        for r in rows
    ])
    if conn is None:
        _conn.commit()
        _conn.close()
