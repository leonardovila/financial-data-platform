"""
Thin HTTP client to call the financial-data-etl API exposed via ALB.

Today only one endpoint is used: POST /internal/increment-plan.
The API runs build_increment_plan() against the RDS in the cloud and
returns {symbol: n_candles_hint}. The VPS uses that to scrape only what
the RDS actually needs, instead of scraping a fixed N every night.
"""
from __future__ import annotations

import logging
from typing import Dict, Iterable, List

import requests

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 30


def fetch_increment_plan(
    api_base_url: str,
    token: str,
    symbols: Iterable[str],
    timeframe: str,
) -> Dict[str, int]:
    """
    POST {api_base_url}/internal/increment-plan
        Authorization: Bearer <token>
        body: {"symbols": [...], "timeframe": "1d"}
        response: {"plan": {"AAPL": 1, "MSFT": 1, "RKLB": 8000, ...}}

    Symbols with n=0 (already up-to-date) are filtered out by the API.
    """
    url = f"{api_base_url.rstrip('/')}/internal/increment-plan"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body: Dict[str, object] = {
        "symbols": list(symbols),
        "timeframe": timeframe,
    }

    logger.info("Fetching increment plan: %d symbols, timeframe=%s", len(body["symbols"]), timeframe)
    resp = requests.post(url, json=body, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
    resp.raise_for_status()
    payload = resp.json()
    plan = payload.get("plan", {})

    if not isinstance(plan, dict):
        raise RuntimeError(f"Malformed /internal/increment-plan response: {payload}")

    # Force all hints to int (json may decode as int already, but be defensive)
    out: Dict[str, int] = {}
    for sym, n in plan.items():
        try:
            n_int = int(n)
        except (TypeError, ValueError):
            continue
        if n_int > 0:
            out[sym] = n_int
    return out
