# README-INGEST · Ingesta y cómputo del primer set de métricas en RDS

> Fuente de verdad de cómo funciona la ingesta y el cómputo de derivados
> sobre RDS PostgreSQL. **No incluye dbt / BigQuery / analíticas avanzadas**
> (eso es otra capa, posterior a este flujo).

---

## 1. Por qué este sprint existió

El scrape de TradingView corría dentro del task de ECS Fargate (`financial-data-etl`).
TradingView bloquea por IP reputation a los rangos de AWS, así que la mayoría
de los símbolos del catálogo fallaban: en el RDS había **~95 símbolos cargados de un
catálogo de 2000+**. El task estaba pagando cómputo y networking para que un
anti-bot le cerrara la conexión.

Aparte, `main_runner.py` mezclaba 5 responsabilidades en el mismo proceso:
plan incremental, scrape, parse, persistencia y derivados. Cualquier cambio era
peligroso y opaco para una entrevista.

**Decisión arquitectónica:** desacoplar el **scrape** del **procesamiento**.
- El **scrape** baja al **VPS** (Digital Ocean), que tiene IP residencial y
  TradingView no le pega.
- El **procesamiento** sigue en **ECS Fargate**, exactamente lo que ya hacía
  (parse → persist → derivados), pero ahora alimentado desde **S3** en
  lugar de desde el WS en vivo.
- La comunicación VPS ↔ cloud se da por **dos canales únicos**:
  1. **HTTPS** vía ALB → API en Fargate → endpoint `/internal/increment-plan`
     autenticado por bearer token. El VPS pide el plan (qué velas faltan
     por símbolo) y la API consulta el RDS por él.
  2. **S3 PutObject** vía credenciales IAM acotadas (sólo `PutObject` bajo
     `raw/tv/*`).
- **El RDS sigue 100% privado** — el VPS jamás abre conexión Postgres directa.

---

## 2. Diagrama del flujo

```
┌──────────────────────────────────────────────────────────────────────────┐
│                       VPS (Digital Ocean — IP residencial)               │
│                                                                          │
│ systemd timer (a futuro 21:00 UTC lun-vie)                               │
│   ├─ python -m financial_data_etl.vps_scraper.runner                     │
│   │                                                                      │
│   ├─ 1. lockfile (flock) anti-overlap                                    │
│   ├─ 2. lee catalog_seed.txt (746 tickers SPX+NDX+RUT deduplicados)      │
│   ├─ 3. valida contra catalog.json (provider_symbol tradingview)         │
│   ├─ 4. POST https://<alb>/internal/increment-plan                       │
│   │      Authorization: Bearer <token>                                   │
│   │      body: {"symbols": [...], "timeframe": "1d"}                     │
│   │      ─────────────────────────────────────────────┐                  │
│   │      ◄── {"plan": {"AAPL": 1, "RKLB": 8000, ...}} │                  │
│   │                                                   │                  │
│   ├─ 5. para cada chunk de 50 (sleep 50s entre chunks):                  │
│   │      run_tv_websocket_scraper(plan, raw_capture=…)                   │
│   │      el callback raw_capture acumula los chunks WS por símbolo       │
│   │      en memoria (no parsea — eso lo hace Fargate)                    │
│   │      sube data.jsonl.gz por símbolo a S3                             │
│   │                                                   │                  │
│   └─ 6. al terminar TODOS los chunks: sube _DONE_{date}.txt              │
└──────────────────────────────────────────────────────┼───────────────────┘
                                                       │ S3 PutObject
                                                       ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ S3: leonardovila-financial-raw                                           │
│   raw/tv/symbol={SYM}/ingestion_date=YYYY-MM-DD/data.jsonl.gz   ← x N    │
│   raw/tv/_DONE_{ingestion_date}.txt                              ← marker│
└──────────────────────────────────────────────────────┼───────────────────┘
                                                       │ S3 Event
                                                       │ filter: prefix=raw/tv/_DONE_
                                                       │         suffix=.txt
                                                       ▼
                                       ┌─────────────────────────┐
                                       │ Lambda s3-done-trigger  │
                                       │ parsea ingestion_date   │
                                       │ ecs.run_task con env:   │
                                       │   USE_VPS_RAW=true      │
                                       │   INGESTION_DATE=YYYY-… │
                                       └────────────┬────────────┘
                                                    │ ECS RunTask
                                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ ECS Fargate task: financial-data-etl (revision 5)                        │
│   python -m financial_data_etl.main_runner                               │
│     ── USE_VPS_RAW=true → fork hacia raw_s3_reader                       │
│     1️⃣ resolve_universe (sin scrape)                                     │
│     2️⃣ build_increment_plan (idempotencia defensiva en upsert)           │
│     3️⃣ read_raw_from_s3(bucket, prefix, ingestion_date) ◄── S3 GetObject│
│         lista raw/tv/symbol=*/ingestion_date={date}/data.jsonl.gz        │
│         por símbolo: gunzip + parse (parse_ohlcv + extract_fundamentals) │
│         devuelve {symbol: body} con el MISMO shape que el scraper        │
│     4️⃣ persist_ohlcv_base()             ──► RDS tv_candles_raw          │
│     5️⃣ persist_fundamentals_snapshot()  ──► RDS fundamentals_snapshot   │
│     6️⃣ run_price_performance_1d()       ──► RDS performance_1d          │
│        run_volatility_1d()                ──► RDS volatility_1d          │
│        run_momentum_1d()                  ──► RDS momentum_1d            │
└──────────────────────────────────────────────────────────────────────────┘
                                                    │
                                                    ▼
                                       ┌─────────────────────────┐
                                       │ RDS PostgreSQL          │
                                       │ (privada en VPC)        │
                                       └─────────────────────────┘
                                                    │
                                                    ▼
                                       Frontend → API → /symbols, /ohlcv,
                                                       /fundamentals,
                                                       /performance/1d/X,
                                                       /volatility/1d/X,
                                                       /momentum/1d/X
```

