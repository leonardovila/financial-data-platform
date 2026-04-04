import json
import time
import hashlib
from typing import List, Optional

from financial_data_etl.storage.database import (
    transaction, execute, fetchone, PH,
)


def init_universe_schema() -> None:
    with transaction() as conn:
        execute(conn, """
            CREATE TABLE IF NOT EXISTS universes (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                asof_ts BIGINT NOT NULL,
                symbols_json TEXT NOT NULL,
                symbols_hash TEXT NOT NULL
            )
        """)
        execute(conn, """
            CREATE INDEX IF NOT EXISTS idx_universes_name_asof
            ON universes(name, asof_ts)
        """)


def save_universe_snapshot(name: str, symbols: List[str]) -> None:
    universe_name = _normalize_universe_name(name)
    normalized_symbols = sorted(_normalize_symbols(symbols))
    payload = json.dumps(normalized_symbols, separators=(",", ":"))
    snapshot_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    asof_ts = int(time.time())

    with transaction() as conn:
        row = fetchone(conn, f"""
            SELECT symbols_hash
            FROM universes
            WHERE name = {PH}
            ORDER BY asof_ts DESC
            LIMIT 1
        """, (universe_name,))

        if row and row[0] == snapshot_hash:
            return

        execute(conn, f"""
            INSERT INTO universes (name, asof_ts, symbols_json, symbols_hash)
            VALUES ({PH}, {PH}, {PH}, {PH})
        """, (universe_name, asof_ts, payload, snapshot_hash))


def load_latest_universe(name: str) -> Optional[List[str]]:
    universe_name = _normalize_universe_name(name)

    with transaction() as conn:
        row = fetchone(conn, f"""
            SELECT symbols_json
            FROM universes
            WHERE name = {PH}
            ORDER BY asof_ts DESC
            LIMIT 1
        """, (universe_name,))

    if not row:
        return None

    symbols = json.loads(row[0])
    return _normalize_symbols(symbols)


def _normalize_universe_name(name: str) -> str:
    if not isinstance(name, str):
        raise TypeError("Universe name must be a string.")
    n = name.strip().upper()
    if not n:
        raise ValueError("Universe name cannot be empty.")
    return n


def _normalize_symbols(symbols: List[str]) -> List[str]:
    if symbols is None:
        raise ValueError("Symbols cannot be None.")

    out: List[str] = []
    seen = set()

    for s in symbols:
        if not isinstance(s, str):
            continue
        sym = s.strip().upper()
        if not sym:
            continue
        if sym in seen:
            continue
        seen.add(sym)
        out.append(sym)

    if not out:
        raise ValueError("Symbols list is empty after normalization.")

    return out
