# Apunte del Sistema — Financial Data ETL

Resumen de alto nivel de todas las piezas que componen la plataforma hoy.
Pensado para leer de corrido en 5-10 min y tener una foto completa.

---

## 1. Qué es

Una plataforma end-to-end que **captura datos de mercados financieros**,
los **procesa en tres capas (bronze / silver / gold)**, los **sirve por una
API** y los **visualiza en un dashboard web** con señales live y analíticas
avanzadas basadas en detección de anomalías (z-scores encadenados).

El universo actual cubre ~50 instrumentos (mega/large caps US + BTC) con
histórico diario desde 1992 — alrededor de 8.000 días de trading por símbolo.

Stack:
- Python 3.11 para ETL y API (FastAPI)
- React 19 + Vite + TypeScript + Tailwind para el front
- PostgreSQL (RDS) como storage OLTP caliente
- S3 (Parquet) como storage frío histórico
- BigQuery + DBT como motor analítico (medallion)
- AWS (ECS, Lambda, EventBridge, S3, RDS, CloudFront) como infra productiva

---

## 2. Capa de ingesta — ETL / Scraping

Código en `financial_data_etl/` + `etl_extract/`.

- **TradingView WebSocket scraper** (`scraping_pipeline/tv_websocket_connection/`):
  se conecta al WS público de TradingView y baja **candles OHLCV** a todas
  las resoluciones necesarias (1m, 1D, 1W, 1M) + **ticks live** para el
  streaming del front. Implementación propia de la spec del WS
  (handshake, subscripción, parsing de frames binarios y texto).

- **Fundamentals extractor** (`scraping_pipeline/fundamentals/`): scrapea
  ratios y snapshots fundamentales por símbolo (P/E, market cap, sector,
  etc.) contra fuentes públicas.

- **Universe resolver** (`universe/`): define qué símbolos trackeamos. Es un
  servicio con screener configurable (por tier de market cap, sector,
  exchange) — la fuente de verdad del "qué entra al pipeline".

- **Derived metrics** (`derived_metrics/`): calcula **momentum** (RSI,
  gaps vs SMAs), **performance** (retornos 1D/1W/1M/3M/6M/1Y) y
  **volatilidad** (anualizada 1M/3M/6M/1Y, rango intradía). Estas
  corren sobre los candles diarios ya almacenados.

- **Orquestación** (`main_runner.py`): entrypoint único que encadena
  scraping → persist RDS → compute derived → persist derived. Pensado para
  correr como job batch (lo dispara Lambda via EventBridge).

- **Bronze export** (`etl_extract/extract_to_s3.py` + `load_to_bigquery.py`):
  lee de RDS, escribe **Parquet particionado en S3** (snapshot histórico
  congelado) y después lo carga a BigQuery como capa bronze. Este es el
  puente RDS → lake analítico.

---

## 3. Capas de almacenamiento

Tres storages que cumplen funciones distintas — no es redundancia, cada uno
tiene su propósito.

### 3.1 PostgreSQL (AWS RDS) — OLTP caliente
Lo que mueve la app en tiempo real. Tablas principales: OHLCV por símbolo,
fundamentals, métricas derivadas diarias. Accedida por la API para servir
requests del front. Pensada para lecturas por clave (símbolo + fecha), no
para analítica pesada.

### 3.2 Amazon S3 (Parquet) — Bronze / archivo frío
Snapshots históricos en Parquet particionado por fecha. Sirve dos
propósitos: (a) respaldo point-in-time barato, (b) capa de hidratación de
BigQuery. No se lee desde la app.

### 3.3 BigQuery — Silver + Gold / motor analítico
Warehouse columnar serverless. Hospeda:
- `financial_raw` — capa bronze (copia fiel del RDS vía S3).
- `financial_staging` — silver (views que derivan señales, z-scores).
- `financial_marts` — gold (tablas físicas, star schema).

---

## 4. Capa analítica — DBT + Medallion

Código en `financial_dwh/`. Arquitectura de tres niveles; cada uno agrega
valor sobre el anterior.

### Bronze (`financial_raw`)
Réplica cruda del OLTP. Sin transformaciones. Su función es aislar el
warehouse del RDS productivo.

### Silver (`financial_staging`) — **Fábrica de señales**
No es sólo limpieza. Es donde se **normalizan las métricas** para que sean
comparables entre símbolos y días:

