from financial_data_etl.storage.database import (
    get_connection, transaction, execute, executemany, fetchone, PH,
)


def init_momentum_schema():
    with transaction() as conn:
        execute(conn, """
            CREATE TABLE IF NOT EXISTS momentum_1d (
                symbol TEXT NOT NULL,
                ts BIGINT NOT NULL,
                rsi_14 DOUBLE PRECISION,
                sma_20_gap DOUBLE PRECISION,
                sma_50_gap DOUBLE PRECISION,
                sma_200_gap DOUBLE PRECISION,
                high_dist_1m DOUBLE PRECISION,
                high_dist_1y DOUBLE PRECISION,
                is_partial INTEGER,
                PRIMARY KEY (symbol, ts)
            );
        """)


def get_last_momentum_ts(symbol: str):
    conn = get_connection()
    try:
        row = fetchone(conn, f"SELECT MAX(ts) FROM momentum_1d WHERE symbol={PH}", (symbol,))
        return row[0] if row and row[0] is not None else None
    finally:
        conn.close()


def upsert_momentum_rows(rows: list[dict], conn=None):
    if not rows:
        return

    _conn = conn if conn is not None else get_connection()
    executemany(_conn, f"""
        INSERT INTO momentum_1d (
            symbol, ts,
            rsi_14,
            sma_20_gap, sma_50_gap, sma_200_gap,
            high_dist_1m, high_dist_1y,
            is_partial
        ) VALUES ({PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH})
        ON CONFLICT(symbol, ts)
        DO UPDATE SET
            rsi_14=EXCLUDED.rsi_14,
            sma_20_gap=EXCLUDED.sma_20_gap,
            sma_50_gap=EXCLUDED.sma_50_gap,
            sma_200_gap=EXCLUDED.sma_200_gap,
            high_dist_1m=EXCLUDED.high_dist_1m,
            high_dist_1y=EXCLUDED.high_dist_1y,
            is_partial=EXCLUDED.is_partial
    """, [
        (
            r["symbol"], r["ts"],
            r["rsi_14"],
            r["sma_20_gap"], r["sma_50_gap"], r["sma_200_gap"],
            r["high_dist_1m"], r["high_dist_1y"],
            r["is_partial"],
        )
        for r in rows
    ])
    if conn is None:
        _conn.commit()
        _conn.close()
