-- int_asset_daily
-- "Fact gordo" unificado: una fila por (symbol, date) con TODAS las métricas
-- crudas pegadas en horizontal. Es el insumo único de los z-scores.
--
-- Diseño:
--   - LEFT JOIN sobre stg_tv_candles (autoridad sobre qué (symbol, date) existen).
--     Si falta vol/perf/momentum para esa fila → NULL, que las window functions
--     de z-scores van a saltear naturalmente.
--   - No hay GROUP BY: confiamos en que stg_* ya están dedupeados a 1 fila
--     por (symbol, date).

{{ config(materialized='view') }}

WITH base AS (
    SELECT
        c.symbol,
        c.date,
        -- OHLCV
        c.open, c.high, c.low, c.close, c.volume,
        -- Volatility
        v.range_intraday,
        v.vol_1w, v.vol_1m, v.vol_3m, v.vol_6m, v.vol_1y,
        -- Performance
        p.ret_1d, p.ret_1w, p.ret_1m, p.ret_3m, p.ret_6m, p.ret_1y,
        -- Momentum
        m.rsi_14,
        m.sma_20_gap, m.sma_50_gap, m.sma_200_gap,
        m.high_dist_1m, m.high_dist_1y
    FROM {{ ref('stg_tv_candles') }} c
    LEFT JOIN {{ ref('stg_volatility') }}  v ON c.symbol = v.symbol AND c.date = v.date
    LEFT JOIN {{ ref('stg_performance') }} p ON c.symbol = p.symbol AND c.date = p.date
    LEFT JOIN {{ ref('stg_momentum') }}    m ON c.symbol = m.symbol AND c.date = m.date
)

SELECT * FROM base
