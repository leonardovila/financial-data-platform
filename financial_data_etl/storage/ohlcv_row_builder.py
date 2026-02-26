from __future__ import annotations
from typing import List, Dict
import time
import exchange_calendars as xcals
import pandas as pd

# =====================================================================
# ======================== ACLARACION FASE 1 ==========================
# =====================================================================
# is_partial – Lógica Fase 1 (1D – US Equities)
#
# Este módulo marca is_partial únicamente para velas 1D y solo para
# equities de USA utilizando el calendario oficial XNYS
# (exchange_calendars).
#
# Criterio:
# - Se toma la última vela del batch (ts == max_ts).
# - Se obtiene la sesión vigente respecto a la hora actual en NY.
# - Se obtiene la sesión asociada al timestamp de la vela.
# - Si ambas sesiones coinciden y la hora actual es anterior al
#   session_close oficial, la vela se marca como parcial.
#
# En términos simples:
# is_partial = 1 si la vela diaria corresponde a la sesión vigente
# y el mercado aún no cerró oficialmente.
#
# Garantías:
# - Respeta horario de verano.
# - Respeta feriados y fines de semana.
# - No depende del timezone local del host (se convierte a NY).
#
# Limitaciones:
# - Solo válido para timeframe 1D.
# - Solo válido para equities USA (XNYS).
# - Depende de que el proveedor entregue como última vela
#   la vela de la sesión vigente.
# - Depende de que el reloj del sistema sea correcto.
#
# Si se amplía a otros exchanges o timeframes, esta lógica debe
# parametrizarse por calendario.
# =====================================================================

# Calendario oficial NYSE (sirve para NYSE + NASDAQ equities)
XNYS_CAL = xcals.get_calendar("XNYS")

def run_ohlcv_row_builder(ticker: str, body: Dict, ctx=None) -> List[Dict]:
    """
    Construye filas OHLCV normalizadas.
    Determina is_partial usando calendario oficial del exchange para 1D.
    """
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

            cal = XNYS_CAL
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