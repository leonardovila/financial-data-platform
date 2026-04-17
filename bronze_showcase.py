"""
Bronze Layer Showcase
=====================
Render visual del layer bronze (RDS → BigQuery) para demos/posts.
Números = snapshot del último run (no live query — determinista,
idempotente, no depende de credenciales ni de red).

Uso:
    python bronze_showcase.py
"""
import sys

# Forzar UTF-8 para que Windows legacy console no muera con los box-drawing chars
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from rich.align import Align
from rich.columns import Columns
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# ── Palette ────────────────────────────────────────────────────────────────────
BRONZE = "#CD7F32"
BRONZE_DIM = "#8B5A2B"
CYAN = "#00D7FF"
GREEN = "#7CE07C"
DIM = "#5C6370"
WHITE = "#E6E6E6"

# Gradient para el banner (claro arriba → oscuro abajo: efecto de fundición)
BRONZE_GRADIENT = [
    "#FFD98A",  # oro pálido
    "#EDB264",  # oro rosado
    "#CD7F32",  # bronce canónico
    "#B0672A",  # bronce medio
    "#8B5A2B",  # bronce oscuro
    "#6B4423",  # bronce profundo
]

# ── Data (snapshot del último run) ─────────────────────────────────────────────
TABLES = [
    ("raw_tv_candles",     305_009, 10),
    ("raw_fundamentals",       430,  9),
    ("raw_volatility",     305_009,  9),
    ("raw_performance",    305_009,  9),
    ("raw_momentum",       305_009,  9),
]
TOTAL_ROWS = sum(r for _, r, _ in TABLES)
N_SYMBOLS = 48
# Span real desde 1994-06 hasta hoy. Máxima profundidad = 31.8 años (blue chips
# del Dow: HD/MSFT/AXP/JNJ/JPM), mínima = 4.7 años (IPOs recientes como HOOD).
HISTORY_LABEL = "back to 1994"

# ── ASCII banner (ANSI Shadow) ────────────────────────────────────────────────
BANNER = r"""
██████╗ ██████╗  ██████╗ ███╗   ██╗███████╗███████╗
██╔══██╗██╔══██╗██╔═══██╗████╗  ██║╚══███╔╝██╔════╝
██████╔╝██████╔╝██║   ██║██╔██╗ ██║  ███╔╝ █████╗
██╔══██╗██╔══██╗██║   ██║██║╚██╗██║ ███╔╝  ██╔══╝
██████╔╝██║  ██║╚██████╔╝██║ ╚████║███████╗███████╗
╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝╚══════╝╚══════╝
""".strip("\n")


# ── Components ────────────────────────────────────────────────────────────────

def gradient_banner() -> Text:
    """Banner con gradient vertical: cada línea del ASCII en un tono distinto."""
    out = Text()
    for i, line in enumerate(BANNER.split("\n")):
        color = BRONZE_GRADIENT[i] if i < len(BRONZE_GRADIENT) else BRONZE_GRADIENT[-1]
        out.append(line + "\n", style=f"bold {color}")
    return out


def hero_panel() -> Panel:
    banner = gradient_banner()
    subtitle = Text("M A T E R I A   P R I M A   L I S T A", style=f"bold {CYAN}")

    bar = Text()
    bar.append("█" * 58, style=BRONZE)
    bar.append("  100%", style=f"bold {GREEN}")

    stats = Text()
    stats.append(f"{TOTAL_ROWS:,}", style=f"bold {CYAN}")
    stats.append(" rows", style=WHITE)
    stats.append("    ·    ", style=DIM)
    stats.append(f"{N_SYMBOLS}", style=f"bold {CYAN}")
    stats.append(" symbols", style=WHITE)
    stats.append("    ·    ", style=DIM)
    stats.append(HISTORY_LABEL, style=f"bold {CYAN}")
    stats.append(" · daily OHLCV", style=WHITE)

    group = Group(
        Align.center(banner),
        Text(""),
        Align.center(subtitle),
        Text(""),
        Align.center(bar),
        Text(""),
        Align.center(stats),
    )

    return Panel(
        group,
        title=f"[bold {WHITE}]FINANCIAL DATA ETL[/]",
        subtitle=f"[{DIM}]bronze layer · RDS → S3 → BigQuery[/]",
        border_style=BRONZE,
        padding=(1, 4),
    )


