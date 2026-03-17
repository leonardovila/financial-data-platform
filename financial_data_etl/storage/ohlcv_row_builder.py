from __future__ import annotations
from typing import List, Dict
import time
import exchange_calendars as xcals
import pandas as pd

def resolve_calendar_for_symbol(symbol: str):
    if symbol == "QNC":
        return xcals.get_calendar("XTSE")

    if symbol in ("SGLN", "URNU"):
        return xcals.get_calendar("XLON")

    return xcals.get_calendar("XNYS")

def run_ohlcv_row_builder(ticker: str, body: Dict, ctx=None) -> List[Dict]:
    """
    Construye filas OHLCV normalizadas.
    Determina is_partial usando calendario oficial del exchange para 1D.
    """
    cal = resolve_calendar_for_symbol(ticker)

    out: List[Dict] = []
    timeframe = body.get("timeframe", "")
    now_ts = int(time.time())

    candles = body.get("candles", [])
    if not candles:
        return out

    # Detectamos última vela del batch
    max_ts = max(int(row[0]) for row in candles if isinstance(row, (list, tuple)))

    for row in candles:
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            continue

        ts, o, h, l, c = row[:5]
        v = row[5] if len(row) >= 6 else None

        ts = int(ts)

        is_partial = 0

        # Solo aplicamos lógica institucional para 1D (case-insensitive)
        if timeframe.upper() == "1D" and ts == max_ts:
            tz = cal.tz
            now_exchange = pd.Timestamp.now(tz=tz)

            # 1) Sesión "vigente" relativa a NOW.
            #    - Si hoy es sesión: usa hoy
            #    - Si ahora cae fuera de horario / finde / holiday: usa la última sesión anterior
            try:
                current_session = cal.minute_to_session(now_exchange, direction="previous")
            except Exception:
                # Fallback ultra defensivo
                try:
                    current_session = cal.date_to_session(now_exchange.date(), direction="previous")
                except Exception:
                    current_session = None

            # 2) Sesión asociada a la vela (también "previous" para tolerar timestamps raros del proveedor)
            bar_time = pd.Timestamp(ts, unit="s", tz="UTC").tz_convert(tz)
            try:
                candle_session = cal.minute_to_session(bar_time, direction="previous")
            except Exception:
                candle_session = None

            if current_session is not None and candle_session is not None:
                # 3) Parcial solo si la vela es la del día vigente y aún no cerró oficialmente
                if candle_session == current_session:
                    session_close = cal.session_close(current_session)
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