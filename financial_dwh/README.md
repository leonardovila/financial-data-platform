# financial_dwh — Data Warehouse

**Qué es esto en una frase:** un proyecto de DBT que toma los datos crudos
que ya están en BigQuery y los transforma en un *star schema* que el
front puede consultar para detectar anomalías de mercado en tiempo real.

Este README existe porque el pipeline tiene 17 archivos SQL y si no
entendés qué hace cada uno, no lo podés defender frente a Ian. Todo
lo de acá está en lenguaje llano, con ejemplos numéricos concretos.

---

## 1. El contexto en 30 segundos

Tenés datos de 48 símbolos (NVDA, IONQ, KO, BTC, etc.) cargados en
**BigQuery** (el data warehouse de Google) en una "capa bronze" —
o sea, copia literal de lo que sale de RDS. Son ~1.2 millones de filas.

Lo que querés hacer con eso:
1. **Normalizar** las métricas para poder comparar "cuán raro está NVDA
   hoy" con "cuán raro está IONQ hoy", aunque sean activos incompatibles.
2. **Rankear** los outliers del día: ¿cuáles son los 10 símbolos que
   están mostrando el comportamiento más anómalo AHORA MISMO?
3. **Servir** eso rápido desde el front, sin recomputar nada.

Para lograrlo usamos el patrón **medallion (bronze → silver → gold)**
con **DBT** como motor de transformaciones.

---

## 2. Qué es DBT (en lenguaje humano)

DBT es un framework que te deja escribir transformaciones de datos en
**SQL puro** pero con tres ventajas sobre SQL a pelo:

1. **Modularización**: cada transformación vive en un archivo `.sql`
   separado (un "model"). Podés referenciarlos entre sí con `{{ ref('foo') }}`
   y DBT arma el grafo de dependencias automáticamente.
2. **Materialización declarativa**: vos decís "este modelo es una vista"
   o "este modelo es una tabla" en un YAML. DBT genera el `CREATE VIEW` /
   `CREATE TABLE` correspondiente y lo re-ejecuta en orden.
3. **Tests**: podés declarar que una columna no puede ser NULL, o que
   una PK tiene que ser única, en un archivo YAML. DBT corre los tests
   después de materializar.

**En concreto:** vos escribís `SELECT ... FROM {{ ref('stg_tv_candles') }}`
y cuando hacés `dbt run`, DBT reemplaza eso por el nombre real de la
tabla/vista en BigQuery y ejecuta todo en el orden correcto.

---

## 3. El patrón medallion (bronze / silver / gold)

Es una convención de la industria (popularizada por Databricks) para
organizar un data warehouse en capas con responsabilidades distintas:

| Capa   | Dataset en BQ        | Responsabilidad                                    | Costo query |
|--------|----------------------|----------------------------------------------------|-------------|
| Bronze | `financial_raw`      | Copia literal de RDS, sin transformar              | Alto        |
| Silver | `financial_staging`  | Limpieza + **fábrica de señales normalizadas**     | Medio       |
| Gold   | `financial_marts`    | Star schema servido al front                       | Bajo        |

> **Regla de oro:** bronze NUNCA se consulta directo. El front NUNCA
> toca silver. Todo lo que el front ve es gold.

---

## 4. Estructura de carpetas en `financial_dwh/`

```
financial_dwh/
├── dbt_project.yml          # Config raíz de DBT
├── packages.yml             # Dependencias externas (dbt-utils)
├── macros/                  # Funciones SQL reutilizables
│   └── generate_schema_name.sql
└── models/                  # TODO el SQL de transformación vive acá
    ├── staging/             # Silver parte 1: limpieza
    ├── intermediate/        # Silver parte 2: fábrica de señales
    └── marts/               # Gold: star schema
```

### 4.1. `dbt_project.yml`

Config raíz. Las tres cosas que importan:

```yaml
models:
  financial_dwh:
    staging:      { +materialized: view,  +schema: staging }
    intermediate: { +materialized: view,  +schema: staging }
    marts:        { +materialized: table, +schema: marts  }
```

