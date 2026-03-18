from __future__ import annotations
from typing import List, Dict, Optional
import time
import exchange_calendars as xcals
import pandas as pd

# ── Module-level calendar cache: {exchange_code: calendar_instance} ──
_CALENDAR_CACHE: Dict[str, xcals.ExchangeCalendar] = {}


def _get_calendar(exchange: str) -> xcals.ExchangeCalendar:
    """Return a cached calendar instance. Instantiate once per exchange."""
    if exchange not in _CALENDAR_CACHE:
        _CALENDAR_CACHE[exchange] = xcals.get_calendar(exchange)
    return _CALENDAR_CACHE[exchange]


def resolve_calendar_for_symbol(symbol: str) -> xcals.ExchangeCalendar:
    if symbol == "QNC":
        return _get_calendar("XTSE")
    if symbol in ("SGLN", "URNU"):
        return _get_calendar("XLON")
    return _get_calendar("XNYS")


def precompute_session_context(cal: xcals.ExchangeCalendar):
    """
    Pre-compute now_exchange, current_session, and session_close ONCE per run.
    Returns a dict to be passed to run_ohlcv_row_builder for all symbols sharing this calendar.
    """
    tz = cal.tz
    now_exchange = pd.Timestamp.now(tz=tz)

    try:
        current_session = cal.minute_to_session(now_exchange, direction="previous")
    except Exception:
        try:
            current_session = cal.date_to_session(now_exchange.date(), direction="previous")
        except Exception:
            current_session = None

    session_close = None
    if current_session is not None:
        session_close = cal.session_close(current_session)

    return {
        "now_exchange": now_exchange,
        "current_session": current_session,
        "session_close": session_close,
        "cal": cal,
    }


def run_ohlcv_row_builder(
    ticker: str,
    body: Dict,
    ctx=None,
    *,
    session_ctx: Optional[Dict] = None,
) -> List[Dict]:
    """
    Construye filas OHLCV normalizadas.
    Determina is_partial usando calendario oficial del exchange para 1D.

    Args:
        session_ctx: Pre-computed session context from precompute_session_context().
                     If None, falls back to per-symbol computation (backward compat).
    """
    out: List[Dict] = []
    timeframe = body.get("timeframe", "")
    now_ts = int(time.time())

    candles = body.get("candles", [])
    if not candles:
        return out

    # Detectamos última vela del batch
    max_ts = max(int(row[0]) for row in candles if isinstance(row, (list, tuple)))

    # Pre-resolve calendar and session context
    if session_ctx is not None:
        cal = session_ctx["cal"]
        now_exchange = session_ctx["now_exchange"]
        current_session = session_ctx["current_session"]
        session_close = session_ctx["session_close"]
    else:
        cal = resolve_calendar_for_symbol(ticker)
        now_exchange = None  # will be computed lazily below if needed

    for row in candles:
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            continue

        ts, o, h, l, c = row[:5]
        v = row[5] if len(row) >= 6 else None

        ts = int(ts)

        is_partial = 0

        # Solo aplicamos lógica institucional para 1D (case-insensitive)
        if timeframe.upper() == "1D" and ts == max_ts:
            if session_ctx is None:
                # Fallback: per-symbol computation (backward compat)
                tz = cal.tz
                now_exchange = pd.Timestamp.now(tz=tz)
                try:
                    current_session = cal.minute_to_session(now_exchange, direction="previous")
                except Exception:
                    try:
                        current_session = cal.date_to_session(now_exchange.date(), direction="previous")
                    except Exception:
                        current_session = None
                session_close = cal.session_close(current_session) if current_session else None

            # 2) Sesión asociada a la vela
            bar_time = pd.Timestamp(ts, unit="s", tz="UTC").tz_convert(cal.tz)
            try:
                candle_session = cal.minute_to_session(bar_time, direction="previous")
            except Exception:
                candle_session = None

            if current_session is not None and candle_session is not None:
                # 3) Parcial solo si la vela es la del día vigente y aún no cerró oficialmente
                if candle_session == current_session:
                    if now_exchange < session_close:
                        is_partial = 1

        out.append({
            "ts": ts,
            "open": float(o),
            "high": float(h),
            "low": float(l),
            "close": float(c),
            "volume": float(v) if v is not None else None,
            "symbol": ticker,
            "timeframe": timeframe,
            "is_partial": is_partial,
            "updated_at": now_ts
        })

    return out
