-- fact_derived_metrics
-- LA fact table con la que el front detecta anomalías.
-- Una fila por (asset_key, date_key) con:
--   - Crudas (vol/perf/momentum, passthrough)
--   - z_intra (anomalía vs propia historia 252d)
--   - z_cross (rareza vs el universo HOY)
--   - z_of_z  (rareza de la anomalía vs la anomalía típica del día)
--
-- Materializada como tabla porque el cómputo es pesado (3 capas de window
-- functions sobre 305k+ filas) y el front la query-ea constantemente.
-- Particionado + clustering iguales a fact_ohlcv para queries simétricas.
--
-- Ejemplo de uso desde el front (detector de outliers del día):
--   SELECT a.symbol, f.z_of_z_rsi_14, f.z_intra_rsi_14, f.rsi_14
--   FROM fact_derived_metrics f
--   JOIN dim_asset a USING (asset_key)
--   WHERE f.date = CURRENT_DATE()
--     AND ABS(f.z_of_z_rsi_14) > 2
--   ORDER BY ABS(f.z_of_z_rsi_14) DESC
--   LIMIT 10

-- NOTA: ver fact_ohlcv.sql — particionado deshabilitado por
-- default_partition_expiration_ms del dataset y falta de permisos.
{{ config(materialized='table', cluster_by=['asset_key']) }}

SELECT
    d.date_key,
    a.asset_key,
    z.date,
    z.symbol,

    -- Crudas
    z.range_intraday,
    z.vol_1w, z.vol_1m, z.vol_3m, z.vol_6m, z.vol_1y,
    z.ret_1d, z.ret_1w, z.ret_1m, z.ret_3m, z.ret_6m, z.ret_1y,
    z.rsi_14,
    z.sma_20_gap, z.sma_50_gap, z.sma_200_gap,
    z.high_dist_1m, z.high_dist_1y,

    -- z_intra (vs propia historia 252d)
    z.z_intra_ret_1d,
    z.z_intra_ret_1m,
    z.z_intra_vol_1m,
    z.z_intra_vol_3m,
    z.z_intra_rsi_14,
    z.z_intra_sma_50_gap,
    z.z_intra_sma_200_gap,
    z.z_intra_range_intraday,
    z.z_intra_high_dist_1y,

    -- z_cross (vs universo HOY, sobre crudas)
    z.z_cross_ret_1d,
    z.z_cross_ret_1m,
    z.z_cross_vol_1m,
    z.z_cross_vol_3m,
    z.z_cross_rsi_14,
    z.z_cross_sma_50_gap,
    z.z_cross_sma_200_gap,
    z.z_cross_range_intraday,
    z.z_cross_high_dist_1y,

    -- z_of_z (anomalía dentro de anomalía)
    z.z_of_z_ret_1d,
    z.z_of_z_ret_1m,
    z.z_of_z_vol_1m,
    z.z_of_z_vol_3m,
    z.z_of_z_rsi_14,
    z.z_of_z_sma_50_gap,
    z.z_of_z_sma_200_gap,
    z.z_of_z_range_intraday,
    z.z_of_z_high_dist_1y

FROM {{ ref('int_z_of_z') }} z
INNER JOIN {{ ref('dim_asset') }} a ON z.symbol = a.symbol
INNER JOIN {{ ref('dim_date') }}  d ON z.date   = d.date
