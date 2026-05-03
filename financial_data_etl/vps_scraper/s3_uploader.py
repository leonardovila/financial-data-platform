"""
S3 upload helpers for the VPS scraper.

Two object types are written:
  - Raw scrape per symbol (gzipped JSONL, one line per WS chunk):
      s3://{bucket}/{prefix}/symbol={SYM}/ingestion_date=YYYY-MM-DD/data.jsonl.gz
  - End-of-run marker (empty .txt) that triggers the Lambda dispatcher:
      s3://{bucket}/{prefix}/_DONE_YYYY-MM-DD.txt

The Lambda's S3 Event filter is suffix=_DONE_*.txt so the data files
do NOT trigger the dispatcher. Only the marker does.
"""
from __future__ import annotations

import gzip
import io
import logging
from typing import Iterable, Optional

import boto3
from botocore.config import Config

logger = logging.getLogger(__name__)

_BOTO_CONFIG = Config(retries={"max_attempts": 5, "mode": "standard"})


def _s3_client(region: str, profile: Optional[str]):
    session = boto3.Session(profile_name=profile, region_name=region) if profile \
        else boto3.Session(region_name=region)
    return session.client("s3", config=_BOTO_CONFIG)


def upload_symbol_raw(
    *,
    bucket: str,
    prefix: str,
    symbol: str,
    ingestion_date: str,
    raw_chunks: Iterable[str],
    region: str = "us-east-2",
    profile: Optional[str] = None,
) -> str:
    """
    Encode `raw_chunks` (each is a JSON string) as gzipped JSONL and upload.

    Returns the S3 key written.
    """
    key = f"{prefix.strip('/')}/symbol={symbol}/ingestion_date={ingestion_date}/data.jsonl.gz"

    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        for chunk in raw_chunks:
            # Each chunk is already a JSON-encoded TradingView frame.
            # We append a single "\n" so the result is valid JSONL.
            gz.write(chunk.encode("utf-8"))
            gz.write(b"\n")

    body = buf.getvalue()
    client = _s3_client(region, profile)
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType="application/gzip",
        ContentEncoding="gzip",
    )
    logger.info("Uploaded %s (%d bytes)", key, len(body))
    return key


def upload_done_marker(
    *,
    bucket: str,
    prefix: str,
    ingestion_date: str,
    body_text: str = "",
    region: str = "us-east-2",
    profile: Optional[str] = None,
) -> str:
    """
    Upload the end-of-run marker that triggers the Lambda dispatcher.
    Path: s3://{bucket}/{prefix}/_DONE_{ingestion_date}.txt
    """
    key = f"{prefix.strip('/')}/_DONE_{ingestion_date}.txt"
    client = _s3_client(region, profile)
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=body_text.encode("utf-8"),
        ContentType="text/plain",
    )
    logger.info("Uploaded marker %s", key)
    return key
