# README-INGEST · Pipeline de ingesta y cómputo de derivados sobre RDS

Documentación técnica del flujo de scrape → S3 → procesamiento → RDS.
**Fuera de scope:** dbt, BigQuery, analíticas avanzadas (capa posterior).

---

## 1. Arquitectura

```
┌──────────────────────────────────────────────────────────────────────────┐
│                  VPS Digital Ocean (forge-api-nyc)                        │
│                  IP residencial — TradingView no la bloquea               │
│                                                                           │
│  systemd timer (Mon..Fri 21:00 UTC)                                       │
│      │                                                                    │
│      ▼                                                                    │
│  python -m financial_data_etl.vps_scraper.runner                          │
│      │                                                                    │
│      │ 1. flock /var/run/financial-vps-scraper.lock (anti-overlap)        │
│      │ 2. lee universe/storage/catalog_seed.txt (747 tickers)             │
│      │ 3. valida cada ticker contra catalog.json (provider_symbol.tradingview)│
│      │ 4. POST /internal/increment-plan ───────────┐                      │
│      │     Authorization: Bearer <token>            │                      │
│      │     body: {"symbols":[...], "timeframe":"1d"}│                      │
│      │     ◄── {"plan": {"AAPL": 1, "RKLB": 4500}} │                      │
│      │ 5. for chunk in chunks(plan, size=50):     │                      │
│      │       run_tv_websocket_scraper(chunk_plan, raw_capture=cb)         │
│      │       cb acumula los WS chunks por símbolo en memoria              │
│      │       sube data.jsonl.gz por símbolo a S3                          │
│      │       sleep 50s                                                    │
│      │ 6. al terminar todos los chunks:                                   │
│      │       sube _DONE_{ingestion_date}.txt                              │
└──────┼─────────────────────────────────────────────┼──────────────────────┘
       │                                             │ HTTPS
       │ S3 PutObject                                ▼
       ▼                                  ┌──────────────────────┐
┌──────────────────────────────────────┐  │ ALB                  │
│ S3 leonardovila-financial-raw        │  │  └─► API ECS Fargate │
│ raw/tv/symbol={SYM}/                 │  │       financial-data-api │
│   ingestion_date=YYYY-MM-DD/         │  │       (FastAPI)      │
│   data.jsonl.gz              × 747   │  │       /internal/     │
│ raw/tv/_DONE_YYYY-MM-DD.txt          │  │       increment-plan │
└──────────────────────────────────────┘  └──────────┬───────────┘
       │                                             │ build_increment_plan()
       │ S3 Event                                    ▼
       │ filter: prefix=raw/tv/_DONE_                ┌──────────────┐
       │         suffix=.txt                         │ RDS Postgres │◄─┐
       ▼                                             │ (VPC privada)│  │
┌──────────────────────────┐                         └──────────────┘  │
│ Lambda s3-done-trigger   │                                           │
│ ecs.run_task             │                                           │
│   INGESTION_DATE=YYYY-…  │                                           │
└────────────┬─────────────┘                                           │
             │ ECS RunTask                                              │
             ▼                                                          │
┌─────────────────────────────────────────────────────────────────────┐ │
│ ECS Fargate task financial-data-etl (cpu=512, memory=1024)          │ │
│ python -m financial_data_etl.main_runner                            │ │
│                                                                     │ │
│   stream_raw_batches_from_s3(batch_size=50)                         │ │
│     ├─ download data.jsonl.gz por símbolo                           │ │
│     ├─ parse_ohlcv + extract_fundamentals_from_quote_raw            │ │
│     └─ yield {symbol: body} batch                                   │ │
│   for batch in stream:                                              │ │
│     ├─ persist_ohlcv_base(batch)         ─► RDS tv_candles_raw     ─┼─┘
│     └─ persist_fundamentals_snapshot(batch) ─► fundamentals_snapshot│
│                                                                     │
│   for runner in (price_performance, volatility, momentum):          │
│     run_*_1d(symbols)         ─► RDS performance_1d / volatility_1d │
│                                                  / momentum_1d      │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
                        Frontend (leonardovila.com)
                          ─► API REST endpoints
                              /symbols
                              /ohlcv/history/{symbol}
                              /fundamentals/{symbol}
                              /performance/1d/{symbol}
                              /volatility/1d/{symbol}
                              /momentum/1d/{symbol}
```

