from typing import List, Optional
from financial_data_etl.observability.run_context import RunContext
from financial_data_etl.universe.screener.get_screener import get_screener_raw
from financial_data_etl.universe.screener.build_index_catalog import build_index_catalog_from_raw

SUPPORTED_INDEX_FLAGS = {
    "spx": "SPX",
    "ndx": "NDX",
    "rut": "RUT",
    "dji": "DJI"
}

def resolve_universe(args, *, ctx: Optional[RunContext] = None) -> List[str]:

    # 1) Assets explícitos tienen prioridad absoluta
    if args.assets:
        return list(dict.fromkeys(args.assets))  # dedupe preservando orden

    requested_universes = []

    for flag_attr, universe_name in SUPPORTED_INDEX_FLAGS.items():
        if getattr(args, flag_attr, False):
            requested_universes.append(universe_name)

    if not requested_universes:
        raise ValueError("No universe specified. Use --assets or index flags.")

    all_symbols: List[str] = []

    for universe in requested_universes:
        raw = get_screener_raw(universe, ctx=ctx)
        symbols = build_index_catalog_from_raw(raw)
        all_symbols.extend(symbols)

    # Deduplicar final
    return list(dict.fromkeys(all_symbols))
