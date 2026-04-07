// ──────────────────────────────────────────────────────────────────────────────
// FRONT-007: FundamentalsBar — horizontal ticker tape
//
// Desktop: all 6 items in one row, no scroll.
// Mobile:  overflow-x-auto with scroll-snap, right-edge gradient fade.
// Always h-10. Never wraps. Hides entirely if fundamentals is null.
// ──────────────────────────────────────────────────────────────────────────────

import { useWsStore } from "../stores/wsStore";
import { formatLargeNumber } from "../lib/formatters";

interface FundItem {
  label: string;
  value: string;
}

function formatShares(val: number | null | undefined): string {
  if (val == null || !isFinite(val)) return "—";
  const abs = Math.abs(val);
  if (abs >= 1e9) return `${(val / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${(val / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${(val / 1e3).toFixed(0)}K`;
  return val.toFixed(0);
}

function formatDecimal(val: number | null | undefined, decimals = 2): string {
  if (val == null || !isFinite(val)) return "—";
  return val.toFixed(decimals);
}

export default function FundamentalsBar() {
  const fundamentals = useWsStore((s) => s.fundamentals);

  if (!fundamentals) return null;

  const items: FundItem[] = [
    { label: "Mkt Cap", value: formatLargeNumber(fundamentals.market_cap) },
    { label: "P/E", value: formatDecimal(fundamentals.pe_ttm) },
    { label: "EPS", value: fundamentals.eps_ttm != null ? `$${formatDecimal(fundamentals.eps_ttm)}` : "—" },
    { label: "Shares", value: formatShares(fundamentals.shares_outstanding) },
    { label: "Sector", value: fundamentals.sector ?? "—" },
    { label: "Industry", value: fundamentals.industry ?? "—" },
  ];

  return (
    <div className="relative h-12 border-b border-[var(--color-border)] scroll-fade-right">
      <div
        className="flex items-center gap-0 h-full overflow-x-auto px-2"
        style={{ WebkitOverflowScrolling: "touch" }}
      >
        {items.map((item, i) => (
          <div
            key={item.label}
            className={[
              "flex items-center gap-2 shrink-0 min-w-[88px] px-3 h-full",
              i > 0 ? "border-l border-[var(--color-border)]/60" : "",
            ].join(" ")}
          >
            <div className="flex flex-col justify-center min-w-0">
              <span className="text-[10px] sm:text-[11px] uppercase tracking-wider text-[var(--color-muted)] leading-none">
                {item.label}
              </span>
              <span className="text-sm font-mono text-[var(--color-text)] truncate leading-tight mt-1">
                {item.value}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
