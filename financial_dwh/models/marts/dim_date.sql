-- dim_date
-- Dimensión calendario. Se materializa físicamente porque el front la
-- joinea contra los facts y queremos lookups O(1) por date_key.
--
-- date_key: surrogate INT64 con formato YYYYMMDD (natural surrogate, ordenable).
-- is_trading_day: heurística simple lun-vie. Para el alcance actual del DWH
-- alcanza; si después incorporamos calendario NYSE/holidays, se cambia
-- esta sola columna.

{{ config(materialized='table') }}

SELECT
    CAST(FORMAT_DATE('%Y%m%d', date) AS INT64) AS date_key,
    date,
    year,
    quarter,
    month,
    week_of_year,
    day_of_week,
    day_name,
    is_weekend,
    NOT is_weekend AS is_trading_day
FROM {{ ref('stg_dates') }}
