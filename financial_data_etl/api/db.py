import sqlite3
from financial_data_etl.storage.paths import DB_PATH


def get_connection() -> sqlite3.Connection:
    """
    Returns a hardened SQLite connection for the FastAPI layer.
    - WAL mode: readers never block writers (and vice versa)
    - synchronous=NORMAL: safe with WAL, reduces fsync overhead
    - busy_timeout=5000: wait 5s on lock contention instead of failing
    """
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn
