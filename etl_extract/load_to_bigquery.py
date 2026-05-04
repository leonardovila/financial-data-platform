"""
P2_04 (parte 2) — Load: RDS → BigQuery bronze tables
======================================================
Lee las mismas 5 tablas de RDS y las carga directamente en BigQuery
en el dataset financial_raw (capa bronze).

Separado de extract_to_s3.py para mantener responsabilidades claras:
  extract_to_s3.py  → archiva en S3 (landing zone inmutable)
  load_to_bigquery.py → carga en BQ para que DBT pueda transformar

Variables de entorno requeridas:
  DATABASE_URL                  : postgresql://...
  GOOGLE_APPLICATION_CREDENTIALS: /path/to/bigquery-sa-key.json
  GCP_PROJECT                   : financial-data-etl (default)
"""

import os
import logging
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import create_engine, text
from google.cloud import bigquery

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ─── Config ────────────────────────────────────────────────────────────────────

DATABASE_URL = os.environ["DATABASE_URL"]
GCP_PROJECT  = os.environ.get("GCP_PROJECT", "financial-data-etl")
BQ_DATASET   = "financial_raw"   # bronze layer
LOADED_AT    = datetime.now(timezone.utc).isoformat()

# ─── Queries (idénticas a extract_to_s3.py) ────────────────────────────────────

EXTRACTS = {
    "raw_tv_candles": """
        SELECT
            symbol,
            timeframe,
            to_timestamp(ts)::date          AS date,
            ts,
            open, high, low, close, volume,
            ingested_at
        FROM tv_candles_raw
        WHERE is_partial = 0
          AND timeframe = '1d'
    """,

    "raw_fundamentals": """
        SELECT
            symbol,
            as_of_ts,
            company_name,
            market_cap,
            pe_ttm,
            eps_ttm,
            shares_outstanding,
            sector,
            industry
        FROM fundamentals_snapshot
    """,

    "raw_volatility": """
        SELECT
            symbol,
            to_timestamp(ts)::date          AS date,
            ts,
            range_intraday,
            vol_1w, vol_1m, vol_3m, vol_6m, vol_1y,
            computed_at
        FROM volatility_1d
        WHERE is_partial = 0
    """,

    "raw_performance": """
        SELECT
            symbol,
            to_timestamp(ts)::date          AS date,
            ts,
            ret_1d, ret_1w, ret_1m, ret_3m, ret_6m, ret_1y,
            computed_at
        FROM performance_1d
        WHERE is_partial = 0
    """,

    "raw_momentum": """
        SELECT
            symbol,
            to_timestamp(ts)::date          AS date,
            ts,
            rsi_14,
            sma_20_gap, sma_50_gap, sma_200_gap,
            high_dist_1m, high_dist_1y
        FROM momentum_1d
        WHERE is_partial = 0
    """,
}

# ─── Helpers ───────────────────────────────────────────────────────────────────

CHUNK_SIZE = 200_000  # rows per pandas chunk; keeps peak RAM ~150 MB.


def stream_table_to_bq(engine, client: bigquery.Client, table_name: str, query: str) -> int:
    """
    Stream a RDS table into BigQuery in chunks. The first chunk uses
    WRITE_TRUNCATE (replaces the table); subsequent chunks WRITE_APPEND.
    Memory stays bounded by CHUNK_SIZE rather than scaling with row count.

    Returns the total row count uploaded.
    """
    table_id = f"{GCP_PROJECT}.{BQ_DATASET}.{table_name}"
    total_rows = 0
    chunk_idx = 0

    log.info(f"Streaming {table_name} from RDS -> {table_id} (chunksize={CHUNK_SIZE:,})")
    # stream_results=True habilita server-side cursor en psycopg2 — sin esto,
    # pd.read_sql(chunksize=...) trae TODAS las filas al cliente antes de
    # chunkear localmente, lo que voltea el container por OOM en tablas
    # grandes. Con stream_results=True el cursor queda abierto en el server
    # y se traen ~CHUNK_SIZE filas por iteración.
    with engine.connect().execution_options(stream_results=True) as conn:
        for chunk_df in pd.read_sql(text(query), conn, chunksize=CHUNK_SIZE):
            disposition = (
                bigquery.WriteDisposition.WRITE_TRUNCATE
                if chunk_idx == 0
                else bigquery.WriteDisposition.WRITE_APPEND
            )
            job_config = bigquery.LoadJobConfig(
                write_disposition=disposition,
                autodetect=True,
            )
            job = client.load_table_from_dataframe(chunk_df, table_id, job_config=job_config)
            job.result()
            total_rows += len(chunk_df)
            chunk_idx += 1
            log.info(f"  chunk {chunk_idx}: +{len(chunk_df):,} rows (total {total_rows:,})")

    if chunk_idx == 0:
        log.warning(f"  {table_name}: no rows returned from RDS — table left as-is")
        return 0

    table = client.get_table(table_id)
    log.info(f"  → {table.num_rows:,} rows in BigQuery ({table_id})")
    return total_rows


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info(f"=== Load RDS → BigQuery bronze | {LOADED_AT} ===")
    log.info(f"Target: {GCP_PROJECT}.{BQ_DATASET}")

    engine = create_engine(DATABASE_URL)
    bq     = bigquery.Client(project=GCP_PROJECT)

    results = {}
    for table_name, query in EXTRACTS.items():
        try:
            n = stream_table_to_bq(engine, bq, table_name, query)
            results[table_name] = f"ok ({n:,} rows)" if n else "empty"
        except Exception as e:
            log.error(f"  {table_name}: FAILED — {e}")
            results[table_name] = f"error: {e}"

    log.info("=== Summary ===")
    for table, status in results.items():
        icon = "✓" if status.startswith("ok") else "✗"
        log.info(f"  {icon} {table}: {status}")

    failed = [t for t, s in results.items() if s.startswith("error")]
    if failed:
        raise SystemExit(f"Load failed for: {failed}")


if __name__ == "__main__":
    main()
