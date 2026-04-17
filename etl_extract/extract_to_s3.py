"""
P2_04 — Extract: RDS → S3 (Parquet)
====================================
Lee las 5 tablas principales de RDS PostgreSQL, convierte a Parquet
columnar particionado por fecha, y los sube a S3.

Patrón: RDS (OLTP) → S3 landing zone → BigQuery (OLAP)

Variables de entorno requeridas:
  DATABASE_URL   : postgresql://user:pass@host:5432/dbname
  S3_BUCKET      : nombre del bucket destino (ej: leonardovila-financial-raw)
  AWS_REGION     : us-east-2
"""

import os
import io
import logging
from datetime import datetime, timezone

import pandas as pd
import boto3
from sqlalchemy import create_engine, text

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ─── Config ────────────────────────────────────────────────────────────────────

DATABASE_URL = os.environ["DATABASE_URL"]
S3_BUCKET    = os.environ.get("S3_BUCKET", "leonardovila-financial-raw")
AWS_REGION   = os.environ.get("AWS_REGION", "us-east-2")
RUN_DATE     = datetime.now(timezone.utc).strftime("%Y-%m-%d")

# ─── Queries ───────────────────────────────────────────────────────────────────
# ts es Unix epoch seconds (BIGINT). Lo convertimos a DATE para particionar.
# is_partial = 1 → vela incompleta (sesión abierta) → excluir del DWH.
# tv_candles_raw: filtramos timeframe '1D' → solo velas diarias para analytics.

EXTRACTS = {
    "tv_candles_raw": """
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

    "fundamentals_snapshot": """
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

    "volatility_1d": """
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

    "performance_1d": """
        SELECT
            symbol,
            to_timestamp(ts)::date          AS date,
            ts,
            ret_1d, ret_1w, ret_1m, ret_3m, ret_6m, ret_1y,
            computed_at
        FROM performance_1d
        WHERE is_partial = 0
    """,

    "momentum_1d": """
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


def upload_parquet(df: pd.DataFrame, s3_client, table_name: str):
    """
    Sube el DataFrame como Parquet a S3.
    Path: s3://<bucket>/<table>/<RUN_DATE>/data.parquet

    Particionado por fecha de ejecución (run date), no por fecha de cada fila.
    Esto permite cargas incrementales: cada run del ETL genera su propia partición.
    Para una carga inicial full, todas las filas van a la misma partición.
    """
    s3_key = f"{table_name}/run_date={RUN_DATE}/data.parquet"

    buffer = io.BytesIO()
    df.to_parquet(buffer, engine="pyarrow", index=False, compression="snappy")
    parquet_bytes = buffer.getvalue()  # capturar antes de seek — getvalue() siempre retorna el buffer completo
    size_mb = len(parquet_bytes) / (1024 * 1024)

    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=parquet_bytes,
        ContentType="application/octet-stream",
    )
    log.info(f"  → Uploaded s3://{S3_BUCKET}/{s3_key} ({size_mb:.2f} MB)")


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info(f"=== Extract RDS → S3 | run_date={RUN_DATE} ===")

    engine   = create_engine(DATABASE_URL)
    s3       = boto3.client("s3", region_name=AWS_REGION)

    results = {}
    for table_name, query in EXTRACTS.items():
        try:
            df = read_table(engine, table_name, query)
            if df.empty:
                log.warning(f"  {table_name}: EMPTY — skipping upload")
                results[table_name] = {"rows": 0, "status": "empty"}
                continue

            upload_parquet(df, s3, table_name)
            results[table_name] = {"rows": len(df), "status": "ok"}

        except Exception as e:
            log.error(f"  {table_name}: FAILED — {e}")
            results[table_name] = {"rows": 0, "status": f"error: {e}"}

    log.info("=== Summary ===")
    for table, r in results.items():
        status_icon = "✓" if r["status"] == "ok" else "✗"
        log.info(f"  {status_icon} {table}: {r['rows']:,} rows — {r['status']}")

    failed = [t for t, r in results.items() if r["status"] not in ("ok", "empty")]
    if failed:
        raise SystemExit(f"Extract failed for: {failed}")


if __name__ == "__main__":
    main()
