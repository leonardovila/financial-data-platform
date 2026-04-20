-- stg_performance
-- Bronze → Silver para performance_1d. Trailing returns ya computados.
-- ret_1d = close_t / close_t-1 - 1 (NO log-return, lo verificamos en runner).

{{ config(materialized='view') }}

WITH source AS (
    SELECT
        symbol,
        date,
        ts,
        CAST(ret_1d AS NUMERIC) AS ret_1d,
        CAST(ret_1w AS NUMERIC) AS ret_1w,
        CAST(ret_1m AS NUMERIC) AS ret_1m,
        CAST(ret_3m AS NUMERIC) AS ret_3m,
        CAST(ret_6m AS NUMERIC) AS ret_6m,
        CAST(ret_1y AS NUMERIC) AS ret_1y
    FROM {{ source('bronze', 'raw_performance') }}
)

SELECT * EXCEPT(rn) FROM (
    SELECT
        *,
        ROW_NUMBER() OVER (PARTITION BY symbol, date ORDER BY ts DESC) AS rn
    FROM source
)
WHERE rn = 1