**Qué significa en la práctica:**
- Los modelos bajo `staging/` y `intermediate/` se crean en BQ como
  **vistas** (no ocupan storage; recalculan cuando alguien los consulta).
- Los modelos bajo `marts/` se crean como **tablas físicas**
  (ocupan storage pero el read es instantáneo).
- `+schema: staging` → van al dataset `financial_staging` en BQ.
- `+schema: marts` → van al dataset `financial_marts` en BQ.

**Defensa:** "¿Por qué vistas en el medio y tablas en gold?"
Porque las window functions sobre 300k filas son pesadas. Queremos
pagar ese cómputo **una vez por día** (cuando corre `dbt run`), no cada
vez que el front consulta. Las vistas del medio son "recetas" que se
ejecutan encadenadas; la tabla final es el producto horneado.

### 4.2. `packages.yml`

Declara que usamos la librería `dbt-utils` (una colección oficial de
macros y tests útiles). Después de `git pull` hay que correr `dbt deps`
para descargarla.

Ejemplo de lo que nos da: `dbt_utils.unique_combination_of_columns`
— un test que valida que la combinación `(symbol, date)` es única en
una tabla. Sin esa librería lo tendríamos que escribir a mano.

### 4.3. `macros/generate_schema_name.sql`

Un "macro" en DBT es una función SQL que podés reusar. Este macro
**anula el comportamiento default de DBT** respecto a cómo nombra los
datasets.

Sin él, cuando ponés `+schema: staging`, DBT crea el dataset como
`<tu_schema_default>_staging` (por ejemplo `financial_dwh_staging`).
Con el macro lo forzamos a llamarse `financial_staging` a secas —
nombres canónicos, sin prefijo redundante.

---

## 5. Capa STAGING (silver parte 1)

**Ubicación:** `models/staging/`
**Dataset destino:** `financial_staging`
**Materialización:** view

**Responsabilidad:** agarrar los datos crudos de bronze y dejarlos
prolijos. NADA de cálculos nuevos. Solo:
1. Cast de tipos (`NUMERIC` para precios, no `FLOAT64`).
2. Dedup defensivo por `(symbol, date)` por si el scraper metió duplicados.
3. Filtrar filas claramente inválidas (`close <= 0`).

### 5.1. `_sources.yml`

No es un modelo, es una declaración. Le dice a DBT:
> "Existen estas tablas en el dataset `financial_raw` (las llamamos
> colectivamente `bronze`). Cuando un modelo haga `{{ source('bronze', 'raw_tv_candles') }}`,
> reemplazalo por `financial-data-etl.financial_raw.raw_tv_candles`."

También declara tests básicos sobre las sources (ej. `symbol` no puede
ser NULL) y "freshness" (avisá si los datos bronze tienen más de 36h).

### 5.2. Los modelos `stg_*`

Todos tienen la misma estructura: leer de `{{ source('bronze', ...) }}`,
castear, dedupear, filtrar, devolver.

| Archivo | Fuente bronze | Qué devuelve (una fila por...) |
|---|---|---|
| `stg_tv_candles.sql`   | `raw_tv_candles`         | `(symbol, date)` con OHLCV |
| `stg_volatility.sql`   | `raw_volatility`         | `(symbol, date)` con vol_1w..vol_1y + range_intraday |
| `stg_performance.sql`  | `raw_performance`        | `(symbol, date)` con ret_1d..ret_1y |
| `stg_momentum.sql`     | `raw_momentum`           | `(symbol, date)` con rsi_14, sma_*_gap, high_dist_* |
| `stg_fundamentals.sql` | `raw_fundamentals`       | `(symbol, as_of_ts)` con market_cap, pe_ttm, etc. |
| `stg_assets.sql`       | `stg_fundamentals` + `stg_tv_candles` | Una fila por símbolo. Universo del DWH. Asigna `market_cap_tier` (mega/large/mid/small/micro/unknown). |
| `stg_dates.sql`        | (`GENERATE_DATE_ARRAY`)  | Una fila por día desde el primer `date` en candles hasta hoy. Date spine. |

