-- fact_fundamentals
-- Fact slowly-changing de fundamentals. Bronze los trae como snapshots
-- esporádicos (as_of_ts), nosotros los expandimos al date spine vía
-- forward-fill: cada (asset, date) hereda los fundamentals más recientes
-- conocidos en ese punto.
--
-- Esto es lo que hace que el join contra fact_ohlcv en gold sea trivial:
-- siempre tenés market_cap / pe_ttm para cualquier (asset, date) histórico,
-- aunque el snapshot original sea de hace 30 días.
--
-- Implementación SQL pura:
--   1. CROSS JOIN dim_asset × dim_date (filtrado a trading days desde
--      la primera aparición del símbolo en candles).
--   2. LEFT JOIN al snapshot.
--   3. LAST_VALUE(... IGNORE NULLS) sobre window ascendente para forward-fill.

-- NOTA: ver fact_ohlcv.sql — particionado deshabilitado por
-- default_partition_expiration_ms del dataset y falta de permisos.
{{ config(materialized='table', cluster_by=['asset_key']) }}

WITH first_date_per_symbol AS (
    SELECT symbol, MIN(date) AS first_date
    FROM {{ ref('stg_tv_candles') }}
    GROUP BY symbol
),

asset_date_grid AS (
    SELECT
        a.asset_key,
        a.symbol,
        d.date_key,
        d.date
    FROM {{ ref('dim_asset') }} a
    JOIN first_date_per_symbol f ON a.symbol = f.symbol
    JOIN {{ ref('dim_date') }}  d ON d.date >= f.first_date
                                 AND d.date <= CURRENT_DATE()
                                 AND d.is_trading_day
),

snapshots AS (
    SELECT
        symbol,
        as_of_date,
        market_cap,
        pe_ttm,
        eps_ttm,
        shares_outstanding
    FROM {{ ref('stg_fundamentals') }}
),

joined AS (
    SELECT
        g.asset_key,
        g.symbol,
        g.date_key,
        g.date,
        s.market_cap,
        s.pe_ttm,
        s.eps_ttm,
        s.shares_outstanding
    FROM asset_date_grid g
    LEFT JOIN snapshots s
      ON g.symbol = s.symbol AND g.date = s.as_of_date
)

SELECT
    date_key,
    asset_key,
    date,
    symbol,
    LAST_VALUE(market_cap         IGNORE NULLS) OVER w AS market_cap,
    LAST_VALUE(pe_ttm             IGNORE NULLS) OVER w AS pe_ttm,
    LAST_VALUE(eps_ttm            IGNORE NULLS) OVER w AS eps_ttm,
    LAST_VALUE(shares_outstanding IGNORE NULLS) OVER w AS shares_outstanding
FROM joined
WINDOW w AS (
    PARTITION BY symbol
    ORDER BY date
    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
)
