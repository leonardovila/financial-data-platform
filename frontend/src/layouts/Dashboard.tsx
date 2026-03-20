// ──────────────────────────────────────────────────────────────────────────────
// FRONT-010: Dashboard — the single source of spatial truth
//
// CSS Grid with responsive breakpoints. ONE grid, four layouts:
//   Mobile portrait (<640px):  1-col, chart 55vh, metrics tabbed, ticks=sheet
//   Tablet (640-1279px):       2-col 65/35, ticks sidebar, metrics 3-col
//   Desktop (≥1280px):         2-col 70/30, full density
//
// h-dvh root (not h-screen) — respects Safari's dynamic toolbar.
// ──────────────────────────────────────────────────────────────────────────────

import { useEffect } from "react";
import { useWsStore } from "../stores/wsStore";

import SymbolSearch from "../components/SymbolSearch";
import FundamentalsBar from "../components/FundamentalsBar";
import Chart from "../components/Chart";
import { TickStackSidebar, TickStackMobile } from "../components/TickStack";
import MetricsGrid from "../components/MetricsGrid";
import StatusBar from "../components/StatusBar";

const DEFAULT_SYMBOL = "BTC";

export default function Dashboard() {
  const connect = useWsStore((s) => s.connect);
  const disconnect = useWsStore((s) => s.disconnect);
  const seedData = useWsStore((s) => s.seedData);

  // ── Connect on mount, disconnect on unmount ──
  useEffect(() => {
    connect(DEFAULT_SYMBOL);
    return () => disconnect();
  }, [connect, disconnect]);

  return (
    <div
      className={[
        // Root: fill dynamic viewport height
        "h-dvh w-full overflow-hidden bg-[var(--color-bg)]",

        // ── MOBILE (<640px): single column ──
        "grid",
        "grid-cols-1",
        "grid-rows-[auto_1fr_auto_auto_auto]",
        // areas: header / chart / fund / metrics / status
        // (fund + metrics scroll within the content area below chart)

        // ── TABLET (≥640px): 2-col 65/35 ──
        "sm:grid-cols-[65fr_35fr]",
        "sm:grid-rows-[auto_auto_1fr_auto_auto]",

        // ── DESKTOP (≥1280px): 2-col 70/30 ──
        "xl:grid-cols-[70fr_30fr]",
      ].join(" ")}
    >
      {/* ── ROW 1: Search header (spans full width) ── */}
      <div className="col-span-1 sm:col-span-2">
        <SymbolSearch />
      </div>

      {/* ── ROW 2: FundamentalsBar (spans full width, hidden on mobile portrait when no seed) ── */}
      <div className="col-span-1 sm:col-span-2">
        <FundamentalsBar />
      </div>

      {/* ── ROW 3: Chart (left) + TickStack sidebar (right, sm+ only) ── */}
      <div className="min-h-0 min-w-0 relative">
        {/* Loading state: pulsing dot */}
        {!seedData && (
          <div className="absolute inset-0 flex items-center justify-center z-10">
            <div className="w-3 h-3 rounded-full bg-[var(--color-neon)] pulse" />
          </div>
        )}
        <Chart />
      </div>

      {/* TickStack sidebar — visible on sm+, hidden on mobile */}
      <div className="hidden sm:block min-h-0 min-w-0">
        <TickStackSidebar />
      </div>

      {/* ── ROW 4: MetricsGrid (spans full width) ── */}
      <div className="col-span-1 sm:col-span-2 overflow-y-auto">
        <MetricsGrid />
      </div>

      {/* ── ROW 5: StatusBar (spans full width) ── */}
      <div className="col-span-1 sm:col-span-2">
        <StatusBar />
      </div>

      {/* ── Mobile-only: TickStack bottom sheet + floating pill ── */}
      <TickStackMobile />
    </div>
  );
}