---

## 3. Catálogo

- Universo: unión de SPX (S&P 500) + NDX (Nasdaq 100) + top-200 RUT (Russell 2000).
- 746 tickers únicos tras deduplicar (overlap SPX↔NDX = 87, SPX↔RUT = 1, NDX↔RUT = 0).
- Archivo plano: `financial_data_etl/universe/storage/catalog_seed.txt` (un ticker por línea).
- Resolución de TradingView: `financial_data_etl/catalog.json` mapea `ticker → {provider_symbol: {tradingview: "EXCHANGE:TICKER"}}`. **Para llamar al WS de TradingView no basta con el ticker — hay que mandar `EXCHANGE:TICKER` (ej. `NASDAQ:AAPL`)**. El VPS valida cada ticker del seed contra el catalog antes de scrapear, y los que no tengan `provider_symbol.tradingview` se loggean como WARNING y se saltean.
- En este sprint se agregaron 4 tickers que faltaban (`CASY`, `COHR`, `LITE`, `VRT`).

---

## 4. Componentes nuevos (este sprint)

### 4.1 VPS scraper — `financial_data_etl/vps_scraper/`

Módulo Python instalado en el VPS junto con el resto del paquete.

| Archivo | Rol |
|---|---|
| `runner.py` | Entrypoint: `python -m financial_data_etl.vps_scraper.runner`. Orquesta lockfile → seed → validación → API → scrape chunked → marker. |
| `chunk_orchestrator.py` | Loop por chunks de 50 con sleep 50s. Inyecta el callback `raw_capture` al scraper, acumula chunks WS por símbolo en memoria, sube uno por símbolo a S3. |
| `api_client.py` | Cliente HTTP del endpoint `/internal/increment-plan`. |
| `s3_uploader.py` | `boto3.put_object` para los `data.jsonl.gz` y para el marker. |
| `lockfile.py` | `fcntl.flock` anti-overlap (no-op en Windows para tests locales). |
| `config.py` | Config desde env vars (`VPS_API_BASE_URL`, `VPS_API_TOKEN_FILE`, `VPS_S3_BUCKET`, `VPS_S3_PREFIX`, `VPS_CHUNK_SIZE`, `VPS_CHUNK_SLEEP_SECONDS`, etc.). |

### 4.2 Hook `raw_capture` en el WS scraper existente

Modificación mínima invasiva en `financial_data_etl/scraping_pipeline/tv_websocket_connection/call_execution/tradingview_ws.py::request_batch_multiplexed`:

- Nuevo parámetro opcional `raw_capture: Optional[Callable[[str, str], None]] = None`.
- Dentro del loop receive, antes del routing/parsing existente, si el callback está presente y el chunk se puede mapear a un símbolo conocido (vía `chart_route` o `quote_route`), se invoca `raw_capture(provider_symbol, raw_chunk_str)`.
- El callback se propaga por `tv_websocket_scraper.py` (3 funciones: `run_tv_websocket_scraper` → `_run_pool` → `_pool_worker` → `request_batch_multiplexed`).
- **Cuando el callback no se pasa (Fargate en modo legacy o en modo procesador) el comportamiento es 100% idéntico al original.**

