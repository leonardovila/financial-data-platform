-- stg_assets
-- Universo de símbolos, derivado del snapshot más reciente de fundamentals.
-- Fuente única de verdad para "qué assets existen en el DWH".
--
-- Bucket de market cap (Wall Street convención, en USD):
--   mega    : >= 200B
--   large   : 10B  → 200B
--   mid     : 2B   → 10B
--   small   : 300M → 2B
--   micro   : <  300M
--   unknown : sin market_cap (cripto sin float, símbolos nuevos)

{{ config(materialized='view') }}

WITH latest AS (
    SELECT
        symbol,
        company_name,
        sector,
        industry,
        market_cap,
        pe_ttm,
        eps_ttm,
        shares_outstanding,
        as_of_ts,
        ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY as_of_ts DESC) AS rn
    FROM {{ ref('stg_fundamentals') }}
),

distinct_in_candles AS (
    -- Aseguramos que no perdamos símbolos que están en candles pero
    -- (todavía) no tienen fundamentals. Quedan con sector NULL.
    SELECT DISTINCT symbol FROM {{ ref('stg_tv_candles') }}
)

SELECT
    c.symbol,
    l.company_name,
    l.sector,
    l.industry,
    l.market_cap,
    l.pe_ttm,
    l.eps_ttm,
    l.shares_outstanding,
    CASE
        WHEN l.market_cap IS NULL                            THEN 'unknown'
        WHEN l.market_cap >= 200000000000                    THEN 'mega'
        WHEN l.market_cap >= 10000000000                     THEN 'large'
        WHEN l.market_cap >= 2000000000                      THEN 'mid'
        WHEN l.market_cap >= 300000000                       THEN 'small'
        ELSE                                                       'micro'
    END AS market_cap_tier,
    -- Exchange no viene en bronze (TradingView no nos lo entrega como tal),
    -- placeholder consistente; si después lo hidratamos desde otra fuente,
    -- cambiamos esta sola línea.
    CAST(NULL AS STRING) AS exchange
FROM distinct_in_candles c
LEFT JOIN latest l
  ON c.symbol = l.symbol AND l.rn = 1
