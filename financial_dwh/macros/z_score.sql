-- Z-score helpers. Tres variantes según el tipo de window.
--
-- z_intra(col)  : sobre window declarada por el modelo (típicamente 252d
--                  rolling intra-symbol). El modelo define `WINDOW w AS (...)`
--                  y este macro se expande a `... OVER w`.
--
-- z_cross(col)  : igual, pero el modelo declara `WINDOW w AS (PARTITION BY date)`.
--
-- z_of_z(col)   : igual, pero usa una window con nombre `w_date` (semánticamente
--                  cross-section por fecha) para no chocar con otras windows
--                  que el modelo pudiera definir.
--
-- SAFE_DIVIDE + NULLIF en stddev evita división por cero cuando la ventana
-- es plana (ej. los primeros 251 días por símbolo).

{% macro z_intra(col) -%}
    SAFE_DIVIDE(
        {{ col }} - AVG({{ col }}) OVER w,
        NULLIF(STDDEV({{ col }}) OVER w, 0)
    )
{%- endmacro %}

{% macro z_cross(col) -%}
    SAFE_DIVIDE(
        {{ col }} - AVG({{ col }}) OVER w,
        NULLIF(STDDEV({{ col }}) OVER w, 0)
    )
{%- endmacro %}

{% macro z_of_z(col) -%}
    SAFE_DIVIDE(
        {{ col }} - AVG({{ col }}) OVER w_date,
        NULLIF(STDDEV({{ col }}) OVER w_date, 0)
    )
{%- endmacro %}