### 4.3 Endpoint `/internal/increment-plan` en `app.py`

`POST https://<alb>/internal/increment-plan`

```http
Authorization: Bearer <token>
Content-Type: application/json

{"symbols": ["AAPL", "MSFT", ...], "timeframe": "1d"}
```

Respuesta:

```json
{"plan": {"AAPL": 1, "MSFT": 1, "RKLB": 8000, ...}}
```

- Auth bearer-token, token en `INTERNAL_API_TOKEN` (env, leído al boot del task desde Secrets Manager `financial-data/internal-api-token-4QMQ9b`).
- Llama internamente al mismo `build_increment_plan()` que ya usa el ETL (`financial_data_etl/storage/increment_planner.py`).
- Filtra los símbolos con `n=0` (ya están al día) — el VPS ni intenta scrapear esos.

### 4.4 Helper `read_raw_from_s3` — `financial_data_etl/storage/raw_s3_reader.py`

- Lista `s3://leonardovila-financial-raw/raw/tv/symbol=*/ingestion_date={date}/data.jsonl.gz`.
- Por símbolo: descarga, gunzip, parsea cada línea como un chunk JSON, reconstruye `body` con los **mismos parsers** del scraper (`parse_ohlcv`, `extract_fundamentals_from_quote_raw`).
- Devuelve un dict `{original_symbol: body}` con la **misma forma exacta** que devolvía `run_tv_websocket_scraper` antes. Por eso `persist_ohlcv_base`, `persist_fundamentals_snapshot` y los runners de derivados **no se tocaron**.

### 4.5 Fork `USE_VPS_RAW` en `main_runner.py`

```python
if _use_vps_raw():
    all_batch_data = read_raw_from_s3(bucket=..., ingestion_date=...)
else:
    all_batch_data = run_tv_websocket_scraper(plan=..., ...)
```

- Detrás de env var `USE_VPS_RAW=true/false` en la task definition.
- El default sigue siendo `false` → comportamiento histórico para rollback inmediato sin redeploy.
- La Lambda dispatcher inyecta `USE_VPS_RAW=true` + `INGESTION_DATE=YYYY-MM-DD` cuando se dispara por el marker.

### 4.6 Lambda `s3-done-trigger` — `aws/lambda/s3-done-trigger/`

- Trigger: S3 Event `s3:ObjectCreated:*` con filter `prefix=raw/tv/_DONE_`, `suffix=.txt`.
- Acción: llama `ecs.run_task` con override de `environment` para inyectar `USE_VPS_RAW=true` y `INGESTION_DATE` (parseado del filename del marker, regex `_DONE_(\d{4}-\d{2}-\d{2})\.txt$`).
- **Una sola task por día** porque el filter solo matchea el marker (los 746 archivos `data.jsonl.gz` no disparan nada).
- Permisos: `ecs:RunTask`, `iam:PassRole` (sobre `ecsTaskExecutionRole` y `financial-etl-task-role`), `logs:*`.

---

## 5. Infra AWS (cuenta `295933007543`, region `us-east-2`)

| Recurso | Identificador | Notas |
|---|---|---|
| Bucket S3 raw | `leonardovila-financial-raw` (existente) | Prefijo nuevo: `raw/tv/`. Conviven con los parquets viejos en `tv_candles_raw/`, `momentum_1d/`, etc. (load_to_bigquery de marzo). |
| S3 Event Notification | `vps-scrape-done-trigger` | Filter `prefix=raw/tv/_DONE_` + `suffix=.txt` → Lambda `s3-done-trigger`. |
| Lambda | `s3-done-trigger` | Python 3.11. Role `s3-done-trigger-role`. |
| IAM user (VPS) | `financial-data-vps-scraper` | Inline policy `write-raw-tv` (solo `s3:PutObject` y `s3:AbortMultipartUpload` sobre `raw/tv/*`). Access keys generadas y guardadas en `.secrets-out/vps-scraper-access-key.json` (chmod 600, NO commiteado). |
| IAM role (Fargate task) | `financial-etl-task-role` | Inline policies `read-s3-raw` (S3 `GetObject`+`ListBucket` sobre `raw/tv/*`) y `read-app-secrets` (`secretsmanager:GetSecretValue` sobre `financial-data/*`). |
| Secret | `financial-data/internal-api-token-4QMQ9b` | Bearer token del endpoint `/internal/*`. Inyectado al task como env `INTERNAL_API_TOKEN`. |
| Task definition (ETL) | `financial-data-etl:5` | `taskRoleArn` apuntando al nuevo role; secrets `DATABASE_URL` + `INTERNAL_API_TOKEN`. |
| Task definition (API) | `financial-data-api:N` (registrada esta iteración) | Agrega `INTERNAL_API_TOKEN` como secret para que el endpoint pueda autenticar. |
| EventBridge (cron viejo) | `financial-etl-daily` | **Sigue habilitado** durante esta iteración. Se deshabilita después de validar que el flujo VPS→S3→Fargate funciona end-to-end. |
| Lambda vieja | `etl-trigger` | Sigue activa, sin tocarla — es el rollback inmediato si algo se rompe. |

