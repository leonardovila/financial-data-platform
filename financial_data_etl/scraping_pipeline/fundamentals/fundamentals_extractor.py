def extract_fundamentals_from_quote_raw(quote_raw: dict) -> dict:
    """
    Recibe el dict 'v' (fundamentals raw) y extrae campos normalizados.
    """
    if not quote_raw or not isinstance(quote_raw, dict):
        return {}

    return {
        "market_cap": quote_raw.get("market_cap_basic"),
        "shares_outstanding": quote_raw.get("total_shares_outstanding_current"),
        "pe_ttm": quote_raw.get("price_earnings_ttm"),
        "eps_ttm": quote_raw.get("earnings_per_share_basic_ttm"),
        "sector": quote_raw.get("sector"),
        "industry": quote_raw.get("industry"),
    }