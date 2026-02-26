# Observability – financial_data_etl 1.0

Infraestructura mínima de logging y métricas para ejecuciones diarias de financial_data_etl.

El objetivo no es hacer un framework enterprise.  
El objetivo es poder:

- Debuggear rápido  
- Medir tiempos por etapa  
- Dejar un rastro auditable  
- No afectar performance  

---

## Filosofía

financial_data_etl 1.0 corre todos los días.  
Si algo falla o se degrada, debemos saber:

- Dónde
- Cuándo
- Cuánto tardó

Nada más.

---

# Contrato obligatorio (reglas duras)

## 1. El `RunContext` nace en el entrypoint

- Se instancia en `main_runner`
- Se pasa explícitamente hacia abajo
- Nunca usar global ni singleton

```python
ctx = RunContext(run_name="financial_data_etl_main")
```

---

## 2. `finalize()` SIEMPRE se ejecuta

Debe estar dentro de un `finally:`.

Motivo:
- Cierra el file handle
- Escribe el `report.json`
- Garantiza consistencia del run

```python
finally:
    ctx.finalize(status=status)
```

Sin `finalize()`, el sistema queda en estado inconsistente.

---

## 3. `span()` solo para etapas grandes

Correcto:

- `universe_resolve`
- `ohlcv_pipeline`
- `derived_metrics`
- `sync_db_to_server`

Incorrecto:

- Por candle
- Por request individual
- Dentro de loops finos

Regla simple:

> Un span debe representar una etapa conceptual del pipeline.

---

# Naming Convention de stages

- Usar nombres estables
- snake_case
- Consistentes

Ejemplos válidos:

- `ohlcv_scrape`
- `ohlcv_store`
- `perf_compute`
- `vol_compute`
- `sync_db`

Evitar:
- Meter datos dinámicos en el nombre del stage  
  (Los datos van en `**data`, no en el nombre)

Correcto:

```python
with ctx.span("ohlcv_scrape", symbols=len(symbols)):
    ...
```

Incorrecto:

```python
with ctx.span(f"ohlcv_scrape_{symbol}"):
```

---

# Ejemplo oficial de entrypoint

Este patrón es obligatorio.

```python
ctx = RunContext(run_name="financial_data_etl_main")
status = "success"

try:

    with ctx.span("universe_resolve", assets=len(assets)):
        ...

    with ctx.span("ohlcv_pipeline"):
        ...

    with ctx.span("derived_metrics"):
        ...

    with ctx.span("sync_db_to_server", mode="dummy"):
        ...

except Exception as e:
    status = "error"
    ctx.stage_err("run", e)
    raise

finally:
    ctx.finalize(status=status)
```

---

# Console Output (Tiempo Real)

Por defecto, `RunContext` imprime en consola exactamente la misma línea JSON que escribe en el archivo `.jsonl`.

Esto está controlado por el parámetro `console`:

```python
ctx = RunContext(run_name="financial_data_etl_main", console=True)
```

- `console=True` → imprime cada evento en tiempo real.
- `console=False` → solo escribe en el archivo de logs.

Esto permite:

- Ver progreso durante la ejecución.
- Evitar sensación de “freeze”.
- Debuggear sin abrir manualmente el `.jsonl`.

---

# Nota sobre performance

El archivo de log:

- Se abre **una sola vez** al inicio del run.
- Se cierra en `finalize()`.

Cada evento:

- Se imprime (si `console=True`).
- Se escribe como una línea JSON en el `.jsonl`.

⚠ Importante:

- `span()` está pensado para etapas grandes.
- Logging por símbolo es aceptable.
- Logging por candle NO es aceptable.
- No usar `event()` dentro de loops finos.

El diseño está optimizado para:

- Logging estructurado.
- Debugging real-time.
- Escritura eficiente (sin abrir/cerrar archivo por evento).

---

# Output esperado

Cada ejecución genera:

- `logs/{run_id}_{run_name}.jsonl`
- `logs/{run_id}_{run_name}.report.json`

El `.jsonl` contiene eventos crudos.  
El `.report.json` contiene resumen estructurado del run.