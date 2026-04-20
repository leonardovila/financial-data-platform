"""
Extrae data real de BigQuery para los 9 rankings de Analiticas Avanzadas
y genera frontend/src/data/anomaliesSnapshot.ts con los valores actuales.

Uso:
  set GOOGLE_APPLICATION_CREDENTIALS=C:\\Users\\leona\\Desktop\\financial-data-etl\\gcp\\bigquery-sa-key.json
  set GCP_PROJECT=financial-data-etl
  python scripts\\extract_snapshot.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from financial_data_etl.api import bq_analytics

METRICS = [
    "rsi_14", "vol_1m", "vol_3m", "ret_1d", "ret_1m",
    "sma_50_gap", "sma_200_gap", "range_intraday", "high_dist_1y",
]

OUT_PATH = ROOT / "frontend" / "src" / "data" / "anomaliesSnapshot.ts"


def js_num(v):
    if v is None:
        return "null"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "null"
    if f != f:  # NaN
        return "null"
    # Preserva precision razonable
    return f"{f:.6g}"


def js_str(v):
    if v is None:
        return "null"
    # Escape comillas/backslashes basico
    s = str(v).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def fetch_metric(metric: str) -> dict:
    print(f"  querying {metric} ...", flush=True)
    # limit=30 para tener bastante pool positivo y negativo
    return bq_analytics.get_top_anomalies(metric=metric, limit=30, min_abs_z=0.5)


def emit_ts(datasets: dict[str, dict]) -> str:
    as_of_dates = [d.get("as_of_date") for d in datasets.values() if d.get("as_of_date")]
    as_of = max(as_of_dates) if as_of_dates else ""

    lines = []
    lines.append("// ──────────────────────────────────────────────────────────────────────────────")
    lines.append("// Snapshot de /analytics/anomalies extraido directamente de")
    lines.append("// BigQuery (financial_marts.fact_derived_metrics) via scripts/extract_snapshot.py.")
    lines.append("// Contiene los top-30 outliers por |z_of_z| de cada metrica para la fecha mas")
    lines.append("// reciente disponible. Se consume en RankingBoard y AdvancedAnalytics.")
    lines.append("// ──────────────────────────────────────────────────────────────────────────────")
    lines.append("")
    lines.append("export interface AnomalyRowSnapshot {")
    lines.append("  symbol: string;")
    lines.append("  company_name: string | null;")
    lines.append("  sector: string | null;")
    lines.append("  market_cap_tier: string | null;")
    lines.append("  date: string;")
    lines.append("  metric_value: number | null;")
    lines.append("  z_intra: number | null;")
    lines.append("  z_cross: number | null;")
    lines.append("  z_of_z: number | null;")
    lines.append("}")
    lines.append("")
    lines.append(f'export const SNAPSHOT_AS_OF = "{as_of}";')
    lines.append("")
    lines.append("export const ANOMALIES_SNAPSHOT: Record<string, AnomalyRowSnapshot[]> = {")

    for metric in METRICS:
        payload = datasets.get(metric, {})
        rows = payload.get("rows", [])
        lines.append(f"  {metric}: [")
        for r in rows:
            lines.append(
                "    {{ symbol: {sym}, company_name: {cn}, sector: {sc}, "
                "market_cap_tier: {tier}, date: {dt}, metric_value: {mv}, "
                "z_intra: {zi}, z_cross: {zc}, z_of_z: {zoz} }},".format(
                    sym=js_str(r.get("symbol")),
                    cn=js_str(r.get("company_name")),
                    sc=js_str(r.get("sector")),
                    tier=js_str(r.get("market_cap_tier")),
                    dt=js_str(r.get("date")),
                    mv=js_num(r.get("metric_value")),
                    zi=js_num(r.get("z_intra")),
                    zc=js_num(r.get("z_cross")),
                    zoz=js_num(r.get("z_of_z")),
                )
            )
        lines.append("  ],")

    lines.append("};")
    lines.append("")
    return "\n".join(lines)


def main():
    if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        default_key = ROOT / "gcp" / "bigquery-sa-key.json"
        if default_key.exists():
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(default_key)
            print(f"[info] GOOGLE_APPLICATION_CREDENTIALS -> {default_key}", flush=True)
        else:
            print("[error] SA key no encontrada. Seteala manualmente.", file=sys.stderr)
            sys.exit(2)

    if not os.environ.get("GCP_PROJECT"):
        os.environ["GCP_PROJECT"] = "financial-data-etl"

    print(f"[info] project  = {os.environ.get('GCP_PROJECT')}")
    print(f"[info] sa key   = {os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')}")
    print("[info] fetching real anomalies from BigQuery ...")

    datasets: dict[str, dict] = {}
    for m in METRICS:
        try:
            datasets[m] = fetch_metric(m)
        except Exception as e:
            print(f"  [warn] {m}: {e}", flush=True)
            datasets[m] = {"metric": m, "as_of_date": None, "rows": []}

    ts = emit_ts(datasets)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(ts, encoding="utf-8")
    total = sum(len(d.get("rows", [])) for d in datasets.values())
    print(f"[ok] wrote {OUT_PATH} ({total} rows across {len(METRICS)} metrics)")


if __name__ == "__main__":
    main()