---

## 6. Cómo correr una ingesta MANUAL (primera vez de validación)

> **Importante:** la primera corrida es manual para confirmar que los nuevos
> assets entran al RDS y son visibles en el frontend. Después de validar, se
> habilita el cron del VPS y se deshabilita el cron viejo de EventBridge.

### Paso 1 — Pre-flight: confirmar que la API tiene el endpoint

Desde tu máquina (local), con el token del archivo `.secrets-out/internal-api-token.txt`:

```bash
TOKEN=$(cat .secrets-out/internal-api-token.txt)
curl -X POST \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"symbols":["AAPL","MSFT"],"timeframe":"1d"}' \
    http://financial-api-alb-1680587852.us-east-2.elb.amazonaws.com/internal/increment-plan
# Esperado: {"plan": {"AAPL": <int>, "MSFT": <int>}}
```

### Paso 2 — Conectarse al VPS y disparar el scrape

```bash
ssh <user>@<vps-ip>
cd /opt/financial-data-etl   # ruta donde está deployado el paquete
source .venv/bin/activate
systemctl start financial-vps-scraper.service   # one-shot del timer
journalctl -u financial-vps-scraper.service -f  # seguir logs
```

### Paso 3 — Verificar S3 y disparo del Fargate

```bash
# Archivos por símbolo
aws s3 ls s3://leonardovila-financial-raw/raw/tv/ --recursive | head
# Marker
aws s3 ls s3://leonardovila-financial-raw/raw/tv/_DONE_$(date -u +%F).txt
# Lambda invocada
aws logs tail /aws/lambda/s3-done-trigger --since 10m
# Task ECS arrancando
aws ecs list-tasks --cluster financial-data --desired-status RUNNING
aws logs tail /ecs/financial-data-etl --since 10m
```

### Paso 4 — Verificar RDS

```sql
-- Cantidad de símbolos cargados hoy
SELECT count(DISTINCT symbol)
FROM tv_candles_raw
WHERE ingested_at::date = CURRENT_DATE;
-- Esperado: ~742 (746 del seed - 4 sin provider_symbol antes del fix)

-- Derivados al día
SELECT count(*) FROM momentum_1d   WHERE date = CURRENT_DATE;
SELECT count(*) FROM volatility_1d WHERE date = CURRENT_DATE;
SELECT count(*) FROM performance_1d WHERE date = CURRENT_DATE;
```

### Paso 5 — Verificar frontend

Abrir `https://leonardovila.com` (o el subdominio del front), entrar al
listado de símbolos y confirmar que aparecen tickers nuevos (ej. tickers RUT
como `IONQ`, `RKLB`, `OKLO`, `WULF`, `MARA`).

### Paso 6 — Habilitar el cron del VPS y deshabilitar el cron viejo

Solo después de que el paso 4 y 5 pasen:

```bash
# En el VPS
sudo systemctl enable --now financial-vps-scraper.timer

# En tu máquina local
aws scheduler update-schedule --name financial-etl-daily --state DISABLED \
    --schedule-expression "cron(0 21 ? * MON-FRI *)" \
    --schedule-expression-timezone UTC \
    --target '{"Arn":"arn:aws:lambda:us-east-2:295933007543:function:etl-trigger","RoleArn":"arn:aws:iam::295933007543:role/EventBridgeSchedulerRole"}' \
    --flexible-time-window '{"Mode":"OFF"}'
```