- **`z_intra`**: z-score rolling 252d por símbolo. Mide qué tan raro está
  el valor de hoy vs el último año de ESE símbolo. Remueve la identidad del
  asset — un RSI z_intra de +2σ significa lo mismo para NVDA que para KO.
- **`z_cross`**: z-score de corte transversal para cada fecha. Mide qué tan
  raro está el símbolo HOY vs el resto del universo HOY.
- **`z_of_z`**: z-score del z_intra contra la distribución de z_intras del
  universo del día. Captura **la rareza de la rareza** — detecta anomalías
  que siguen siendo anomalías incluso después de controlar por régimen del
  mercado.

Esto es la materia prima que permite que gold sea apenas una capa fina de
serving.

### Gold (`financial_marts`) — Star schema Kimball
Tablas físicas, fast reads:
- `dim_date`, `dim_asset` — dimensiones
- `fact_ohlcv` — precios diarios
- `fact_fundamentals` — fundamentales con forward-fill SQL
  (`LAST_VALUE IGNORE NULLS` sobre un date-spine)
- `fact_derived_metrics` — las métricas + sus tres capas de z-score listas
  para ser consumidas por el front sin cómputo

### Por qué DBT (y no SQL suelto)
Lineage automático, tests declarativos, docs generadas. Cualquier data
engineer lee la arquitectura en 30 segundos vía `dbt docs`.

---

## 5. API backend (FastAPI)

Código en `financial_data_etl/api/`.

**REST endpoints** (OLTP → RDS):
- `/symbols` — universo disponible
- `/ohlcv`, `/fundamentals` — series históricas por símbolo
- `/performance`, `/volatility`, `/volume` — métricas derivadas

**WebSocket** (`/ws`):
- Stream de ticks live desde TradingView re-ruteados al browser
- Un `live_session_manager` multiplexa múltiples clientes sobre una sola
  conexión upstream (evita abrir un WS por usuario)
- `live_compute` calcula métricas intra-sesión en tiempo real

**Analytics endpoints** (nuevos — OLAP → BigQuery):
- `/analytics/anomalies` — top-N outliers del día por métrica
- `/analytics/zscore-history/{symbol}` — historia temporal de las 3 capas
  de z-score para un símbolo
- `/analytics/universe` — snapshot agregado del universo (# outliers,
  breakdown por sector)

El cliente de BigQuery es lazy + singleton (la app bootea aunque falte la SA
key; sólo esos 3 endpoints responden 500 hasta que se aprovisione). Cache
en memoria con TTL de 5min — el gold cambia 1×/día, no vale la pena pegarle
a BQ en cada request.

---

## 6. Frontend (React 19 + Vite + TS + Tailwind)

Código en `frontend/`. Diseño brutalista: JetBrains Mono, paneles con
bordes, paleta neón sobre fondo oscuro.

### Dashboard principal (`/financial/`)
Vista del día-a-día centrada en un símbolo:
- **SymbolSearch** — selector de instrumento
- **FundamentalsBar** — snapshot de ratios clave arriba
- **Chart** — candlestick con lightweight-charts, overlay de SMAs
- **TickStack** — feed de ticks live entrando por WebSocket
- **MetricsGrid** — Performance / Volatility / Momentum en tabs
- **StatusBar** — estado de la conexión WS

Store global en **Zustand** (`wsStore.ts`): abre el WS al montar, recibe
seed data + ticks, y cada componente sólo se suscribe al slice que le
interesa (evita re-renders innecesarios).

### Analíticas Avanzadas (`/financial/avanzadas`)
Vista separada que consume la capa gold directo desde BigQuery.

- Hero con mini-glosario inline (z_intra / z_cross / z_of_z)
- **Grid 3×3 de RankingBoards** — cada card es un top-3 de outliers para
  una métrica + signo: sobrecomprados, sobrevendidos, volatilidad anómala,
  rally/caída del mes, gap vs SMA 200, cerca del máximo 1Y, rango intradía
  raro, volatilidad 3M
- **Tabla densa multi-métrica** abajo con selector libre, mostrando las
  tres capas de z-score por fila
- Tooltips explicativos en cada ranking (reusa el `InfoTooltip` del resto
  de la app)

El enrutado es ligero (mini-router por `window.location.pathname` en
`App.tsx`) — no se metió `react-router` para dos rutas.

