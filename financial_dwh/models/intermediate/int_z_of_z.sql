-- int_z_of_z
-- EL move conceptual del DWH: anomalía dentro de anomalía.
--
-- Tomamos z_intra (rareza del asset vs su propia historia, ya unitless)
-- y la z-scoreamos contra el universo HOY:
--
--   z_of_z(symbol, date, M) = (z_intra_t - μ_universo(z_intra_t)) / σ_universo(z_intra_t)
--
-- Significado: "de todas las anomalías que está mostrando el universo
-- hoy en la métrica M, ¿qué tan extrema es la de este asset?"
--
-- Caso de uso: si TODO el mercado está sobrecomprado en RSI (regime
-- change global), TODOS van a tener z_intra_rsi_14 alto. z_of_z te dice
-- *quién está sobrecomprado incluso para el régimen actual de sobrecompra*.
-- Detección de outlier en régimen de outliers.
--
-- Es la columna que el front filtra para el ranking "los más raros del día":
--   SELECT symbol, z_of_z_rsi_14
--   FROM fact_derived_metrics
--   WHERE date = CURRENT_DATE() AND ABS(z_of_z_rsi_14) > 2
--   ORDER BY ABS(z_of_z_rsi_14) DESC

{% macro z_of_z(col) -%}
    SAFE_DIVIDE(
        {{ col }} - AVG({{ col }}) OVER w_date,
        NULLIF(STDDEV({{ col }}) OVER w_date, 0)
    )
{%- endmacro %}

{{ config(materialized='view') }}

SELECT
    i.symbol,
    i.date,

    -- Crudas (passthrough para que fact_derived_metrics no tenga que joinear más)
    i.open, i.high, i.low, i.close, i.volume,
    i.range_intraday,
    i.vol_1w, i.vol_1m, i.vol_3m, i.vol_6m, i.vol_1y,
    i.ret_1d, i.ret_1w, i.ret_1m, i.ret_3m, i.ret_6m, i.ret_1y,
    i.rsi_14,
    i.sma_20_gap, i.sma_50_gap, i.sma_200_gap,
    i.high_dist_1m, i.high_dist_1y,

    -- Z intra-asset (passthrough)
    i.z_intra_ret_1d,
    i.z_intra_ret_1m,
    i.z_intra_vol_1m,
    i.z_intra_vol_3m,
    i.z_intra_rsi_14,
    i.z_intra_sma_50_gap,
    i.z_intra_sma_200_gap,
    i.z_intra_range_intraday,
    i.z_intra_high_dist_1y,

    -- Z cross-asset (passthrough)
    c.z_cross_ret_1d,
    c.z_cross_ret_1m,
    c.z_cross_vol_1m,
    c.z_cross_vol_3m,
    c.z_cross_rsi_14,
    c.z_cross_sma_50_gap,
    c.z_cross_sma_200_gap,
    c.z_cross_range_intraday,
    c.z_cross_high_dist_1y,

    -- Z OF Z: z-score del z_intra contra el universo del día
    {{ z_of_z('i.z_intra_ret_1d')         }} AS z_of_z_ret_1d,
    {{ z_of_z('i.z_intra_ret_1m')         }} AS z_of_z_ret_1m,
    {{ z_of_z('i.z_intra_vol_1m')         }} AS z_of_z_vol_1m,
    {{ z_of_z('i.z_intra_vol_3m')         }} AS z_of_z_vol_3m,
    {{ z_of_z('i.z_intra_rsi_14')         }} AS z_of_z_rsi_14,
    {{ z_of_z('i.z_intra_sma_50_gap')     }} AS z_of_z_sma_50_gap,
    {{ z_of_z('i.z_intra_sma_200_gap')    }} AS z_of_z_sma_200_gap,
    {{ z_of_z('i.z_intra_range_intraday') }} AS z_of_z_range_intraday,
    {{ z_of_z('i.z_intra_high_dist_1y')   }} AS z_of_z_high_dist_1y

FROM {{ ref('int_intra_asset_zscores') }} i
LEFT JOIN {{ ref('int_cross_asset_zscores') }} c
  ON i.symbol = c.symbol AND i.date = c.date
WINDOW w_date AS (PARTITION BY i.date)
