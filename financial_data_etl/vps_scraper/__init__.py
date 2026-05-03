"""
VPS scraper package.

Runs on the VPS (Digital Ocean) under a systemd timer. Responsibilities:
  1. Read catalog_seed.txt and validate against catalog.json.
  2. Ask the Fargate API (HTTPS through ALB) for the increment plan
     (how many candles to fetch per symbol, computed against RDS).
  3. Scrape TradingView WebSocket in chunks of 50 with 50s sleep between
     chunks (anti rate-limit / IP reputation).
  4. Capture raw WS chunks per symbol via the raw_capture callback hook
     in tradingview_ws.request_batch_multiplexed (NO local parsing).
  5. Upload one data.jsonl.gz per symbol to S3 under
       s3://leonardovila-financial-raw/raw/tv/symbol={SYM}/ingestion_date=YYYY-MM-DD/data.jsonl.gz
  6. When all chunks finish, upload an empty marker
       s3://leonardovila-financial-raw/raw/tv/_DONE_YYYY-MM-DD.txt
     S3 Event on the marker triggers the Lambda dispatcher, which calls
     ECS RunTask on the Fargate processor (one single task), which lists the
     day's files, parses them, persists to RDS and computes derivatives.

The VPS only writes to S3 — it never touches RDS directly. The plan it
receives from the API is a {symbol: n_candles} dict; the API runs
build_increment_plan() in the cloud.
"""
