import sqlite3
import json
import time
import hashlib
from pathlib import Path
from typing import List, Optional

from financial_data_etl.storage.paths import DB_PATH

def init_universe_schema() -> None:
    """
    Crea la tabla 'universes' si no existe.
    Guarda hash del snapshot para evitar inserts redundantes.
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS universes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                asof_ts INTEGER NOT NULL,
                symbols_json TEXT NOT NULL,
                symbols_hash TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_universes_name_asof
            ON universes(name, asof_ts)
            """
        )
        conn.commit()


def save_universe_snapshot(name: str, symbols: List[str]) -> None:
    """
    Persiste snapshot del universo en DB.
    - Normaliza y deduplica symbols.
    - Evita insertar si el snapshot no cambió (comparando hash contra el último).
    """
    universe_name = _normalize_universe_name(name)
    normalized_symbols = _normalize_symbols(symbols)

    normalized_symbols = sorted(normalized_symbols)
    payload = json.dumps(normalized_symbols, separators=(",", ":"))
    snapshot_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    asof_ts = int(time.time())

    with sqlite3.connect(DB_PATH) as conn:
        # Si el último snapshot es igual, no insertamos
        cur = conn.execute(
            """
            SELECT symbols_hash
            FROM universes
            WHERE name = ?
            ORDER BY asof_ts DESC
            LIMIT 1
            """,
            (universe_name,),
        )
        row = cur.fetchone()
        if row and row[0] == snapshot_hash:
            return

        conn.execute(
            """
            INSERT INTO universes (name, asof_ts, symbols_json, symbols_hash)
            VALUES (?, ?, ?, ?)
            """,
            (universe_name, asof_ts, payload, snapshot_hash),
        )
        conn.commit()


def load_latest_universe(name: str) -> Optional[List[str]]:
    """
    Devuelve la lista más reciente de símbolos para un universo.
    Si no existe snapshot, devuelve None.
    """
    universe_name = _normalize_universe_name(name)

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            """
            SELECT symbols_json
            FROM universes
            WHERE name = ?
            ORDER BY asof_ts DESC
            LIMIT 1
            """,
            (universe_name,),
        )
        row = cursor.fetchone()

    if not row:
        return None

    symbols = json.loads(row[0])
    # garantizamos consistencia al leer también
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
