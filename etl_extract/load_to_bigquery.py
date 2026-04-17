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

def read_table(engine, table_name: str, query: str) -> pd.DataFrame:
    log.info(f"Reading {table_name} from RDS...")
    with engine.connect() as conn:
        df = pd.read_sql(text(query), conn)
    log.info(f"  → {len(df):,} rows, {len(df.columns)} columns")
    return df


def load_to_bq(client: bigquery.Client, df: pd.DataFrame, table_name: str):
    """
    Carga el DataFrame a BigQuery con WRITE_TRUNCATE (reemplaza la tabla entera).
    Para cargas incrementales futuras se cambia a WRITE_APPEND.
    """
    table_id = f"{GCP_PROJECT}.{BQ_DATASET}.{table_name}"

    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        autodetect=True,   # infiere schema desde el DataFrame
    )

    log.info(f"Loading to {table_id}...")
    job = client.load_table_from_dataframe(df, table_id, job_config=job_config)
    job.result()  # espera a que termine

    table = client.get_table(table_id)
    log.info(f"  → {table.num_rows:,} rows in BigQuery ({table_id})")


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info(f"=== Load RDS → BigQuery bronze | {LOADED_AT} ===")
    log.info(f"Target: {GCP_PROJECT}.{BQ_DATASET}")

    engine = create_engine(DATABASE_URL)
    bq     = bigquery.Client(project=GCP_PROJECT)

    results = {}
    for table_name, query in EXTRACTS.items():
        try:
            df = read_table(engine, table_name, query)
            if df.empty:
                log.warning(f"  {table_name}: EMPTY — skipping")
                results[table_name] = "empty"
                continue

            load_to_bq(bq, df, table_name)
            results[table_name] = f"ok ({len(df):,} rows)"

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
