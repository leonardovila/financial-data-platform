// ──────────────────────────────────────────────────────────────────────────────
// AdvancedAnalytics — "Analiticas Avanzadas" panel
//
// Consume el endpoint /analytics/anomalies del API. Renderiza una tabla con
// el ranking de outliers del dia segun |z_of_z| para una metrica seleccionable.
//
// El move conceptual del DWH: muestra TRES capas de z-score por simbolo
//   z_intra : que tan raro esta vs su propia historia (252d rolling)
//   z_cross : que tan raro esta vs los pares HOY
//   z_of_z  : que tan rara es su rareza vs la rareza tipica del dia
//                (anomalia dentro de anomalia — detector de outlier en regimen)
//
// El front pide top-N ordenados por |z_of_z|. Eso es lo que lo hace valer.
// ──────────────────────────────────────────────────────────────────────────────

import { useEffect, useState, useCallback } from "react";
import { useI18n } from "../i18n";
import type { TKey } from "../i18n";

const API_BASE =
  import.meta.env.VITE_API_URL ?? `${window.location.origin}`;

const METRIC_IDS = [
  "rsi_14", "vol_1m", "vol_3m", "ret_1d", "ret_1m",
  "sma_50_gap", "sma_200_gap", "range_intraday", "high_dist_1y",
] as const;

interface AnomalyRow {
  symbol: string;
  company_name: string | null;
  sector: string | null;
  market_cap_tier: string | null;
  date: string;
  metric_value: number | null;
  z_intra: number | null;
  z_cross: number | null;
  z_of_z: number | null;
}

interface AnomalyResponse {
  metric: string;
  as_of_date: string | null;
  min_abs_z: number;
  limit: number;
  rows: AnomalyRow[];
}

function fmtNum(v: number | null, digits = 2): string {
  if (v == null || !isFinite(v)) return "—";
  return v.toFixed(digits);
}

function fmtZ(v: number | null): string {
  if (v == null || !isFinite(v)) return "—";
  return (v >= 0 ? "+" : "") + v.toFixed(2) + "σ";
}

function zColor(v: number | null): string {
  if (v == null || !isFinite(v)) return "text-[var(--color-muted)]";
  const abs = Math.abs(v);
  if (abs >= 2) return v > 0 ? "text-[var(--color-neon)]" : "text-[var(--color-red)]";
  if (abs >= 1) return v > 0 ? "text-[var(--color-yellow)]" : "text-[var(--color-yellow)]";
  return "text-[var(--color-text)]";
}

