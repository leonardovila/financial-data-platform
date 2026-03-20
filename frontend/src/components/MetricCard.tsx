// ──────────────────────────────────────────────────────────────────────────────
// FRONT-006: MetricCard — single metric panel (Performance / Volatility / Volume)
//
// Brutalist: no rounded corners, #111111 bg, #222222 border.
// Flashes green/red on value change via CSS animation classes.
// Desktop: 1-column key-value rows. Mobile: 2-column grid for density.
// ──────────────────────────────────────────────────────────────────────────────

import { memo, useRef, useEffect } from "react";
import { signClass } from "../lib/formatters";

interface MetricRow {
  label: string;
  value: number | null | undefined;
  format: (v: number) => string;
  /** If true, color the value green/red based on sign. If false, use muted. */
  colored?: boolean;
}

interface MetricCardProps {
  title: string;
  rows: MetricRow[];
}

const MetricCard = memo(function MetricCard({ title, rows }: MetricCardProps) {
  return (
    <div className="bg-[var(--color-panel)] border border-[var(--color-border)] min-w-full snap-start sm:min-w-0">
      {/* Title */}
      <div className="px-3 py-1.5 text-[10px] uppercase tracking-widest text-[var(--color-muted)] border-b border-[var(--color-border)]">
        {title}
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
  const { label, value, format, colored = true } = row;
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
      className="flex items-center justify-between px-3 py-1 border-b border-[var(--color-border)]/30"
    >
      <span className="text-[10px] uppercase tracking-wider text-[var(--color-muted)] truncate">
        {label}
      </span>
      <span className={`text-xs font-mono tabular-nums text-right ${colorCls}`}>
        {displayValue}
      </span>
    </div>
  );
});
