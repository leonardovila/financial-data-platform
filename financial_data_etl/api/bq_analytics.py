"""
bq_analytics
============
Wrapper sobre BigQuery para servir las consultas de la "capa de analiticas
avanzadas" expuesta al front. Lee de los marts (financial_marts.*).

El cliente de BigQuery es lazy y singleton: se construye en el primer
acceso (asi el import de este modulo no falla si el SA key no esta presente
en algun entorno, ej. tests unitarios).

Cache en memoria con TTL: las analiticas son por dia, no necesitan
refresco sub-segundo. Default TTL = 5 min.
"""

from __future__ import annotations

import os
import time
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
GCP_PROJECT       = os.environ.get("GCP_PROJECT", "financial-data-etl")
BQ_MARTS_DATASET  = "financial_marts"
DEFAULT_CACHE_TTL = 300  # seconds

# Whitelist de metricas que el front puede pedir. Evita SQL injection en el
# WHERE/ORDER BY (los nombres de columna no se pueden parametrizar en BQ).
SUPPORTED_METRICS = {
    "ret_1d", "ret_1m",
    "vol_1m", "vol_3m",
    "rsi_14",
    "sma_50_gap", "sma_200_gap",
    "range_intraday",
    "high_dist_1y",
}

# ── Lazy client ───────────────────────────────────────────────────────────────
_client: Any = None


def _get_client():
    global _client
    if _client is None:
        import json
        from google.cloud import bigquery
        from google.oauth2 import service_account

        # Prefer in-memory credentials from env var (Secrets Manager injection
        # in ECS). Falls back to GOOGLE_APPLICATION_CREDENTIALS file path or
        # ADC if neither is present (local dev).
        sa_json_raw = os.environ.get("GCP_SA_KEY_JSON")
        if sa_json_raw:
            credentials = service_account.Credentials.from_service_account_info(
                json.loads(sa_json_raw)
            )
            _client = bigquery.Client(project=GCP_PROJECT, credentials=credentials)
        else:
            _client = bigquery.Client(project=GCP_PROJECT)
        logger.info("BigQuery client initialized for analytics (project=%s)", GCP_PROJECT)
    return _client


# ── Cache ─────────────────────────────────────────────────────────────────────
_cache: dict[str, tuple[float, Any]] = {}


def _cache_get(key: str, ttl: int = DEFAULT_CACHE_TTL):
    if key not in _cache:
        return None
    ts, value = _cache[key]
    if time.monotonic() - ts > ttl:
        return None
    return value


def _cache_set(key: str, value: Any):
    _cache[key] = (time.monotonic(), value)


# ── Queries ───────────────────────────────────────────────────────────────────
def _row_to_dict(row) -> dict:
    """Convierte un Row de BigQuery a dict serializable. Maneja Decimal y date."""
    from decimal import Decimal
    from datetime import date, datetime

    out = {}
    for k, v in dict(row).items():
        if isinstance(v, Decimal):
            out[k] = float(v)
        elif isinstance(v, (date, datetime)):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


def get_top_anomalies(metric: str, limit: int = 10, min_abs_z: float = 1.5) -> dict:
    """
    Top-N simbolos con z_of_z mas extremo para `metric` en la fecha mas
    reciente disponible en fact_derived_metrics.

    Returns:
        {
          "metric": "rsi_14",
          "as_of_date": "2026-04-16",
          "min_abs_z": 1.5,
          "rows": [
            {"symbol": "AMZN", "sector": "...", "rsi_14": 76.18,
             "z_intra_rsi_14": 2.34, "z_cross_rsi_14": 1.21, "z_of_z_rsi_14": 2.02},
            ...
          ]
        }
    """
    if metric not in SUPPORTED_METRICS:
        raise ValueError(f"Unsupported metric: {metric}. Allowed: {sorted(SUPPORTED_METRICS)}")

    cache_key = f"top_anomalies:{metric}:{limit}:{min_abs_z}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    client = _get_client()
    z_of_z_col   = f"z_of_z_{metric}"
    z_intra_col  = f"z_intra_{metric}"
    z_cross_col  = f"z_cross_{metric}"

    query = f"""
    WITH latest AS (
        SELECT MAX(date) AS d
        FROM `{GCP_PROJECT}.{BQ_MARTS_DATASET}.fact_derived_metrics`
        WHERE {z_of_z_col} IS NOT NULL
    )
    SELECT
        a.symbol,
        a.company_name,
        a.sector,
        a.market_cap_tier,
        f.date,
        f.{metric}        AS metric_value,
        f.{z_intra_col}   AS z_intra,
        f.{z_cross_col}   AS z_cross,
        f.{z_of_z_col}    AS z_of_z
    FROM `{GCP_PROJECT}.{BQ_MARTS_DATASET}.fact_derived_metrics` f
    JOIN `{GCP_PROJECT}.{BQ_MARTS_DATASET}.dim_asset` a USING (asset_key)
    WHERE f.date = (SELECT d FROM latest)
      AND ABS(f.{z_of_z_col}) >= @min_abs_z
    ORDER BY ABS(f.{z_of_z_col}) DESC
    LIMIT @lim
    """

    from google.cloud import bigquery as _bq
    job_config = _bq.QueryJobConfig(
        query_parameters=[
            _bq.ScalarQueryParameter("min_abs_z", "FLOAT64", float(min_abs_z)),
            _bq.ScalarQueryParameter("lim",       "INT64",   int(limit)),
        ]
    )
    rows = [_row_to_dict(r) for r in client.query(query, job_config=job_config).result()]
    as_of = rows[0]["date"] if rows else None

    payload = {
        "metric":     metric,
        "as_of_date": as_of,
        "min_abs_z":  min_abs_z,
        "limit":      limit,
        "rows":       rows,
    }
    _cache_set(cache_key, payload)
    return payload


