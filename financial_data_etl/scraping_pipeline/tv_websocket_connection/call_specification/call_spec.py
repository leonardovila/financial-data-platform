from typing import Optional, Dict
from dataclasses import dataclass, asdict
@dataclass(frozen=True)
class CallSpec:
    """
    Especificación completa de una solicitud; se ejecuta luego en `call_exec`.
    """
    symbol: str                   # símbolo humano, ej: "BTC", "TSLA"
    provider: str                 # ej: "tradingview"
    provider_symbol: str          # ej: "BINANCE:BTCUSDT" (mapeo del proveedor)
    timeframe: str                # timeframe normalizado, ej: "1h", "1d"
    tf_seconds: int               # segundos por vela (derivado del timeframe)
    mode: str                     # "backfill" | "catchup" | "realtime"
    since_ts: Optional[int]       # epoch (incl.) o None
    until_ts: Optional[int]       # epoch (incl. por ahora) o None
    n_candles_hint: Optional[int]     # sugerencia de máx. velas por request (paginación)

    def to_dict(self) -> Dict:
        return asdict(self)