**Reglas de la frontera VPS ↔ cloud:**

- VPS solo se comunica con AWS por dos canales: HTTPS al ALB (con bearer token) y `s3:PutObject` con un IAM user limitado al prefix `raw/tv/*`.
- VPS jamás abre conexión Postgres al RDS.
- RDS está en subnet privada de la VPC. Solo el security group de ECS puede llegar.

---

## 2. Catálogo

- 747 tickers únicos: SPX (S&P 500) ∪ NDX (Nasdaq 100) ∪ top-200 RUT (Russell 2000) + BTC.
- Archivo plano: [`financial_data_etl/universe/storage/catalog_seed.txt`](financial_data_etl/universe/storage/catalog_seed.txt) (un ticker por línea).
- Resolución de TradingView: [`financial_data_etl/catalog.json`](financial_data_etl/catalog.json) mapea `ticker → {provider_symbol: {tradingview: "EXCHANGE:TICKER"}}`. El WS de TradingView requiere el formato `EXCHANGE:TICKER` (ej. `NASDAQ:AAPL`, `BINANCE:BTCUSDT`).
- El VPS valida cada ticker del seed contra el catalog antes de scrapear; los que no tengan `provider_symbol.tradingview` se loggean como WARN y se saltean.

---

## 3. Componentes

### 3.1 VPS scraper — `financial_data_etl/vps_scraper/`

| Archivo | Rol |
|---|---|
| `runner.py` | Entrypoint. Orquesta lockfile → seed → API plan → chunked scrape → marker. |
| `chunk_orchestrator.py` | Loop de chunks de 50 con `sleep 50s`. Inyecta el callback `raw_capture` al scraper, acumula chunks WS por símbolo en memoria, sube uno por símbolo a S3. |
| `api_client.py` | Cliente HTTP del endpoint `/internal/increment-plan`. |
| `s3_uploader.py` | `boto3.put_object` para los `data.jsonl.gz` y para el marker. |
| `lockfile.py` | `fcntl.flock` anti-overlap (no-op en Windows para tests locales). |
| `config.py` | Config desde env vars (`VPS_API_BASE_URL`, `VPS_API_TOKEN_FILE`, `VPS_S3_BUCKET`, `VPS_S3_PREFIX`, `VPS_CHUNK_SIZE`, `VPS_CHUNK_SLEEP_SECONDS`). |

### 3.2 Hook `raw_capture` en el scraper de WebSocket

[`tradingview_ws.py::request_batch_multiplexed`](financial_data_etl/scraping_pipeline/tv_websocket_connection/call_execution/tradingview_ws.py) acepta un parámetro opcional `raw_capture: Optional[Callable[[str, str], None]]`. Cuando está seteado, antes de parsear cada chunk WS routeable a un símbolo conocido invoca `raw_capture(provider_symbol, raw_chunk_str)`. El callback se propaga por `tv_websocket_scraper.py` (3 funciones).

El VPS lo setea para volcar los chunks a JSONL.gz **sin parsear localmente**. Cuando no se pasa el callback, el comportamiento del scraper es 100% idéntico al original.

### 3.3 Endpoint `/internal/increment-plan`

`POST https://api.leonardovila.com/internal/increment-plan`

```http
Authorization: Bearer <token>
Content-Type: application/json

{"symbols": ["AAPL", "MSFT", ...], "timeframe": "1d"}
```

Respuesta:

```json
{"plan": {"AAPL": 1, "MSFT": 1, "RKLB": 4500}}
```