def get_z_score_history(symbol: str, metric: str, days: int = 252) -> dict:
    """
    Serie temporal de las 3 capas de z-score para un (symbol, metric) en los
    ultimos `days` dias. Util para graficar la evolucion de la anomalia.
    """
    if metric not in SUPPORTED_METRICS:
        raise ValueError(f"Unsupported metric: {metric}")

    cache_key = f"z_history:{symbol.upper()}:{metric}:{days}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    client = _get_client()
    z_intra_col  = f"z_intra_{metric}"
    z_cross_col  = f"z_cross_{metric}"
    z_of_z_col   = f"z_of_z_{metric}"

    query = f"""
    SELECT
        f.date,
        f.{metric}       AS metric_value,
        f.{z_intra_col}  AS z_intra,
        f.{z_cross_col}  AS z_cross,
        f.{z_of_z_col}   AS z_of_z
    FROM `{GCP_PROJECT}.{BQ_MARTS_DATASET}.fact_derived_metrics` f
    JOIN `{GCP_PROJECT}.{BQ_MARTS_DATASET}.dim_asset` a USING (asset_key)
    WHERE a.symbol = @sym
    ORDER BY f.date DESC
    LIMIT @days
    """
    from google.cloud import bigquery as _bq
    job_config = _bq.QueryJobConfig(
        query_parameters=[
            _bq.ScalarQueryParameter("sym",  "STRING", symbol.upper()),
            _bq.ScalarQueryParameter("days", "INT64",  int(days)),
        ]
    )
    rows = [_row_to_dict(r) for r in client.query(query, job_config=job_config).result()]
    rows.reverse()  # ascending date

    payload = {
        "symbol": symbol.upper(),
        "metric": metric,
        "days":   days,
        "rows":   rows,
    }
    _cache_set(cache_key, payload)
    return payload


def get_universe_snapshot() -> dict:
    """
    Snapshot del universo en la ultima fecha: cuantos simbolos por sector,
    distribucion de market_cap_tier, conteo de outliers (|z_of_z|>2) por
    metrica. Util como header del dashboard.
    """
    cache_key = "universe_snapshot"
    cached = _cache_get(cache_key, ttl=600)
    if cached is not None:
        return cached

    client = _get_client()

    # Outlier counts cross-metric en la fecha mas reciente
    metric_cols = [f"COUNTIF(ABS(z_of_z_{m}) > 2) AS outliers_{m}" for m in sorted(SUPPORTED_METRICS)]
    metric_select = ",\n        ".join(metric_cols)

    query = f"""
    WITH latest AS (
        SELECT MAX(date) AS d FROM `{GCP_PROJECT}.{BQ_MARTS_DATASET}.fact_derived_metrics`
    ),
    snap AS (
        SELECT
            (SELECT d FROM latest) AS as_of_date,
            COUNT(DISTINCT symbol) AS n_symbols,
            {metric_select}
        FROM `{GCP_PROJECT}.{BQ_MARTS_DATASET}.fact_derived_metrics`
        WHERE date = (SELECT d FROM latest)
    )
    SELECT * FROM snap
    """
    row = next(iter(client.query(query).result()), None)
    snap = _row_to_dict(row) if row else {}

    # Sector breakdown
    sector_query = f"""
    SELECT sector, COUNT(*) AS n
    FROM `{GCP_PROJECT}.{BQ_MARTS_DATASET}.dim_asset`
    GROUP BY sector
    ORDER BY n DESC
    """
    sectors = [_row_to_dict(r) for r in client.query(sector_query).result()]

    payload = {**snap, "sectors": sectors}
    _cache_set(cache_key, payload)
    return payload
