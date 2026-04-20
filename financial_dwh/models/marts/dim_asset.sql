-- dim_asset
-- Dimensión de activos. Una fila por símbolo.
--
-- asset_key: surrogate INT64 deterministico (DENSE_RANK sobre symbol).
-- Es estable entre re-runs porque DENSE_RANK alfabético es determinista.
-- Si en el futuro entran símbolos nuevos pueden cambiar los keys; cuando
-- pase, se migra a una hash surrogate (FARM_FINGERPRINT) o a un seed estable.
--
-- Para el alcance actual (48 símbolos, demo Ian) alcanza con dense rank.

{{ config(materialized='table') }}

SELECT
    DENSE_RANK() OVER (ORDER BY symbol) AS asset_key,
    symbol,
    company_name,
    sector,
    industry,
    exchange,
    market_cap,
    market_cap_tier,
    pe_ttm,
    eps_ttm,
    shares_outstanding
FROM {{ ref('stg_assets') }}
