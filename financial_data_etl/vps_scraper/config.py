"""
Runtime configuration for the VPS scraper.

Reads everything from env vars so the same module runs identically in
dev, the VPS systemd unit and any future replacement host.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class VpsConfig:
    api_base_url: str          # e.g. http://financial-api-alb-1680587852.us-east-2.elb.amazonaws.com
    api_token: str             # bearer token for /internal/* endpoints
    s3_bucket: str             # leonardovila-financial-raw
    s3_prefix: str             # raw/tv
    chunk_size: int            # default 50
    chunk_sleep_seconds: int   # default 50
    timeframe: str             # default 1d
    aws_region: str            # default us-east-2
    aws_profile: str | None    # default None (uses default credentials chain)
    lockfile_path: str         # default /tmp/financial-vps-scraper.lock


def _read_token_from_file_or_env() -> str:
    """
    Token loading order:
      1. VPS_API_TOKEN_FILE (path to a file with the raw token, chmod 600)
      2. VPS_API_TOKEN (raw token in env var)
    """
    path = os.environ.get("VPS_API_TOKEN_FILE")
    if path:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    raw = os.environ.get("VPS_API_TOKEN")
    if not raw:
        raise RuntimeError(
            "Missing API token. Set VPS_API_TOKEN_FILE (preferred) or VPS_API_TOKEN."
        )
    return raw.strip()


def load_config() -> VpsConfig:
    api_base_url = os.environ.get(
        "VPS_API_BASE_URL",
        "http://financial-api-alb-1680587852.us-east-2.elb.amazonaws.com",
    ).rstrip("/")

    return VpsConfig(
        api_base_url=api_base_url,
        api_token=_read_token_from_file_or_env(),
        s3_bucket=os.environ.get("VPS_S3_BUCKET", "leonardovila-financial-raw"),
        s3_prefix=os.environ.get("VPS_S3_PREFIX", "raw/tv").strip("/"),
        chunk_size=int(os.environ.get("VPS_CHUNK_SIZE", "50")),
        chunk_sleep_seconds=int(os.environ.get("VPS_CHUNK_SLEEP_SECONDS", "50")),
        timeframe=os.environ.get("VPS_TIMEFRAME", "1d"),
        aws_region=os.environ.get("AWS_REGION", "us-east-2"),
        aws_profile=os.environ.get("AWS_PROFILE") or None,
        lockfile_path=os.environ.get(
            "VPS_LOCKFILE", "/tmp/financial-vps-scraper.lock"
        ),
    )
