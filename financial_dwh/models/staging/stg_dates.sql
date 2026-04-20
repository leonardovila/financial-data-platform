-- stg_dates
-- Date spine del DWH. Se genera desde la fecha mínima en stg_tv_candles
-- hasta hoy. Sirve como esqueleto para dim_date y para forward-filling de
-- fundamentals. No depende de sources externas.

{{ config(materialized='view') }}

WITH bounds AS (
    SELECT
        MIN(date) AS min_date,
        CURRENT_DATE() AS max_date
    FROM {{ ref('stg_tv_candles') }}
),

spine AS (
    SELECT day
    FROM bounds,
         UNNEST(GENERATE_DATE_ARRAY(min_date, max_date, INTERVAL 1 DAY)) AS day
)

SELECT
    day                                            AS date,
    EXTRACT(YEAR        FROM day)                  AS year,
    EXTRACT(QUARTER     FROM day)                  AS quarter,
    EXTRACT(MONTH       FROM day)                  AS month,
    EXTRACT(WEEK        FROM day)                  AS week_of_year,
    EXTRACT(DAYOFWEEK   FROM day)                  AS day_of_week,    -- 1=Sun .. 7=Sat
    FORMAT_DATE('%A',   day)                       AS day_name,
    EXTRACT(DAYOFWEEK   FROM day) IN (1, 7)        AS is_weekend
FROM spine
