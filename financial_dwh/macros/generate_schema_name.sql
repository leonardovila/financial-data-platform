-- Override el default de DBT para que +schema: foo vaya al dataset "foo"
-- directo, no al dataset "<default>_foo" (que es el comportamiento estándar).
-- Esto nos permite usar nombres de datasets canónicos (financial_staging,
-- financial_marts) sin prefijos redundantes.
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        financial_{{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
