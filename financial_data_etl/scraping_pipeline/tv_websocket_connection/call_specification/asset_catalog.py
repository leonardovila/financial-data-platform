"""
Carga y resolución de catálogo de activos (símbolo humano → provider_symbol).
No construye CallSpec.
No resuelve timeframes.
"""
from pathlib import Path
from financial_data_etl.storage.paths import CATALOG_PATH
from typing import Dict, Optional
from importlib.resources import files
import json

def load_assets_catalog() -> Dict[str, dict]:
    """
    Carga y valida catalog.json (formato dinámico).
    Devuelve catálogo listo para uso: { "AAPL": { "provider_symbol": {...}, ... }, ... }
    """

    if not CATALOG_PATH.exists():
        raise FileNotFoundError(f"No se encontró catalog.json en {CATALOG_PATH}")

    with open(CATALOG_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict) or not data:
        raise ValueError("catalog.json inválido o vacío.")

    # Si existiera legacy con {"assets": {...}}, lo soportamos,
    # pero si ya eliminaste legacy, esto igual no molesta.
    assets = data["assets"] if "assets" in data and isinstance(data["assets"], dict) else data

    cleaned: Dict[str, dict] = {}

    for sym, cfg in assets.items():
        if not isinstance(sym, str) or not sym:
            continue
        if not isinstance(cfg, dict):
            continue

        prov = cfg.get("provider_symbol") or {}
        if not isinstance(prov, dict) or not prov:
            continue

        # normalizamos provider_symbol a str->str
        cleaned[sym] = dict(cfg)  # preserva campos extra (ticker, etc.)
        cleaned[sym]["provider_symbol"] = {str(k): str(v) for k, v in prov.items()}

    if not cleaned:
        raise ValueError("Catálogo limpio vacío tras parseo de catalog.json.")

    return cleaned

def validate_symbol(catalog: Dict[str, dict], symbol: str) -> None:
    if symbol not in catalog:
        raise ValueError(f"Símbolo desconocido: {symbol!r}.")

def resolve_provider_symbol(
    catalog: Dict[str, dict],
    symbol: str,
    provider: str
) -> str:
    try:
        return catalog[symbol]["provider_symbol"][provider]
    except KeyError as exc:
        raise ValueError(
            f"Falta provider_symbol para {symbol=} y {provider=}."
        ) from exc

def get_asset_start(
    catalog: Dict[str, dict],
    symbol: str
) -> Optional[str]:
    return catalog.get(symbol, {}).get("start")