---

## 7. Decisiones de diseño y por qué (chuleta para entrevista)

**P: ¿Por qué partir el sistema en VPS + cloud en vez de tenerlo todo en cloud?**
R: Por **IP reputation**. TradingView bloquea los rangos de IP de los datacenters. Antes de este sprint el RDS tenía 95 símbolos cargados sobre 2000 porque el WS desde Fargate fallaba la mayoría de las veces. Mover el scrape al VPS (IP residencial) sube la tasa de éxito a >95%.

**P: ¿Por qué el VPS no consulta directo al RDS?**
R: Para mantener el RDS aislado en la VPC privada. El VPS sólo se comunica con AWS por dos canales **bien acotados**:
1. HTTPS al ALB → API → endpoint autenticado por bearer.
2. S3 PutObject con un IAM user que sólo puede escribir bajo `raw/tv/*`.
Eso me da: una sola superficie expuesta (la API), control sobre qué consultas puede correr el VPS (sólo el endpoint expuesto) y rotación de credenciales independiente. Si el VPS es comprometido, no hay acceso al RDS, no hay acceso a otros buckets, no hay acceso a otros endpoints.

**P: ¿Por qué un marker `_DONE_` en S3 en lugar de cada `data.jsonl.gz` triggereando la Lambda?**
R: Porque el VPS escribe ~700 archivos por noche, uno por símbolo. Si la Lambda escuchara cada `data.jsonl.gz` se dispararían 700 tasks de Fargate (basura: cada una procesando 1 símbolo). Con el marker la Lambda se dispara **exactamente una vez** por noche y la task procesa todo el día de una sola pasada. Sin SQS, sin debounce, sin lock: el filter `suffix=_DONE_*.txt` ya garantiza el dedupe.

**P: ¿Para qué sirve el `increment_planner` si el upsert en RDS ya es idempotente?**
R: Para **eficiencia**, no para corrección. El upsert en `tv_candles_raw` está deduplicando por `(symbol, timeframe, ts)`, así que reescribir velas existentes es seguro pero inútil. El planner consulta `MAX(ts)` por símbolo y le dice al VPS exactamente cuántas velas pedirle a TradingView: 1 vela para los símbolos al día, 8000 (`BOOTSTRAP_BARS`) para los nuevos. Resultado: el `data.jsonl.gz` que sube el VPS es chico para los símbolos al día y grande sólo cuando hace falta bootstrap.

**P: ¿Por qué dejaste el cron viejo (`financial-etl-daily`) habilitado durante la iteración?**
R: Como rollback inmediato. Si el flujo nuevo falla la primera noche, podemos seguir corriendo el viejo (que tiene baja tasa de éxito pero algo entrega). Una vez validado, se deshabilita.

**P: ¿Por qué el VPS captura el chunk WS crudo y no lo parsea localmente?**
R: Porque el VPS solo entrega RAW. Los parsers (`parse_ohlcv`, `extract_fundamentals_from_quote_raw`) viven en Fargate y son los **mismos** que el scraper original usa internamente. Si los duplicara en el VPS tendría que mantenerlos sincronizados manualmente. Con el callback `raw_capture` el VPS guarda el chunk JSON tal cual lo emitió TradingView (1 línea de JSONL por chunk) y Fargate corre los parsers reales.

**P: ¿Por qué `JSONL.gz` y no Parquet?**
R: Porque la regla operativa es "el VPS solo entrega RAW". Parquet implica tipar columnas, descartar campos que no entendés, fijar un schema. Eso es transformación. JSONL es exactamente lo que vino del WS, comprimido.

**P: ¿Y el cleanup del raw en S3?**
R: Por ahora lifecycle pendiente. La cantidad de raw es chica (con `increment_planner` la mayoría son archivos de 1 vela, ~5KB), así que no quema espacio. A futuro, lifecycle de 3-7 días para limpieza automática y dejar safety net por si hay que reprocesar tras fix de un parser bug.

---

## 8. Archivos relevantes (referencia rápida)

