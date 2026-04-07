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

  useEffect(() => {
    connect(DEFAULT_SYMBOL);
    return () => disconnect();
  }, [connect, disconnect]);

  return (
    <div
      className={[
        "h-dvh w-full overflow-hidden bg-[var(--color-bg)]",

        "grid grid-cols-1 gap-1",

        // ── MOBILE: 5 filas ahora. header(48) chart(1fr) ticks(auto) metrics(auto) status(28) ──
        "grid-rows-[48px_1fr_auto_auto_28px]",

        // ── TABLET (≥640px) ──
        "sm:grid-cols-[78fr_22fr]",
        "sm:grid-rows-[auto_auto_1fr_auto_auto]",

        // ── DESKTOP (≥1280px) ──
        "xl:grid-cols-[82fr_18fr]",
      ].join(" ")}
    >
      {/* ── ROW 1: Header ── */}
      <div className="sm:col-span-2 min-w-0">
        <SymbolSearch />
      </div>

      {/* ── ROW 2 (tablet+): FundamentalsBar ── */}
      <div className="hidden sm:block sm:col-span-2">
        <FundamentalsBar />
      </div>

      {/* ── ROW 2 mobile / ROW 3 tablet+: Chart ── */}
      <div className="min-h-0 min-w-0 relative">
        {!seedData && (
          <div className="absolute inset-0 flex items-center justify-center z-10">
            <div className="w-3 h-3 rounded-full bg-[var(--color-neon)] pulse" />
          </div>
        )}
        <Chart />
      </div>

      {/* ── TickStack sidebar (tablet+ only) ── */}
      <div className="hidden sm:block min-h-0 min-w-0">
        <TickStackSidebar />
      </div>

      {/* ── ROW 3 mobile / Hidden on tablet+: TickStackMobile ── */}
      {/* Al estar en el flujo del grid, ocupa su 'auto' y el chart se achica gracias al 1fr */}
      <TickStackMobile />

      {/* ── ROW 4 mobile / ROW 4 tablet+: MetricsGrid ── */}
      <div className="sm:col-span-2 min-w-0 overflow-hidden">
        <MetricsGrid />
      </div>

      {/* ── ROW 5 mobile / ROW 5 tablet+: StatusBar ── */}
      <div
        className="sm:col-span-2"
        style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
      >
        <StatusBar />
      </div>
    </div>
  );
}