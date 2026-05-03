# VPS setup — financial-vps-scraper

Versioned reference of how the Digital Ocean VPS is configured to run the
nightly raw scrape that feeds the cloud pipeline. Apply by hand the first
time (and every time the host changes); the values below match what is
deployed today.

Host: `forge-api-nyc` (Digital Ocean droplet, IP `147.182.219.80`)

## Filesystem layout

| Path | Owned by | Purpose |
|---|---|---|
| `/root/financial-system/` | root | Git checkout of `leonardovila/financial-data-etl`. |
| `/root/financial-system/.venv/` | root | Python 3.12 venv with the package installed via `pip install -e .`. |
| `/root/.aws/credentials` | root (chmod 600) | AWS profile `vps-scraper` (IAM user with `s3:PutObject` on `raw/tv/*` only). |
| `/etc/financial-data/api-token` | root (chmod 600) | Bearer token for `/internal/*` API endpoints. Mirror of the AWS Secret `financial-data/internal-api-token-*`. |
| `/etc/systemd/system/financial-vps-scraper.service` | root | Oneshot scrape unit. See `systemd/financial-vps-scraper.service`. |
| `/etc/systemd/system/financial-vps-scraper.timer` | root | Mon..Fri 21:00 UTC trigger. See `systemd/financial-vps-scraper.timer`. |
| `/var/log/financial-vps-scraper.log` | root | Append-only stdout/stderr of the unit. |
| `/var/run/financial-vps-scraper.lock` | root | `flock` lockfile (anti-overlap). |

## First-time setup (manual, ~5 min)

```bash
ssh root@147.182.219.80

# 1. Clone (or git pull if already cloned)
cd /root && git clone https://github.com/leonardovila/financial-data-etl.git financial-system
cd /root/financial-system

# 2. Python env
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e .

# 3. AWS creds (paste values from your local .secrets-out/vps-scraper-access-key.json)
mkdir -p /root/.aws
cat > /root/.aws/credentials <<'EOF'
[vps-scraper]
aws_access_key_id = AKIAxxxxxxxxxx
aws_secret_access_key = xxxxxxxxxxxxxxxx
EOF
chmod 600 /root/.aws/credentials

# 4. API token (paste from .secrets-out/internal-api-token.txt)
mkdir -p /etc/financial-data
printf '%s' 'PASTE_TOKEN_HERE' > /etc/financial-data/api-token
chmod 600 /etc/financial-data/api-token

# 5. systemd
# Copy aws/vps/systemd/financial-vps-scraper.service AND .timer
# to /etc/systemd/system/, then:
systemctl daemon-reload

# 6. Smoke test (does NOT start the timer yet)
systemctl start financial-vps-scraper.service
tail -f /var/log/financial-vps-scraper.log

# 7. After a successful manual run, enable the timer:
systemctl enable --now financial-vps-scraper.timer
systemctl list-timers --all | grep financial
```

## Operations

```bash
# manual run (one-shot)
systemctl start financial-vps-scraper.service

# follow logs (real-time JSONL)
LOG=$(ls -1t /root/financial-system/logs/RUN_*_vps_scraper.jsonl | head -1)
tail -f $LOG

# check next scheduled run
systemctl list-timers financial-vps-scraper.timer

# pause the daily cron (for example during maintenance)
systemctl stop financial-vps-scraper.timer
systemctl disable financial-vps-scraper.timer
```

## What it does, in one paragraph

Loads `financial_data_etl/universe/storage/catalog_seed.txt` (746 SPX+NDX+RUT
tickers), validates each ticker exists in `catalog.json`, asks the cloud API
(`POST /internal/increment-plan` with bearer token) which symbols actually
need scraping, then loops through chunks of 50 symbols (sleeping 50 s between
chunks) firing the existing TradingView WebSocket scraper. The scraper now
accepts a `raw_capture` callback that hands back each parseable WS chunk
**before** parsing; the VPS buffers those chunks in memory per symbol and at
the end of each chunk gzips them into `s3://leonardovila-financial-raw/raw/tv/symbol={SYM}/ingestion_date=YYYY-MM-DD/data.jsonl.gz`.
When all chunks finish, an empty `_DONE_{date}.txt` marker is uploaded to
the same prefix; an S3 PutObject Event on that marker triggers the Lambda
`s3-done-trigger`, which in turn launches a single ECS Fargate task with
`USE_VPS_RAW=true`. That task lists the day's raw files, parses them with
the same parsers the scraper used to use, and persists into RDS — exactly
the same shape as before the split. **The VPS never opens a connection to
RDS.**
