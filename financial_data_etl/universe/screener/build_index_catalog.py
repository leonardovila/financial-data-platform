from typing import List, Dict, Tuple
from financial_data_etl.storage.paths import CATALOG_PATH
import json

def build_index_catalog_from_raw(
    raw_payload
) -> Tuple[List[str], Dict[str, dict]]:
    """
    Construye:

      - Lista de tickers internos
      - Catálogo dinámico compatible con el scraper

    Además:
      - Escribe catalog.json en la raíz del repo (financial-data-etl/catalog.json)
    """

    data = raw_payload.get("data", [])
    symbols: List[str] = []
    catalog: Dict[str, dict] = {}

    for item in data:
        provider_symbol = item.get("s")  # ej: "NASDAQ:CRDO"
        d = item.get("d", [])

        if not provider_symbol or not d:
            continue

        symbol = d[0]
        if not symbol:
            continue

        symbol = symbol.strip().upper()

        symbols.append(symbol)

        catalog[symbol] = {
            "provider_symbol": {
                "tradingview": provider_symbol
            },
            "ticker": symbol
        }

    # Deduplicar preservando orden
    symbols = list(dict.fromkeys(symbols))

    # Cargar catálogo existente si existe
    if CATALOG_PATH.exists():
        with open(CATALOG_PATH, "r", encoding="utf-8") as f:
            existing_catalog = json.load(f)
    else:
        existing_catalog = {}

    # Merge (nuevo pisa viejo si coincide symbol)
    existing_catalog.update(catalog)

    # Escribir resultado final
    with open(CATALOG_PATH, "w", encoding="utf-8") as f:
        json.dump(existing_catalog, f, indent=2)

    return symbols