export default function AdvancedAnalytics() {
  const { t } = useI18n();
  const METRICS = METRIC_IDS.map((id) => ({
    id,
    label: t(`metric.${id}` as TKey),
    help: t(`metricHelp.${id}` as TKey),
  }));

  const [metric, setMetric] = useState("rsi_14");
  const [data, setData] = useState<AnomalyResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async (m: string) => {
    setLoading(true);
    setError(null);
    try {
      const url = `${API_BASE}/analytics/anomalies?metric=${m}&limit=10&min_abs_z=1.0`;
      const r = await fetch(url);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const json = (await r.json()) as AnomalyResponse;
      setData(json);
    } catch (e) {
      setError(String(e));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData(metric);
  }, [metric, fetchData]);

  const selected = METRICS.find((m) => m.id === metric)!;

  return (
    <section className="bg-[var(--color-panel)] border-t-2 border-[var(--color-border)] w-full">
      {/* ── Header ── */}
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 border-b border-[var(--color-border)]">
        <div className="flex items-baseline gap-3 min-w-0">
          <span className="text-sm uppercase tracking-widest font-bold text-[var(--color-neon)]">
            {t("aa.title")}
          </span>
          <span className="text-[11px] uppercase tracking-wider text-[var(--color-muted)]">
            {t("aa.subtitle")}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <label
            htmlFor="metric-select"
            className="text-[11px] uppercase tracking-wider text-[var(--color-muted)]"
          >
            {t("aa.metricLabel")}
          </label>
          <select
            id="metric-select"
            value={metric}
            onChange={(e) => setMetric(e.target.value)}
            className="bg-[var(--color-bg)] border border-[var(--color-border)] text-xs font-mono text-[var(--color-text)] px-2 py-1 focus:outline-none focus:border-[var(--color-neon)]"
          >
            {METRICS.map((m) => (
              <option key={m.id} value={m.id}>{m.label}</option>
            ))}
          </select>
        </div>
      </div>

      {/* ── Caption ── */}
      <div className="px-4 py-2 border-b border-[var(--color-border)] bg-[var(--color-bg)]">
        <p className="text-[11px] text-[var(--color-muted)] leading-relaxed">
          {t("aa.topN")} <strong className="text-[var(--color-text)]">{t("aa.topNBold")}</strong> {t("aa.topNEnd")}{" "}
          <span className="text-[var(--color-text)] font-semibold">{selected.label}</span>.
          {" "}{t("aa.topNSort")} <code className="text-[var(--color-yellow)]">|z_of_z|</code> {t("aa.topNZDesc")}
          {" "}{t("aa.topNSource")} <code>financial_marts.fact_derived_metrics</code>.
        </p>
        <p className="text-[10px] text-[var(--color-muted)] mt-1">{selected.help}</p>
      </div>

      {/* ── Status ── */}
      <div className="flex items-center justify-between px-4 py-1.5 text-[10px] uppercase tracking-wider border-b border-[var(--color-border)]">
        <div className="flex items-center gap-3">
          {loading && (
            <span className="flex items-center gap-1.5 text-[var(--color-yellow)]">
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-yellow)] animate-pulse" />
              {t("aa.loading")}
            </span>
          )}
          {!loading && data && (
            <span className="flex items-center gap-1.5 text-[var(--color-neon)]">
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-neon)]" />
              live · as_of {data.as_of_date}
            </span>
          )}
          {error && (
            <span className="text-[var(--color-red)]">error: {error}</span>
          )}
        </div>
        <span className="text-[var(--color-muted)]">
          {data ? `${data.rows.length} ${t("aa.results")}` : "—"}
        </span>
      </div>

      {/* ── Table ── */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs font-mono tabular-nums">
          <thead>
            <tr className="border-b border-[var(--color-border)] text-[10px] uppercase tracking-wider text-[var(--color-muted)]">
              <th className="text-left px-3 py-2 w-10">#</th>
              <th className="text-left px-3 py-2">{t("aa.symbol")}</th>
              <th className="text-left px-3 py-2 hidden sm:table-cell">{t("aa.sector")}</th>
              <th className="text-left px-3 py-2 hidden lg:table-cell">{t("aa.tier")}</th>
              <th className="text-right px-3 py-2">{selected.label}</th>
              <th className="text-right px-3 py-2" title="Z-score vs propia historia 252d">z_intra</th>
              <th className="text-right px-3 py-2 hidden md:table-cell" title="Z-score cruda vs universo HOY">z_cross</th>
              <th className="text-right px-3 py-2" title="Z-score del z_intra vs universo HOY (anomalia dentro de anomalia)">z_of_z</th>
            </tr>
          </thead>
          <tbody>
            {data?.rows.map((row, i) => (
              <tr
                key={row.symbol}
                className="border-b border-[var(--color-border)]/50 hover:bg-[var(--color-hover)] transition-colors"
              >
                <td className="px-3 py-2 text-[var(--color-muted)]">{i + 1}</td>
                <td className="px-3 py-2">
                  <div className="flex flex-col">
                    <span className="font-bold text-[var(--color-text)]">{row.symbol}</span>
                    <span className="text-[10px] text-[var(--color-muted)] truncate max-w-[180px]">
                      {row.company_name ?? "—"}
                    </span>
                  </div>
                </td>
                <td className="px-3 py-2 text-[var(--color-muted)] hidden sm:table-cell">
                  {row.sector ?? "—"}
                </td>
                <td className="px-3 py-2 text-[var(--color-muted)] uppercase hidden lg:table-cell">
                  {row.market_cap_tier ?? "—"}
                </td>
                <td className="px-3 py-2 text-right text-[var(--color-text)]">
                  {fmtNum(row.metric_value, 2)}
                </td>
                <td className={`px-3 py-2 text-right ${zColor(row.z_intra)}`}>
                  {fmtZ(row.z_intra)}
                </td>
                <td className={`px-3 py-2 text-right hidden md:table-cell ${zColor(row.z_cross)}`}>
                  {fmtZ(row.z_cross)}
                </td>
                <td className={`px-3 py-2 text-right font-bold ${zColor(row.z_of_z)}`}>
                  {fmtZ(row.z_of_z)}
                </td>
              </tr>
            ))}
            {!loading && data && data.rows.length === 0 && (
              <tr>
                <td colSpan={8} className="px-3 py-6 text-center text-[var(--color-muted)]">
                  {t("aa.noOutliers")}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* ── Footer leyenda ── */}
      <div className="px-4 py-2 border-t border-[var(--color-border)] flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-[var(--color-muted)]">
        <span>
          <span className="inline-block w-2 h-2 bg-[var(--color-neon)] mr-1.5 align-middle" />
          z &gt; +2σ
        </span>
        <span>
          <span className="inline-block w-2 h-2 bg-[var(--color-yellow)] mr-1.5 align-middle" />
          1σ &lt; |z| &lt; 2σ
        </span>
        <span>
          <span className="inline-block w-2 h-2 bg-[var(--color-red)] mr-1.5 align-middle" />
          z &lt; -2σ
        </span>
        <span className="ml-auto">
          source: <code>financial_marts.fact_derived_metrics</code>
        </span>
      </div>
    </section>
  );
}
