// ──────────────────────────────────────────────────────────────────────────────
// RankingBoard — bloque visualmente cargado para mostrar un ranking de
// outliers para una metrica especifica del Gold Layer.
//
// Distinto a AdvancedAnalytics (tabla densa de 8 columnas): este componente
// muestra POCAS filas (3-5) con MUCHO peso visual. Tipografia grande, color
// dominante por signo de la anomalia, podium implicito (#1 mas grande).
//
// Layout responsive:
//   - mobile (<sm): 2 columnas → izq [#] [SYMBOL + company]  ·  der [metric] [zσ]
//   - desktop (≥sm): 4 columnas con metric_value + zσ separados.
//
// Tooltips (InfoTooltip de la app) explican que mide el ranking y como leer zσ.
// ──────────────────────────────────────────────────────────────────────────────

import { useEffect, useState } from "react";
import InfoTooltip from "./InfoTooltip";

const API_BASE = import.meta.env.VITE_API_URL ?? `${window.location.origin}`;

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
  rows: AnomalyRow[];
}

export interface RankingBoardProps {
  /** Titulo grande arriba, ej. "MAS SOBRECOMPRADOS" */
  title: string;
  /** Subtitulo chico, ej. "RSI z_of_z > 0" */
  subtitle: string;
  /** Texto explicativo corto que aparece en el InfoTooltip */
  help: string;
  /** Endpoint metric param */
  metric: string;
  /** "pos" = solo positivos · "neg" = solo negativos · "abs" = ambos */
  filter: "pos" | "neg" | "abs";
  /** Cuantos mostrar (3 default) */
  limit?: number;
  /** Color dominante de la card */
  accent: "neon" | "red" | "yellow" | "blue";
  /** Formateador de la metrica cruda */
  formatMetric?: (v: number | null) => string;
  /** Etiqueta corta de la metrica, ej. "RSI" */
  metricShort: string;
}

const ACCENT_MAP: Record<RankingBoardProps["accent"], { text: string; bg: string; border: string }> = {
  neon:   { text: "text-[var(--color-neon)]",   bg: "bg-[var(--color-neon)]/5",   border: "border-[var(--color-neon)]/40" },
  red:    { text: "text-[var(--color-red)]",    bg: "bg-[var(--color-red)]/5",    border: "border-[var(--color-red)]/40" },
  yellow: { text: "text-[var(--color-yellow)]", bg: "bg-[var(--color-yellow)]/5", border: "border-[var(--color-yellow)]/40" },
  blue:   { text: "text-[var(--color-blue)]",   bg: "bg-[var(--color-blue)]/5",   border: "border-[var(--color-blue)]/40" },
};

function fmtZ(v: number | null): string {
  if (v == null || !isFinite(v)) return "—";
  return (v >= 0 ? "+" : "") + v.toFixed(2) + "σ";
}
function fmtNum(v: number | null, d = 2): string {
  if (v == null || !isFinite(v)) return "—";
  return v.toFixed(d);
}

