-- int_cross_asset_zscores
-- Z-score cross-section: ¿qué tan raro es este asset HOY vs sus pares HOY?
--
--   z_cross(symbol, date, M) = (M_t - μ_universo_t) / σ_universo_t
--
-- Snapshot diario, NO rolling. Toma todos los símbolos vivos en `date`
-- y computa la distribución de la métrica cruda en ese instante.
--
-- Útil para: "NVDA está cara HOY vs el resto del universo HOY" — sin
-- importar la historia de cada uno.
--
-- Importante: usamos las MÉTRICAS CRUDAS, no las z_intra. Para cruzar
-- z_intra vs el universo existe int_z_of_z (segundo orden).

{% macro z_cross(col) -%}
    SAFE_DIVIDE(
        {{ col }} - AVG({{ col }}) OVER w,
        NULLIF(STDDEV({{ col }}) OVER w, 0)
    )
{%- endmacro %}

{{ config(materialized='view') }}

SELECT
    symbol,
    date,

    -- Z-scores cross-section sobre crudas
    {{ z_cross('ret_1d')        }} AS z_cross_ret_1d,
    {{ z_cross('ret_1m')        }} AS z_cross_ret_1m,
    {{ z_cross('vol_1m')        }} AS z_cross_vol_1m,
    {{ z_cross('vol_3m')        }} AS z_cross_vol_3m,
    {{ z_cross('rsi_14')        }} AS z_cross_rsi_14,
    {{ z_cross('sma_50_gap')    }} AS z_cross_sma_50_gap,
    {{ z_cross('sma_200_gap')   }} AS z_cross_sma_200_gap,
    {{ z_cross('range_intraday')}} AS z_cross_range_intraday,
    {{ z_cross('high_dist_1y')  }} AS z_cross_high_dist_1y

FROM {{ ref('int_asset_daily') }}
WINDOW w AS (PARTITION BY date)