def density_bar(rows: int, max_rows: int, width: int = 14) -> Text:
    """Barra de densidad: proporción de rows vs max. Usa bloques de media altura."""
    filled = max(1, round(width * (rows / max_rows))) if max_rows else 0
    empty = width - filled
    t = Text()
    t.append("█" * filled, style=BRONZE)
    t.append("░" * empty, style=DIM)
    return t


def tables_panel() -> Panel:
    max_rows = max(r for _, r, _ in TABLES)
    t = Table(
        show_header=True,
        header_style=f"bold {BRONZE}",
        border_style=DIM,
        box=None,
        pad_edge=False,
        expand=True,
    )
    t.add_column("table", style=WHITE, no_wrap=True)
    t.add_column("rows", justify="right", style=f"bold {CYAN}")
    t.add_column("cols", justify="right", style=CYAN)
    t.add_column("density", justify="left")
    t.add_column("", justify="right")

    for name, rows, cols in TABLES:
        t.add_row(
            name,
            f"{rows:>9,}",
            f"{cols}",
            density_bar(rows, max_rows),
            f"[{GREEN}]●[/] [bold {GREEN}]ready[/]",
        )

    return Panel(
        t,
        title=f"[bold {BRONZE}]BigQuery · financial_raw[/]",
        border_style=BRONZE_DIM,
        padding=(1, 2),
    )


def pipeline_panel() -> Panel:
    arrow = f"[{DIM}]│[/]\n[{DIM}]▼[/]"
    lines = [
        f"[bold {WHITE}]TradingView  WS[/]",
        arrow,
        f"[{WHITE}]RDS  [/][{DIM}](OLTP)[/]",
        arrow,
        f"[{WHITE}]S3  Parquet[/]",
        arrow,
        f"[bold {BRONZE}]BigQuery  [/][{DIM}](OLAP)[/]",
    ]
    body = Align.center(Text.from_markup("\n".join(lines)))
    return Panel(
        body,
        title=f"[bold {BRONZE}]pipeline[/]",
        border_style=BRONZE_DIM,
        padding=(1, 3),
    )


def footer() -> Text:
    t = Text()
    t.append("next  ", style=f"bold {DIM}")
    t.append("▸ ", style=BRONZE)
    t.append("DBT silver  ", style=WHITE)
    t.append("▸ ", style=BRONZE)
    t.append("DBT gold  ", style=WHITE)
    t.append("▸ ", style=BRONZE)
    t.append("star schema  ", style=WHITE)
    t.append("▸ ", style=BRONZE)
    t.append("analytics API", style=f"bold {CYAN}")
    return Align.center(t)


# ── Main ──────────────────────────────────────────────────────────────────────

def status_line() -> Text:
    """Barra superior con badge de estado + timestamp + autor."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    t = Text()
    t.append("  ● ", style=f"bold {GREEN}")
    t.append("LIVE", style=f"bold {GREEN}")
    t.append("   │   ", style=DIM)
    t.append("v1.0 · production", style=WHITE)
    t.append("   │   ", style=DIM)
    t.append(f"last run  {now}", style=DIM)
    t.append("   │   ", style=DIM)
    t.append("leonardovila.com", style=f"bold {BRONZE}")
    return t


def main():
    # Ancho fijo de 110 cols → layout apaisado predecible para screenshot
    console = Console(force_terminal=True, legacy_windows=False, width=110)
    console.print()
    console.print(status_line())
    console.print()
    console.print(hero_panel())
    console.print()
    console.print(Columns([tables_panel(), pipeline_panel()], expand=True, equal=False))
    console.print()
    console.print(footer())
    console.print()


if __name__ == "__main__":
    main()
