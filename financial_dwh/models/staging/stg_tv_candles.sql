-- stg_tv_candles
-- Bronze → Silver staging for daily OHLCV bars.
-- Responsabilities (the only ones that staging owns):
--   1. Cast tipos a NUMERIC (BigQuery decimal preciso, no FLOAT64).
--   2. Dedup defensivo: si bronze tuviera duplicados (symbol, date) por race
--      condition del scraper, nos quedamos con la fila más nueva por ts.
--   3. Filtrar OHLCV inválido (close <= 0, volume < 0) — cualquier métrica
--      derivada se rompe si dejamos pasar basura.
--
-- NO se computan metrics acá. Eso vive en intermediate/.

{{ config(materialized='view') }}

WITH source AS (
    SELECT
        symbol,
        date,
        ts,
        CAST(open   AS NUMERIC) AS open,
        CAST(high   AS NUMERIC) AS high,
        CAST(low    AS NUMERIC) AS low,
        CAST(close  AS NUMERIC) AS close,
        CAST(volume AS NUMERIC) AS volume
    FROM {{ source('bronze', 'raw_tv_candles') }}
    WHERE close > 0
      AND volume >= 0
),

deduped AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY symbol, date
            ORDER BY ts DESC
        ) AS rn
    FROM source
)

SELECT
    symbol,
    date,
    ts,
    open,
    high,
    low,
    close,
    volume
FROM deduped
WHERE rn = 1