export default function RankingBoard({
  title,
  subtitle,
  help,
  metric,
  filter,
  limit = 3,
  accent,
  formatMetric = (v) => fmtNum(v, 2),
  metricShort,
}: RankingBoardProps) {
  const [rows, setRows] = useState<AnomalyRow[]>([]);
  const [asOf, setAsOf] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const colors = ACCENT_MAP[accent];

  useEffect(() => {
    let cancelled = false;

    const applyFilter = (pool: AnomalyRow[]): AnomalyRow[] => {
      let filtered = [...pool];
      if (filter === "pos") {
        filtered = filtered.filter((x) => (x.z_of_z ?? 0) > 0);
      } else if (filter === "neg") {
        filtered = filtered.filter((x) => (x.z_of_z ?? 0) < 0);
      }
      filtered.sort((a, b) => Math.abs(b.z_of_z ?? 0) - Math.abs(a.z_of_z ?? 0));
      return filtered.slice(0, limit);
    };

    (async () => {
      setLoading(true);
      setError(null);
      try {
        const url = `${API_BASE}/analytics/anomalies?metric=${metric}&limit=20&min_abs_z=0.5`;
        const r = await fetch(url);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const json = (await r.json()) as AnomalyResponse;
        if (cancelled) return;

        setRows(applyFilter(json.rows));
        setAsOf(json.as_of_date);
      } catch (e) {
        if (cancelled) return;
        setRows([]);
        setError(String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [metric, filter, limit]);

  return (
    <div className={`relative border ${colors.border} ${colors.bg} flex flex-col min-w-0`}>
      {/* ── Header ── */}
      <div className={`px-3 sm:px-4 py-3 border-b ${colors.border} flex items-start justify-between gap-2`}>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <div className={`text-[11px] uppercase tracking-[0.18em] font-bold ${colors.text} truncate`}>
              {title}
            </div>
            <InfoTooltip text={help} />
          </div>
          <div className="text-[10px] uppercase tracking-wider text-[var(--color-muted)] mt-0.5 truncate">
            {subtitle}
          </div>
        </div>
        <div className="text-[9px] uppercase tracking-wider text-[var(--color-muted)] shrink-0 text-right pt-0.5">
          {asOf ?? "—"}
        </div>
      </div>

      {/* ── Body ── */}
      <div className="flex-1 flex flex-col">
        {loading && (
          <div className="px-4 py-6 text-center text-[10px] uppercase text-[var(--color-muted)]">
            cargando…
          </div>
        )}
        {error && (
          <div className="px-4 py-6 text-center text-[10px] text-[var(--color-red)]">
            error: {error}
          </div>
        )}
        {!loading && !error && rows.length === 0 && (
          <div className="px-4 py-6 text-center text-[10px] uppercase text-[var(--color-muted)]">
            sin resultados
          </div>
        )}
        {!loading && !error && rows.map((row, idx) => {
          const isFirst = idx === 0;
          return (
            <div
              key={row.symbol}
              className={[
                "grid grid-cols-[auto_1fr_auto] items-center gap-x-2 sm:gap-x-3",
                "px-3 sm:px-4",
                isFirst ? "py-3 sm:py-4" : "py-2 sm:py-2.5",
                idx > 0 ? `border-t ${colors.border}` : "",
              ].join(" ")}
            >
              {/* Rank */}
              <div
                className={[
                  "font-mono font-bold tabular-nums",
                  isFirst ? `text-2xl sm:text-3xl ${colors.text}` : "text-base text-[var(--color-muted)]",
                  "w-6 sm:w-7 text-center",
                ].join(" ")}
              >
                {idx + 1}
              </div>

              {/* Symbol + company (truncate aggressively to never overflow) */}
              <div className="min-w-0 overflow-hidden">
                <div
                  className={[
                    "font-mono font-bold leading-tight truncate",
                    isFirst ? "text-lg sm:text-2xl text-[var(--color-text)]" : "text-sm text-[var(--color-text)]",
                  ].join(" ")}
                  title={row.company_name ?? row.symbol}
                >
                  {row.symbol}
                </div>
                <div className="text-[10px] text-[var(--color-muted)] truncate mt-0.5">
                  {row.company_name ?? "—"}
                  {row.sector && (
                    <span className="hidden sm:inline ml-1.5 opacity-70">· {row.sector}</span>
                  )}
                </div>
              </div>

              {/* Metric value + z_of_z stacked en mobile, en linea en desktop */}
              <div className="text-right shrink-0 flex flex-col items-end leading-tight">
                {/* zσ — la senal estrella, siempre primero/arriba */}
                <div
                  className={[
                    "font-mono tabular-nums font-bold",
                    isFirst ? `text-base sm:text-2xl ${colors.text}` : `text-xs sm:text-sm ${colors.text}`,
                  ].join(" ")}
                  title="z_of_z — anomalia dentro de anomalia"
                >
                  {fmtZ(row.z_of_z)}
                </div>
                {/* metric value debajo, mas chico, gris */}
                <div className="font-mono tabular-nums text-[10px] sm:text-xs text-[var(--color-muted)] mt-0.5">
                  {formatMetric(row.metric_value)} <span className="opacity-70">{metricShort}</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
