-- fact_ohlcv
-- Fact table de barras diarias. Una fila por (asset_key, date_key).
-- Granularidad: día.
--
-- Particionado por date para que queries del front filtrando por rango
-- de fechas escaneen solo las particiones relevantes (cost saving en BQ).
-- Cluster por asset_key para agrupar las barras del mismo símbolo en el
-- mismo bloque (range scans rápidos).

-- NOTA: el dataset tiene default_partition_expiration_ms = 60d (legado del
-- proyecto en GCP free tier). La SA actual no tiene bigquery.datasets.update.
-- Sin partition_by la tabla NO sufre la expiration y conserva 1994 → hoy.
-- Cuando se eleven permisos: limpiar el default y re-introducir partition_by.
{{ config(materialized='table', cluster_by=['asset_key']) }}

SELECT
    d.date_key,
    a.asset_key,
    c.date,
    c.symbol,
    c.open,
    c.high,
    c.low,
    c.close,
    c.volume
FROM {{ ref('stg_tv_candles') }} c
INNER JOIN {{ ref('dim_asset') }} a ON c.symbol = a.symbol
INNER JOIN {{ ref('dim_date') }}  d ON c.date   = d.date