**Ejemplo concreto de `stg_assets`:**

Bronze tiene varios snapshots de NVDA a lo largo del tiempo. El modelo
se queda con el más reciente y le asigna un tier según el market cap:

```
symbol  | company_name    | sector     | market_cap         | market_cap_tier
--------+-----------------+------------+--------------------+----------------
NVDA    | NVIDIA Corp     | Technology | 3,200,000,000,000  | mega
IONQ    | IonQ Inc        | Technology | 8,400,000,000      | mid
KO      | Coca-Cola       | Staples    | 280,000,000,000    | mega
HOOD    | Robinhood       | Financials | 35,000,000,000     | large
```

### 5.3. `_models.yml`

Tests + documentación de todos los `stg_*`. Ejemplo de una línea:

```yaml
- name: stg_momentum
  columns:
    - name: rsi_14
      tests:
        - dbt_utils.accepted_range: { min_value: 0, max_value: 100 }
```

Esto hace que `dbt test` falle si alguna fila tiene `rsi_14 = 150`
(imposible por definición: RSI vive entre 0 y 100). Detector de bugs
del runner que calcula el RSI en Python — si alguna vez sale roto,
DBT te avisa antes de que contamines silver/gold.

---

## 6. Capa INTERMEDIATE (silver parte 2 — **el cerebro**)

**Ubicación:** `models/intermediate/`
**Dataset destino:** `financial_staging` (mismo que staging)
**Materialización:** view

**Responsabilidad:** generar las **señales normalizadas** que hacen que
el DWH valga algo. Acá vive toda la matemática.

### 6.1. ¿Por qué normalizar? El ejemplo del RSI

Imaginate que el RSI de 4 símbolos hoy es:

| Asset | RSI hoy | Media RSI últimos 252d | σ RSI últimos 252d |
|---|---|---|---|
| NVDA | 78 | 58 | 12 |
| IONQ | 82 | 61 | 18 |
| KO   | 73 | 50 | 9  |
| SPY  | 55 | 52 | 5  |

**Pregunta naive:** ¿quién está más sobrecomprado hoy?
Respuesta naive: IONQ (RSI 82, el más alto).

**Pregunta correcta:** ¿quién está más **fuera de lo normal para sí mismo**?

Para cada uno calculamos `z_intra = (RSI_hoy - media) / σ`:

| Asset | z_intra_rsi_14 |
|---|---|
| NVDA | (78-58)/12 = **+1.67** |
| IONQ | (82-61)/18 = **+1.17** |
| KO   | (73-50)/9  = **+2.56** ← el más raro |
| SPY  | (55-52)/5  = +0.60 |

**KO es quien está más fuera de personaje**, aunque su RSI absoluto
sea el tercero más alto. Ese es el punto entero de silver: sacarle la
identidad a cada asset y dejar todo en la misma unidad (**desviaciones estándar**).

### 6.2. Los modelos `int_*`

#### `int_asset_daily.sql` — el "fact gordo"

Un `LEFT JOIN` de los 4 stg_* por `(symbol, date)`. Devuelve una fila
por asset-día con TODAS las métricas crudas juntas:

```
symbol | date       | open | close | vol_1m | ret_1d | rsi_14 | sma_50_gap | ...
-------+------------+------+-------+--------+--------+--------+------------+------
NVDA   | 2026-04-18 | 890  | 905   | 0.42   | 0.017  | 78     | 0.12       | ...
IONQ   | 2026-04-18 |  42  |  45   | 0.85   | 0.071  | 82     | 0.23       | ...
```

No computa nada nuevo — solo junta. Es el insumo único de las 3 capas
de z-scores siguientes.

#### `int_intra_asset_zscores.sql` — z-score vs uno mismo

Para cada métrica y cada símbolo, computa el z-score usando una
**ventana rodante de 252 días** (≈ 1 año de trading):

