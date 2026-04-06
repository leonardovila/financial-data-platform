"""
P0_02 Test 1 — Import smoke + CLI parser contract.

Why this test exists:
  Importing `main_runner` transitively imports the entire ETL dependency chain
  (tv_websocket_scraper, universe_service, increment_planner, storage, derived
  metrics, observability). If *any* import in that chain is broken — a missing
  dependency in pyproject.toml, a renamed file, a syntax error in a module that
  main_runner indirectly uses — this test will fail in <1 second, with no
  network and no database.

  The CLI tests additionally lock the contract of the CLI surface:
  --assets / --spx / --timeframe. When we reach Phase 2 (ECS + EventBridge),
  the scheduled task will invoke the container with flags like
  `--assets AAPL MSFT` or `--spx`. If a refactor silently breaks the parser,
  the scheduled task would fail in production — this test catches it at PR time.
"""

from financial_data_etl import main_runner
from financial_data_etl.main_runner import build_cli_parser, main, parse_cli


def test_main_runner_module_imports_cleanly():
    """Transitively validates the entire ETL import chain is healthy."""
    assert hasattr(main_runner, "main")
    assert callable(main_runner.main)


def test_cli_parser_is_constructible():
    """The argparse parser must be buildable without side effects."""
    parser = build_cli_parser()
    assert parser.prog == "financial_data_etl"


def test_cli_parses_assets_flag():
    """Locks the --assets + --timeframe contract (EventBridge/ECS entrypoint)."""
    args = parse_cli(["--assets", "BTCUSDT", "--timeframe", "1d"])
    assert args.assets == ["BTCUSDT"]
    assert args.timeframe == "1d"


def test_cli_parses_multiple_assets():
    """nargs='+' contract: --assets must accept multiple symbols."""
    args = parse_cli(["--assets", "AAPL", "MSFT", "GOOG"])
    assert args.assets == ["AAPL", "MSFT", "GOOG"]


def test_cli_parses_universe_flags():
    """Locks the --spx / --ndx / --dji / --rut universe flag contract."""
    args = parse_cli(["--spx"])
    assert args.spx is True
    assert args.ndx is False
    assert args.dji is False


def test_cli_default_timeframe_is_1d():
    """Timeframe defaults to 1d when not specified — critical for daily ETL runs."""
    args = parse_cli(["--spx"])
    assert args.timeframe == "1d"


def test_main_is_callable():
    """The main() entrypoint must be importable and callable (EventBridge target)."""
    assert callable(main)
