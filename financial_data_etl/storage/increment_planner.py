from typing import Dict, List, Optional
from financial_data_etl.observability.run_context import RunContext
import time

from .tv_candles_store import (
    init_tv_candles_schema,
    _get_connection,   # usamos conexión directa para query masiva
)

# Política inicial (simple pero correcta)
BOOTSTRAP_BARS = 8000
MAX_CATCHUP_BARS = 600
OVERLAP_BARS = 1 # Al no calcular derivadas de forma directa como hacia version previa, el overlap no se justifica

# segundos por timeframe (extensible luego)
TF_SECONDS = {
    "1d": 86400,
    "1h": 3600,
    "4h": 14400,
}

def build_increment_plan(
    symbols: List[str],
    timeframe: str,
    *,
    ctx: Optional[RunContext] = None,
) -> Dict[str, int]:
    """
    Devuelve dict {symbol: n_candles_hint}

    Hace:
      - init schema
      - query masiva de últimos timestamps
      - cálculo incremental eficiente
    """

    init_tv_candles_schema()

    timeframe = timeframe.lower()
    tf_sec = TF_SECONDS.get(timeframe)

    if tf_sec is None:
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    now = int(time.time())

    if not symbols:
        return {}

    # ==============================
    # Query masiva
    # ==============================
    placeholders = ",".join("?" for _ in symbols)

    query = f"""
        SELECT symbol, MAX(ts) as last_ts
        FROM tv_candles_raw
        WHERE timeframe = ?
          AND symbol IN ({placeholders})
        GROUP BY symbol
    """

    with _get_connection() as conn:
        cur = conn.execute(query, [timeframe] + symbols)
        rows = cur.fetchall()

    # Convertimos a dict
    last_map = {row[0]: row[1] for row in rows}

    plan: Dict[str, int] = {}

    for symbol in symbols:
        last_ts = last_map.get(symbol)

        # ==============================
        # Caso bootstrap
        # ==============================
        if last_ts is None:
            plan[symbol] = BOOTSTRAP_BARS
            continue

        # ==============================
        # Caso incremental
        # ==============================
        start_anchor = int(last_ts) - OVERLAP_BARS * tf_sec

        # ceil division
        n = ((now - start_anchor) + tf_sec - 1) // tf_sec

        # incluir la barra ancla
        n = n + 1

        n = max(n, OVERLAP_BARS + 1)
        n = min(n, MAX_CATCHUP_BARS)

        plan[symbol] = int(n)

    if ctx:
        bootstrap = sum(1 for s in symbols if s not in last_map)
        incremental = len(symbols) - bootstrap
        total_requested = sum(plan.values())
        capped = sum(1 for v in plan.values() if v >= MAX_CATCHUP_BARS)
        bootstraps = sum(1 for v in plan.values() if v == BOOTSTRAP_BARS)

        ctx.event(
            "increment_plan_summary",
            stage="increment_plan",
            symbols=len(symbols),
            bootstrap=bootstrap,
            incremental=incremental,
            total_candles_requested=total_requested,
            max_hint=max(plan.values()) if plan else 0,
            min_hint=min(plan.values()) if plan else 0,
            overlap_bars=OVERLAP_BARS,
            max_catchup_bars=MAX_CATCHUP_BARS,
            bootstrap_bars=BOOTSTRAP_BARS,
            capped_symbols=capped,
            bootstrap_symbols=bootstraps,
        )

    return plan