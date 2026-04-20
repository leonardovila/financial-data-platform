-- Modelo trivial para validar que dbt se conecta a BigQuery y puede
-- materializar. Se borra una vez que silver real empiece a correr.
SELECT
    1 AS ok,
    CURRENT_TIMESTAMP() AS checked_at
