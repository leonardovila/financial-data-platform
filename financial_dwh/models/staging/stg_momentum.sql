-- stg_momentum
-- Bronze → Silver para momentum_1d. RSI Wilder + SMA gaps + Donchian.
--
--   rsi_14            : 0..100
--   sma_N_gap         : (close - sma_N) / sma_N — fracción, no porcentaje
--   high_dist_1m/1y   : (close - donchian_high_N) / donchian_high_N
--                       (típicamente ≤ 0; 0 = nuevo máximo)

{{ config(materialized='view') }}

WITH source AS (
    SELECT
        symbol,
        date,
        ts,
        CAST(rsi_14       AS NUMERIC) AS rsi_14,
        CAST(sma_20_gap   AS NUMERIC) AS sma_20_gap,
        CAST(sma_50_gap   AS NUMERIC) AS sma_50_gap,
        CAST(sma_200_gap  AS NUMERIC) AS sma_200_gap,
        CAST(high_dist_1m AS NUMERIC) AS high_dist_1m,
        CAST(high_dist_1y AS NUMERIC) AS high_dist_1y
    FROM {{ source('bronze', 'raw_momentum') }}
)

SELECT * EXCEPT(rn) FROM (
    SELECT
        *,
        ROW_NUMBER() OVER (PARTITION BY symbol, date ORDER BY ts DESC) AS rn
    FROM source
)
WHERE rn = 1
