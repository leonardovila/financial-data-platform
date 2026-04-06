"""
P0_02 Integration Smoke Test — Full ETL end-to-end with BTC.

Why this test exists (and why it is marked `integration`):
  Leonardo's original P0_02 instinct: "if something as basic as running the
  ETL fails, the change is a time bomb". That instinct is correct — the most
  powerful smoke test is actually running the damn thing.

  BUT running the real ETL hits:
    - TradingView WebSockets (external network, rate limiting, GH runner IPs
      may be on blacklists)
    - PostgreSQL (CI runners have no DB)
    - ~30-60 seconds of runtime per invocation

  So this test is marked with `@pytest.mark.integration`. By default
  (`pytest`) it is SKIPPED. To run it explicitly:

      pytest -m integration tests/integration/

  Run this locally before merging anything touching the scraper, storage,
  or the TradingView protocol layer. Later, in Phase 2, we may schedule
  this nightly in CI with proper secrets.
"""

import pytest


@pytest.mark.integration
def test_etl_runs_with_btc_asset():
    """
    Execute the ETL end-to-end on a single BTC symbol.

    Success criteria: main() returns 0 without raising.
    Failure modes this catches:
      - Broken TradingView WebSocket handshake
      - Broken universe resolution
      - Broken increment plan
      - Broken persistence (ohlcv / fundamentals)
      - Broken derived metrics runners
    """
    from financial_data_etl.main_runner import main

    exit_code = main(["--assets", "BTCUSDT", "--timeframe", "1d"])
    assert exit_code == 0, f"ETL exited with non-zero code: {exit_code}"
