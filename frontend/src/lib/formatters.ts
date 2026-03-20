// ──────────────────────────────────────────────────────────────────────────────
// FRONT-011: Shared formatting utilities
//
// Pure functions. Zero dependencies. Cached Intl.NumberFormat instances.
// Used by TickStack, MetricsGrid, FundamentalsBar.
// ──────────────────────────────────────────────────────────────────────────────

const currencyFmt = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const currencyCompactFmt = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
});

export function formatCurrency(val: number, decimals = 2): string {
  if (decimals === 2) return currencyFmt.format(val);
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(val);
}

export function formatLargeNumber(val: number | null | undefined): string {
  if (val == null || !isFinite(val)) return "—";
  const abs = Math.abs(val);
  const sign = val < 0 ? "-" : "";
  if (abs >= 1e12) return `${sign}$${(abs / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(1)}K`;
  return currencyCompactFmt.format(val);
}

export function formatPercent(val: number | null | undefined): string {
  if (val == null || !isFinite(val)) return "—";
  const sign = val > 0 ? "+" : "";
  return `${sign}${(val * 100).toFixed(2)}%`;
}

export function formatTimestamp(unixTs: number): string {
  const d = new Date(unixTs * 1000);
  const h = d.getHours().toString().padStart(2, "0");
  const m = d.getMinutes().toString().padStart(2, "0");
  const s = d.getSeconds().toString().padStart(2, "0");
  return `${h}:${m}:${s}`;
}

export function formatDate(unixTs: number): string {
  const d = new Date(unixTs * 1000);
  return d.toISOString().slice(0, 10);
}

export function signClass(val: number | null | undefined): string {
  if (val == null || val === 0) return "text-[var(--color-muted)]";
  return val > 0 ? "text-[var(--color-neon)]" : "text-[var(--color-red)]";
}
