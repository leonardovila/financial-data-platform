# Changelog

## [1.0.0] - 2026-02-25
### Added
- CLI main_runner
- Scrape OHLCV and fundamentals data from TradingView website via websocket
- Data cleaning
- Data storage
- Derived price performance metrics
- Derived volatility metrics
- Derived volume metrics

### Notes
Initial stable public release.

## [1.1.0] - 2026-02-27

### Added
- Optional `--sync` flag in `main_runner` to enable server synchronization.
- Full-file SQLite replication to VPS via snapshot + SCP + atomic `mv`.
- Sync integrated into execution context logging (CTX).

### Notes
- Replication transfers a consolidated SQLite snapshot (WAL-safe via `VACUUM INTO`).
- Atomic remote DB swap using `mv` prevents partial-write states.
- Intended for once-daily post-market execution (Phase 1 scope).