Token leído de la env var `INTERNAL_API_TOKEN` (Secrets Manager `financial-data/internal-api-token-*`). Internamente llama a `build_increment_plan()` del [`increment_planner.py`](financial_data_etl/storage/increment_planner.py); filtra `n=0` antes de devolver.

### 3.4 Lambda `s3-done-trigger`

[`aws/lambda/s3-done-trigger/lambda_function.py`](aws/lambda/s3-done-trigger/lambda_function.py)

- Trigger: S3 Event `s3:ObjectCreated:*` con filter `prefix=raw/tv/_DONE_`, `suffix=.txt`.
- Acción: parsea `INGESTION_DATE` del nombre del marker y llama `ecs.run_task(taskDefinition="financial-data-etl", overrides={environment: [INGESTION_DATE=...]})`.
- Garantiza una sola task por marker (los `data.jsonl.gz` no disparan nada — el filter solo matchea `_DONE_*.txt`).

### 3.5 Fargate processor — `financial_data_etl/main_runner.py`

Entrypoint `python -m financial_data_etl.main_runner`. Lee env vars:
- `INGESTION_DATE` (default = today UTC)
- `VPS_S3_BUCKET`, `VPS_S3_PREFIX`
- `VPS_PROCESSOR_BATCH_SIZE` (default 50)

Flujo:

1. **Streaming raw → persist por batch** vía [`stream_raw_batches_from_s3`](financial_data_etl/storage/raw_s3_reader.py): lista S3, descarga gzipeado, parsea con `parse_ohlcv` + `extract_fundamentals_from_quote_raw`, yieldea batches de 50 símbolos. Por cada batch corre `persist_ohlcv_base` y `persist_fundamentals_snapshot` y descarta el dict.
2. **Derivados serializados** sobre el set de símbolos procesados: `run_price_performance_1d`, `run_volatility_1d`, `run_momentum_1d`. Uno por vez (no en paralelo) — cada runner carga toda la historia en pandas (~500 MB pico), y tres simultáneos darían OOM.

### 3.6 Sizing de Fargate

| Recurso | Valor | Justificación |
|---|---|---|
| `cpu` | 512 (0.5 vCPU) | Suficiente para I/O + pandas mono-thread. |
| `memory` | 1024 MB | Pico real medido: ~500 MB (1 derivado en pandas). 1 GB da safety margin del 100%. |

Streaming + serialización mantienen este sizing constante para bootstrap (744 símbolos × 4500 velas) **y** para incremental (744 × 1 vela). No hay auto-scaling porque el peor caso ya cabe.

---

## 4. Recursos AWS (account 295933007543, region us-east-2)

| Recurso | Identificador | Notas |
|---|---|---|
| Bucket S3 | `leonardovila-financial-raw` | Prefix de este pipeline: `raw/tv/`. Convive con parquets de un export anterior bajo otros prefijos. |
| S3 Event Notification | `vps-scrape-done-trigger` | Filter `prefix=raw/tv/_DONE_` + `suffix=.txt` → Lambda. |
| Lambda | `s3-done-trigger` | Python 3.11. Role `s3-done-trigger-role` con `ecs:RunTask` + `iam:PassRole`. |
| IAM user (VPS) | `financial-data-vps-scraper` | Inline policy `write-raw-tv` (solo `s3:PutObject` y `s3:AbortMultipartUpload` sobre `raw/tv/*`). Access keys en `/root/.aws/credentials` del VPS (chmod 600). |
| IAM role (task ETL) | `financial-etl-task-role` | `read-s3-raw` (S3 GetObject + ListBucket sobre `raw/tv/*`) + `read-app-secrets` (Secrets Manager `financial-data/*`). |
| IAM role (task execution) | `ecsTaskExecutionRole` | + inline `read-financial-data-secrets` para que ECS pueda pullear los secrets antes de arrancar el container. |
| Secret | `financial-data/internal-api-token-4QMQ9b` | Bearer token para `/internal/*`. Inyectado al task de la API como env `INTERNAL_API_TOKEN`. |
| Secret | `financial-data/rds-vqG2ip` | DATABASE_URL del RDS. Inyectado a las tasks ETL y API. |
| Task definition (ETL) | `financial-data-etl:8` | cpu=512, mem=1024, taskRoleArn=`financial-etl-task-role`. |
| Task definition (API) | `financial-data-api:N` | Sirve los endpoints REST + WebSocket edge. |

