// ──────────────────────────────────────────────────────────────────────────────
// FRONT-006: MetricCard — single metric panel (Performance / Volatility / Momentum)
//
// Brutalist: no rounded corners, panel bg, panel border.
// Flashes green/red on value change via CSS animation classes.
// Desktop: 1-column key-value rows. Mobile: 2-column grid for density.
//
// PL_02/PL_03: Each row and the category title accept an optional `help` text.
// When set, an InfoTooltip ? icon is rendered next to the label.
// ──────────────────────────────────────────────────────────────────────────────

import { memo, useRef, useEffect } from "react";
import { signClass } from "../lib/formatters";
import InfoTooltip from "./InfoTooltip";

interface MetricRow {
  label: string;
  value: number | null | undefined;
  format: (v: number) => string;
  /** If true, color the value green/red based on sign. If false, use muted. */
  colored?: boolean;
  /** Plain-English help text for the InfoTooltip popup. */
  help?: string;
}

interface MetricCardProps {
  title: string;
  rows: MetricRow[];
  /** Plain-English help text for the category title (e.g. "Performance"). */
  categoryHelp?: string;
}

const MetricCard = memo(function MetricCard({ title, rows, categoryHelp }: MetricCardProps) {
  return (
    <div className="bg-[var(--color-panel)] border border-[var(--color-border)] min-w-full snap-start sm:min-w-0">
      {/* Title + category tooltip */}
      <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-[var(--color-border)]">
        <span className="text-xs sm:text-sm uppercase tracking-widest text-[var(--color-text)] font-bold">
          {title}
        </span>
        {categoryHelp && <InfoTooltip text={categoryHelp} size="md" />}
      </div>

      {/* Key-value grid: 2 cols on mobile, 1 col on sm+ */}
      <div className="grid grid-cols-2 sm:grid-cols-1">
        {rows.map((row) => (
          <MetricValue key={row.label} row={row} />
        ))}
      </div>
    </div>
  );
});

export default MetricCard;

// ── Individual metric value with flash-on-change ──

const MetricValue = memo(function MetricValue({ row }: { row: MetricRow }) {
  const { label, value, format, colored = true, help } = row;
  const prevRef = useRef<number | null | undefined>(undefined);
  const elRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const prev = prevRef.current;
    prevRef.current = value;

    // Skip flash on initial render (prev === undefined)
    if (prev === undefined || value == null || prev === value) return;

    const el = elRef.current;
    if (!el) return;

    const cls = value > (prev ?? 0) ? "flash-green" : "flash-red";
    el.classList.add(cls);

    const timer = setTimeout(() => el.classList.remove(cls), 300);
    return () => clearTimeout(timer);
  }, [value]);

  const displayValue =
    value != null && isFinite(value) ? format(value) : "—";

  const colorCls =
    value != null && colored
      ? signClass(value)
      : "text-[var(--color-muted)]";

  return (
    <div
      ref={elRef}
      className="flex items-center justify-between gap-2 px-3 py-1.5 border-b border-[var(--color-border)]/60"
    >
      <div className="flex items-center gap-1.5 min-w-0">
        <span className="text-[11px] sm:text-xs uppercase tracking-wider text-[var(--color-muted)] truncate">
          {label}
        </span>
        {help && <InfoTooltip text={help} size="sm" />}
      </div>
      <span className={`text-sm sm:text-base font-mono tabular-nums text-right ${colorCls}`}>
        {displayValue}
      </span>
    </div>
  );
});
