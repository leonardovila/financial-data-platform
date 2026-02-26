from typing import Dict, List, Optional
from contextlib import contextmanager
from financial_data_etl.observability.run_context import RunContext
from financial_data_etl.universe.universe_resolver import resolve_universe
from financial_data_etl.universe.storage.universe_store import (
    init_universe_schema,
    save_universe_snapshot,
    load_latest_universe,
)
from importlib.resources import files
from financial_data_etl.storage.paths import CATALOG_PATH

def ensure_catalog_exists(*, ctx: Optional[RunContext] = None) -> None:
    if CATALOG_PATH.exists():
        return

    seed = files("financial_data_etl.universe.storage") / "catalog.json"
    CATALOG_PATH.write_bytes(seed.read_bytes())

    if ctx:
        ctx.event(
            "catalog_bootstrap",
            level="INFO",
            stage="universe_resolve",
            catalog_path=str(CATALOG_PATH),
        )

def resolve_and_cache_universe(args, *, ctx: Optional[RunContext] = None) -> List[str]:
    """
    Permite múltiples universos en una ejecución,
    pero los procesa y persiste de forma independiente.

    Devuelve la lista combinada SOLO para uso inmediato,
    pero NO los persiste combinados.
    """

    init_universe_schema()
    ensure_catalog_exists(ctx=ctx)
    if ctx:
        ctx.event(
            "universe_begin",
            level="INFO",
            stage="universe_resolve",
            assets_explicit=bool(args.assets),
            update_universe=bool(args.update_universe),
            spx=bool(getattr(args, "spx", False)),
            ndx=bool(getattr(args, "ndx", False)),
            rut=bool(getattr(args, "rut", False)),
            dji=bool(getattr(args, "dji", False)),
        )

    # Caso assets explícitos → no hay universos
    if args.assets:
        return resolve_universe(args)

    requested = _extract_requested_universes(args)

    all_symbols: List[str] = []

    for universe_name in requested:

        with (ctx.span("universe_single", universe=universe_name) if ctx else _nullcontext()):
            if ctx:
                ctx.event(
                    "universe_single_begin",
                    stage="universe_resolve",
                    universe=universe_name,
                    mode="update" if args.update_universe else "cache",
                )

            if args.update_universe:
                single_args = _build_single_universe_args(args, universe_name)
                symbols = resolve_universe(single_args, ctx=ctx)
                save_universe_snapshot(universe_name, symbols)
            else:
                symbols = load_latest_universe(universe_name)
                if symbols is None:
                    raise RuntimeError(
                        f"Universe '{universe_name}' not cached. Run with --update-universe."
                    )

            if ctx:
                ctx.event(
                    "universe_single_done",
                    stage="universe_resolve",
                    universe=universe_name,
                    symbols=len(symbols),
                )

        all_symbols.extend(symbols)

    if ctx:
        ctx.event(
            "universe_resolved",
            level="INFO",
            stage="universe_resolve",
            symbols=len(all_symbols),
            universes=requested if not args.assets else [],
        )
    # Para ejecución posterior del pipeline devolvemos combinados,
    # pero solo en memoria (no persistidos como un universo nuevo).
    return list(dict.fromkeys(all_symbols))


def _extract_requested_universes(args) -> List[str]:
    universes = []
    if args.spx:
        universes.append("SPX")
    if args.ndx:
        universes.append("NDX")
    if args.rut:
        universes.append("RUT")
    if args.dji:
        universes.append("DJI")

    if not universes:
        raise ValueError("No universe specified.")

    return universes


def _build_single_universe_args(original_args, universe_name: str):
    """
    Crea copia mínima de args activando solo un universo.
    """
    class Args:
        pass

    new_args = Args()
    new_args.assets = None
    new_args.update_universe = original_args.update_universe

    new_args.spx = universe_name == "SPX"
    new_args.ndx = universe_name == "NDX"
    new_args.rut = universe_name == "RUT"
    new_args.dji = universe_name == "DJI"

    return new_args

@contextmanager
def _nullcontext():
    yield