---

## 5. Recursos VPS

Host `forge-api-nyc` (`147.182.219.80`).

| Path | Owner | Rol |
|---|---|---|
| `/root/financial-system/` | root | Git checkout del repo. |
| `/root/financial-system/.venv/` | root | Python 3.12 venv (`pip install -e .`). |
| `/root/.aws/credentials` | root, chmod 600 | Profile `vps-scraper`. |
| `/etc/financial-data/api-token` | root, chmod 600 | Bearer token para `/internal/*`. |
| `/etc/systemd/system/financial-vps-scraper.{service,timer}` | root | Versionados en [`aws/vps/systemd/`](aws/vps/systemd/). |
| `/var/log/financial-vps-scraper.log` | root | stdout/stderr de la unit. |
| `/var/run/financial-vps-scraper.lock` | root | Lockfile flock. |

Setup de cero documentado en [`aws/vps/README.md`](aws/vps/README.md).

---

## 6. Operación

### Ejecución manual

```bash
ssh root@147.182.219.80
systemctl start financial-vps-scraper.service
LOG=$(ls -1t /root/financial-system/logs/RUN_*_vps_scraper.jsonl | head -1)
tail -f $LOG
```

El resto del flujo (S3 marker → Lambda → ECS task → RDS) corre solo.

### Schedule

```bash
systemctl list-timers financial-vps-scraper.timer
# next: Mon..Fri 21:00 UTC
```

### Pausar el cron

```bash
systemctl stop financial-vps-scraper.timer
systemctl disable financial-vps-scraper.timer
```

### Logs en CloudWatch

```bash
aws logs tail /aws/lambda/s3-done-trigger --since 10m
aws logs tail /ecs/financial-data-etl --since 30m
```

---

## 7. Validación post-run

```sql
-- Símbolos con velas cargadas hoy
SELECT count(DISTINCT symbol)
FROM tv_candles_raw
WHERE ingested_at::date = CURRENT_DATE;
-- Esperado: ~747

-- Derivados al día
SELECT count(*) FROM momentum_1d   WHERE date = CURRENT_DATE;
SELECT count(*) FROM volatility_1d WHERE date = CURRENT_DATE;
SELECT count(*) FROM performance_1d WHERE date = CURRENT_DATE;
-- Esperado: ~747 cada una
```

```bash
# Vía API (no requiere acceso al RDS)
curl -s https://api.leonardovila.com/symbols | jq 'length'
curl -s https://api.leonardovila.com/momentum/1d/AAPL | jq
```

---

## 8. Tiempos y costos medidos

| Fase | Bootstrap (1er run) | Incremental (run normal) |
|---|---|---|
| VPS scrape (15 chunks × 50 + sleep) | ~15 min | ~15 min (idéntico, dominado por sleeps) |
| S3 → Lambda → ECS RunTask cold start | ~30 s | ~30 s |
| Streaming + persist a RDS | ~10 min (744 × 4500 velas) | ~30 s (744 × 1 vela) |
| Derivados serializados | ~2 min | ~2 min |
| **Total wall-clock** | **~28 min** | **~18 min** |

Costos estimados:
- Fargate task: ~$0.04/run × 5 runs/sem ≈ **$0.80/mes**.
- Lambda: <$0.01/mes.
- S3: ~14 MB/run × 22 runs ≈ 300 MB/mes ≈ centavos.
- ALB + RDS: sin cambio (ya facturado para el resto del sistema).
