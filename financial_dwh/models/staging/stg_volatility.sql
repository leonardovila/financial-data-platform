-- stg_volatility
-- Bronze → Silver para volatility_1d. Cast + dedup. Las vol vienen ya
-- annualized desde el runner (rolling std de log-returns × √252), no hay
-- que recomputar nada. range_intraday = (high - low) / close en absoluto.

{{ config(materialized='view') }}

WITH source AS (
    SELECT
        symbol,
        date,
        ts,
        CAST(range_intraday AS NUMERIC) AS range_intraday,
        CAST(vol_1w  AS NUMERIC) AS vol_1w,
        CAST(vol_1m  AS NUMERIC) AS vol_1m,
        CAST(vol_3m  AS NUMERIC) AS vol_3m,
        CAST(vol_6m  AS NUMERIC) AS vol_6m,
        CAST(vol_1y  AS NUMERIC) AS vol_1y
    FROM {{ source('bronze', 'raw_volatility') }}
)

SELECT * EXCEPT(rn) FROM (
    SELECT
        *,
        ROW_NUMBER() OVER (PARTITION BY symbol, date ORDER BY ts DESC) AS rn
    FROM source
)
WHERE rn = 1