```sql
(rsi_14 - AVG(rsi_14) OVER w) / STDDEV(rsi_14) OVER w

WINDOW w AS (
    PARTITION BY symbol
    ORDER BY date
    ROWS BETWEEN 251 PRECEDING AND CURRENT ROW
)
```

Traducción: "agarrá los últimos 252 días de RSI de este símbolo,
sacá media y desvío, y decime cuántos σ está lejos el valor de hoy".

**Por qué 252 días y no 4 años:**
- Algunos símbolos solo tienen 4.7 años de historia (HOOD, PLTR).
  Ventanas más largas dejarían esos activos sin baseline al inicio.
- 252d captura el **régimen actual** de mercado. Una ventana de 4 años
  te contamina con 2008, COVID, etc., y te da un baseline "histórico"
  que no refleja las condiciones de trading de hoy.

El modelo aplica esto a 9 métricas:
`ret_1d`, `ret_1m`, `vol_1m`, `vol_3m`, `rsi_14`, `sma_50_gap`,
`sma_200_gap`, `range_intraday`, `high_dist_1y`.

Output: la misma grilla `(symbol, date)` pero con 9 columnas nuevas
tipo `z_intra_rsi_14`, `z_intra_vol_1m`, etc.

#### `int_cross_asset_zscores.sql` — z-score vs los pares HOY

Para cada día, z-scoreamos la métrica cruda contra **todos los símbolos
vivos ese día**:

```sql
(rsi_14 - AVG(rsi_14) OVER (PARTITION BY date)) / STDDEV(rsi_14) OVER (PARTITION BY date)
```

Traducción: "¿qué tan alto está el RSI de NVDA hoy **comparado con los
otros 47 símbolos hoy**?".

Es un snapshot diario. Útil cuando querés saber si un asset está
extremo en términos absolutos hoy, ignorando su historia.

#### `int_z_of_z.sql` — **anomalía dentro de anomalía**

Este es **el move conceptual** del DWH. En vez de z-scorear la métrica
cruda cross-section, z-scoreamos el `z_intra`:

```sql
(z_intra_rsi_14 - AVG(z_intra_rsi_14) OVER (PARTITION BY date))
    / STDDEV(z_intra_rsi_14) OVER (PARTITION BY date)
```

**¿Qué te dice este número?**

Ejemplo: supongamos que HOY todo el mercado está rompiendo récords de
RSI (régimen de euforia global):

| Asset | z_intra_rsi_14 | z_of_z_rsi_14 |
|---|---|---|
| NVDA | +1.67 | +0.8  |
| IONQ | +1.17 | -0.3  |
| KO   | +2.56 | **+3.1** |
| SPY  | +0.60 | -1.2  |

Todos tienen `z_intra` positivo (todos sobrecomprados vs su historia).
Pero **KO está sobrecomprado incluso para el régimen actual de sobrecompra**
(z_of_z +3.1 σ). Eso es **detector de outlier en régimen de outliers**.

Ninguna plataforma de retail (TradingView, Finviz, Yahoo) te muestra eso.
Es la razón por la que este DWH vale algo.

**Las 9 métricas se propagan a las 3 capas** → 27 señales nuevas por
`(symbol, date)`.

### 6.3. `_models.yml`

Tests sobre los `int_*`. Principalmente: `(symbol, date)` tiene que
ser única y no-null en todos los modelos.

---

## 7. Capa MARTS (gold — star schema)

**Ubicación:** `models/marts/`
**Dataset destino:** `financial_marts`
**Materialización:** table (física, con particionado + clustering)

**Responsabilidad:** servir los datos al front en un formato estándar
de BI — **star schema** (Kimball). Una tabla de hechos al medio,
dimensiones alrededor.

### 7.1. Qué es un star schema y por qué

Un star schema tiene dos tipos de tablas:
- **Dimensiones (`dim_*`)**: descripciones. Una fila por entidad del
  mundo real (un símbolo, un día). Cambian poco.
