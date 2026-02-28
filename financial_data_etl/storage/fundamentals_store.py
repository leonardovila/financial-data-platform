from pathlib import Path
import sqlite3
from datetime import datetime
from typing import Dict, Any
from financial_data_etl.observability.run_context import RunContext
from financial_data_etl.storage.paths import DB_PATH

def _ensure_table_exists(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fundamentals_snapshot (
            symbol TEXT NOT NULL,
            as_of_ts TEXT NOT NULL,
            company_name TEXT,
            market_cap REAL,
            pe_ttm REAL,
            eps_ttm REAL,
            shares_outstanding REAL,
            sector TEXT,
            industry TEXT,
            PRIMARY KEY (symbol, as_of_ts)
        );
    """)
    conn.commit()


def persist_fundamentals_snapshot(
    all_batch_data: Dict[str, Dict[str, Any]],
    ctx: RunContext,
) -> None:

    conn = sqlite3.connect(DB_PATH)
    try:
        _ensure_table_exists(conn)

        as_of_ts = datetime.now().isoformat()

        rows_inserted = 0
        symbols_processed = 0

        for symbol, payload in all_batch_data.items():
            fundamentals = payload.get("fundamentals")
            if not fundamentals:
                continue

            conn.execute(
                """
                INSERT OR REPLACE INTO fundamentals_snapshot (
                    symbol,
                    as_of_ts,
                    company_name,
                    market_cap,
                    pe_ttm,
                    eps_ttm,
                    shares_outstanding,
                    sector,
                    industry
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    symbol,
                    as_of_ts,
                    payload.get("company_name"),   # ← NUEVO
                    fundamentals.get("market_cap"),
                    fundamentals.get("pe_ttm"),
                    fundamentals.get("eps_ttm"),
                    fundamentals.get("shares_outstanding"),
                    fundamentals.get("sector"),
                    fundamentals.get("industry"),
                ),
            )

            rows_inserted += 1
            symbols_processed += 1

        conn.commit()

        ctx.event(
            "fundamentals_snapshot_summary",
            symbols_processed=symbols_processed,
            rows_inserted=rows_inserted,
        )

    finally:
        conn.close()