```
financial_data_etl/
├── vps_scraper/                                    ← NUEVO (corre en VPS)
│   ├── runner.py
│   ├── chunk_orchestrator.py
│   ├── api_client.py
│   ├── s3_uploader.py
│   ├── lockfile.py
│   └── config.py
├── storage/
│   └── raw_s3_reader.py                            ← NUEVO (corre en Fargate)
├── api/app.py                                       ← endpoint /internal/increment-plan
├── main_runner.py                                   ← fork USE_VPS_RAW
├── catalog.json                                     ← +4 tickers (CASY, COHR, LITE, VRT)
├── universe/storage/catalog_seed.txt                ← NUEVO (746 tickers)
└── scraping_pipeline/tv_websocket_connection/
    ├── call_execution/tradingview_ws.py             ← +callback raw_capture
    └── tv_websocket_scraper.py                      ← propaga callback

aws/
├── lambda/s3-done-trigger/                          ← NUEVO
│   ├── lambda_function.py
│   ├── trust-policy.json
│   └── policy.json
├── iam/                                             ← NUEVO
│   ├── vps-scraper-policy.json
│   ├── financial-etl-task-trust-policy.json
│   ├── financial-etl-task-role-policy.json
│   └── financial-etl-task-role-secrets-policy.json
├── s3/raw-bucket-notification.json                  ← NUEVO
└── ecs/etl-task-definition.json                     ← +taskRoleArn +INTERNAL_API_TOKEN

pyproject.toml                                       ← +boto3
```

---

## 9. Hotfixes que aparecieron en el primer run real (post-deploy)

Documentados acá para que entren en la chuleta de la entrevista — son los típicos "lo que NO está en el plan" que un revisor pregunta.

### 9.1 `WebSocketException 1009 — message too big`
- **Síntoma:** todos los batches del primer chunk caían inmediatamente con el cierre 1009.
- **Causa raíz:** la librería `websockets` de Python tiene `max_size=1MB` por default. Pedimos 4500 velas × 5 símbolos por batch + multiplexed quote frames → la respuesta de TradingView pasa fácil 1MB. TV cierra la conexión, el batch se reencola, vuelve a fallar, todos los símbolos van a `failures`.
- **Fix:** `max_size=50 * 1024 * 1024` en `websockets.connect()` dentro de `connect_to_tradingview` ([tradingview_ws.py](financial_data_etl/scraping_pipeline/tv_websocket_connection/call_execution/tradingview_ws.py)). 50 MB da margen para `SYMBOLS_PER_BATCH` hasta ~20 incluso en bootstrap.
- **Lección:** los defaults de las librerías son conservadores. Cuando un componente "anda bien en pruebas chicas pero falla en producción", el primer sospechoso son los límites de tamaño del transporte.

### 9.2 `BOOTSTRAP_BARS = 8000` (más que las 4500 del seed del front)
- **Síntoma:** durante el primer run los símbolos en bootstrap recibían ~8000 velas, pero el front solo sirve 4500.
- **Causa raíz:** `increment_planner.BOOTSTRAP_BARS` quedó en 8000 desde antes del sprint. Sobre-ingestaba.
- **Fix:** `BOOTSTRAP_BARS = 4500` ([increment_planner.py](financial_data_etl/storage/increment_planner.py)). Match exacto con `live_seed.load_historical_seed`.
- **Lección:** mantener consistentes las constantes de "cuánto historico cargar" entre planner / store / front evita escribir velas que nadie va a leer.

---

## 10. Validación técnica (qué tiene que pasar para considerarlo OK)

| # | Check | Cómo verificar | Esperado |
|---|---|---|---|
| 1 | Endpoint `/internal/increment-plan` autentica y devuelve plan | curl con bearer token | `{"plan": {...}}` con tamaño > 0 |
| 2 | VPS scrapea sin que TradingView lo bloquee | `journalctl -u financial-vps-scraper.service` | tasa de éxito > 95% |
| 3 | Archivos en S3 con shape correcto | `aws s3 ls s3://.../raw/tv/symbol=AAPL/...` | un `data.jsonl.gz` por símbolo |
| 4 | Marker dispara la Lambda | `aws logs tail /aws/lambda/s3-done-trigger` | log "Marker received... launching ECS RunTask" |
| 5 | Lambda lanza UNA task ECS | `aws ecs list-tasks --cluster financial-data` | exactamente 1 task corriendo |
| 6 | Task lee S3 y persiste a RDS | `aws logs tail /ecs/financial-data-etl` | spans `read_raw_from_s3` + `ohlcv_persist` + `derived_metrics` |
| 7 | RDS tiene los 742 símbolos del día | query SQL del paso 4 de la sección 6 | `count distinct symbol ≈ 742` |
| 8 | Frontend muestra los nuevos símbolos | https://leonardovila.com → listado | tickers RUT visibles |
