"""
Construye una CallSpec determinista a partir de entradas explícitas y catálogo provisto.
No carga configuración.
No mantiene estado.
"""

from typing import Optional, Dict

from financial_data_etl.scraping_pipeline.tv_websocket_connection.call_specification.call_spec import CallSpec
from financial_data_etl.scraping_pipeline.tv_websocket_connection.call_specification.asset_catalog import (
    validate_symbol,
    resolve_provider_symbol,
    get_asset_start
)
from financial_data_etl.scraping_pipeline.tv_websocket_connection.call_specification.timeframes_registry import TIMEFRAME_SECONDS, ALIASES
from financial_data_etl.time_utils import parse_date_to_ts, now_ts

def _normalize_timeframe(tf: str) -> str:
    if tf in TIMEFRAME_SECONDS:
        return tf
    alias = ALIASES.get(tf.upper())
    if alias:
        return alias
    low = tf.lower()
    if low in TIMEFRAME_SECONDS:
        return low
    raise ValueError(f"Timeframe no soportado: {tf!r}")

def run_call_builder(
    *,
    symbol: str,
    timeframe: str,
    provider: str,
    mode: str,
    catalog: Dict[str, dict],
    since: Optional[object] = None,
    until: Optional[object] = None,
    n_candles_hint: Optional[int] = None
) -> CallSpec:
    """
    Construye una CallSpec completamente resuelta y lista para ejecución.
    """

    # 1️⃣ Validación símbolo
    validate_symbol(catalog, symbol)

    # 2️⃣ Resolución provider_symbol
    provider_symbol = resolve_provider_symbol(catalog, symbol, provider)

    # 3️⃣ Normalización timeframe
    tf_norm = _normalize_timeframe(timeframe)
    tf_seconds = TIMEFRAME_SECONDS[tf_norm]

    # 4️⃣ Resolución temporal
    since_ts = parse_date_to_ts(since)
    until_ts = parse_date_to_ts(until)

    if mode == "backfill":
        if since_ts is None:
            start = get_asset_start(catalog, symbol)
            since_ts = parse_date_to_ts(start) if start else 0
        if until_ts is None:
            until_ts = now_ts()

    elif mode in ("catchup", "realtime"):
        # No forzamos defaults aquí; el caller decide.
        pass

    else:
        raise ValueError(f"Mode inválido: {mode!r}")

    return CallSpec(
        symbol=symbol,
        provider=provider,
        provider_symbol=provider_symbol,
        timeframe=tf_norm,
        tf_seconds=tf_seconds,
        mode=mode,
        since_ts=since_ts,
        until_ts=until_ts,
        n_candles_hint=n_candles_hint,
    )