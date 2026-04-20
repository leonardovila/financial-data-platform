-- int_intra_asset_zscores
-- Z-score rolling intra-asset: ¿qué tan rara es la métrica HOY vs la propia
-- historia reciente del símbolo?
--
--   z_intra(symbol, date, M) = (M_t - μ_252d_symbol) / σ_252d_symbol
--
-- Ventana: 252 días de trading ≈ 1 año. Captura régimen actual sin
-- contaminarse con eras pasadas (2008, COVID, etc).
--
-- Por qué z_intra es la métrica clave:
--   Una vez normalizado, el asset DEJA DE TENER IDENTIDAD. El número
--   "está 2σ fuera de lo normal" significa lo mismo para NVDA que para
--   IONQ que para KO. Eso permite el ranking cross-asset que hace
--   `int_cross_asset_zscores` y `int_z_of_z` después.
--
-- NULLIF en σ evita división por cero cuando el rolling window es plano
-- (por ejemplo, las primeras filas de cada símbolo donde no hay 252d todavía).
--
-- Macro local para no repetir la fórmula 9 veces:
{% macro z_intra(col) -%}
    SAFE_DIVIDE(
        {{ col }} - AVG({{ col }}) OVER w,
        NULLIF(STDDEV({{ col }}) OVER w, 0)
    )
{%- endmacro %}

{{ config(materialized='view') }}

SELECT
    symbol,
    date,

    -- Pasamos las crudas tal cual (las consume int_z_of_z y los marts)
    open, high, low, close, volume,
    range_intraday,
    vol_1w, vol_1m, vol_3m, vol_6m, vol_1y,
    ret_1d, ret_1w, ret_1m, ret_3m, ret_6m, ret_1y,
    rsi_14,
    sma_20_gap, sma_50_gap, sma_200_gap,
    high_dist_1m, high_dist_1y,

    -- Z-scores intra-asset (252d rolling)
    {{ z_intra('ret_1d')        }} AS z_intra_ret_1d,
    {{ z_intra('ret_1m')        }} AS z_intra_ret_1m,
    {{ z_intra('vol_1m')        }} AS z_intra_vol_1m,
    {{ z_intra('vol_3m')        }} AS z_intra_vol_3m,
    {{ z_intra('rsi_14')        }} AS z_intra_rsi_14,
    {{ z_intra('sma_50_gap')    }} AS z_intra_sma_50_gap,
    {{ z_intra('sma_200_gap')   }} AS z_intra_sma_200_gap,
    {{ z_intra('range_intraday')}} AS z_intra_range_intraday,
    {{ z_intra('high_dist_1y')  }} AS z_intra_high_dist_1y

FROM {{ ref('int_asset_daily') }}
WINDOW w AS (
    PARTITION BY symbol
    ORDER BY date
    ROWS BETWEEN 251 PRECEDING AND CURRENT ROW
)
