// ──────────────────────────────────────────────────────────────────────────────
// FRONT-009: StatusBar — connection status, symbol, tick count, latency
//
// Desktop (sm+): h-6. [dot LIVE] [BTC] [Ticks: 142] [Last: 3s ago]
// Mobile (<sm):  h-7. [dot] [BTC] [142] [3s] — labels dropped, values only.
// safe-area-inset-bottom for iPhone home indicator.
// ──────────────────────────────────────────────────────────────────────────────

import { useState, useEffect } from "react";
import { useWsStore } from "../stores/wsStore";

const STATUS_CONFIG = {
  connected: { color: "bg-[var(--color-neon)]", label: "LIVE" },
  connecting: { color: "bg-[var(--color-yellow)]", label: "CONNECTING" },
  reconnecting: { color: "bg-[var(--color-yellow)]", label: "RECONNECTING" },
  disconnected: { color: "bg-[var(--color-red)]", label: "OFFLINE" },
} as const;

export default function StatusBar() {
  const status = useWsStore((s) => s.status);
  const currentSymbol = useWsStore((s) => s.currentSymbol);
  const tickHistory = useWsStore((s) => s.tickHistory);
  const latestTickTs = useWsStore((s) => s.latestTick?.ts ?? null);

  const [elapsed, setElapsed] = useState<number | null>(null);

  // ── Live clock: "Xs ago" relative to last tick ──
  useEffect(() => {
    if (latestTickTs === null) {
      setElapsed(null);
      return;
    }

    // Immediate update
    setElapsed(Math.floor(Date.now() / 1000 - latestTickTs));

    const iv = setInterval(() => {
      setElapsed(Math.floor(Date.now() / 1000 - latestTickTs));
    }, 1000);

    return () => clearInterval(iv);
  }, [latestTickTs]);

  const { color, label } = STATUS_CONFIG[status];
  const tickCount = tickHistory.length;

  return (
    <div
      className={[
        "flex items-center justify-between px-3 font-mono",
        "h-7 sm:h-6 text-[10px]",
        "bg-[var(--color-bg)] border-t border-[var(--color-border)]",
        "text-[var(--color-muted)]",
      ].join(" ")}
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
    >
      {/* Left: status dot + label */}
      <div className="flex items-center gap-1.5 shrink-0">
        <span className={`inline-block w-1.5 h-1.5 rounded-full ${color} ${status === "connected" ? "pulse" : ""}`} />
        <span className="hidden sm:inline uppercase tracking-wider">{label}</span>
      </div>

      {/* Center: symbol */}
      <span className="truncate text-center text-[var(--color-text)]">
        {currentSymbol || "—"}
      </span>

      {/* Right: tick count + elapsed */}
      <div className="flex items-center gap-3 shrink-0">
        {tickCount > 0 && (
          <span>
            <span className="hidden sm:inline">Ticks: </span>
            {tickCount}
          </span>
        )}
        {elapsed !== null && (
          <span>
            <span className="hidden sm:inline">Last: </span>
            {elapsed}s
          </span>
        )}
      </div>
    </div>
  );
}
