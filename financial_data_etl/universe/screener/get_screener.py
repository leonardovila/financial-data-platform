import json
import requests
from typing import Optional
from financial_data_etl.observability.run_context import RunContext

def get_screener_raw(universe: str, *, ctx: Optional[RunContext] = None):
    # ================================================================
    # CONFIG
    # ================================================================
    URL = "https://scanner.tradingview.com/america/scan?label-product=screener-stock"

    HEADERS = {
        "accept": "application/json",
        "accept-language": "en-US,en;q=0.9",
        "content-type": "text/plain;charset=UTF-8",
        "origin": "https://www.tradingview.com",
        "referer": "https://www.tradingview.com/",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        # -------------------------------------------------------------
        # **PONÉ ACÁ TUS COOKIES EXACTAS COPIADAS DEL NETWORK TAB**
        # -------------------------------------------------------------
        "cookie": '_ga=...; sessionid=...; tv_ecuid=...;'  # TU COOKIE REAL COMPLETA
    }

    SYMBOLSET_BY_UNIVERSE = {
        "RUT": "SYML:TVC;RUT",
        "SPX": "SYML:SP;SPX",
        "NDX": "SYML:NASDAQ;NDX",
        "DJI": "SYML:DJ;DJI"
    }

    symbolset = SYMBOLSET_BY_UNIVERSE.get(universe)
    if not symbolset:
        raise ValueError(f"Unsupported universe: {universe}")


    PAYLOAD = {
        "columns": [
            "name", "description", "logoid", "update_mode",
            "type", "typespecs", "close", "pricescale", "minmov",
            "fractional", "minmove2", "currency", "change",
            "volume", "relative_volume_10d_calc", "market_cap_basic",
            "fundamental_currency_code", "price_earnings_ttm",
            "earnings_per_share_diluted_ttm",
            "earnings_per_share_diluted_yoy_growth_ttm",
            "dividends_yield_current", "sector.tr", "market", "sector",
            "AnalystRating", "AnalystRating.tr", "exchange"
        ],
        "filter": [
            {"left": "is_blacklisted", "operation": "equal", "right": False},
            {"left": "is_primary", "operation": "equal", "right": True}
        ],
        "ignore_unknown_fields": False,
        "options": {"lang": "en"},
        "range": [0, 100],  # solo primeras 100 filas; para más, iterar offsets
        "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
        "symbols": {"symbolset": [symbolset]},
        "markets": ["america"],
        "filter2": {
            "operator": "and",
            "operands": [
                {
                    "operation": {
                        "operator": "or",
                        "operands": [
                            {
                                "operation": {
                                    "operator": "and",
                                    "operands": [
                                        {"expression": {"left": "type", "operation": "equal", "right": "stock"}},
                                        {"expression": {"left": "typespecs", "operation": "has", "right": ["common"]}}
                                    ]
                                }
                            },
                            {
                                "operation": {
                                    "operator": "and",
                                    "operands": [
                                        {"expression": {"left": "type", "operation": "equal", "right": "stock"}},
                                        {"expression": {"left": "typespecs", "operation": "has", "right": ["preferred"]}}
                                    ]
                                }
                            },
                            {
                                "operation": {
                                    "operator": "and",
                                    "operands": [
                                        {"expression": {"left": "type", "operation": "equal", "right": "dr"}}
                                    ]
                                }
                            },
                            {
                                "operation": {
                                    "operator": "and",
                                    "operands": [
                                        {"expression": {"left": "type", "operation": "equal", "right": "fund"}},
                                        {"expression": {"left": "typespecs", "operation": "has_none_of", "right": ["etf"]}}
                                    ]
                                }
                            }
                        ]
                    }
                },
                {"expression": {"left": "typespecs", "operation": "has_none_of", "right": ["pre-ipo"]}}
            ]
        }
    }

    # ================================================================
    # EXECUTE PAGINATED REQUEST
    # ================================================================
    all_items = []
    offset = 0
    batch_size = 100

    while True:
        if ctx:
            ctx.event(
                "screener_page_fetch",
                universe=universe,
                offset=offset,
                limit=batch_size,
            )

        # actualizar rango
        PAYLOAD["range"] = [offset, offset + batch_size]

        response = requests.post(URL, headers=HEADERS, data=json.dumps(PAYLOAD))

        if response.status_code != 200:
            if ctx:
                ctx.event(
                    "screener_http_error",
                    level="ERROR",
                    universe=universe,
                    status_code=response.status_code,
                    body_preview=response.text[:500],
                )
            break

        chunk = response.json()

        # si no trae data o viene vacía, terminamos
        if "data" not in chunk or not chunk["data"]:
            if ctx:
                ctx.event(
                    "screener_no_more_data",
                    universe=universe,
                    total_items=len(all_items),
                )
            break

        # agregamos items
        all_items.extend(chunk["data"])

        # si trajo menos que el batch, también terminamos
        if len(chunk["data"]) < batch_size:
            if ctx:
                ctx.event(
                    "screener_last_page",
                    universe=universe,
                    total_items=len(all_items),
                    last_page_size=len(chunk["data"]),
                )
            break

        offset += batch_size

    # ================================================================
    # SAVE OUTPUT
    # ================================================================
    output = {
        "totalCount": len(all_items),
        "data": all_items
    }

    return output