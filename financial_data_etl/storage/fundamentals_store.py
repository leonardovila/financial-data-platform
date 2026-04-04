from datetime import datetime
from typing import Dict, Any

from financial_data_etl.observability.run_context import RunContext
from financial_data_etl.storage.database import (
    transaction, execute, executemany, PH,
)


def _ensure_table_exists(conn) -> None:
    execute(conn, """
        CREATE TABLE IF NOT EXISTS fundamentals_snapshot (
            symbol TEXT NOT NULL,
            as_of_ts TEXT NOT NULL,
            company_name TEXT,
            market_cap DOUBLE PRECISION,
            pe_ttm DOUBLE PRECISION,
            eps_ttm DOUBLE PRECISION,
            shares_outstanding DOUBLE PRECISION,
            sector TEXT,
            industry TEXT,
            PRIMARY KEY (symbol, as_of_ts)
        );
    """)


def persist_fundamentals_snapshot(
    all_batch_data: Dict[str, Dict[str, Any]],
    ctx: RunContext,
) -> None:

    with transaction() as conn:
        _ensure_table_exists(conn)
        as_of_ts = datetime.now().isoformat()

        values_to_insert = []
        for symbol, payload in all_batch_data.items():
            fundamentals = payload.get("fundamentals")
            if not fundamentals:
                continue

            values_to_insert.append((
                symbol,
                as_of_ts,
                payload.get("company_name"),
                fundamentals.get("market_cap"),
                fundamentals.get("pe_ttm"),
                fundamentals.get("eps_ttm"),
                fundamentals.get("shares_outstanding"),
                fundamentals.get("sector"),
                fundamentals.get("industry"),
            ))

        if values_to_insert:
            executemany(conn, f"""
                INSERT INTO fundamentals_snapshot (
                    symbol, as_of_ts, company_name,
                    market_cap, pe_ttm, eps_ttm,
                    shares_outstanding, sector, industry
                ) VALUES ({PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH})
                ON CONFLICT(symbol, as_of_ts)
                DO UPDATE SET
                    company_name=EXCLUDED.company_name,
                    market_cap=EXCLUDED.market_cap,
                    pe_ttm=EXCLUDED.pe_ttm,
                    eps_ttm=EXCLUDED.eps_ttm,
                    shares_outstanding=EXCLUDED.shares_outstanding,
                    sector=EXCLUDED.sector,
                    industry=EXCLUDED.industry
            """, values_to_insert)

        ctx.event(
            "fundamentals_snapshot_summary",
            symbols_processed=len(all_batch_data),
            rows_inserted=len(values_to_insert),
        )
