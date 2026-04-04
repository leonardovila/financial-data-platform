"""
Database adapter — single point of contact for all DB operations.

Every store and runner imports from here instead of touching sqlite3/psycopg2
directly. If the DB engine changes tomorrow, only this file changes.

Connection is determined by DATABASE_URL env var:
  - starts with "postgresql://" → psycopg2 (TCP to Postgres server)
  - absent or file path         → sqlite3   (local file, dev/legacy only)
"""

import os
import sqlite3
from contextlib import contextmanager
from typing import Optional

# ── Engine detection ──────────────────────────────────────────────────────────

DATABASE_URL = os.getenv("DATABASE_URL", "")
_USE_POSTGRES = DATABASE_URL.startswith("postgresql://")

if _USE_POSTGRES:
    import psycopg2
    import psycopg2.extras

# ── Placeholder ───────────────────────────────────────────────────────────────
# SQLite uses ? — PostgreSQL uses %s. Queries use PH and we swap at runtime.

PH = "%s" if _USE_POSTGRES else "?"

# ── Connection ────────────────────────────────────────────────────────────────

def get_connection():
    """
    Returns a DB connection configured for the active engine.

    PostgreSQL: TCP connection via DATABASE_URL.
    SQLite:     File connection via FORGE_DB_PATH (legacy fallback).
    """
    if _USE_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        return conn
    else:
        from financial_data_etl.storage.paths import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn


def get_dict_connection():
    """
    Returns a connection that returns rows as dicts (for API/seed layer).

    PostgreSQL: RealDictCursor — each row is a dict.
    SQLite:     row_factory = sqlite3.Row — dict-like access via keys.
    """
    if _USE_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        conn.cursor_factory = psycopg2.extras.RealDictCursor
        return conn
    else:
        from financial_data_etl.storage.paths import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn


@contextmanager
def transaction():
    """
    Context manager that yields a connection, commits on success,
    rolls back on error, and always closes.

    Usage:
        with transaction() as conn:
            conn.execute(...)
    """
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Query helpers ─────────────────────────────────────────────────────────────

def execute(conn, sql: str, params=None):
    """Execute a single query, abstracting cursor differences."""
    if _USE_POSTGRES:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur
    else:
        return conn.execute(sql, params or ())


def executemany(conn, sql: str, params_list):
    """Execute a batch query."""
    if _USE_POSTGRES:
        cur = conn.cursor()
        # psycopg2.extras.execute_batch is 5-10x faster than executemany
        psycopg2.extras.execute_batch(cur, sql, params_list, page_size=2000)
        return cur
    else:
        conn.executemany(sql, params_list)


def fetchall(conn, sql: str, params=None):
    """Execute and fetch all rows."""
    if _USE_POSTGRES:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()
    else:
        return conn.execute(sql, params or ()).fetchall()


def fetchone(conn, sql: str, params=None):
    """Execute and fetch one row."""
    if _USE_POSTGRES:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchone()
    else:
        return conn.execute(sql, params or ()).fetchone()


def fetchall_dict(conn, sql: str, params=None):
    """Execute and fetch all rows as dicts."""
    if _USE_POSTGRES:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        return cur.fetchall()
    else:
        old_factory = conn.row_factory
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params or ()).fetchall()
        conn.row_factory = old_factory
        return rows


def fetchone_dict(conn, sql: str, params=None):
    """Execute and fetch one row as dict."""
    if _USE_POSTGRES:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        return cur.fetchone()
    else:
        old_factory = conn.row_factory
        conn.row_factory = sqlite3.Row
        row = conn.execute(sql, params or ()).fetchone()
        conn.row_factory = old_factory
        return row


# ── Placeholder builder ──────────────────────────────────────────────────────

def placeholders(n: int) -> str:
    """Generate n comma-separated placeholders: '?, ?, ?' or '%s, %s, %s'."""
    return ", ".join(PH for _ in range(n))


def in_clause(items: list) -> str:
    """Generate an IN clause: 'IN (?, ?, ?)' or 'IN (%s, %s, %s)'."""
    return f"IN ({placeholders(len(items))})"