---

## 7. Infraestructura AWS

Código IaC en `aws/` + `iac/` (scaffold GCP). Mezcla de JSON task
definitions y policies listas para `aws-cli apply`.

### Runtime
- **ECS** (`aws/ecs/`) — tres task definitions:
  - `api-task-definition.json`: la FastAPI servida detrás del ALB
  - `etl-task-definition.json`: el main_runner corriendo como job
  - `utility-task-definition.json`: ad-hoc (backfills, rebuilds)
  - Más `autoscaling-policy.json` para escalar API por CPU

### Scheduling
- **Lambda** (`aws/lambda/lambda-etl-trigger.py`) + **EventBridge**: dispara
  el ECS ETL task en horarios fijos (post-cierre de mercado US). Lambda es
  liviana, sólo hace `ecs.run_task`.

### Storage infra
- **RDS PostgreSQL** — OLTP, accedida vía Secrets Manager (credentials
  nunca en código)
- **S3** — bucket de bronze Parquet + bucket de logs
- **CloudFront** (`aws/cloudfront/`) — CDN para el front estático

### Seguridad / Auth
- IAM roles con policies mínimas por servicio
- Service Account de GCP (BigQuery reader) montado como secret en el ECS
  API task — nunca commiteada al repo (gitignoreada)
- Secrets de DB leídos vía `secrets-policy.json`

### CI/CD
- **GitHub Actions** (`aws/github-actions/`): pipelines para build/push de
  imágenes Docker y deploy a ECS

### Estado actual
La infra AWS está **parcialmente desplegada**: ECS + Lambda + S3 + RDS
operativos. Falta cerrar **ALB + SSL** para completar el switch del VPS a
AWS como prod. El VPS sigue siendo el entry point público hoy.

---

## 8. Observabilidad

- `financial_data_etl/observability/run_context.py` — contexto estructurado
  que acompaña a cada run del ETL (run_id, timestamps, contadores) y se
  loggea con keys consistentes
- Logs de ETL aterrizan en CloudWatch via el task definition
- DBT escribe logs locales (`financial_dwh/logs/`, gitignoreado) y sus
  `run_results.json` sirven para alertar sobre tests fallidos

Pendiente: métricas aplicativas (API latency, WS connection count)
publicadas a CloudWatch Metrics.

---

## 9. Flujo end-to-end en una oración

**TradingView WS → Python scraper → PostgreSQL RDS (+ derived metrics
calculadas y persistidas) → S3 Parquet bronze → BigQuery bronze → DBT
silver (3 capas de z-scores) → DBT gold (star schema) → FastAPI
(REST + WS + /analytics) → React (Dashboard live + Analíticas Avanzadas).**

---

## 10. Qué falla hoy si se corta algo

- **Scraper TV cae** → no hay ticks live, pero el front sigue mostrando
  históricos (degradación graceful)
- **RDS cae** → la app se cae. Es el SPOF crítico hoy
- **BigQuery cae** → la página de Analíticas Avanzadas falla, el dashboard
  principal sigue operativo (desacoplados por diseño)
- **Lambda de scheduling falla** → el ETL no corre esa noche, el día
  siguiente los derived metrics están stale. No afecta reads.

---

## 11. Deuda técnica y próximos pasos conocidos

- Cerrar ALB + SSL para migrar prod del VPS a AWS
- `asset_key` en gold usa `DENSE_RANK` — migrar a `FARM_FINGERPRINT` para
  keys estables cross-run
- `is_trading_day` heurístico (lun-vie) ignora holidays NYSE — sumar
  calendario NYSE como seed de DBT
- Métricas de observabilidad aplicativa (latencia, error rate) a
  CloudWatch
- Universo limitado a ~50 símbolos — la arquitectura escala a 500+ sin
  cambios, es decisión de producto cuándo abrir

---

## 12. Números gruesos

- Universo: ~50 instrumentos
- Historia OHLCV: ~8.000 días por símbolo (desde 1992)
- `fact_derived_metrics` en gold: ~305k filas (50 × 8k × densidad)
- `fact_fundamentals` en gold: ~384k filas (forward-fill sobre date spine)
- Latencia de tick live end-to-end: sub-segundo (TV WS → FastAPI → browser)
- Refresh del gold: 1×/día post-cierre US
- Cache de `/analytics/*`: TTL 5 min