- **Hechos (`fact_*`)**: mediciones. Una fila por evento/observación
  (el precio de NVDA el 18/04/2026). Crecen con el tiempo.

Las `fact_*` tienen **surrogate keys** (INT64 generados por nosotros)
que apuntan a las dimensiones. Esto hace los JOINs baratos y las
tablas compactas.

**Por qué este patrón:** es el estándar de la industria desde los 90s
(Kimball's "Data Warehouse Toolkit"). Tableau, PowerBI, Superset,
Looker — todos esperan un star schema. Si tu DWH no tiene esto, no
es "corporate" y cualquier analyst lo nota en 30 segundos.

### 7.2. Los modelos `dim_*` y `fact_*`

#### `dim_date.sql`

Una fila por día desde 1994-06-13 hasta hoy.

| date_key | date       | year | quarter | month | week_of_year | day_name | is_weekend | is_trading_day |
|----------|------------|------|---------|-------|--------------|----------|------------|----------------|
| 20260418 | 2026-04-18 | 2026 | 2       | 4     | 16           | Saturday | true       | false          |
| 20260417 | 2026-04-17 | 2026 | 2       | 4     | 16           | Friday   | false      | true           |

`date_key` es un surrogate INT64 con formato `YYYYMMDD`. Ventaja:
es ordenable y debuggeable a ojo (`20260418 > 20260417`).

#### `dim_asset.sql`

Una fila por símbolo.

| asset_key | symbol | company_name | sector     | market_cap_tier | pe_ttm |
|-----------|--------|--------------|------------|-----------------|--------|
| 1         | AAPL   | Apple Inc    | Technology | mega            | 34.2   |
| 2         | AMZN   | Amazon       | Cons. Disc | mega            | 48.1   |
| 23        | NVDA   | NVIDIA       | Technology | mega            | 72.5   |
| 42        | IONQ   | IonQ         | Technology | mid             | NULL   |

`asset_key` sale de `DENSE_RANK() OVER (ORDER BY symbol)`. Es
determinístico entre re-runs (mientras el universo no cambie).

#### `fact_ohlcv.sql`

Una fila por `(asset_key, date_key)` con precios.

| date_key | asset_key | date       | symbol | open | high | low | close | volume |
|----------|-----------|------------|--------|------|------|-----|-------|--------|
| 20260418 | 23        | 2026-04-18 | NVDA   | 890  | 910  | 885 | 905   | 42M    |

**Particionado por `date` mensual + clusterizado por `asset_key`:**
cuando el front pide "dame NVDA último año", BQ escanea solo las 12
particiones del último año y dentro de cada una salta directo a los
bloques de `asset_key=23`. Factura centavos en vez de dólares.

#### `fact_derived_metrics.sql` — **la tabla estrella**

Una fila por `(asset_key, date_key)` con **28 columnas** de señales:
- 9 métricas crudas (vol_1m, ret_1d, rsi_14, ...)
- 9 z_intra (rolling 252d)
- 9 z_cross (snapshot diario)
- **9 z_of_z** (el detector de anomalía dentro de anomalía)

**Esta es la tabla que el front consulta.** Todas las capas de
silver se cosechan acá.

#### `fact_fundamentals.sql`

Fundamentals forward-filleados al date spine.

**Problema que resuelve:** bronze solo tiene snapshots de fundamentals
cada tantos días (el scraper los toma cuando puede). Si el front
pregunta "market_cap de NVDA el 15 de marzo" y ese día no hubo
snapshot, obtenés NULL.

**Solución SQL pura:**
1. `CROSS JOIN dim_asset × dim_date` → grid completo `(asset, date)`.
2. `LEFT JOIN snapshots` → las fechas sin snapshot quedan NULL.
3. `LAST_VALUE(... IGNORE NULLS) OVER (PARTITION BY symbol ORDER BY date)`
   → rellena cada NULL con el último valor conocido.

Después de esto: el front pregunta "market_cap de NVDA el 15/03" y
obtiene el último snapshot anterior a esa fecha. Siempre hay un valor.

### 7.3. `_models.yml`

Tests más estrictos que en las otras capas:
- PKs únicas (`dbt_utils.unique_combination_of_columns`).
- FKs válidas (`relationships` — cada `asset_key` en `fact_ohlcv`
  tiene que existir en `dim_asset`). Si el DWH rompe la integridad
  referencial, `dbt test` falla.

---

## 8. El pipeline end-to-end en un diagrama

```
          BRONZE (financial_raw)
          ┌──────────────────────────────────────────┐
          │ raw_tv_candles    raw_volatility         │
          │ raw_performance   raw_momentum           │
          │ raw_fundamentals                         │
          └────────────────────┬─────────────────────┘
                               │
                         [staging/]
                               │
          SILVER — parte 1 (limpieza, views)
          ┌────────────────────┼─────────────────────┐
          │ stg_tv_candles   stg_volatility          │
          │ stg_performance  stg_momentum            │
          │ stg_fundamentals stg_assets stg_dates    │
          └────────────────────┬─────────────────────┘
                               │
                       [intermediate/]
                               │
          SILVER — parte 2 (fábrica de señales, views)
          ┌────────────────────┼─────────────────────┐
          │ int_asset_daily  (join gordo)            │
          │       │                                  │
          │       ├─→ int_intra_asset_zscores  (252d)│
          │       └─→ int_cross_asset_zscores (diario)│
          │                    │                     │
          │                    └─→ int_z_of_z        │
          └────────────────────┬─────────────────────┘
                               │
                          [marts/]
                               │
          GOLD — star schema (tablas físicas, financial_marts)
          ┌────────────────────┼─────────────────────┐
          │ dim_date    ←──┐                         │
          │ dim_asset   ←──┤                         │
          │                ├──  fact_ohlcv           │
          │                ├──  fact_derived_metrics │
          │                └──  fact_fundamentals    │
          └──────────────────────────────────────────┘
                               │
                           (front)
```

---

## 9. Cómo correrlo

Desde `financial_dwh/`:

```bash
# Primera vez: descargar dbt-utils
dbt deps

# Compilar y materializar todo, en orden, respetando el DAG
dbt run

# O por capa si querés debuggear
dbt run --select staging+       # staging y todo lo que dependa
dbt run --select intermediate+
dbt run --select marts+

# Correr los tests declarados en los _models.yml
dbt test

# Generar la documentación interactiva (lineage diagram)
dbt docs generate
dbt docs serve
```

`dbt docs serve` levanta un server local que muestra:
- Cada modelo con su descripción
- El grafo de dependencias entre modelos
- Los tests que corren sobre cada uno
- El SQL generado final

**Esto es lo que le vas a mostrar a Ian**: el lineage diagram
es el entregable visual más contundente de un DWH.

---

## 10. Cómo consulta el front

El front solo toca `financial_marts`. Query ejemplo para "top 10
anomalías del día en RSI":

```sql
SELECT
    a.symbol,
    a.sector,
    a.market_cap_tier,
    f.rsi_14,
    f.z_intra_rsi_14,
    f.z_of_z_rsi_14
FROM `financial-data-etl.financial_marts.fact_derived_metrics` f
JOIN `financial-data-etl.financial_marts.dim_asset` a USING (asset_key)
WHERE f.date = CURRENT_DATE()
  AND ABS(f.z_of_z_rsi_14) > 2
ORDER BY ABS(f.z_of_z_rsi_14) DESC
LIMIT 10
```

Traducción: "de todos los símbolos hoy, dame los 10 que están más
de 2 σ fuera del régimen actual de anomalía en RSI, ordenados por
extremidad".

**Costo estimado:** < 10 MB escaneados gracias al particionado por
fecha. Centavos por query.

---

## 11. Defensa frente a preguntas típicas

**"¿Por qué silver hace tanto cómputo? ¿No tendría que ser solo dedup?"**
Porque si silver solo limpia, gold tiene que computar las 3 capas de
z-scores — y gold es donde el front lee. No queremos que una query del
front dispare window functions sobre 300k filas. Mejor pagar ese
cómputo una vez por día en `dbt run`.

**"¿Por qué rolling 252 días y no 4 años o all-time?"**
Historial heterogéneo: HOOD tiene 4.7 años, blue chips tienen 31.8.
Ventanas largas dejan a los símbolos jóvenes sin baseline. Además,
1 año = régimen actual; 4 años = contaminado con 2008, COVID.

**"¿Por qué el z_of_z se computa sobre el z_intra y no sobre la métrica cruda?"**
Porque `z_intra` ya es **unitless** (está en σ). Cuando z-scoreás
cross-section sobre unidades comparables, el ranking tiene sentido.
Si lo hacés sobre crudas, cruzás vol (~0.4) con RSI (~60) y el
resultado es ruido.

**"¿Por qué tablas físicas en gold y no vistas?"**
Vistas recalculan en cada query. El front hace muchas queries. Si la
query detrás de la vista son 3 window functions, el front paga el
cómputo cada vez. Tabla = pagás una vez, leés mil.

**"¿Qué pasa si mañana agregan un símbolo nuevo al universo?"**
`asset_key` es `DENSE_RANK(symbol)`. Si entra AAAA (antes de AAPL),
todos los keys corren +1. Los facts se regeneran enteros en cada
`dbt run` así que no hay inconsistencia, pero si el front cachea
keys, se rompe. Mitigación futura: migrar a `FARM_FINGERPRINT(symbol)`
(hash estable entre runs).

**"¿Por qué DBT y no SQL a pelo en BigQuery?"**
Tres razones: (1) lineage automático (DBT sabe qué depende de qué),
(2) tests declarativos (no hace falta orquestar scripts de validación),
(3) docs generadas (el lineage diagram de `dbt docs` es estándar de la
industria — cualquier data engineer lo entiende en 30 segundos).

---

## 12. Deuda técnica conocida

- `asset_key` via DENSE_RANK rompe si cambia el universo — migrar a
  `FARM_FINGERPRINT` cuando pase.
- `is_trading_day` es heurístico (lun-vie), ignora holidays NYSE.
  Suficiente para la demo; si después hace falta precisión, sumar
  calendario NYSE como seed.
- `exchange` en `dim_asset` es NULL (TradingView no lo expone).
- Los macros `z_intra / z_cross / z_of_z` están inline en los modelos
  (no en `macros/`). Elección consciente por legibilidad; migrar a
  `macros/z_score.sql` si crecen.
- `fact_fundamentals` genera ~384k filas (48 símbolos × 8000 trading days).
  Si el universo sube a SPX (500 símbolos), revisar si conviene SCD2 en
  vez de forward-fill.

---

## 13. Integración Gold → API → Frontend

El gold no vive en BigQuery solo: el front lo consume vía un endpoint
FastAPI que envuelve el cliente Python de BigQuery. Tres piezas:

### 13.1 Backend (`financial_data_etl/api/bq_analytics.py`)

Wrapper sobre `google.cloud.bigquery.Client` con tres funciones:

- `get_top_anomalies(metric, limit, min_abs_z)` — Top-N por |z_of_z|
  para la fecha más reciente de `fact_derived_metrics`. JOIN contra
  `dim_asset` para traer `company_name`, `sector`, `market_cap_tier`.
- `get_z_score_history(symbol, metric, days)` — Serie temporal de las
  3 capas de z-score para un (symbol, metric). Útil para gráficos.
- `get_universe_snapshot()` — Conteos cross-metric de outliers
  (|z_of_z|>2) en la última fecha + breakdown por sector.

Hardening:
- Cliente lazy + singleton (no falla en import si falta SA key).
- Whitelist `SUPPORTED_METRICS` para evitar SQL injection en nombres
  de columna (BQ no parametriza identificadores).
- Cache en memoria con TTL=300s. El gold cambia 1×/día; no hace falta
  pegarle a BQ por cada request.
- Parámetros numéricos vía `ScalarQueryParameter` (@min_abs_z, @lim).

### 13.2 Endpoints (`financial_data_etl/api/app.py`)

Tres endpoints REST montados sobre el FastAPI existente:

```
GET /analytics/anomalies?metric=rsi_14&limit=10&min_abs_z=1.0
GET /analytics/zscore-history/{symbol}?metric=rsi_14&days=252
GET /analytics/universe
```

Manejo de errores: `ValueError` (métrica no soportada) → HTTP 400,
cualquier otra excepción → HTTP 500 con detail loggeado.

### 13.3 Frontend

Tres piezas del lado del cliente (todas en `frontend/src/`):

- `components/AdvancedAnalytics.tsx` — Tabla densa con dropdown de métrica.
  8 columnas: `# | Símbolo | Sector | Tier | metric_value | z_intra | z_cross | z_of_z`.
  Color-coding por |z|: `>+2σ` neon green, `±1σ-2σ` yellow, `<-2σ` red.
- `components/RankingBoard.tsx` — Card visualmente cargada para mostrar el
  podio (3 filas) de outliers en una métrica + signo. Filtros `pos` / `neg`
  / `abs`. Tipografía grande para el #1 — pensado para "se come con los ojos".
- `layouts/AdvancedAnalyticsPage.tsx` — Vista a pantalla completa en
  `/financial/avanzadas`. Hero + grilla 3×3 de RankingBoards (sobrecomprados,
  sobrevendidos, vol anómala, rally/caída del mes, gap vs SMA200, cerca del
  máximo 1Y, rango intradía, vol 3M) + tabla densa abajo. Link de vuelta al
  dashboard inicial.

Routing: mini-router por `window.location.pathname` en `App.tsx` (no vale la
pena meter `react-router` para 2 rutas). Vite tiene `base: '/financial/'`,
así que el dashboard normal vive en `/financial/` y la vista pijuda en
`/financial/avanzadas`.

Entrada al show-off: en `Dashboard.tsx` hay un botón GRANDE de banner neon
(`Ver Analíticas Avanzadas → ENTRAR`) entre el bridge a `leonardovila.com`
y el `SymbolSearch`. Imposible no verlo.

Vite proxy (`vite.config.ts`) forwardea `/analytics/*` a `localhost:8000`,
así el front en dev no necesita CORS ni configuración de URL absoluta.

### 13.4 Run local end-to-end

```bash
# Terminal 1: backend
GOOGLE_APPLICATION_CREDENTIALS="gcp/bigquery-sa-key.json" \
  python -m uvicorn financial_data_etl.api.app:app --host 127.0.0.1 --port 8000

# Terminal 2: frontend
cd frontend && npm run dev
# → http://localhost:5173/financial/
```

Verificación que sirvió como visual proof (2026-04-16, métrica `rsi_14`):

| #  | Símbolo | Sector                | RSI    | z_intra | z_cross | z_of_z  |
|----|---------|-----------------------|--------|---------|---------|---------|
| 1  | AMZN    | Retail Trade          | 76.18  | +2.34σ  | +1.75σ  | +2.02σ  |
| 2  | JNJ     | Health Technology     | 39.62  | -1.73σ  | -1.37σ  | -1.98σ  |
| 3  | AVGO    | Electronic Technology | 77.36  | +1.87σ  | +1.85σ  | +1.57σ  |
| 4  | NOC     | Electronic Technology | 39.53  | -1.25σ  | -1.37σ  | -1.51σ  |
| 5  | XOM     | Energy Minerals       | 43.10  | -1.22σ  | -1.07σ  | -1.48σ  |

Lectura: AMZN sobrecomprado fuera de su rango histórico Y fuera del
rango cross-section del día — el detector lo rankea #1 con z_of_z=+2.02σ.
JNJ es la cara opuesta (sobrevendido raro).
