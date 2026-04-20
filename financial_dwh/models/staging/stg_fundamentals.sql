-- stg_fundamentals
-- Bronze → Silver para fundamentals_snapshot. Source es snapshot por símbolo
-- (430 rows ≈ 1 row × 48 simbolos × historial corto). Si llegan duplicados
-- por re-scraping, nos quedamos con el más reciente por as_of_ts.
--
-- IMPORTANTE: fundamentals NO van por (symbol, date) sino por (symbol, as_of_ts).
-- En fact_fundamentals los expandimos al date spine (forward fill) — eso vive
-- en intermediate/, no acá.

{{ config(materialized='view') }}

WITH source AS (
    SELECT
        symbol,
        as_of_ts,
        DATE(as_of_ts) AS as_of_date,
        company_name,
        sector,
        industry,
        CAST(market_cap         AS NUMERIC) AS market_cap,
        CAST(pe_ttm             AS NUMERIC) AS pe_ttm,
        CAST(eps_ttm            AS NUMERIC) AS eps_ttm,
        CAST(shares_outstanding AS NUMERIC) AS shares_outstanding
    FROM {{ source('bronze', 'raw_fundamentals') }}
)

SELECT * EXCEPT(rn) FROM (
    SELECT
        *,
        ROW_NUMBER() OVER (PARTITION BY symbol, as_of_ts ORDER BY as_of_ts DESC) AS rn
    FROM source
)
WHERE rn = 1
